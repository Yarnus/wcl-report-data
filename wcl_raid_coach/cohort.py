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
from .analysis import ANALYSIS_SCHEMA_VERSION, analyze_player, is_finite_number, per_minute, valid_duration_ms
from .storage import sha256_file


REFERENCE_SAMPLE_MAX = 10


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
    seen: set[tuple[str, int, int]] = set()
    for rank, item in enumerate(rankings, 1):
        if not isinstance(item, dict):
            rejected.append({"rank": rank, "reason": "malformed_candidate"})
            continue
        candidate_rank = item.get("rank", rank)
        candidate_score = item.get("rankPercent", item.get("score", item.get("amount")))
        if not _json_number(candidate_rank) or candidate_score is not None and not _json_number(candidate_score):
            raise InputError("Ranking Candidate rank and score must be finite JSON numbers.")
        report = item.get("report")
        report = report if isinstance(report, dict) else {}
        code = item.get("reportCode", report.get("code"))
        fight_id = item.get("fightID", item.get("fightId", report.get("fightID")))
        source_id = item.get("sourceID", item.get("sourceId", item.get("actorID")))
        if not isinstance(code, str) or not code.isalnum() or not _positive_int(fight_id):
            rejected.append({"rank": rank, "reason": "incomplete_identity"})
            continue
        if source_id is not None and not _positive_int(source_id):
            rejected.append({"rank": rank, "reason": "incomplete_identity"})
            continue
        if _positive_int(source_id):
            identity = (code, fight_id, source_id)
            if identity in seen:
                rejected.append({"rank": rank, "reason": "duplicate_identity"})
                continue
            seen.add(identity)
        candidate = {
            "rank": candidate_rank,
            "score": candidate_score,
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


def identify_cohort(cohort: Any) -> dict[str, Any]:
    identified = _validate_cohort_shape(cohort)
    identified.pop("cohort_id", None)
    identified.pop("signature", None)
    return identified | {"cohort_id": _content_id(identified)}


def verify_cohort(cohort: Any) -> None:
    cohort = _validate_cohort_shape(cohort)
    if type(cohort.get("schema_version")) is not int or cohort["schema_version"] != 2 or "signature" in cohort:
        raise InputError("Ranking Cohort uses an unsupported schema version; discover candidates again.")
    cohort_id = cohort.get("cohort_id")
    if not isinstance(cohort_id, str) or cohort_id != identify_cohort(cohort)["cohort_id"]:
        raise InputError("Ranking Cohort content ID is missing or invalid.")


def _validate_cohort_shape(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError("Ranking Cohort must be a JSON object.")
    cohort = dict(value)
    if "filters" in cohort and not isinstance(cohort["filters"], dict):
        raise InputError("Ranking Cohort filters must be a JSON object.")
    if "pagination" in cohort:
        pagination = cohort["pagination"]
        if not isinstance(pagination, dict):
            raise InputError("Ranking Cohort pagination must be a JSON object.")
        for field in ("first_page", "last_page", "next_page", "resume_page"):
            if field in pagination and not _positive_int(pagination[field]):
                raise InputError(f"Ranking Cohort pagination {field} must be a positive integer.")
        for field in ("has_more_pages", "truncated", "target_reached", "exhausted"):
            if field in pagination and type(pagination[field]) is not bool:
                raise InputError(f"Ranking Cohort pagination {field} must be boolean.")
        first = pagination.get("first_page")
        last = pagination.get("last_page")
        if (first is None) != (last is None) or first is not None and first > last:
            raise InputError("Ranking Cohort pagination page range is invalid.")
        exhausted = pagination.get("exhausted")
        has_more = pagination.get("has_more_pages")
        truncated = pagination.get("truncated")
        if (
            exhausted is True and (
                has_more is not False or truncated is not False or first is None
            )
            or has_more is False and truncated is False and exhausted is False
        ):
            raise InputError("Ranking Cohort pagination state is inconsistent.")
        next_pages = [pagination[field] for field in ("next_page", "resume_page") if field in pagination]
        if (
            len(set(next_pages)) > 1
            or next_pages and last is not None and next_pages[0] <= last
            or next_pages and exhausted is True
        ):
            raise InputError("Ranking Cohort pagination continuation metadata is invalid.")
    for field in (
        "eligible_recent_candidates", "unverified_recency_candidates", "rejected_candidates",
    ):
        if field in cohort and (
            not isinstance(cohort[field], list)
            or any(not isinstance(item, dict) for item in cohort[field])
        ):
            raise InputError(f"Ranking Cohort {field} must be a JSON array of objects.")
    return cohort


def identify_benchmark(benchmark: dict[str, Any]) -> dict[str, Any]:
    identified = dict(benchmark)
    identified.pop("benchmark_id", None)
    identified.pop("signature", None)
    return identified | {"benchmark_id": _content_id(identified)}


def verify_benchmark(benchmark: dict[str, Any]) -> None:
    if type(benchmark.get("schema_version")) is not int or benchmark["schema_version"] != 3 or "signature" in benchmark:
        raise InputError("Encounter Benchmark uses an unsupported schema version; build it again.")
    if not _sha256_id(benchmark.get("cohort_id")):
        raise InputError("Encounter Benchmark Ranking Cohort content ID is missing or invalid.")
    benchmark_id = benchmark.get("benchmark_id")
    if not isinstance(benchmark_id, str) or benchmark_id != identify_benchmark(benchmark)["benchmark_id"]:
        raise InputError("Encounter Benchmark content ID is missing or invalid.")
    sample_count = benchmark.get("sample_count")
    reference_samples = benchmark.get("reference_samples")
    if (
        type(sample_count) is not int
        or not 3 <= sample_count <= REFERENCE_SAMPLE_MAX
        or not isinstance(reference_samples, list)
        or sample_count != len(reference_samples)
    ):
        raise InputError("Encounter Benchmark must contain 3 to 10 matching Reference Samples.")


def verify_benchmark_for_cohort(
    benchmark: dict[str, Any],
    cohort: dict[str, Any],
    encounter_profile: dict[str, Any],
    specialization_profile: dict[str, Any],
) -> None:
    """Rebuild a Benchmark from its Complete Bundle evidence before reuse."""
    verify_benchmark(benchmark)
    verify_cohort(cohort)
    if benchmark.get("cohort_id") != cohort["cohort_id"]:
        raise InputError("Encounter Benchmark does not belong to the current Ranking Cohort.")
    samples = benchmark.get("reference_samples")
    if (
        not isinstance(samples, list)
        or not 3 <= len(samples) <= REFERENCE_SAMPLE_MAX
        or benchmark.get("sample_count") != len(samples)
        or not isinstance(benchmark.get("identity"), dict)
    ):
        raise InputError("Encounter Benchmark Reference Sample structure is invalid.")
    analyses = []
    for sample in samples:
        if not isinstance(sample, dict):
            raise InputError("Encounter Benchmark Reference Sample is malformed.")
        player = sample.get("player")
        evidence = sample.get("evidence")
        if not isinstance(player, dict) or not isinstance(evidence, dict):
            raise InputError("Encounter Benchmark Reference Sample provenance is incomplete.")
        try:
            analysis = analyze_player(
                Path(str(evidence["manifest_path"])),
                Path(str(evidence["index_path"])),
                player["actor_id"],
                partition_id=(benchmark.get("identity") or {}).get("partition_id"),
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise InputError("Encounter Benchmark Reference Sample evidence could not be verified.") from exc
        analyses.append(analysis)
    validate_analysis_membership(analyses, cohort)
    rebuilt = identify_benchmark(build_benchmark(
        analyses,
        encounter_profile,
        specialization_profile,
        benchmark.get("identity"),
        cohort_id=cohort["cohort_id"],
    ))
    if rebuilt != benchmark:
        raise InputError("Encounter Benchmark does not match its validated Reference Samples.")


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
    priority_ids = {str(item) for item in profile["eligibility"]["priority_target_ids"]}
    excluded_ids = {str(item) for item in profile["eligibility"]["excluded_target_ids"]}
    key_action_ids = sorted({
        str(item["id"]) for item in spec_profile["abilities"]
        if item.get("action_type") == "player_cast" and item["id"] > 1
    })
    accepted, rejected = qualify_reference_samples(
        analyses, expected, priority_ids, excluded_ids,
        specialization_role(str(expected.get("class_name")), str(expected.get("spec_name"))),
    )
    if len(accepted) < 3:
        raise InputError("Fewer than three Reference Samples passed Encounter Profile eligibility.")
    if len(accepted) > REFERENCE_SAMPLE_MAX:
        raise InputError("Encounter Benchmark exceeds the maximum of 10 qualified Reference Samples.")
    role = specialization_role(str(expected.get("class_name")), str(expected.get("spec_name")))

    casts: set[str] = set()
    first_casts: dict[str, list[float]] = {}
    target_damage: set[str] = set()
    for analysis in accepted:
        metrics = analysis.get("metrics")
        if not isinstance(metrics, dict) or not isinstance(metrics.get("casts", {}), dict):
            raise InputError("Reference Sample cast metrics are malformed.")
        if not is_finite_number(metrics.get("damage_total")) or metrics["damage_total"] < 0:
            raise InputError("Reference Sample damage total is malformed.")
        for field in ("player_casts", "player_first_cast_ms"):
            values = metrics.get(field, {})
            if not isinstance(values, dict) or any(
                not is_finite_number(value) or value < 0 for value in values.values()
            ):
                raise InputError(f"Reference Sample {field} metrics are malformed.")
        for ability, count in metrics.get("casts", {}).items():
            if not isinstance(count, (int, float)) or isinstance(count, bool):
                raise InputError("Reference Sample cast count is malformed.")
            casts.add(ability)
        first_cast_metrics = metrics.get("first_cast_ms", {})
        target_metrics = metrics.get("damage_by_npc", {})
        if not isinstance(first_cast_metrics, dict) or not isinstance(target_metrics, dict):
            raise InputError("Reference Sample timing or target metrics are malformed.")
        for ability, timestamp in first_cast_metrics.items():
            if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
                raise InputError("Reference Sample first-cast timing is malformed.")
            first_casts.setdefault(ability, []).append(timestamp)
        for target, amount in target_metrics.items():
            if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                raise InputError("Reference Sample target damage is malformed.")
            target_damage.add(target)


    durations = [valid_duration_ms(item["metrics"].get("duration_ms")) for item in accepted]
    valid_durations = [duration for duration in durations if duration is not None]
    damage_rates = [per_minute(item["metrics"]["damage_total"], duration)
                    for item, duration in zip(accepted, durations)]
    damage_rates = [rate for rate in damage_rates if rate is not None]
    healing_rates = [rate for item, duration in zip(accepted, durations)
                     if (rate := per_minute(item["metrics"].get("healing_total"), duration)) is not None]
    key_counts = {
        ability: [item["metrics"].get("player_casts", {}).get(ability, 0) for item in accepted]
        for ability in key_action_ids
    }
    key_rates = {
        ability: [rate for count, duration in zip(counts, durations)
                  if (rate := per_minute(count, duration)) is not None]
        for ability, counts in key_counts.items()
    }
    return {
        "schema_version": 3,
        "cohort_id": cohort_id,
        "identity": dict(expected),
        "encounter_profile_id": profile["profile_id"],
        "specialization_profile_id": spec_profile["profile_id"],
        "sources": {"encounter": profile["sources"], "specialization": spec_profile["sources"]},
        "mechanic_anchors": [dict(anchor) for anchor in profile["mechanic_anchors"]],
        "reference_samples": [
            {"identity": item["identity"], "player": item["player"], "evidence": item["evidence"],
             "duration_ms": duration, "damage_per_minute": per_minute(item["metrics"]["damage_total"], duration),
             "healing_per_minute": per_minute(item["metrics"].get("healing_total"), duration)}
            for item, duration in zip(accepted, durations)
        ],
        "sample_count": len(accepted),
        "role": role,
        "confidence": "normal" if len(accepted) == 10 else "low",
        "stable_pattern_claims_allowed": len(accepted) >= 3,
        "metrics": {
            "duration_ms_median": median(valid_durations) if valid_durations else None,
            "duration_ms_min": min(valid_durations) if valid_durations else None,
            "duration_ms_max": max(valid_durations) if valid_durations else None,
            "rate_sample_count": len(damage_rates),
            "damage_per_minute_median": median(damage_rates) if damage_rates else None,
            "healing_per_minute_median": median(healing_rates) if healing_rates else None,
            "healing_rate_sample_count": len(healing_rates),
            "key_action_casts_median": {ability: median(counts) for ability, counts in key_counts.items()},
            "key_action_casts_per_minute_median": {
                ability: median(rates) if rates else None for ability, rates in key_rates.items()
            },
            "key_action_rate_sample_count": {
                ability: len(rates) for ability, rates in key_rates.items()
            },
            "key_action_first_cast_ms_median": {
                ability: median(values) if (values := [item["metrics"]["player_first_cast_ms"][ability]
                    for item in accepted if ability in item["metrics"].get("player_first_cast_ms", {})]) else None
                for ability in key_counts
            },
            "damage_total_median": median(item["metrics"]["damage_total"] for item in accepted),
            "casts_median": {
                ability: median(item["metrics"].get("casts", {}).get(ability, 0) for item in accepted)
                for ability in sorted(casts)
            },
            "first_cast_ms_median": {ability: median(values) for ability, values in sorted(first_casts.items())},
            "damage_by_npc_median": {
                target: median(item["metrics"].get("damage_by_npc", {}).get(target, 0) for item in accepted)
                for target in sorted(target_damage)
            },
        },
        "rejected_samples": rejected,
    }


def qualify_reference_samples(
    analyses: list[dict[str, Any]], expected: dict[str, Any], priority_ids: set[str],
    excluded_ids: set[str], role: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted = []
    rejected = []
    for index, analysis in enumerate(analyses, 1):
        if not isinstance(analysis, dict) or not all(isinstance(analysis.get(field), dict) for field in ("identity", "player", "evidence")):
            rejected.append({"sample": index, "reason": "missing_complete_bundle_provenance"})
            continue
        reason = _analysis_rejection(analysis, expected, priority_ids, excluded_ids, role)
        if reason:
            rejected.append({"sample": index, "reason": reason})
        else:
            accepted.append(analysis)
    return accepted, rejected


def _content_id(value: dict[str, Any]) -> str:
    _reject_non_finite_floats(value)
    try:
        message = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (TypeError, ValueError) as exc:
        raise InputError("Canonical coaching artifacts must contain valid JSON values.") from exc
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
    if type(analysis.get("schema_version")) is not int or analysis["schema_version"] != ANALYSIS_SCHEMA_VERSION:
        return "unsupported_analysis_schema"
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
    targets = metrics.get("damage_by_npc")
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


def _json_number(value: Any) -> bool:
    return is_finite_number(value)


def _reject_non_finite_floats(value: Any) -> None:
    if isinstance(value, float) and not is_finite_number(value):
        raise InputError("Canonical coaching artifacts must not contain non-finite numbers.")
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                key == "rank" and not _json_number(item)
                or key == "score" and item is not None and not _json_number(item)
            ):
                raise InputError("Ranking Candidate rank and score must be finite JSON numbers.")
            _reject_non_finite_floats(key)
            _reject_non_finite_floats(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_non_finite_floats(item)
