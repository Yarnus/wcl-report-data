from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from statistics import median
from pathlib import Path
from typing import Any

from .errors import ApiError, InputError
from .coach_models import specialization_role
from .profiles import validate_profile
from .analysis import ANALYSIS_SCHEMA_VERSION, analyze_player
from .storage import sha256_file


def extract_ranking_candidates(payload: Any, *, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ApiError("WCL ranking payload must be an object.")
    rankings = payload.get("rankings")
    if not isinstance(rankings, list):
        raise ApiError("WCL ranking payload did not contain a rankings list.")
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=14)
    recent = []
    unverified = []
    rejected = []
    seen: set[tuple[str, int, Any]] = set()
    for rank, item in enumerate(rankings, 1):
        if not isinstance(item, dict):
            rejected.append({"rank": rank, "reason": "malformed_candidate"})
            continue
        report = item.get("report")
        report = report if isinstance(report, dict) else {}
        code = item.get("reportCode", report.get("code"))
        fight_id = item.get("fightID", item.get("fightId", report.get("fightID")))
        source_id = item.get("sourceID", item.get("sourceId", item.get("actorID")))
        if not isinstance(code, str) or not code.isalnum() or not _positive_int(fight_id):
            rejected.append({"rank": rank, "reason": "incomplete_identity"})
            continue
        identity = (code, fight_id, source_id if source_id is not None else item.get("name"))
        if identity in seen:
            rejected.append({"rank": rank, "reason": "duplicate_identity"})
            continue
        seen.add(identity)
        candidate = {
            "rank": item.get("rank", rank),
            "score": item.get("rankPercent", item.get("score", item.get("amount"))),
            "report_code": code,
            "fight_id": fight_id,
            "source_id": source_id,
            "name": item.get("name"),
            "class_name": item.get("class"),
            "spec_name": item.get("spec"),
            "server": item.get("server", {}).get("name") if isinstance(item.get("server"), dict) else None,
            "start_time": item.get("startTime", report.get("startTime")),
            "url": f"https://www.warcraftlogs.com/reports/{code}#fight={fight_id}&source={source_id}",
        }
        timestamp = _timestamp(candidate["start_time"])
        if timestamp is None:
            unverified.append(candidate)
        elif timestamp >= cutoff:
            recent.append(candidate)
        else:
            rejected.append(candidate | {"reason": "outside_recent_window"})
    return {
        "eligible_recent_candidates": recent,
        "unverified_recency_candidates": unverified,
        "rejected_candidates": rejected,
    }


def identify_cohort(cohort: dict[str, Any]) -> dict[str, Any]:
    identified = dict(cohort)
    identified.pop("cohort_id", None)
    identified.pop("signature", None)
    return identified | {"cohort_id": _content_id(identified)}


def verify_cohort(cohort: dict[str, Any]) -> None:
    if type(cohort.get("schema_version")) is not int or cohort["schema_version"] != 2 or "signature" in cohort:
        raise InputError("Ranking Cohort uses an unsupported schema version; discover candidates again.")
    cohort_id = cohort.get("cohort_id")
    if not isinstance(cohort_id, str) or cohort_id != identify_cohort(cohort)["cohort_id"]:
        raise InputError("Ranking Cohort content ID is missing or invalid.")


def identify_benchmark(benchmark: dict[str, Any]) -> dict[str, Any]:
    identified = dict(benchmark)
    identified.pop("benchmark_id", None)
    identified.pop("signature", None)
    return identified | {"benchmark_id": _content_id(identified)}


def verify_benchmark(benchmark: dict[str, Any]) -> None:
    if type(benchmark.get("schema_version")) is not int or benchmark["schema_version"] != 2 or "signature" in benchmark:
        raise InputError("Encounter Benchmark uses an unsupported schema version; build it again.")
    if not _sha256_id(benchmark.get("cohort_id")):
        raise InputError("Encounter Benchmark Ranking Cohort content ID is missing or invalid.")
    benchmark_id = benchmark.get("benchmark_id")
    if not isinstance(benchmark_id, str) or benchmark_id != identify_benchmark(benchmark)["benchmark_id"]:
        raise InputError("Encounter Benchmark content ID is missing or invalid.")


def validate_analysis_membership(analyses: list[dict[str, Any]], cohort: dict[str, Any]) -> None:
    verify_cohort(cohort)
    candidates = cohort.get("eligible_recent_candidates")
    if not isinstance(candidates, list):
        raise InputError("Ranking Cohort has no eligible recent candidates.")
    allowed = {
        (item.get("report_code"), item.get("fight_id"), item.get("source_id"))
        for item in candidates
        if isinstance(item, dict)
    }
    seen = set()
    for analysis in analyses:
        if (
            not isinstance(analysis, dict)
            or type(analysis.get("schema_version")) is not int
            or analysis["schema_version"] != ANALYSIS_SCHEMA_VERSION
        ):
            raise InputError("Personal Analysis uses an unsupported schema version; run coach review again.")
        identity = analysis.get("identity") if isinstance(analysis, dict) else None
        player = analysis.get("player") if isinstance(analysis, dict) else None
        key_value = (
            identity.get("report_code") if isinstance(identity, dict) else None,
            identity.get("fight_id") if isinstance(identity, dict) else None,
            player.get("actor_id") if isinstance(player, dict) else None,
        )
        if key_value not in allowed:
            raise InputError("Analysis is absent from the content-addressed Ranking Cohort.")
        if key_value in seen:
            raise InputError("Duplicate Reference Sample analysis.")
        seen.add(key_value)
        evidence = analysis.get("evidence") if isinstance(analysis, dict) else None
        if not isinstance(evidence, dict):
            raise InputError("Reference Sample analysis has no Complete Bundle provenance.")
        try:
            manifest_path = Path(str(evidence["manifest_path"]))
            index_path = Path(str(evidence["index_path"]))
        except KeyError as exc:
            raise InputError("Reference Sample provenance is incomplete.") from exc
        if sha256_file(manifest_path) != evidence.get("manifest_sha256") or sha256_file(index_path) != evidence.get("index_sha256"):
            raise InputError("Reference Sample provenance hash is invalid.")
        comparison_identity = analysis.get("comparison_identity")
        if not isinstance(comparison_identity, dict):
            raise InputError("Reference Sample comparison identity is malformed.")
        partition_id = comparison_identity.get("partition_id")
        recomputed = analyze_player(manifest_path, index_path, key_value[2], partition_id=partition_id)
        if recomputed != analysis:
            raise InputError("Reference Sample analysis does not match its Complete Bundle evidence.")


def build_benchmark(
    analyses: list[dict[str, Any]],
    encounter_profile: dict[str, Any],
    specialization_profile: dict[str, Any],
    expected: dict[str, Any],
    *,
    cohort_id: str,
) -> dict[str, Any]:
    profile = validate_profile(encounter_profile, "encounter")
    spec_profile = validate_profile(specialization_profile, "specialization")
    profile_identity = profile["identity"]
    for field in ("game_version", "encounter_id", "difficulty_id", "partition_id"):
        if profile_identity.get(field) != expected.get(field):
            raise InputError(f"Encounter Profile {field} does not match the requested benchmark.")
    for field in ("game_version", "partition_id", "class_name", "spec_name"):
        if spec_profile["identity"].get(field) != expected.get(field):
            raise InputError(f"Specialization Profile {field} does not match the requested benchmark.")
    accepted = []
    rejected = []
    priority_ids = {str(item) for item in profile["eligibility"]["priority_target_ids"]}
    excluded_ids = {str(item) for item in profile["eligibility"]["excluded_target_ids"]}
    role = specialization_role(str(expected.get("class_name")), str(expected.get("spec_name")))
    for index, analysis in enumerate(analyses, 1):
        if not all(isinstance(analysis.get(field), dict) for field in ("identity", "player", "evidence")):
            rejected.append({"sample": index, "reason": "missing_complete_bundle_provenance"})
            continue
        reason = _analysis_rejection(analysis, expected, priority_ids, excluded_ids, role)
        if reason:
            rejected.append({"sample": index, "reason": reason})
        else:
            accepted.append(analysis)
    if len(accepted) < 3:
        raise InputError("Fewer than three Reference Samples passed Encounter Profile eligibility.")
    casts: dict[str, list[int]] = {}
    first_casts: dict[str, list[float]] = {}
    target_damage: dict[str, list[int]] = {}
    for analysis in accepted:
        metrics = analysis.get("metrics")
        if not isinstance(metrics, dict) or not isinstance(metrics.get("casts", {}), dict):
            raise InputError("Reference Sample cast metrics are malformed.")
        if not isinstance(metrics.get("damage_total"), (int, float)) or isinstance(metrics.get("damage_total"), bool):
            raise InputError("Reference Sample damage total is malformed.")
        for ability, count in metrics.get("casts", {}).items():
            if not isinstance(count, (int, float)) or isinstance(count, bool):
                raise InputError("Reference Sample cast count is malformed.")
            casts.setdefault(ability, []).append(count)
        first_cast_metrics = metrics.get("first_cast_ms", {})
        target_metrics = metrics.get("damage_by_target", {})
        if not isinstance(first_cast_metrics, dict) or not isinstance(target_metrics, dict):
            raise InputError("Reference Sample timing or target metrics are malformed.")
        for ability, timestamp in first_cast_metrics.items():
            if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
                raise InputError("Reference Sample first-cast timing is malformed.")
            first_casts.setdefault(ability, []).append(timestamp)
        for target, amount in target_metrics.items():
            if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                raise InputError("Reference Sample target damage is malformed.")
            target_damage.setdefault(target, []).append(amount)
    return {
        "schema_version": 2,
        "cohort_id": cohort_id,
        "identity": dict(expected),
        "encounter_profile_id": profile["profile_id"],
        "specialization_profile_id": spec_profile["profile_id"],
        "sources": {"encounter": profile["sources"], "specialization": spec_profile["sources"]},
        "mechanic_anchors": [dict(anchor) for anchor in profile["mechanic_anchors"]],
        "reference_samples": [
            {"identity": item["identity"], "player": item["player"], "evidence": item["evidence"]}
            for item in accepted
        ],
        "sample_count": len(accepted),
        "role": role,
        "confidence": "normal" if len(accepted) == 10 else "low",
        "stable_pattern_claims_allowed": len(accepted) >= 3,
        "metrics": {
            "damage_total_median": median(item["metrics"]["damage_total"] for item in accepted),
            "casts_median": {ability: median(values) for ability, values in sorted(casts.items())},
            "first_cast_ms_median": {ability: median(values) for ability, values in sorted(first_casts.items())},
            "damage_by_target_median": {target: median(values) for target, values in sorted(target_damage.items())},
        },
        "rejected_samples": rejected,
    }


def _content_id(value: dict[str, Any]) -> str:
    message = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(message).hexdigest()


def _sha256_id(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _analysis_rejection(
    analysis: Any,
    expected: dict[str, Any],
    priority_ids: set[str],
    excluded_ids: set[str],
    role: str,
) -> str | None:
    if not isinstance(analysis, dict) or not isinstance(analysis.get("metrics"), dict):
        return "malformed_analysis"
    identity = analysis.get("comparison_identity")
    if not isinstance(identity, dict) or any(identity.get(field) != value for field, value in expected.items()):
        return "hard_condition_mismatch"
    metrics = analysis["metrics"]
    if metrics.get("deaths", 0):
        return "player_death"
    if role == "healer":
        if not isinstance(metrics.get("healing_total"), (int, float)) or metrics["healing_total"] <= 0:
            return "missing_healing_evidence"
        return None
    targets = metrics.get("damage_by_target")
    if not isinstance(targets, dict):
        return "missing_target_damage"
    useful = sum(amount for target, amount in targets.items() if target in priority_ids and isinstance(amount, int))
    padding = sum(amount for target, amount in targets.items() if target in excluded_ids and isinstance(amount, int))
    if priority_ids and useful <= 0:
        return "no_priority_target_damage"
    if padding > useful and useful > 0:
        return "excluded_target_damage_dominates"
    return None


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(timestamp, timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
