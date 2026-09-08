from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from .analysis import ANALYSIS_SCHEMA_VERSION
from .cohort import verify_benchmark
from .comparison import compare_player, verify_analysis_evidence
from .errors import InputError
from .profiles import validate_profile
from .storage import artifact_lock, atomic_write_json, read_json, sha256_file


ADVICE_SCHEMA_VERSION = 2
FULL_SOURCE_KINDS = ("personal_analysis", "encounter_benchmark", "comparison", "encounter_profile", "specialization_profile")
PARTIAL_SOURCE_KINDS = ("personal_analysis", "encounter_profile", "specialization_profile")
ACTION_KINDS = {"use_ability", "review_fact", "observe_pattern", "adjust_timing"}
CONDITION_KINDS = {"effective_window", "mechanic_safe", "target_available", "next_attempt"}
VERIFICATION_KINDS = {"compare_next_attempt", "check_event_fact", "check_ability_usage"}
FACT_PATHS = {
    "output": {
        "personal_analysis": {
            "/metrics/damage_total", "/metrics/healing_total",
            "/metrics/damage_per_minute", "/metrics/healing_per_minute",
        },
        "encounter_benchmark": {
            "/metrics/damage_total_median", "/metrics/damage_per_minute_median",
            "/metrics/healing_per_minute_median",
        },
        "comparison": {
            "/metrics/damage_total_delta", "/metrics/reference_damage_total_median",
            "/metrics/damage_per_minute_delta", "/metrics/healing_per_minute_delta",
            "/metrics/reference_damage_per_minute_median", "/metrics/reference_healing_per_minute_median",
        },
    },
    "survival": {
        "personal_analysis": {"/metrics/deaths"},
        "comparison": {"/guardrails/player_death"},
    },
    "mechanics": {},
    "team_contribution": {
        "personal_analysis": {
            "/metrics/interrupts", "/metrics/healing_total",
            "/metrics/healing_per_minute", "/metrics/resource_events",
        },
    },
}
ABILITY_FACT_PREFIXES = {
    "output": {
        "personal_analysis": (
            "/metrics/player_casts/", "/metrics/player_first_cast_ms/",
            "/metrics/player_casts_per_minute/",
        ),
        "encounter_benchmark": (
            "/metrics/key_action_casts_median/", "/metrics/key_action_casts_per_minute_median/",
            "/metrics/key_action_rate_sample_count/", "/metrics/key_action_first_cast_ms_median/",
        ),
        "comparison": (
            "/metrics/cast_count_deltas/", "/metrics/key_action_casts_per_minute_deltas/",
            "/metrics/key_action_player_casts_per_minute/",
            "/metrics/key_action_reference_casts_per_minute_median/",
            "/metrics/key_action_rate_sample_counts/",
        ),
    },
    "survival": {},
    "mechanics": {},
    "team_contribution": {},
}


def create_coaching_advice(
    draft: Any,
    analysis_path: Path,
    benchmark_path: Path | None,
    comparison_path: Path | None,
    output_dir: Path,
    encounter_profile_path: Path,
    specialization_profile_path: Path,
) -> dict[str, Any]:
    if (benchmark_path is None) != (comparison_path is None):
        raise InputError("Coaching Advice requires both Benchmark and Comparison or neither.")
    paths: dict[str, Path] = {
        "personal_analysis": analysis_path.expanduser().resolve(),
        "encounter_profile": encounter_profile_path.expanduser().resolve(),
        "specialization_profile": specialization_profile_path.expanduser().resolve(),
    }
    if benchmark_path is not None and comparison_path is not None:
        paths["encounter_benchmark"] = benchmark_path.expanduser().resolve()
        paths["comparison"] = comparison_path.expanduser().resolve()
    sources = {kind: _read_object(path, kind) for kind, path in paths.items()}
    _verify_sources(sources)
    artifact = _build_artifact(draft, paths, sources)
    advice_id = hashlib.sha256(_canonical_bytes(artifact)).hexdigest()
    artifact["advice_id"] = advice_id
    path = output_dir.expanduser().resolve() / f"{advice_id}.json"
    expected_bytes = _json_file_bytes(artifact)
    expected_sha256 = hashlib.sha256(expected_bytes).hexdigest()
    created = False
    with artifact_lock(path):
        if path.exists():
            try:
                payload = path.read_bytes()
            except OSError as exc:
                raise InputError("Existing Coaching Advice is unreadable.") from exc
            if payload != expected_bytes or hashlib.sha256(payload).hexdigest() != expected_sha256:
                raise InputError("Existing Coaching Advice has an invalid identity.")
        else:
            atomic_write_json(path, artifact)
            created = True
    return {"path": str(path), "sha256": expected_sha256, "artifact": artifact, "created": created}


def verify_coaching_advice(
    value: Any,
    sources: dict[str, dict[str, Any]],
    source_refs: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    advice = _object(value, "Coaching Advice")
    _fields(advice, "Coaching Advice", {
        "schema_version", "artifact_type", "advice_id", "locale", "identity",
        "source_artifacts", "items",
    })
    if advice["schema_version"] != ADVICE_SCHEMA_VERSION or advice["artifact_type"] != "coaching_advice":
        raise InputError("Coaching Advice uses an unsupported schema or artifact type.")
    body = dict(advice)
    claimed_id = body.pop("advice_id")
    if not _digest(claimed_id) or hashlib.sha256(_canonical_bytes(body)).hexdigest() != claimed_id:
        raise InputError("Coaching Advice content ID is missing or invalid.")
    refs = _source_artifacts(advice["source_artifacts"])
    if not isinstance(sources, dict) or any(not isinstance(source, dict) for source in sources.values()):
        raise InputError("Coaching Advice source values must be objects.")
    for kind in ("encounter_profile", "specialization_profile"):
        ref = refs[kind]
        path = Path(ref["path"])
        try:
            if ref.get("sha256") != sha256_file(path):
                raise InputError("Coaching Advice Profile artifact hash is invalid.")
            profile = _read_object(path, kind)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise InputError("Coaching Advice Profile artifact is missing or unreadable.") from exc
        if kind in sources and sources[kind] != profile:
            raise InputError("Coaching Advice Profile artifact does not match the supplied source.")
        sources[kind] = profile
    _verify_sources(sources)
    expected_identity = _identity(sources)
    if advice["identity"] != expected_identity:
        raise InputError("Coaching Advice player, Boss Attempt, Report Revision, or Benchmark identity does not match.")
    if source_refs is not None and refs != source_refs:
        raise InputError("Coaching Advice source provenance does not match the Personal Review sources.")
    return {
        "schema_version": ADVICE_SCHEMA_VERSION,
        "artifact_type": "coaching_advice",
        "advice_id": claimed_id,
        "locale": _locale(advice["locale"]),
        "identity": expected_identity,
        "source_artifacts": refs,
        "items": _items(advice["items"], sources),
    }


def _build_artifact(
    draft: Any, paths: dict[str, Path], sources: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    draft = _object(draft, "Coaching Advice draft")
    _fields(draft, "Coaching Advice draft", {"schema_version", "locale", "items"})
    if draft["schema_version"] != ADVICE_SCHEMA_VERSION:
        raise InputError("Coaching Advice draft schema_version is unsupported.")
    return {
        "schema_version": ADVICE_SCHEMA_VERSION,
        "artifact_type": "coaching_advice",
        "locale": _locale(draft["locale"]),
        "identity": _identity(sources),
        "source_artifacts": {
            kind: {"path": str(paths[kind]), "sha256": sha256_file(paths[kind])}
            for kind in paths
        },
        "items": _items(draft["items"], sources),
    }


def _verify_sources(sources: dict[str, dict[str, Any]]) -> None:
    if (
        not isinstance(sources, dict)
        or any(not isinstance(source, dict) for source in sources.values())
        or set(sources) not in (set(FULL_SOURCE_KINDS), set(PARTIAL_SOURCE_KINDS))
    ):
        raise InputError("Coaching Advice sources are incomplete.")
    analysis = sources["personal_analysis"]
    encounter_profile = validate_profile(sources["encounter_profile"], "encounter")
    specialization_profile = validate_profile(sources["specialization_profile"], "specialization")
    if type(analysis.get("schema_version")) is not int or analysis["schema_version"] != ANALYSIS_SCHEMA_VERSION:
        raise InputError("Personal Analysis uses an unsupported schema version; run coach review again.")
    verify_analysis_evidence(analysis)
    identity = analysis.get("comparison_identity")
    if not isinstance(identity, dict):
        raise InputError("Personal Analysis comparison identity is malformed.")
    for field in ("game_version", "partition_id", "encounter_id", "difficulty_id"):
        if encounter_profile["identity"].get(field) != identity.get(field):
            raise InputError("Coaching Advice Encounter Profile does not match the Personal Analysis.")
    for field in ("game_version", "partition_id", "class_name", "spec_name"):
        if specialization_profile["identity"].get(field) != identity.get(field):
            raise InputError("Coaching Advice Specialization Profile does not match the Personal Analysis.")
    if "encounter_benchmark" in sources:
        benchmark = sources["encounter_benchmark"]
        comparison = sources["comparison"]
        verify_benchmark(benchmark)
        if comparison != compare_player(analysis, benchmark) or comparison.get("schema_version") != 3:
            raise InputError("Coaching Advice Comparison source does not match its Analysis and Benchmark.")
        if benchmark.get("encounter_profile_id") != encounter_profile["profile_id"] or benchmark.get("specialization_profile_id") != specialization_profile["profile_id"]:
            raise InputError("Coaching Advice Profiles do not match the Encounter Benchmark identities.")
        for kind, profile in (("encounter", encounter_profile), ("specialization", specialization_profile)):
            if benchmark.get("sources", {}).get(kind) != profile["sources"]:
                raise InputError("Coaching Advice Benchmark Profile sources do not match the local Profile artifact.")


def _identity(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    analysis = sources["personal_analysis"]
    identity = _object(analysis.get("identity"), "Personal Analysis identity")
    player = _object(analysis.get("player"), "Personal Analysis player")
    return {
        "report_code": identity.get("report_code"),
        "report_revision": identity.get("report_revision"),
        "fight_id": identity.get("fight_id"),
        "actor_id": player.get("actor_id"),
        "benchmark_id": sources.get("encounter_benchmark", {}).get("benchmark_id"),
    }


def _items(value: Any, sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 20:
        raise InputError("Coaching Advice items must be a list with at most 20 items.")
    result = []
    player_cast_abilities = {
        ability["id"]
        for ability in validate_profile(sources["specialization_profile"], "specialization")["abilities"]
        if ability.get("action_type") == "player_cast"
    }
    for value in value:
        item = _object(value, "Coaching Advice item")
        _fields(item, "Coaching Advice item", {
            "dimension", "evidence_class", "action", "conditions", "verification_goal",
            "ability_ids", "fact_references", "guidance_references",
        })
        if item["dimension"] not in {"output", "survival", "mechanics", "team_contribution"}:
            raise InputError("Coaching Advice dimension is invalid.")
        if item["evidence_class"] not in {"event_supported", "experience_based"}:
            raise InputError("Coaching Advice evidence_class is invalid.")
        ability_ids = _ability_ids(item["ability_ids"])
        if any(ability_id not in player_cast_abilities for ability_id in ability_ids):
            raise InputError("Coaching Advice ability_ids require Specialization Profile player_cast declarations.")
        action = _action(item["action"], ability_ids, player_cast_abilities)
        goal = _verification_goal(item["verification_goal"])
        conditions = _conditions(item["conditions"])
        facts = _fact_references(item["fact_references"], sources, ability_ids)
        guidance = _guidance_references(item["guidance_references"], sources)
        validate_advice_evidence(item["dimension"], item["evidence_class"], action, facts)
        if item["evidence_class"] == "experience_based" and not guidance:
            raise InputError("Experience-based Coaching Advice requires current guidance.")
        result.append({
            "dimension": item["dimension"], "evidence_class": item["evidence_class"],
            "action": action, "conditions": conditions, "verification_goal": goal,
            "ability_ids": ability_ids, "fact_references": facts,
            "guidance_references": guidance,
        })
    return result


def _fact_references(
    value: Any, sources: dict[str, dict[str, Any]], ability_ids: list[int]
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 20:
        raise InputError("Coaching Advice fact_references must be a list with at most 20 items.")
    result = []
    for value in value:
        ref = _object(value, "Coaching Advice fact reference")
        _fields(ref, "Coaching Advice fact reference", {"source", "path", "value"})
        source = ref["source"]
        path = ref["path"]
        if source not in {"personal_analysis", "encounter_benchmark", "comparison"} or not isinstance(path, str):
            raise InputError("Coaching Advice fact reference path is unsupported.")
        if source not in sources:
            raise InputError("Coaching Advice fact reference source is unavailable.")
        actual = _pointer(sources[source], path)
        if not _scalar(actual) or actual != ref["value"] or type(actual) is not type(ref["value"]):
            raise InputError("Coaching Advice fact reference value does not match its source.")
        ability_id = _ability_fact_id(source, path)
        if ability_id is not None and ability_id not in ability_ids:
            raise InputError("Coaching Advice ability fact references require matching ability_ids.")
        result.append({"source": source, "path": path, "value": actual})
    return result


def validate_advice_evidence(
    dimension: str, evidence_class: str, action: dict[str, Any], facts: list[dict[str, Any]]
) -> None:
    if evidence_class == "event_supported" and dimension == "mechanics":
        raise InputError("Mechanics event-supported Coaching Advice requires Mechanic Review evidence, which Personal Review does not contain.")
    if evidence_class == "event_supported" and not facts:
        raise InputError("Event-supported Coaching Advice requires a dimension-relevant local fact reference.")
    ability_facts = set()
    for fact in facts:
        source, path = fact["source"], fact["path"]
        ability_id = _ability_fact_id(source, path, dimension)
        if path not in FACT_PATHS.get(dimension, {}).get(source, set()) and ability_id is None:
            raise InputError("Coaching Advice fact reference is not eligible for its dimension; ability recommendations require direct-player key-action/player_cast metrics.")
        if ability_id is not None:
            ability_facts.add(ability_id)
    action_ability = action.get("ability_id")
    if evidence_class == "event_supported" and action_ability is not None and action_ability not in ability_facts:
        raise InputError("Event-supported Coaching Advice ability action requires a matching ability fact reference.")


def _ability_fact_id(source: str, path: str, dimension: str | None = None) -> int | None:
    dimensions = (dimension,) if dimension is not None else ABILITY_FACT_PREFIXES
    for candidate in dimensions:
        for prefix in ABILITY_FACT_PREFIXES.get(candidate, {}).get(source, ()):
            suffix = path.removeprefix(prefix) if path.startswith(prefix) else ""
            if suffix.isdigit() and int(suffix) > 1:
                return int(suffix)
    return None


def _guidance_references(value: Any, sources_by_kind: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 10:
        raise InputError("Coaching Advice guidance_references must be a list with at most 10 items.")
    benchmark = sources_by_kind.get("encounter_benchmark", {})
    sources = benchmark.get("sources") if benchmark else {
        "encounter": sources_by_kind["encounter_profile"]["sources"],
        "specialization": sources_by_kind["specialization_profile"]["sources"],
    }
    result = []
    for value in value:
        ref = _object(value, "Coaching Advice guidance reference")
        if set(ref) == {
            "profile_kind", "profile_id", "title", "url", "accessed_at",
            "quote_summary", "content_hash",
        }:
            kind = ref["profile_kind"]
            available = sources.get(kind)
            profile_id = benchmark.get(f"{kind}_profile_id") or sources_by_kind.get(f"{kind}_profile", {}).get("profile_id")
            if (
                kind not in {"encounter", "specialization"}
                or not isinstance(available, list)
                or ref.get("profile_id") != profile_id
                or not any(_guidance_source(item) == {
                    field: ref[field]
                    for field in ("title", "url", "accessed_at", "quote_summary", "content_hash")
                } for item in available)
            ):
                raise InputError("Coaching Advice guidance reference does not match its Profile source.")
            result.append(dict(ref))
            continue
        _fields(ref, "Coaching Advice guidance reference", {"profile_kind", "source_index"})
        kind = ref["profile_kind"]
        index = ref["source_index"]
        if kind not in {"encounter", "specialization"} or type(index) is not int or index < 0:
            raise InputError("Coaching Advice guidance reference is invalid.")
        available = sources.get(kind)
        if not isinstance(available, list) or index >= len(available):
            raise InputError("Coaching Advice guidance reference is absent from the Benchmark Profiles.")
        source = _guidance_source(available[index])
        profile_id = benchmark.get(f"{kind}_profile_id") or sources_by_kind[f"{kind}_profile"]["profile_id"]
        if not _digest(profile_id):
            raise InputError("Coaching Advice guidance Profile identity is missing.")
        result.append({"profile_kind": kind, "profile_id": profile_id, **source})
    return result


def _guidance_source(value: Any) -> dict[str, str]:
    source = _object(value, "Coaching Advice guidance source")
    required = ("title", "url", "accessed_at", "quote_summary", "content_hash")
    result = {field: _text(source.get(field), f"Coaching Advice guidance {field}", 1000) for field in required}
    if not _digest(result["content_hash"]):
        raise InputError("Coaching Advice guidance content_hash must be a SHA-256 digest.")
    try:
        datetime.fromisoformat(result["accessed_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputError("Coaching Advice guidance accessed_at must be ISO 8601.") from exc
    result["url"] = _public_url(result["url"])
    return result


def _source_artifacts(value: Any) -> dict[str, dict[str, str]]:
    refs = _object(value, "Coaching Advice source_artifacts")
    if set(refs) not in (set(FULL_SOURCE_KINDS), set(PARTIAL_SOURCE_KINDS)):
        raise InputError("Coaching Advice source_artifacts are incomplete.")
    result = {}
    for kind, value in refs.items():
        ref = _object(value, "Coaching Advice source artifact")
        _fields(ref, "Coaching Advice source artifact", {"path", "sha256"})
        digest = ref["sha256"]
        if not _digest(digest):
            raise InputError("Coaching Advice source artifact hash is invalid.")
        result[kind] = {"path": _text(ref["path"], "Coaching Advice source artifact path", 1000), "sha256": digest}
    return result


def _pointer(value: Any, path: str) -> Any:
    if not path.startswith("/") or "~" in path:
        raise InputError("Coaching Advice fact reference path is malformed.")
    current = value
    for segment in path[1:].split("/"):
        if not isinstance(current, dict) or segment not in current:
            raise InputError("Coaching Advice fact reference path is absent from its source.")
        current = current[segment]
    return current


def _ability_ids(value: Any) -> list[int]:
    if not isinstance(value, list) or len(value) > 20 or any(type(item) is not int or item <= 1 for item in value):
        raise InputError("Coaching Advice ability_ids must contain at most 20 client Spell IDs.")
    if len(set(value)) != len(value):
        raise InputError("Coaching Advice ability_ids must be unique.")
    return value


def _text_list(value: Any, label: str, maximum: int, text_maximum: int, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum or nonempty and not value:
        raise InputError(f"{label} must contain between {1 if nonempty else 0} and {maximum} items.")
    return [_prose(item, label, text_maximum) for item in value]


def _prose(value: Any, label: str, maximum: int) -> str:
    text = _text(value, label, maximum)
    if any(character.isdigit() for character in text):
        raise InputError(f"{label} must cite numbers through structured fact references.")
    return text


def _action(value: Any, ability_ids: list[int], player_cast_abilities: set[int]) -> dict[str, Any]:
    action = _object(value, "Coaching Advice action")
    _fields(action, "Coaching Advice action", {"kind", "ability_id"})
    if action["kind"] not in ACTION_KINDS:
        raise InputError("Coaching Advice action kind is unsupported.")
    ability_id = action["ability_id"]
    if ability_id is not None and (type(ability_id) is not int or ability_id <= 1):
        raise InputError("Coaching Advice action ability_id must be a client Spell ID.")
    if action["kind"] == "use_ability" and ability_id is None:
        raise InputError("Coaching Advice use_ability action requires ability_id.")
    if ability_id is not None and ability_id not in ability_ids:
        raise InputError("Coaching Advice action ability_id must be listed in ability_ids.")
    if ability_id is not None and ability_id not in player_cast_abilities:
        raise InputError("Coaching Advice ability actions require a Specialization Profile player_cast declaration.")
    return {"kind": action["kind"], "ability_id": ability_id}


def _conditions(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 10 or any(item not in CONDITION_KINDS for item in value):
        raise InputError("Coaching Advice conditions must use supported structured kinds.")
    return list(value)


def _verification_goal(value: Any) -> str:
    if value not in VERIFICATION_KINDS:
        raise InputError("Coaching Advice verification_goal must use a supported structured kind.")
    return value


def _public_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        parameters = parse_qsl(parsed.query, keep_blank_values=True) + parse_qsl(parsed.fragment, keep_blank_values=True)
    except ValueError as exc:
        raise InputError("Coaching Advice guidance URL is malformed.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None:
        raise InputError("Coaching Advice guidance URL must be public HTTP or HTTPS.")
    sensitive = {"accesstoken", "apikey", "auth", "authentication", "authorization", "clientsecret", "credential", "key", "secret", "signature", "token", "xamzcredential", "xamzsignature"}
    names = []
    for name, _ in parameters:
        while (decoded := unquote(name)) != name:
            name = decoded
        names.append(re.sub(r"[^a-z0-9]", "", name.lower()))
    if any(name in sensitive for name in names):
        raise InputError("Coaching Advice guidance URL must not contain credentials.")
    return value


def _read_object(path: Path, kind: str) -> dict[str, Any]:
    try:
        value = read_json(path)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"Coaching Advice {kind} source must be valid UTF-8 JSON.") from exc
    return _object(value, f"Coaching Advice {kind} source")


def _locale(value: Any) -> str:
    if value not in {"zh-CN", "en"}:
        raise InputError("Coaching Advice locale must be zh-CN or en.")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{label} must be an object.")
    return value


def _fields(value: dict[str, Any], label: str, required: set[str]) -> None:
    if missing := sorted(required - value.keys()):
        raise InputError(f"{label} is missing field: {missing[0]}.")
    if unexpected := sorted(value.keys() - required):
        raise InputError(f"{label} has unexpected field: {unexpected[0]}.")


def _text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InputError(f"{label} must be non-empty text with at most {maximum} characters.")
    return value.strip()


def _digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, str) or isinstance(value, bool) or (
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _json_file_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
