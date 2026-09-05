from __future__ import annotations

import hashlib
import json
import math
import re
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from .analysis import ANALYSIS_SCHEMA_VERSION
from .cohort import verify_benchmark
from .comparison import compare_player
from .errors import InputError, WclRaidCoachError
from .guides import verify_guide_snapshot
from .storage import artifact_lock, atomic_write_json, atomic_write_text, read_json, sha256_file


DOCUMENT_SCHEMA_VERSION = 1
RENDERER_SCHEMA_VERSION = 1
EVIDENCE_EXCERPT_FIELDS = {
    "event_type", "ability_id", "source_id", "target_id", "amount",
    "duration_ms", "delta_ms", "episode", "outcome", "note",
}
MECHANIC_REVIEW_SOURCE_SCHEMA_VERSION = 1


def create_mechanic_review_report(
    review: Any, data_root: Path, *, locale: str = "zh-CN"
) -> dict[str, Any]:
    source = sanitize_mechanic_review(review)
    source_bytes = _json_file_bytes(source)
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    source_dir = data_root.expanduser().resolve() / "outputs" / "mechanic-reviews"
    source_path = source_dir / f"{source_sha256}.json"
    created = False
    try:
        with artifact_lock(source_path):
            if source_path.exists():
                if (
                    not source_path.is_file()
                    or sha256_file(source_path) != source_sha256
                    or read_json(source_path) != source
                ):
                    raise InputError("Existing Mechanic Review source has an invalid identity.")
            else:
                atomic_write_json(source_path, source)
                created = True
            try:
                document = assemble_mechanic_review_document(source, source_path, locale=locale)
                report = render_report_document(document, data_root / "outputs" / "reports")
            except BaseException:
                if created:
                    source_path.unlink(missing_ok=True)
                raise
    except BaseException:
        if created:
            try:
                source_dir.rmdir()
                source_dir.parent.rmdir()
            except OSError:
                pass
        raise
    return {
        "action": "coach_mechanic_report",
        "source": {"path": str(source_path), "sha256": source_sha256},
        "document": validate_report_document(document),
        "report": report,
    }


def sanitize_mechanic_review(value: Any) -> dict[str, Any]:
    try:
        review = _object(value, "Mechanic Review")
        if review.get("action") != "coach_mechanics" or review.get("selection_required") is not False:
            raise InputError("Only a completed Mechanic Review can be persisted.")
        identity = _object(review.get("identity"), "Mechanic Review identity")
        attempt = _object(review.get("boss_attempt"), "Mechanic Review Boss Attempt")
        evidence = _object(review.get("evidence"), "Mechanic Review evidence")
        if (
            evidence.get("class") != "mechanic_evidence_set"
            or evidence.get("storage") != "process_memory"
            or evidence.get("pagination_terminated") is not True
            or evidence.get("report_revision_checked_before_and_after") is not True
        ):
            raise InputError("Mechanic Review collection is not complete and revision-isolated.")
        mechanics = _list(review.get("mechanics"), "Mechanic Review mechanics", nonempty=True, maximum=50)
        return validate_mechanic_review_source({
            "schema_version": MECHANIC_REVIEW_SOURCE_SCHEMA_VERSION,
            "artifact_type": "mechanic_review",
            "identity": {
                "report_code": identity.get("report_code"),
                "report_revision": identity.get("report_revision"),
                "fight_id": identity.get("fight_id"),
                "encounter_id": identity.get("encounter_id"),
                "difficulty_id": identity.get("difficulty_id"),
                "encounter_name_en": attempt.get("name_en"),
                "encounter_name_zh": attempt.get("name_zh"),
                "difficulty_name": attempt.get("difficulty"),
                "start_time": attempt.get("start_time"),
                "end_time": attempt.get("end_time"),
                "outcome": "kill" if attempt.get("kill") is True else "wipe" if attempt.get("kill") is False else None,
                "boss_percentage": attempt.get("boss_percentage"),
            },
            "ruleset": review.get("ruleset"),
            "collection": {
                "event_count": evidence.get("event_count"),
                "page_count": evidence.get("page_count"),
                "pagination_terminated": True,
                "report_revision_checked_before_and_after": True,
                "storage": "minimal_excerpts",
            },
            "phases": _sanitize_source_phases(review.get("phases", [])),
            "mechanics": [_sanitize_source_mechanic(item) for item in mechanics],
            "scope_note": {
                "en": "Anomalies are verified event-pattern matches; they do not assign player responsibility, performance, or wipe causality.",
                "zh": "异常仅表示已验证事件模式命中，不表示玩家责任、表现评价或灭团因果。",
            },
        })
    except InputError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise InputError("Mechanic Review could not be sanitized for persistence.") from exc


def validate_mechanic_review_source(value: Any) -> dict[str, Any]:
    source = _object(value, "Mechanic Review source")
    if source.get("artifact_type") != "mechanic_review":
        raise InputError("Report Document mechanic_review source kind is invalid.")
    _fields(source, "Mechanic Review source", {
        "schema_version", "artifact_type", "identity", "ruleset", "collection",
        "phases", "mechanics", "scope_note",
    })
    if source.get("schema_version") != MECHANIC_REVIEW_SOURCE_SCHEMA_VERSION:
        raise InputError("Mechanic Review source schema_version is unsupported.")
    identity = _object(source["identity"], "Mechanic Review source identity")
    _fields(identity, "Mechanic Review source identity", {
        "report_code", "report_revision", "fight_id", "encounter_id", "difficulty_id",
        "encounter_name_en", "encounter_name_zh", "difficulty_name", "start_time",
        "end_time", "outcome", "boss_percentage",
    })
    report_code = _text(identity["report_code"], "Mechanic Review source report_code", 64)
    if re.fullmatch(r"[A-Za-z0-9]+", report_code) is None:
        raise InputError("Mechanic Review source report_code must be alphanumeric.")
    start = _finite_number(identity["start_time"], "Mechanic Review source start_time")
    end = _finite_number(identity["end_time"], "Mechanic Review source end_time")
    if end <= start or not float(end - start).is_integer():
        raise InputError("Mechanic Review source Boss Attempt range is invalid.")
    if identity["outcome"] not in {"kill", "wipe"}:
        raise InputError("Mechanic Review source outcome must be kill or wipe.")
    percentage = identity["boss_percentage"]
    if percentage is not None and (not _number(percentage) or not 0 <= float(percentage) <= 100):
        raise InputError("Mechanic Review source boss_percentage is invalid.")
    collection = _object(source["collection"], "Mechanic Review source collection")
    _fields(collection, "Mechanic Review source collection", {
        "event_count", "page_count", "pagination_terminated",
        "report_revision_checked_before_and_after", "storage",
    })
    if (
        collection["pagination_terminated"] is not True
        or collection["report_revision_checked_before_and_after"] is not True
        or collection["storage"] != "minimal_excerpts"
    ):
        raise InputError("Mechanic Review source does not establish complete collection.")
    phases = _validate_source_phases(source["phases"], int(end - start))
    mechanics = _validate_source_mechanics(source["mechanics"], int(end - start))
    scope_note = _validate_localized_text(source["scope_note"], "Mechanic Review source scope_note", 2000)
    return {
        "schema_version": MECHANIC_REVIEW_SOURCE_SCHEMA_VERSION,
        "artifact_type": "mechanic_review",
        "identity": {
            "report_code": report_code,
            "report_revision": _integer(identity["report_revision"], "Mechanic Review source report_revision", positive=True),
            "fight_id": _integer(identity["fight_id"], "Mechanic Review source fight_id", positive=True),
            "encounter_id": _integer(identity["encounter_id"], "Mechanic Review source encounter_id", positive=True),
            "difficulty_id": _integer(identity["difficulty_id"], "Mechanic Review source difficulty_id", positive=True),
            "encounter_name_en": _text(identity["encounter_name_en"], "Mechanic Review source encounter_name_en", 200),
            "encounter_name_zh": _text(identity["encounter_name_zh"], "Mechanic Review source encounter_name_zh", 200),
            "difficulty_name": _text(identity["difficulty_name"], "Mechanic Review source difficulty_name", 100),
            "start_time": start,
            "end_time": end,
            "outcome": identity["outcome"],
            "boss_percentage": float(percentage) if percentage is not None else None,
        },
        "ruleset": _validate_ruleset(source["ruleset"]),
        "collection": {
            "event_count": _integer(collection["event_count"], "Mechanic Review source event_count"),
            "page_count": _integer(collection["page_count"], "Mechanic Review source page_count", positive=True),
            "pagination_terminated": True,
            "report_revision_checked_before_and_after": True,
            "storage": "minimal_excerpts",
        },
        "phases": phases,
        "mechanics": mechanics,
        "scope_note": scope_note,
    }


def assemble_mechanic_review_document(
    value: Any, source_path: Path, *, locale: str = "zh-CN"
) -> dict[str, Any]:
    source = validate_mechanic_review_source(value)
    if locale not in {"zh-CN", "en"}:
        raise InputError("Mechanic Review report locale must be zh-CN or en.")
    source_path = source_path.expanduser().resolve()
    if not source_path.is_file():
        raise InputError("Mechanic Review source artifact is missing.")
    identity = source["identity"]
    language = "zh" if locale == "zh-CN" else "en"
    name_field = "encounter_name_zh" if locale == "zh-CN" else "encounter_name_en"
    mechanics = []
    for item in source["mechanics"]:
        mechanics.append({
            "name": item["name"][language],
            "status": item["status"],
            **item["counts"],
            "description": item["conclusion"][language],
            "events": [
                {
                    "fight_time_ms": event["fight_time_ms"],
                    "tone": "danger",
                    "title": item["name"][language],
                    "description": _event_description(event, language),
                    "participants": event["participants"],
                    "evidence_excerpt": event["evidence_excerpt"],
                }
                for event in item["events"]
            ],
        })
    return {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "document_type": "mechanic_review",
        "locale": locale,
        "title": f"{identity[name_field]}{'机制复盘' if locale == 'zh-CN' else ' mechanic review'}",
        "subtitle": f"{identity['difficulty_name']} Boss Attempt {identity['fight_id']}",
        "source_artifacts": [{
            "kind": "mechanic_review", "path": str(source_path), "sha256": sha256_file(source_path),
        }],
        "identity": {
            "report_code": identity["report_code"],
            "report_revision": identity["report_revision"],
            "fight_id": identity["fight_id"],
            "encounter_name": identity[name_field],
            "difficulty_name": identity["difficulty_name"],
            "duration_ms": int(identity["end_time"] - identity["start_time"]),
            "outcome": identity["outcome"],
            "boss_percentage": identity["boss_percentage"],
        },
        "ruleset": source["ruleset"],
        "evidence": {"event_count": source["collection"]["event_count"], "storage": "minimal_excerpts"},
        "phases": [
            {"name": phase["name"][language], "start_ms": phase["start_ms"], "end_ms": phase["end_ms"]}
            for phase in source["phases"]
        ],
        "mechanics": mechanics,
        "actions": [],
        "scope_note": source["scope_note"][language],
    }


def _sanitize_source_phases(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    phases = _list(value, "Mechanic Review phases", maximum=20)
    result = []
    for value in phases:
        phase = _object(value, "Mechanic Review phase")
        name_en = phase.get("name_en", phase.get("name"))
        name_zh = phase.get("name_zh", phase.get("name"))
        result.append({
            "name": {"en": name_en, "zh": name_zh},
            "start_ms": phase.get("start_ms"),
            "end_ms": phase.get("end_ms"),
        })
    return result


def _sanitize_source_mechanic(value: Any) -> dict[str, Any]:
    mechanic = _object(value, "Mechanic Review mechanic")
    summary = _object(mechanic.get("summary"), "Mechanic Review mechanic summary")
    counts = {
        field: summary.get(field)
        for field in ("trigger_count", "success_count", "failure_count")
    }
    anomalies = mechanic.get("anomalies")
    anomalies = anomalies if isinstance(anomalies, list) else []
    verified = mechanic.get("anomaly_detection") == "enabled"
    if mechanic.get("validation_status") == "event_pattern_unverified":
        status = "unverified"
    elif verified and counts["failure_count"]:
        status = "anomaly"
    elif verified and counts["failure_count"] == 0:
        status = "ok"
    else:
        status = "review"
    expectation = mechanic.get("expectation")
    conclusion_en = {
        "anomaly": "The verified event pattern matched; review the listed minimal excerpts.",
        "ok": "No anomaly matched this verified event pattern; this does not prove perfect execution.",
        "unverified": "This event pattern is not verified for the selected difficulty; no anomaly is asserted.",
        "review": "The observed counts require manual review and do not establish an anomaly.",
    }[status]
    conclusion_zh = {
        "anomaly": "已验证事件模式命中；请复核列出的最小证据摘录。",
        "ok": "该已验证事件模式未命中异常；这不证明机制处理完全正确。",
        "unverified": "该事件模式尚未在所选难度验证，因此不声明异常。",
        "review": "观察计数需要人工复核，不能据此确认异常。",
    }[status]
    if isinstance(expectation, str) and expectation.strip():
        conclusion_en = f"{conclusion_en} Ruleset expectation: {expectation.strip()}"
    return {
        "rule_id": mechanic.get("rule_id"),
        "name": {"en": mechanic.get("name_en"), "zh": mechanic.get("name_zh")},
        "validation_status": mechanic.get("validation_status"),
        "status": status,
        "counts": counts,
        "conclusion": {"en": conclusion_en, "zh": conclusion_zh},
        "events": [_sanitize_source_event(item) for item in anomalies[:20]] if status == "anomaly" else [],
    }


def _sanitize_source_event(value: Any) -> dict[str, Any]:
    anomaly = _object(value, "Mechanic Review anomaly")
    actors = anomaly.get("actors") if isinstance(anomaly.get("actors"), list) else [anomaly.get("actor")]
    participants = [
        actor["name"] for actor in actors
        if isinstance(actor, dict) and isinstance(actor.get("name"), str) and actor["name"].strip()
    ]
    excerpt = {
        "event_type": anomaly.get("event_type"),
        "ability_id": anomaly.get("ability_id"),
        "duration_ms": anomaly.get("aura_duration_ms"),
        "episode": anomaly.get("episode"),
        "outcome": anomaly.get("outcome"),
    }
    raw = anomaly.get("raw_event") if isinstance(anomaly.get("raw_event"), dict) else {}
    excerpt |= {
        "source_id": raw.get("sourceID"),
        "target_id": raw.get("targetID"),
        "amount": raw.get("amount"),
    }
    return {
        "fight_time_ms": _whole_milliseconds(
            anomaly.get("time_ms"), "Mechanic Review anomaly time_ms"
        ),
        "participants": participants,
        "evidence_excerpt": {
            key: value for key, value in excerpt.items() if value is not None
        },
    }


def _validate_source_phases(value: Any, duration_ms: int) -> list[dict[str, Any]]:
    phases = _list(value, "Mechanic Review source phases", maximum=20)
    result = []
    previous_end = 0
    for value in phases:
        phase = _object(value, "Mechanic Review source phase")
        _fields(phase, "Mechanic Review source phase", {"name", "start_ms", "end_ms"})
        start = _integer(phase["start_ms"], "Mechanic Review source phase start_ms")
        end = _integer(phase["end_ms"], "Mechanic Review source phase end_ms", positive=True)
        if start < previous_end or end <= start or end > duration_ms:
            raise InputError("Mechanic Review source phases must be ordered within the Boss Attempt.")
        result.append({
            "name": _validate_localized_text(phase["name"], "Mechanic Review source phase name", 100),
            "start_ms": start,
            "end_ms": end,
        })
        previous_end = end
    return result


def _validate_source_mechanics(value: Any, duration_ms: int) -> list[dict[str, Any]]:
    mechanics = _list(value, "Mechanic Review source mechanics", nonempty=True, maximum=50)
    result = []
    rule_ids = set()
    for value in mechanics:
        mechanic = _object(value, "Mechanic Review source mechanic")
        _fields(mechanic, "Mechanic Review source mechanic", {
            "rule_id", "name", "validation_status", "status", "counts", "conclusion", "events",
        })
        rule_id = _text(mechanic["rule_id"], "Mechanic Review source rule_id", 200)
        if rule_id in rule_ids:
            raise InputError("Mechanic Review source rule IDs must be unique.")
        rule_ids.add(rule_id)
        validation_status = mechanic["validation_status"]
        if validation_status not in {"verified", "event_pattern_unverified"}:
            raise InputError("Mechanic Review source validation_status is invalid.")
        status = mechanic["status"]
        if status not in {"anomaly", "review", "ok", "unverified"}:
            raise InputError("Mechanic Review source mechanic status is invalid.")
        counts_value = _object(mechanic["counts"], "Mechanic Review source mechanic counts")
        _fields(counts_value, "Mechanic Review source mechanic counts", {
            "trigger_count", "success_count", "failure_count",
        })
        counts = {
            field: None if counts_value[field] is None else _integer(
                counts_value[field], f"Mechanic Review source mechanic {field}"
            )
            for field in ("trigger_count", "success_count", "failure_count")
        }
        events = _validate_source_events(mechanic["events"], duration_ms)
        if status == "anomaly" and (validation_status != "verified" or not counts["failure_count"] or not events):
            raise InputError("Mechanic Review source anomaly is not supported by verified evidence.")
        if status == "ok" and counts["failure_count"] != 0:
            raise InputError("Mechanic Review source ok status requires zero failures.")
        if status == "unverified" and (counts["success_count"] is not None or counts["failure_count"] is not None or events):
            raise InputError("Mechanic Review source unverified status cannot claim outcomes.")
        result.append({
            "rule_id": rule_id,
            "name": _validate_localized_text(mechanic["name"], "Mechanic Review source mechanic name", 200),
            "validation_status": validation_status,
            "status": status,
            "counts": counts,
            "conclusion": _validate_localized_text(mechanic["conclusion"], "Mechanic Review source conclusion", 5000),
            "events": events,
        })
    return result


def _validate_source_events(value: Any, duration_ms: int) -> list[dict[str, Any]]:
    events = _list(value, "Mechanic Review source events", maximum=20)
    result = []
    for value in events:
        event = _object(value, "Mechanic Review source event")
        _fields(event, "Mechanic Review source event", {"fight_time_ms", "participants", "evidence_excerpt"})
        timestamp = _integer(event["fight_time_ms"], "Mechanic Review source fight_time_ms")
        if timestamp > duration_ms:
            raise InputError("Mechanic Review source event is outside the Boss Attempt.")
        participants = _list(event["participants"], "Mechanic Review source participants", maximum=40)
        excerpt = _object(event["evidence_excerpt"], "Mechanic Review source evidence excerpt")
        if len(excerpt) > len(EVIDENCE_EXCERPT_FIELDS) or any(key not in EVIDENCE_EXCERPT_FIELDS for key in excerpt):
            raise InputError("Mechanic Review source evidence excerpt contains an unsupported field.")
        if any(not _scalar(item) for item in excerpt.values()):
            raise InputError("Mechanic Review source evidence excerpt values must be scalar.")
        if any(isinstance(item, str) and len(item) > 300 for item in excerpt.values()):
            raise InputError("Mechanic Review source evidence excerpt text must not exceed 300 characters.")
        result.append({
            "fight_time_ms": timestamp,
            "participants": [_text(item, "Mechanic Review source participant", 200) for item in participants],
            "evidence_excerpt": dict(excerpt),
        })
    result.sort(key=lambda item: item["fight_time_ms"])
    return result


def _validate_localized_text(value: Any, label: str, maximum: int) -> dict[str, str]:
    localized = _object(value, label)
    _fields(localized, label, {"en", "zh"})
    return {
        "en": _text(localized["en"], f"{label} en", maximum),
        "zh": _text(localized["zh"], f"{label} zh", maximum),
    }


def _event_description(event: dict[str, Any], language: str) -> str:
    excerpt = event["evidence_excerpt"]
    event_type = excerpt.get("event_type", "event")
    ability_id = excerpt.get("ability_id")
    if language == "zh":
        return f"{event_type} 事件支持该结论" + (f"（ability {ability_id}）" if ability_id is not None else "。")
    return f"A {event_type} event supports this conclusion" + (f" (ability {ability_id})." if ability_id is not None else ".")


def _finite_number(value: Any, label: str) -> int | float:
    if not _number(value):
        raise InputError(f"{label} must be a finite number.")
    return value


def _whole_milliseconds(value: Any, label: str) -> int:
    if not _number(value) or not float(value).is_integer() or value < 0:
        raise InputError(f"{label} must be non-negative whole milliseconds.")
    return int(value)


def _json_file_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def assemble_raid_guide_document(snapshot: Any, snapshot_path: Path) -> dict[str, Any]:
    try:
        return _assemble_raid_guide_document(snapshot, snapshot_path)
    except InputError:
        raise
    except (OSError, KeyError, TypeError, ValueError, OverflowError) as exc:
        raise InputError("Guide Snapshot could not be assembled as a Raid Guide Report Document.") from exc


def _assemble_raid_guide_document(snapshot: Any, snapshot_path: Path) -> dict[str, Any]:
    snapshot = verify_guide_snapshot(snapshot)
    snapshot_path = snapshot_path.expanduser().resolve()
    if not snapshot_path.is_file():
        raise InputError("Guide Snapshot artifact is missing.")
    chapters = []
    for source in snapshot["chapters"]:
        identity = source["identity"]
        metrics = source.get("metrics") if isinstance(source.get("metrics"), dict) else {}
        chapters.append({
            "encounter_id": identity.get("encounter_id"),
            "encounter_name": source.get("encounter_name_zh"),
            "benchmark_id": source.get("benchmark_id"),
            "sample_count": source.get("sample_count"),
            "confidence": source.get("confidence"),
            "damage_total_median": metrics.get("damage_total_median"),
            "abilities": [
                {
                    "name": ability.get("name_zh"),
                    "median_casts": ability.get("median_casts"),
                    "median_first_cast_ms": ability.get("median_first_cast_ms"),
                }
                for ability in source.get("abilities", []) if isinstance(ability, dict)
            ],
            "target_damage": [
                {"target_id": int(target_id), "median_amount": amount}
                for target_id, amount in sorted(
                    (metrics.get("damage_by_target_median") or {}).items(), key=lambda item: int(item[0])
                )
            ],
            "mechanic_anchors": [
                {"name": anchor.get("name_zh"), "observed_anchor_ms": anchor.get("observed_anchor_ms")}
                for anchor in source.get("mechanic_anchors", []) if isinstance(anchor, dict)
            ],
            "encounter_profile_id": source.get("encounter_profile_id"),
            "specialization_profile_id": source.get("specialization_profile_id"),
            "sources": [
                {"kind": kind, **{field: item.get(field) for field in ("title", "url", "quote_summary")}}
                for kind in ("encounter", "specialization")
                for item in (source.get("sources") or {}).get(kind, [])
                if isinstance(item, dict)
            ],
        })
    first_identity = snapshot["chapters"][0]["identity"]
    difficulty_name = {3: "Normal", 4: "Heroic", 5: "Mythic"}.get(first_identity.get("difficulty_id"))
    specialization = snapshot.get("specialization")
    return {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "document_type": "raid_guide",
        "locale": "zh-CN",
        "title": f"{specialization}高分日志攻略",
        "subtitle": "按 Boss 隔离的 Encounter Benchmark 与来源审计",
        "source_artifacts": [{
            "kind": "guide_snapshot", "path": str(snapshot_path), "sha256": sha256_file(snapshot_path),
        }],
        "identity": {
            "game_version": first_identity.get("game_version"),
            "partition_id": first_identity.get("partition_id"),
            "difficulty_name": difficulty_name,
            "class_name": first_identity.get("class_name"),
            "spec_name": first_identity.get("spec_name"),
        },
        "specialization": specialization,
        "snapshot_id": snapshot.get("snapshot_id"),
        "ability_names_build": snapshot.get("ability_names_build"),
        "chapters": chapters,
        "scope_note": "只展示 Guide Snapshot 中的日志事实、机制锚点和来源；样本中位数不是推荐或可实现目标。",
    }


def validate_report_document(value: Any) -> dict[str, Any]:
    document = _object(value, "Report Document")
    if document.get("schema_version") != DOCUMENT_SCHEMA_VERSION:
        raise InputError(f"Report Document schema_version must be {DOCUMENT_SCHEMA_VERSION}.")
    document_type = document.get("document_type")
    if document_type not in {"mechanic_review", "personal_review", "raid_guide"}:
        raise InputError("Report Document document_type is unsupported.")
    if document.get("locale") not in {"zh-CN", "en"}:
        raise InputError("Report Document locale must be zh-CN or en.")
    common = {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "document_type": document_type,
        "locale": document["locale"],
        "title": _text(document.get("title"), "Report Document title", 200),
        "subtitle": _text(document.get("subtitle"), "Report Document subtitle", 300),
        "scope_note": _text(document.get("scope_note"), "Report Document scope_note", 2000),
    }
    if document_type == "mechanic_review":
        canonical = _validate_mechanic_document(document, common)
    elif document_type == "personal_review":
        canonical = _validate_personal_document(document, common)
    else:
        canonical = _validate_guide_document(document, common)
    document_id = hashlib.sha256(_canonical_bytes(canonical)).hexdigest()
    return canonical | {"document_id": document_id}


def _validate_mechanic_document(document: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    _fields(
        document,
        "Report Document",
        {
            "schema_version", "document_type", "locale", "title", "subtitle",
            "source_artifacts", "identity", "ruleset", "evidence", "phases",
            "mechanics", "actions", "scope_note",
        },
    )
    canonical = common | {
        "source_artifacts": _validate_sources(document["source_artifacts"], {"mechanic_review"}),
        "identity": _validate_identity(document["identity"]),
        "ruleset": _validate_ruleset(document["ruleset"]),
        "evidence": _validate_evidence(document["evidence"]),
        "phases": _validate_phases(document["phases"]),
        "mechanics": _validate_mechanics(document["mechanics"]),
        "actions": _validate_actions(document["actions"]),
    }
    duration = canonical["identity"]["duration_ms"]
    if any(phase["end_ms"] > duration for phase in canonical["phases"]):
        raise InputError("Report Document phase times must stay within duration_ms.")
    if any(
        event["fight_time_ms"] > duration
        for mechanic in canonical["mechanics"]
        for event in mechanic["events"]
    ):
        raise InputError("Report Document event times must stay within duration_ms.")
    return canonical


def _validate_personal_document(document: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    _fields(
        document,
        "Report Document",
        {
            "schema_version", "document_type", "locale", "title", "subtitle",
            "source_artifacts", "identity", "player", "comparison", "metrics",
            "abilities", "scope_note",
        },
    )
    player = _validate_player(document["player"])
    comparison = _validate_comparison(document["comparison"])
    if (comparison["class_name"], comparison["spec_name"]) != (player["class_name"], player["spec_name"]):
        raise InputError("Report Document player and comparison specialization do not match.")
    return common | {
        "source_artifacts": _validate_sources(
            document["source_artifacts"], {"personal_analysis", "encounter_benchmark", "comparison"}
        ),
        "identity": _validate_identity(document["identity"]),
        "player": player,
        "comparison": comparison,
        "metrics": _validate_personal_metrics(document["metrics"]),
        "abilities": _validate_personal_abilities(document["abilities"]),
    }


def _validate_guide_document(document: dict[str, Any], common: dict[str, Any]) -> dict[str, Any]:
    _fields(
        document,
        "Report Document",
        {
            "schema_version", "document_type", "locale", "title", "subtitle",
            "source_artifacts", "identity", "specialization", "snapshot_id",
            "ability_names_build", "chapters", "scope_note",
        },
    )
    snapshot_id = _digest(document["snapshot_id"], "Report Document snapshot_id")
    return common | {
        "source_artifacts": _validate_sources(document["source_artifacts"], {"guide_snapshot"}),
        "identity": _validate_guide_identity(document["identity"]),
        "specialization": _text(document["specialization"], "Report Document specialization", 200),
        "snapshot_id": snapshot_id,
        "ability_names_build": _text(
            document["ability_names_build"], "Report Document ability_names_build", 100
        ),
        "chapters": _validate_guide_chapters(document["chapters"]),
    }


def render_report_document(value: Any, output_dir: Path) -> dict[str, Any]:
    document = validate_report_document(value)
    verification = _validate_source_artifacts(document)
    html = (
        _render_personal_html(document, verification)
        if document["document_type"] == "personal_review"
        else {
            "mechanic_review": _render_mechanic_html,
            "raid_guide": _render_guide_html,
        }[document["document_type"]](document)
    )
    html_sha256 = hashlib.sha256(html.encode("utf-8")).hexdigest()
    output_dir = output_dir.expanduser().resolve()
    html_path = output_dir / f"{html_sha256}.html"
    index_path = output_dir / f"{html_sha256}.json"
    index = {
        "schema_version": 1,
        "document": document,
        "render": {
            "renderer_schema_version": RENDERER_SCHEMA_VERSION,
            "html_file": html_path.name,
            "html_sha256": html_sha256,
        },
    }
    with artifact_lock(index_path):
        if index_path.exists():
            if read_json(index_path) != index or not html_path.is_file() or sha256_file(html_path) != html_sha256:
                raise InputError("Existing rendered Report Document is incomplete or has an invalid identity.")
        else:
            if html_path.exists() and sha256_file(html_path) != html_sha256:
                raise InputError("Existing rendered Report Document HTML has an invalid identity.")
            if not html_path.exists():
                atomic_write_text(html_path, html)
            atomic_write_json(index_path, index)
    return {
        "document_id": document["document_id"],
        "document_schema_version": DOCUMENT_SCHEMA_VERSION,
        "renderer_schema_version": RENDERER_SCHEMA_VERSION,
        "html_path": str(html_path),
        "html_sha256": html_sha256,
        "index_path": str(index_path),
    }


def _validate_sources(value: Any, expected_kinds: set[str]) -> list[dict[str, str]]:
    sources = _list(value, "Report Document source_artifacts", nonempty=True, maximum=20)
    result = []
    for item in sources:
        source = _object(item, "Report Document source artifact")
        _fields(source, "Report Document source artifact", {"kind", "path", "sha256"})
        kind = _text(source["kind"], "Report Document source artifact kind", 100)
        if kind not in expected_kinds:
            raise InputError("Report Document source artifact kind is invalid for document_type.")
        digest = _digest(source["sha256"], "Report Document source artifact sha256")
        result.append({
            "kind": kind,
            "path": _text(source["path"], "Report Document source artifact path", 1000),
            "sha256": digest,
        })
    if {source["kind"] for source in result} != expected_kinds:
        raise InputError("Report Document source artifacts are incomplete for document_type.")
    return result


def _validate_source_artifacts(document: dict[str, Any]) -> dict[str, bool]:
    artifacts: dict[str, dict[str, Any]] = {}
    try:
        for source in document["source_artifacts"]:
            source_path = Path(source["path"]).expanduser()
            if not source_path.is_file():
                raise InputError(
                    f"Report Document source artifact is missing or has an invalid hash: {source_path}"
                )
            try:
                payload = source_path.read_bytes()
                if hashlib.sha256(payload).hexdigest() != source["sha256"]:
                    raise InputError(
                        f"Report Document source artifact is missing or has an invalid hash: {source_path}"
                    )
                artifact = json.loads(payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise InputError(
                    f"Report Document {source['kind']} source must be valid UTF-8 JSON."
                ) from exc
            if not isinstance(artifact, dict):
                raise InputError(f"Report Document {source['kind']} source must be a JSON object.")
            if source["kind"] in artifacts:
                raise InputError("Report Document source artifact kinds must be unique.")
            artifacts[source["kind"]] = artifact

        if document["document_type"] == "mechanic_review":
            _verify_mechanic_source(document, artifacts["mechanic_review"])
            return {"mechanic_source": True}
        elif document["document_type"] == "personal_review":
            _verify_personal_sources(document, artifacts)
            return {"complete_bundle": True, "hard_conditions": True, "comparison": True}
        else:
            _verify_guide_source(document, verify_guide_snapshot(artifacts["guide_snapshot"]))
            return {"guide_snapshot": True, "hard_conditions": True, "profiles": True}
    except InputError:
        raise
    except (WclRaidCoachError, OSError, KeyError, TypeError, ValueError, OverflowError) as exc:
        raise InputError("Report Document source artifacts could not be verified.") from exc


def _verify_mechanic_source(document: dict[str, Any], source: dict[str, Any]) -> None:
    source = validate_mechanic_review_source(source)
    identity = source["identity"]
    claimed = document["identity"]
    if identity.get("report_code") != claimed["report_code"] or identity.get("report_revision") != claimed["report_revision"]:
        raise InputError("Report Document source Report Revision does not match.")
    if identity.get("fight_id") != claimed["fight_id"]:
        raise InputError("Report Document source Boss Attempt does not match.")
    language = "zh" if document["locale"] == "zh-CN" else "en"
    source_name = identity["encounter_name_zh"] if document["locale"] == "zh-CN" else identity["encounter_name_en"]
    expected_attempt = {
        "encounter_name": source_name,
        "difficulty_name": identity["difficulty_name"],
        "duration_ms": int(identity["end_time"] - identity["start_time"]),
        "outcome": identity["outcome"],
        "boss_percentage": identity["boss_percentage"],
    }
    if any(claimed[field] != value for field, value in expected_attempt.items()):
        raise InputError("Report Document source Boss Attempt difficulty or outcome does not match.")
    if source["ruleset"] != document["ruleset"]:
        raise InputError("Report Document source ruleset does not match.")
    expected_title = f"{source_name}{'机制复盘' if document['locale'] == 'zh-CN' else ' mechanic review'}"
    expected_subtitle = f"{identity['difficulty_name']} Boss Attempt {identity['fight_id']}"
    if (
        document["title"] != expected_title
        or document["subtitle"] != expected_subtitle
        or document["scope_note"] != source["scope_note"][language]
        or document["actions"]
    ):
        raise InputError("Report Document narrative does not match the Mechanic Review source.")
    if source["collection"]["event_count"] != document["evidence"]["event_count"]:
        raise InputError("Report Document Mechanic Evidence Set verification does not match.")
    expected_phases = [
        {
            "name": phase["name"][language],
            "start_ms": phase["start_ms"],
            "end_ms": phase["end_ms"],
        }
        for phase in source["phases"]
    ]
    if document["phases"] != expected_phases:
        raise InputError("Report Document phases do not match the Mechanic Review source.")
    source_by_name = {
        item["name"][language]: item for item in source["mechanics"]
    }
    if len(document["mechanics"]) != len(source_by_name):
        raise InputError("Report Document mechanics do not match the Mechanic Review source.")
    for mechanic in document["mechanics"]:
        source_mechanic = source_by_name.get(mechanic["name"])
        counts = source_mechanic.get("counts") if isinstance(source_mechanic, dict) else None
        if not isinstance(counts, dict) or any(
            mechanic[field] != counts.get(field)
            for field in ("trigger_count", "success_count", "failure_count")
        ):
            raise InputError("Report Document mechanic claims do not match the Mechanic Review source.")
        if mechanic["status"] != source_mechanic["status"] or mechanic["description"] != source_mechanic["conclusion"][language]:
            raise InputError("Report Document mechanic conclusions do not match the Mechanic Review source.")
        anomalies = source_mechanic["events"]
        if len(mechanic["events"]) != len(anomalies):
            raise InputError("Report Document evidence excerpts do not match the Mechanic Review source.")
        for event in mechanic["events"]:
            excerpt = event["evidence_excerpt"]
            if not any(
                event["fight_time_ms"] == item["fight_time_ms"]
                and event["participants"] == item["participants"]
                and excerpt == item["evidence_excerpt"]
                and event["tone"] == "danger"
                and event["title"] == source_mechanic["name"][language]
                and event["description"] == _event_description(item, language)
                for item in anomalies
            ):
                raise InputError("Report Document evidence excerpt does not match a source anomaly.")


def _verify_personal_sources(document: dict[str, Any], sources: dict[str, dict[str, Any]]) -> None:
    analysis = sources["personal_analysis"]
    benchmark = sources["encounter_benchmark"]
    comparison = sources["comparison"]
    if type(analysis.get("schema_version")) is not int or analysis["schema_version"] != ANALYSIS_SCHEMA_VERSION:
        raise InputError("Personal Analysis uses an unsupported schema version; run coach review again.")
    verify_benchmark(benchmark)
    recomputed_comparison = compare_player(analysis, benchmark)
    if comparison != recomputed_comparison:
        raise InputError("Report Document Comparison source does not match its Personal Analysis and Benchmark.")
    if comparison.get("schema_version") != 2:
        raise InputError("Report Document Comparison uses an unsupported schema version.")
    analysis_identity = analysis.get("identity")
    analysis_player = analysis.get("player")
    analysis_metrics = analysis.get("metrics")
    benchmark_identity = benchmark.get("identity")
    benchmark_metrics = benchmark.get("metrics")
    if not all(isinstance(item, dict) for item in (analysis_identity, analysis_player, analysis_metrics, benchmark_identity, benchmark_metrics)):
        raise InputError("Report Document Personal Review source is malformed.")
    claimed_identity = document["identity"]
    if (
        analysis_identity.get("report_code") != claimed_identity["report_code"]
        or analysis_identity.get("report_revision") != claimed_identity["report_revision"]
    ):
        raise InputError("Report Document source Report Revision does not match.")
    if analysis_identity.get("fight_id") != claimed_identity["fight_id"]:
        raise InputError("Report Document source Boss Attempt does not match.")
    index, fight = _analysis_report_index(analysis, analysis_identity)
    difficulty_names = {
        item.get("id"): item.get("name")
        for item in ((index.get("report") or {}).get("zone") or {}).get("difficulties", [])
        if isinstance(item, dict)
    }
    expected_attempt = {
        "encounter_name": fight.get("name"), "difficulty_name": difficulty_names.get(fight.get("difficulty")),
        "duration_ms": fight.get("duration_ms"),
        "outcome": "kill" if fight.get("kill") is True else "wipe" if fight.get("kill") is False else None,
        "boss_percentage": fight.get("boss_percentage"),
    }
    if any(claimed_identity[field] != value for field, value in expected_attempt.items()):
        raise InputError("Report Document source Boss Attempt details do not match.")
    player = document["player"]
    expected_player = {
        "name": analysis_player.get("name"), "class_name": analysis_player.get("class"),
        "spec_name": analysis_player.get("spec"), "item_level": analysis_player.get("item_level"),
        "anonymous": analysis_player.get("anonymous", False),
    }
    if any(player[field] != value for field, value in expected_player.items()):
        raise InputError("Report Document player does not match the Personal Analysis actor.")
    expected_comparison = dict(benchmark_identity) | {
        "sample_count": benchmark.get("sample_count"), "confidence": benchmark.get("confidence")
    }
    if document["comparison"] != expected_comparison:
        raise InputError("Report Document comparison hard conditions or Benchmark identity do not match.")
    expected_metrics = {
        field: analysis_metrics.get(field)
        for field in ("damage_total", "healing_total", "interrupts", "deaths", "resource_events")
    } | {"damage_total_delta": (comparison.get("metrics") or {}).get("damage_total_delta")}
    if document["metrics"] != expected_metrics:
        raise InputError("Report Document personal metrics do not match their source artifacts.")
    if document["abilities"] != _personal_source_abilities(analysis_metrics, benchmark_metrics, index):
        raise InputError("Report Document ability claims do not match their source artifacts.")


def _verify_guide_source(document: dict[str, Any], snapshot: dict[str, Any]) -> None:
    if document["snapshot_id"] != snapshot.get("snapshot_id"):
        raise InputError("Report Document Snapshot identity does not match.")
    if document["specialization"] != snapshot.get("specialization") or document["ability_names_build"] != snapshot.get("ability_names_build"):
        raise InputError("Report Document Guide Snapshot metadata does not match.")
    snapshot_chapters = snapshot["chapters"]
    markdown = Path(snapshot["markdown_path"]).read_text(encoding="utf-8")
    first_identity = snapshot_chapters[0]["identity"]
    difficulty_name = {3: "Normal", 4: "Heroic", 5: "Mythic"}.get(first_identity.get("difficulty_id"))
    expected_identity = {
        "game_version": first_identity.get("game_version"), "partition_id": first_identity.get("partition_id"),
        "difficulty_name": difficulty_name, "class_name": first_identity.get("class_name"),
        "spec_name": first_identity.get("spec_name"),
    }
    if document["identity"] != expected_identity:
        raise InputError("Report Document Guide Snapshot hard conditions do not match.")
    if len(document["chapters"]) != len(snapshot_chapters):
        raise InputError("Report Document Guide Snapshot chapters do not match.")
    snapshot_by_encounter = {chapter["identity"].get("encounter_id"): chapter for chapter in snapshot_chapters}
    for chapter in document["chapters"]:
        source = snapshot_by_encounter.get(chapter["encounter_id"])
        if not isinstance(source, dict):
            raise InputError("Report Document guide chapter is absent from the Guide Snapshot.")
        source_name = source.get("encounter_name_zh") if document["locale"] == "zh-CN" else source.get("encounter_name_en")
        if chapter["encounter_name"] != source_name:
            raise InputError("Report Document guide chapter encounter identity does not match.")
        for field in ("benchmark_id", "sample_count", "confidence", "encounter_profile_id", "specialization_profile_id"):
            if chapter[field] != source.get(field):
                label = "Profile" if "profile" in field else "chapter"
                raise InputError(f"Report Document guide chapter {label} identity does not match.")
        metrics = source.get("metrics") if isinstance(source.get("metrics"), dict) else {}
        if chapter["damage_total_median"] != metrics.get("damage_total_median"):
            raise InputError("Report Document guide chapter metrics do not match.")
        expected_targets = [
            {"target_id": int(target), "median_amount": amount}
            for target, amount in sorted((metrics.get("damage_by_target_median") or {}).items(), key=lambda item: int(item[0]))
        ]
        if chapter["target_damage"] != expected_targets:
            raise InputError("Report Document guide target metrics do not match.")
        expected_anchors = [
            {"name": item.get("name_zh") if document["locale"] == "zh-CN" else item.get("name"),
             "observed_anchor_ms": item.get("observed_anchor_ms")}
            for item in source.get("mechanic_anchors", []) if isinstance(item, dict)
        ]
        if chapter["mechanic_anchors"] != expected_anchors:
            raise InputError("Report Document guide Profile mechanic anchors do not match.")
        expected_sources = [
            {"kind": kind, **{field: item.get(field) for field in ("title", "url", "quote_summary")}}
            for kind in ("encounter", "specialization")
            for item in (source.get("sources") or {}).get(kind, [])
            if isinstance(item, dict)
        ]
        if chapter["sources"] != expected_sources:
            raise InputError("Report Document guide Profile sources do not match.")
        expected_abilities = [
            {
                "name": item.get("name_zh"),
                "median_casts": None if item.get("median_casts") is None else float(item["median_casts"]),
                "median_first_cast_ms": None if item.get("median_first_cast_ms") is None else float(item["median_first_cast_ms"]),
            }
            for item in source.get("abilities", []) if isinstance(item, dict)
        ]
        if chapter["abilities"] != expected_abilities:
            raise InputError("Report Document guide ability names or metrics do not match.")
        if any(ability["name"] not in markdown for ability in chapter["abilities"]):
            raise InputError("Report Document guide ability names do not match the Guide Snapshot.")


def _analysis_report_index(analysis: dict[str, Any], identity: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = analysis.get("evidence")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("index_path"), str):
        raise InputError("Personal Analysis Report Index provenance is missing.")
    index = read_json(Path(evidence["index_path"]))
    if not isinstance(index, dict) or not isinstance(index.get("fights"), list):
        raise InputError("Personal Analysis Report Index is malformed.")
    fight = next(
        (item for item in index["fights"] if isinstance(item, dict) and item.get("fight_id") == identity.get("fight_id")),
        None,
    )
    if fight is None:
        raise InputError("Personal Analysis Boss Attempt is absent from its Report Index.")
    return index, fight


def _personal_source_abilities(
    analysis_metrics: dict[str, Any], benchmark_metrics: dict[str, Any], index: dict[str, Any]
) -> list[dict[str, Any]]:
    casts = analysis_metrics.get("casts") if isinstance(analysis_metrics.get("casts"), dict) else {}
    first_casts = analysis_metrics.get("first_cast_ms") if isinstance(analysis_metrics.get("first_cast_ms"), dict) else {}
    median_casts = benchmark_metrics.get("casts_median") if isinstance(benchmark_metrics.get("casts_median"), dict) else {}
    median_first = benchmark_metrics.get("first_cast_ms_median") if isinstance(benchmark_metrics.get("first_cast_ms_median"), dict) else {}
    names = {
        str(item.get("gameID")): item.get("name")
        for item in index.get("abilities", []) if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    return [
        {
            "name": names.get(ability, ability), "player_casts": casts.get(ability, 0),
            "median_casts": None if ability not in median_casts else float(median_casts[ability]),
            "player_first_cast_ms": None if ability not in first_casts else float(first_casts[ability]),
            "median_first_cast_ms": None if ability not in median_first else float(median_first[ability]),
        }
        for ability in sorted(
            set(casts) | set(median_casts),
            key=lambda value: (0, int(value)) if value.isdigit() else (1, value),
        )
    ]


def _source_duration(attempt: dict[str, Any]) -> int | None:
    start = attempt.get("start_time")
    end = attempt.get("end_time")
    if not _number(start) or not _number(end):
        return None
    duration = float(end) - float(start)
    return int(duration) if duration.is_integer() else None


def _event_matches_anomaly(event: dict[str, Any], excerpt: dict[str, Any] | None, anomaly: Any) -> bool:
    if not isinstance(anomaly, dict) or anomaly.get("time_ms") != event["fight_time_ms"]:
        return False
    actors = anomaly.get("actors") if isinstance(anomaly.get("actors"), list) else [anomaly.get("actor")]
    names = [actor.get("name") for actor in actors if isinstance(actor, dict) and isinstance(actor.get("name"), str)]
    if any(participant not in names for participant in event["participants"]):
        return False
    return excerpt is None or all(anomaly.get(field) == value for field, value in excerpt.items())


def _validate_identity(value: Any) -> dict[str, Any]:
    identity = _object(value, "Report Document identity")
    _fields(
        identity,
        "Report Document identity",
        {
            "report_code", "report_revision", "fight_id", "encounter_name",
            "difficulty_name", "duration_ms", "outcome", "boss_percentage",
        },
    )
    report_code = _text(identity["report_code"], "Report Document report_code", 64)
    if re.fullmatch(r"[A-Za-z0-9]+", report_code) is None:
        raise InputError("Report Document report_code must be alphanumeric.")
    outcome = identity["outcome"]
    if outcome not in {"kill", "wipe"}:
        raise InputError("Report Document outcome must be kill or wipe.")
    percentage = identity["boss_percentage"]
    if percentage is not None and (not _number(percentage) or not 0 <= float(percentage) <= 100):
        raise InputError("Report Document boss_percentage must be null or between 0 and 100.")
    return {
        "report_code": report_code,
        "report_revision": _integer(identity["report_revision"], "Report Document report_revision", positive=True),
        "fight_id": _integer(identity["fight_id"], "Report Document fight_id", positive=True),
        "encounter_name": _text(identity["encounter_name"], "Report Document encounter_name", 200),
        "difficulty_name": _text(identity["difficulty_name"], "Report Document difficulty_name", 100),
        "duration_ms": _integer(identity["duration_ms"], "Report Document duration_ms", positive=True),
        "outcome": outcome,
        "boss_percentage": float(percentage) if percentage is not None else None,
    }


def _validate_player(value: Any) -> dict[str, Any]:
    player = _object(value, "Report Document player")
    _fields(player, "Report Document player", {"name", "class_name", "spec_name", "item_level", "anonymous"})
    item_level = player["item_level"]
    if item_level is not None and (not _number(item_level) or item_level <= 0):
        raise InputError("Report Document player item_level must be null or a positive number.")
    if not isinstance(player["anonymous"], bool):
        raise InputError("Report Document player anonymous must be a boolean.")
    return {
        "name": _text(player["name"], "Report Document player name", 200),
        "class_name": _text(player["class_name"], "Report Document player class_name", 100),
        "spec_name": _text(player["spec_name"], "Report Document player spec_name", 100),
        "item_level": float(item_level) if item_level is not None else None,
        "anonymous": player["anonymous"],
    }


def _validate_comparison(value: Any) -> dict[str, Any]:
    comparison = _object(value, "Report Document comparison")
    _fields(
        comparison,
        "Report Document comparison",
        {
            "game_version", "partition_id", "encounter_id", "difficulty_id",
            "class_name", "spec_name", "sample_count", "confidence",
        },
    )
    if comparison["confidence"] not in {"low", "normal"}:
        raise InputError("Report Document comparison confidence must be low or normal.")
    sample_count = _integer(comparison["sample_count"], "Report Document comparison sample_count", positive=True)
    if sample_count < 3:
        raise InputError("Report Document comparison requires at least three samples.")
    return {
        "game_version": _text(comparison["game_version"], "Report Document comparison game_version", 100),
        "partition_id": _integer(comparison["partition_id"], "Report Document comparison partition_id", positive=True),
        "encounter_id": _integer(comparison["encounter_id"], "Report Document comparison encounter_id", positive=True),
        "difficulty_id": _integer(comparison["difficulty_id"], "Report Document comparison difficulty_id", positive=True),
        "class_name": _text(comparison["class_name"], "Report Document comparison class_name", 100),
        "spec_name": _text(comparison["spec_name"], "Report Document comparison spec_name", 100),
        "sample_count": sample_count,
        "confidence": comparison["confidence"],
    }


def _validate_personal_metrics(value: Any) -> dict[str, Any]:
    metrics = _object(value, "Report Document personal metrics")
    fields = {"damage_total", "healing_total", "interrupts", "deaths", "resource_events", "damage_total_delta"}
    _fields(metrics, "Report Document personal metrics", fields)
    delta = metrics["damage_total_delta"]
    if delta is not None and not _number(delta):
        raise InputError("Report Document damage_total_delta must be null or a finite number.")
    return {
        field: _integer(metrics[field], f"Report Document personal metrics {field}")
        for field in fields - {"damage_total_delta"}
    } | {"damage_total_delta": float(delta) if delta is not None else None}


def _validate_personal_abilities(value: Any) -> list[dict[str, Any]]:
    abilities = _list(value, "Report Document personal abilities", maximum=100)
    result = []
    for value in abilities:
        ability = _object(value, "Report Document personal ability")
        _fields(
            ability,
            "Report Document personal ability",
            {"name", "player_casts", "median_casts", "player_first_cast_ms", "median_first_cast_ms"},
        )
        result.append({
            "name": _text(ability["name"], "Report Document personal ability name", 200),
            "player_casts": _integer(ability["player_casts"], "Report Document personal ability player_casts"),
            "median_casts": _optional_nonnegative_number(
                ability["median_casts"], "Report Document personal ability median_casts"
            ),
            "player_first_cast_ms": _optional_nonnegative_number(
                ability["player_first_cast_ms"], "Report Document personal ability player_first_cast_ms"
            ),
            "median_first_cast_ms": _optional_nonnegative_number(
                ability["median_first_cast_ms"], "Report Document personal ability median_first_cast_ms"
            ),
        })
    return result


def _validate_guide_identity(value: Any) -> dict[str, Any]:
    identity = _object(value, "Report Document guide identity")
    fields = {"game_version", "partition_id", "difficulty_name", "class_name", "spec_name"}
    _fields(identity, "Report Document guide identity", fields)
    return {
        "game_version": _text(identity["game_version"], "Report Document guide game_version", 100),
        "partition_id": _integer(identity["partition_id"], "Report Document guide partition_id", positive=True),
        "difficulty_name": _text(identity["difficulty_name"], "Report Document guide difficulty_name", 100),
        "class_name": _text(identity["class_name"], "Report Document guide class_name", 100),
        "spec_name": _text(identity["spec_name"], "Report Document guide spec_name", 100),
    }


def _validate_guide_chapters(value: Any) -> list[dict[str, Any]]:
    chapters = _list(value, "Report Document guide chapters", nonempty=True, maximum=20)
    result = []
    for value in chapters:
        chapter = _object(value, "Report Document guide chapter")
        _fields(
            chapter,
            "Report Document guide chapter",
            {
                "encounter_id", "encounter_name", "sample_count", "confidence",
                "benchmark_id", "damage_total_median", "abilities", "target_damage", "mechanic_anchors",
                "encounter_profile_id", "specialization_profile_id", "sources",
            },
        )
        if chapter["confidence"] not in {"low", "normal"}:
            raise InputError("Report Document guide chapter confidence must be low or normal.")
        sample_count = _integer(chapter["sample_count"], "Report Document guide chapter sample_count", positive=True)
        if sample_count < 3:
            raise InputError("Report Document guide chapter requires at least three samples.")
        result.append({
            "encounter_id": _integer(chapter["encounter_id"], "Report Document guide chapter encounter_id", positive=True),
            "encounter_name": _text(chapter["encounter_name"], "Report Document guide chapter encounter_name", 200),
            "benchmark_id": _digest(chapter["benchmark_id"], "Report Document guide chapter benchmark_id"),
            "sample_count": sample_count,
            "confidence": chapter["confidence"],
            "damage_total_median": _optional_nonnegative_number(
                chapter["damage_total_median"], "Report Document guide chapter damage_total_median"
            ),
            "abilities": _validate_guide_abilities(chapter["abilities"]),
            "target_damage": _validate_target_damage(chapter["target_damage"]),
            "mechanic_anchors": _validate_mechanic_anchors(chapter["mechanic_anchors"]),
            "encounter_profile_id": _digest(
                chapter["encounter_profile_id"], "Report Document guide chapter encounter_profile_id"
            ),
            "specialization_profile_id": _digest(
                chapter["specialization_profile_id"], "Report Document guide chapter specialization_profile_id"
            ),
            "sources": _validate_guide_sources(chapter["sources"]),
        })
    if len({chapter["encounter_id"] for chapter in result}) != len(result):
        raise InputError("Report Document guide chapters must have unique encounter IDs.")
    return result


def _validate_guide_abilities(value: Any) -> list[dict[str, Any]]:
    abilities = _list(value, "Report Document guide abilities", maximum=100)
    result = []
    for value in abilities:
        ability = _object(value, "Report Document guide ability")
        _fields(ability, "Report Document guide ability", {"name", "median_casts", "median_first_cast_ms"})
        result.append({
            "name": _text(ability["name"], "Report Document guide ability name", 200),
            "median_casts": _optional_nonnegative_number(
                ability["median_casts"], "Report Document guide ability median_casts"
            ),
            "median_first_cast_ms": _optional_nonnegative_number(
                ability["median_first_cast_ms"], "Report Document guide ability median_first_cast_ms"
            ),
        })
    return result


def _validate_target_damage(value: Any) -> list[dict[str, Any]]:
    targets = _list(value, "Report Document guide target damage", maximum=100)
    result = []
    for value in targets:
        target = _object(value, "Report Document guide target damage item")
        _fields(target, "Report Document guide target damage item", {"target_id", "median_amount"})
        result.append({
            "target_id": _integer(target["target_id"], "Report Document guide target_id", positive=True),
            "median_amount": _optional_nonnegative_number(
                target["median_amount"], "Report Document guide median_amount"
            ),
        })
    return result


def _validate_mechanic_anchors(value: Any) -> list[dict[str, Any]]:
    anchors = _list(value, "Report Document guide mechanic anchors", maximum=50)
    result = []
    for value in anchors:
        anchor = _object(value, "Report Document guide mechanic anchor")
        _fields(anchor, "Report Document guide mechanic anchor", {"name", "observed_anchor_ms"})
        result.append({
            "name": _text(anchor["name"], "Report Document guide mechanic anchor name", 200),
            "observed_anchor_ms": _optional_nonnegative_number(
                anchor["observed_anchor_ms"], "Report Document guide mechanic anchor observed_anchor_ms"
            ),
        })
    return result


def _validate_guide_sources(value: Any) -> list[dict[str, str]]:
    sources = _list(value, "Report Document guide sources", maximum=30)
    result = []
    for value in sources:
        source = _object(value, "Report Document guide source")
        _fields(source, "Report Document guide source", {"kind", "title", "url", "quote_summary"})
        if source["kind"] not in {"encounter", "specialization"}:
            raise InputError("Report Document guide source kind is invalid.")
        result.append({
            "kind": source["kind"],
            "title": _text(source["title"], "Report Document guide source title", 300),
            "url": _public_url(source["url"], "Report Document guide source"),
            "quote_summary": _text(source["quote_summary"], "Report Document guide source quote_summary", 1000),
        })
    return result


def _validate_ruleset(value: Any) -> dict[str, Any]:
    ruleset = _object(value, "Report Document ruleset")
    _fields(ruleset, "Report Document ruleset", {"version", "selection_policy", "sources"})
    if ruleset["selection_policy"] != "latest":
        raise InputError("Report Document ruleset selection_policy must be latest.")
    sources = _list(ruleset["sources"], "Report Document ruleset sources", nonempty=True, maximum=30)
    normalized_sources = []
    for source in sources:
        normalized_sources.append(_public_url(source, "Report Document ruleset source"))
    return {
        "version": _text(ruleset["version"], "Report Document ruleset version", 100),
        "selection_policy": "latest",
        "sources": normalized_sources,
    }


def _validate_evidence(value: Any) -> dict[str, Any]:
    evidence = _object(value, "Report Document evidence")
    _fields(evidence, "Report Document evidence", {"event_count", "storage"})
    if evidence["storage"] != "minimal_excerpts":
        raise InputError("Report Document evidence storage must be minimal_excerpts.")
    return {
        "event_count": _integer(evidence["event_count"], "Report Document evidence event_count"),
        "storage": "minimal_excerpts",
    }


def _validate_phases(value: Any) -> list[dict[str, Any]]:
    phases = _list(value, "Report Document phases", maximum=20)
    result = []
    previous_end = 0
    for item in phases:
        phase = _object(item, "Report Document phase")
        _fields(phase, "Report Document phase", {"name", "start_ms", "end_ms"})
        start = _integer(phase["start_ms"], "Report Document phase start_ms")
        end = _integer(phase["end_ms"], "Report Document phase end_ms", positive=True)
        if start < previous_end or end <= start:
            raise InputError("Report Document phases must be ordered, non-overlapping ranges.")
        result.append({"name": _text(phase["name"], "Report Document phase name", 100), "start_ms": start, "end_ms": end})
        previous_end = end
    return result


def _validate_mechanics(value: Any) -> list[dict[str, Any]]:
    mechanics = _list(value, "Report Document mechanics", nonempty=True, maximum=50)
    result = []
    for item in mechanics:
        mechanic = _object(item, "Report Document mechanic")
        _fields(
            mechanic,
            "Report Document mechanic",
            {"name", "status", "trigger_count", "success_count", "failure_count", "description", "events"},
        )
        status = mechanic["status"]
        if status not in {"anomaly", "review", "ok", "unverified"}:
            raise InputError("Report Document mechanic status is invalid.")
        counts = {
            field: None if mechanic[field] is None else _integer(mechanic[field], f"Report Document mechanic {field}")
            for field in ("trigger_count", "success_count", "failure_count")
        }
        events = _validate_events(mechanic["events"])
        if status == "anomaly" and (not counts["failure_count"] or not events):
            raise InputError("Report Document anomaly mechanics require a positive failure_count and events.")
        if status == "ok" and counts["failure_count"] != 0:
            raise InputError("Report Document ok mechanics require failure_count 0.")
        if status == "unverified" and (counts["success_count"] is not None or counts["failure_count"] is not None):
            raise InputError("Report Document unverified mechanics cannot claim success or failure counts.")
        result.append({
            "name": _text(mechanic["name"], "Report Document mechanic name", 200),
            "status": status,
            **counts,
            "description": _text(mechanic["description"], "Report Document mechanic description", 5000),
            "events": events,
        })
    return result


def _validate_events(value: Any) -> list[dict[str, Any]]:
    events = _list(value, "Report Document mechanic events", maximum=20)
    result = []
    for item in events:
        event = _object(item, "Report Document mechanic event")
        _fields(
            event,
            "Report Document mechanic event",
            {"fight_time_ms", "tone", "title", "description", "participants", "evidence_excerpt"},
        )
        if event["tone"] not in {"danger", "warn", "ok", "info"}:
            raise InputError("Report Document mechanic event tone is invalid.")
        participants = _list(event["participants"], "Report Document mechanic event participants", maximum=40)
        excerpt = event["evidence_excerpt"]
        if excerpt is not None:
            excerpt = _object(excerpt, "Report Document evidence excerpt")
            if len(excerpt) > len(EVIDENCE_EXCERPT_FIELDS) or any(key not in EVIDENCE_EXCERPT_FIELDS for key in excerpt):
                raise InputError("Report Document evidence excerpt contains an unsupported field.")
            if any(not _scalar(item) for item in excerpt.values()):
                raise InputError("Report Document evidence excerpt values must be scalar.")
            if any(isinstance(item, str) and len(item) > 300 for item in excerpt.values()):
                raise InputError("Report Document evidence excerpt text must not exceed 300 characters.")
        result.append({
            "fight_time_ms": _integer(event["fight_time_ms"], "Report Document mechanic event fight_time_ms"),
            "tone": event["tone"],
            "title": _text(event["title"], "Report Document mechanic event title", 300),
            "description": _text(event["description"], "Report Document mechanic event description", 2000),
            "participants": [_text(item, "Report Document mechanic event participant", 200) for item in participants],
            "evidence_excerpt": dict(excerpt) if excerpt is not None else None,
        })
    result.sort(key=lambda item: item["fight_time_ms"])
    return result


def _validate_actions(value: Any) -> list[dict[str, str]]:
    actions = _list(value, "Report Document actions", maximum=6)
    result = []
    for item in actions:
        action = _object(item, "Report Document action")
        _fields(action, "Report Document action", {"title", "description"})
        result.append({
            "title": _text(action["title"], "Report Document action title", 200),
            "description": _text(action["description"], "Report Document action description", 1000),
        })
    return result


def _render_mechanic_html(document: dict[str, Any]) -> str:
    identity = document["identity"]
    mechanics = document["mechanics"]
    labels = _labels(document["locale"])
    failure_total = sum(item["failure_count"] or 0 for item in mechanics)
    review_total = sum(item["status"] == "review" for item in mechanics)
    success_total = sum(item["success_count"] or 0 for item in mechanics)
    outcome = labels[identity["outcome"]]
    if identity["boss_percentage"] is not None:
        outcome += f" {identity['boss_percentage']:g}%"
    timeline_events = [
        (mechanic["name"], event)
        for mechanic in mechanics if mechanic["status"] == "anomaly"
        for event in mechanic["events"]
    ][:6]
    participants = list(dict.fromkeys(
        participant
        for mechanic in mechanics
        for event in mechanic["events"]
        for participant in event["participants"]
    ))
    phases = document["phases"] or [{"name": labels["full_attempt"], "start_ms": 0, "end_ms": identity["duration_ms"]}]
    return f"""<!doctype html>
<html lang="{escape(document['locale'], quote=True)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(document['title'])}</title>
<style>{_CSS}</style>
</head>
<body>
<input class="theme-radio" id="theme-auto" name="theme" type="radio" checked><input class="theme-radio" id="theme-light" name="theme" type="radio"><input class="theme-radio" id="theme-dark" name="theme" type="radio">
<div class="report">
  <nav class="theme-controls" aria-label="{escape(labels['theme'])}"><label for="theme-auto">A</label><label for="theme-light">☀</label><label for="theme-dark">☾</label></nav>
  <div class="shell">
    <header class="masthead"><span class="mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span><div><h1>{escape(document['title'])}</h1><p>{escape(document['subtitle'])}</p></div><div class="attempt"><small>{escape(labels['boss_attempt'])}</small><b>#{identity['fight_id']} / {_format_time(identity['duration_ms'])}</b></div></header>
    <section class="hero"><div class="verdict"><small>{escape(labels['result'])}</small><strong>{escape(outcome)}</strong><p>{failure_total} {escape(labels['verified_anomalies_count'])}<br>{review_total} {escape(labels['manual_review_count'])}</p><span>{escape(labels['reviewable'])}</span></div><div class="timeline"><div class="section-head"><h2>{escape(labels['attempt_timeline'])}</h2><code>00:00 → {_format_time(identity['duration_ms'])}</code></div><div class="phase-rail">{_render_phases(phases, identity['duration_ms'])}{_render_timeline_events(timeline_events, identity['duration_ms'])}</div></div></section>
    <section class="summary"><div><small>{escape(labels['verified_anomalies'])}</small><b class="bad">{failure_total:02d}</b></div><div><small>{escape(labels['manual_review'])}</small><b class="warning">{review_total:02d}</b></div><div><small>{escape(labels['successful_signals'])}</small><b class="good">{success_total:02d}</b></div><div><small>{escape(labels['evidence_events'])}</small><b>{document['evidence']['event_count']}</b></div></section>
    <section class="workspace"><aside class="panel mechanic-nav"><h2>{escape(labels['mechanics'])}</h2>{_render_mechanic_nav(mechanics, labels)}</aside><div class="findings">{''.join(_render_mechanic(item, index, labels) for index, item in enumerate(mechanics))}</div><aside class="panel participants"><h2>{escape(labels['involved_players'])}</h2>{_render_participants(participants, labels)}</aside>{_render_actions(document['actions'], labels)}</section>
    <footer><p>{escape(document['scope_note'])}</p><code>{escape(identity['report_code'])} / Revision {identity['report_revision']} / {escape(document['ruleset']['version'])} / {escape(document['document_id'][:12])}</code></footer>
  </div>
</div>
</body>
</html>
"""


def _render_personal_html(document: dict[str, Any], verification: dict[str, bool]) -> str:
    identity = document["identity"]
    player = document["player"]
    comparison = document["comparison"]
    metrics = document["metrics"]
    labels = _personal_labels(document["locale"])
    abilities = "".join(_render_personal_ability(ability, labels) for ability in document["abilities"])
    item_level = labels["unavailable"] if player["item_level"] is None else f'{player["item_level"]:g}'
    damage_delta = metrics["damage_total_delta"]
    delta_text = labels["unavailable"] if damage_delta is None else _format_amount(damage_delta)
    hard_match = labels["hard_match"] if verification.get("hard_conditions") else labels["not_verified"]
    evidence_status = labels["bundle_verified"] if verification.get("complete_bundle") else labels["not_verified"]
    return f"""<!doctype html>
<html lang="{escape(document['locale'], quote=True)}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(document['title'])}</title><style>{_COACHING_CSS}</style></head>
<body>
<input class="theme-radio" id="theme-auto" name="theme" type="radio" checked><input class="theme-radio" id="theme-light" name="theme" type="radio"><input class="theme-radio" id="theme-dark" name="theme" type="radio">
<div class="report"><nav class="theme-controls" aria-label="{escape(labels['theme'])}"><label for="theme-auto">A</label><label for="theme-light">☀</label><label for="theme-dark">☾</label></nav><div class="p-shell">
<header class="p-head"><span class="mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span><div><h1>{escape(document['title'])}</h1><p>{escape(document['subtitle'])}</p></div><div class="p-id"><span class="kicker">Boss Attempt</span><b>#{identity['fight_id']} / Revision {identity['report_revision']}</b></div></header>
<section class="player-strip"><div class="player-card"><span class="avatar">{escape(_initials(player['name']))}</span><div><h2>{escape(player['name'])}</h2><p>{escape(player['class_name'])} · {escape(player['spec_name'])}<br>{escape(labels['item_level'])} {item_level}{' · ' + escape(labels['anonymous']) if player['anonymous'] else ''}</p></div></div><div class="fact-ribbon">{_metric(labels['damage'], _format_amount(metrics['damage_total']))}{_metric(labels['healing'], _format_amount(metrics['healing_total']))}{_metric(labels['interrupts'], str(metrics['interrupts']))}{_metric(labels['deaths'], str(metrics['deaths']), 'bad' if metrics['deaths'] else '')}</div><aside class="benchmark-seal"><span class="kicker">{escape(labels['comparison_scope'])}</span><strong>{comparison['sample_count']} {escape(labels['samples'])}</strong><p>{escape(identity['difficulty_name'])} · Partition {comparison['partition_id']}<br>{escape(labels[comparison['confidence']])} · {escape(hard_match)}</p></aside></section>
<section class="p-grid"><aside class="panel"><h2 class="panel-title">{escape(labels['identity_evidence'])}<span>LOG FACT</span></h2><ul class="scope-list"><li><small>WCL Report</small><b>{escape(identity['report_code'])} / Revision {identity['report_revision']}</b></li><li><small>Boss Attempt</small><b>{escape(identity['encounter_name'])} · {escape(identity['difficulty_name'])}</b></li><li><small>{escape(labels['specialization'])}</small><b>{escape(player['class_name'])} / {escape(player['spec_name'])}</b></li><li><small>{escape(labels['ranking_partition'])}</small><b>{escape(comparison['game_version'])} / Partition {comparison['partition_id']}</b></li><li><small>{escape(labels['evidence_status'])}</small><b class="{'good' if verification.get('complete_bundle') else ''}">{escape(evidence_status)}</b></li></ul></aside>
<section class="panel ability-board"><h2 class="panel-title">{escape(labels['ability_track'])}<span>{escape(labels['player_vs_median'])}</span></h2><div class="ability-head"><span>{escape(labels['ability'])}</span><span>{escape(labels['player'])}</span><span>{escape(labels['median'])}</span><span>{escape(labels['delta'])}</span><span>{escape(labels['relative_count'])}</span></div>{abilities or f'<p class="empty">{escape(labels["no_abilities"])}</p>'}</section>
<aside class="panel guard"><h2 class="panel-title">{escape(labels['claim_limits'])}<span>GUARDRAILS</span></h2><article><b class="{'bad' if metrics['deaths'] else ''}">{metrics['deaths']} {escape(labels['death_events'])}</b><p>{escape(labels['death_limit'])}</p></article><article><b>{escape(labels['damage_delta'])} {escape(delta_text)}</b><p>{escape(labels['damage_limit'])}</p></article><article><b>{escape(labels['resource_events'])} {metrics['resource_events']}</b><p>{escape(labels['resource_limit'])}</p></article></aside>
<section class="panel evidence-lane"><h2>{escape(labels['evidence_layers'])}</h2><div><article><h3>{escape(labels['log_facts'])}</h3><p>{escape(labels['log_fact_copy'])}</p></article><article><h3>{escape(labels['benchmark_comparison'])}</h3><p>{escape(labels['benchmark_copy'].format(samples=comparison['sample_count']))}</p></article><article><h3>{escape(labels['no_advice'])}</h3><p>{escape(labels['no_advice_copy'])}</p></article></div></section></section>
<footer>{escape(document['scope_note'])}<code>{escape(identity['report_code'])} / {escape(document['document_id'][:12])}</code></footer></div></div></body></html>
"""


def _render_guide_html(document: dict[str, Any]) -> str:
    identity = document["identity"]
    labels = _guide_labels(document["locale"])
    navigation = "".join(
        f'<a href="#boss-{chapter["encounter_id"]}"><b>{escape(chapter["encounter_name"])}</b><small>{chapter["sample_count"]} {escape(labels["samples"])} · {escape(labels[chapter["confidence"]])}</small></a>'
        for chapter in document["chapters"]
    )
    chapters = "".join(_render_guide_chapter(chapter, labels) for chapter in document["chapters"])
    return f"""<!doctype html>
<html lang="{escape(document['locale'], quote=True)}">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(document['title'])}</title><style>{_COACHING_CSS}</style></head>
<body>
<input class="theme-radio" id="theme-auto" name="theme" type="radio" checked><input class="theme-radio" id="theme-light" name="theme" type="radio"><input class="theme-radio" id="theme-dark" name="theme" type="radio">
<div class="report"><nav class="theme-controls" aria-label="{escape(labels['theme'])}"><label for="theme-auto">A</label><label for="theme-light">☀</label><label for="theme-dark">☾</label></nav><div class="g-shell">
<header class="g-head"><span class="mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span><div><h1>{escape(document['title'])}</h1><p>{escape(document['subtitle'])}</p></div><div class="edition"><span class="kicker">Guide Snapshot</span><strong>{len(document['chapters']):02d}</strong><small>{escape(labels['bosses'])}</small></div></header>
<div class="guide-scope"><span>{escape(identity['game_version'])} · {escape(identity['difficulty_name'])} · Partition {identity['partition_id']} · {escape(identity['class_name'])} / {escape(identity['spec_name'])}</span><span>SpellName {escape(document['ability_names_build'])} · Snapshot <code>{escape(document['snapshot_id'][:12])}</code></span></div>
<section class="g-layout"><nav class="panel chapter-nav" aria-label="{escape(labels['chapters'])}">{navigation}</nav><main class="chapters">{chapters}</main><aside class="panel guide-boundary"><h2>{escape(labels['boundary'])}</h2><p>{escape(document['scope_note'])}</p><p>{escape(labels['missing'])}</p></aside></section>
<footer>{escape(labels['boss_isolation'])}<code>{escape(document['snapshot_id'][:12])} / {escape(document['document_id'][:12])}</code></footer></div></div></body></html>
"""


def _render_personal_ability(ability: dict[str, Any], labels: dict[str, str]) -> str:
    median = ability["median_casts"]
    maximum = max(float(ability["player_casts"]), median or 0, 1)
    player_width = ability["player_casts"] / maximum * 100
    median_width = (median or 0) / maximum * 100
    delta = None if median is None else ability["player_casts"] - median
    return f'<div class="ability-row"><div class="ability-name"><b>{escape(ability["name"])}</b><small>{escape(labels["first_cast"])} {_format_optional_time(ability["player_first_cast_ms"], labels)} / {escape(labels["median_short"])} {_format_optional_time(ability["median_first_cast_ms"], labels)}</small></div><span>{ability["player_casts"]}</span><span>{_format_optional_number(median, labels)}</span><span class="delta {"bad" if delta is not None and delta < 0 else ""}">{_signed(delta, labels)}</span><div class="cast-track" style="--player:{player_width:.2f}%;--median:{median_width:.2f}%"><i></i><b></b></div></div>'


def _render_guide_chapter(chapter: dict[str, Any], labels: dict[str, str]) -> str:
    anchors = "".join(
        f'<li><time>{_format_optional_time(anchor["observed_anchor_ms"], labels)}</time><b>{escape(anchor["name"])}</b></li>'
        for anchor in chapter["mechanic_anchors"]
    ) or f'<li class="empty">{escape(labels["no_anchors"])}</li>'
    abilities = "".join(
        f'<tr><td>{escape(ability["name"])}</td><td>{_format_optional_number(ability["median_casts"], labels)}</td><td>{_format_optional_time(ability["median_first_cast_ms"], labels)}</td><td>{escape(labels["observed_only"])}</td></tr>'
        for ability in chapter["abilities"]
    ) or f'<tr><td colspan="4">{escape(labels["no_abilities"])}</td></tr>'
    targets = "".join(
        f'<tr><td>{escape(labels["target_id"])} {target["target_id"]}</td><td>{_format_optional_amount(target["median_amount"], labels)}</td><td>{escape(labels["target_limit"])}</td></tr>'
        for target in chapter["target_damage"]
    )
    sources = "".join(
        f'<article><b>{escape(source["title"])}</b><small>{escape(labels[source["kind"]])}</small><p>{escape(source["quote_summary"])}</p><a href="{escape(source["url"], quote=True)}" rel="noreferrer">{escape(source["url"])}</a></article>'
        for source in chapter["sources"]
    ) or f'<p class="empty">{escape(labels["no_sources"])}</p>'
    return f'<article class="chapter" id="boss-{chapter["encounter_id"]}"><header class="chapter-lede"><div><span class="kicker">Encounter Benchmark</span><h2>{escape(chapter["encounter_name"])}</h2><p>Encounter {chapter["encounter_id"]} · {escape(chapter["benchmark_id"][:12])}</p></div><div class="confidence"><span>{escape(labels["confidence"])}</span><strong>{escape(labels[chapter["confidence"]]).upper()}</strong><small>{chapter["sample_count"]} {escape(labels["samples"])}</small></div></header><section class="pattern-block"><h3>{escape(labels["anchors"])} <span>ENCOUNTER PROFILE</span></h3><ol class="anchor-list">{anchors}</ol></section><section class="pattern-block"><h3>{escape(labels["patterns"])} <span>{escape(labels["not_recommendations"])}</span></h3><div class="table-wrap"><table><thead><tr><th>{escape(labels["ability"])}</th><th>{escape(labels["median_casts"])}</th><th>{escape(labels["median_first_cast"])}</th><th>{escape(labels["interpretation"])}</th></tr></thead><tbody>{abilities}</tbody></table></div></section><section class="pattern-block"><h3>{escape(labels["facts"])} <span>{chapter["sample_count"]} REFERENCE SAMPLES</span></h3><div class="table-wrap"><table><tbody><tr><td>{escape(labels["damage_median"])}</td><td>{_format_optional_amount(chapter["damage_total_median"], labels)}</td><td>{escape(labels["damage_limit"])}</td></tr>{targets}</tbody></table></div></section><section class="pattern-block sources"><h3>{escape(labels["sources"])}</h3>{sources}<div class="audit"><code>Encounter Benchmark {escape(chapter["benchmark_id"][:12])}<br>Encounter Profile {escape(chapter["encounter_profile_id"][:12])}<br>Specialization Profile {escape(chapter["specialization_profile_id"][:12])}</code></div></section></article>'


def _render_phases(phases: list[dict[str, Any]], duration: int) -> str:
    return "".join(
        f'<span class="phase" style="left:{phase["start_ms"] / duration * 100:.3f}%;width:{(phase["end_ms"] - phase["start_ms"]) / duration * 100:.3f}%">{escape(phase["name"])}</span>'
        for phase in phases
    )


def _render_timeline_events(events: list[tuple[str, dict[str, Any]]], duration: int) -> str:
    return "".join(
        f'<i class="timeline-event {event["tone"]}" style="left:{event["fight_time_ms"] / duration * 100:.3f}%"><span>{_format_time(event["fight_time_ms"])} {escape(name)}</span></i>'
        for name, event in events
    )


def _render_mechanic_nav(mechanics: list[dict[str, Any]], labels: dict[str, str]) -> str:
    return "".join(
        f'<a href="#mechanic-{index}"><i class="{item["status"]}"></i><span><b>{escape(item["name"])}</b><small>{escape(_status_text(item, labels))}</small></span></a>'
        for index, item in enumerate(mechanics)
    )


def _render_mechanic(item: dict[str, Any], index: int, labels: dict[str, str]) -> str:
    counts = " · ".join(
        f"{escape(labels[field])} <b>{item[field] if item[field] is not None else '—'}</b>"
        for field in ("trigger_count", "success_count", "failure_count")
    )
    events = "".join(_render_event(event, labels) for event in item["events"])
    return f'<article class="panel finding" id="mechanic-{index}"><div class="finding-head"><div><small class="status {item["status"]}">{escape(_status_text(item, labels))}</small><h2>{escape(item["name"])}</h2></div><p class="counts">{counts}</p></div><p class="description">{escape(item["description"])}</p>{f"<div class=event-chain>{events}</div>" if events else ""}</article>'


def _render_event(event: dict[str, Any], labels: dict[str, str]) -> str:
    evidence = ""
    if event["evidence_excerpt"] is not None:
        encoded = json.dumps(event["evidence_excerpt"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        evidence = f'<details><summary>{escape(labels["evidence_excerpt"])}</summary><pre>{escape(encoded)}</pre></details>'
    participants = ", ".join(event["participants"])
    participant_line = f'<small>{escape(participants)}</small>' if participants else ""
    return f'<time>{_format_time(event["fight_time_ms"])}</time><span class="track {event["tone"]}"></span><div class="event-copy"><b>{escape(event["title"])}</b>{participant_line}<p>{escape(event["description"])}</p>{evidence}</div>'


def _render_participants(participants: list[str], labels: dict[str, str]) -> str:
    if not participants:
        return f'<p class="empty">{escape(labels["none"])}</p>'
    return '<div class="participant-grid">' + "".join(f'<span>{escape(item)}</span>' for item in participants) + "</div>"


def _render_actions(actions: list[dict[str, str]], labels: dict[str, str]) -> str:
    if not actions:
        return ""
    items = "".join(f'<div><b>{escape(item["title"])}</b><p>{escape(item["description"])}</p></div>' for item in actions)
    return f'<section class="panel actions"><h2>{escape(labels["next_attempt"])}</h2><div>{items}</div></section>'


def _status_text(item: dict[str, Any], labels: dict[str, str]) -> str:
    if item["status"] == "anomaly":
        return f'{item["failure_count"]} {labels["anomalies"]}'
    return labels[item["status"]]


def _personal_labels(locale: str) -> dict[str, str]:
    if locale == "en":
        return {
            "theme": "Color theme", "item_level": "Item level", "anonymous": "anonymized data",
            "damage": "Damage total", "healing": "Healing total", "interrupts": "Interrupt events", "deaths": "Deaths",
            "comparison_scope": "Comparison scope", "samples": "samples", "low": "Low confidence", "normal": "Normal confidence", "hard_match": "Hard conditions match",
            "identity_evidence": "Identity and evidence", "specialization": "Specialization", "ranking_partition": "Ranking partition", "evidence_status": "Evidence status", "bundle_verified": "Complete Bundle verified", "not_verified": "Not verified",
            "ability_track": "Key ability cast track", "player_vs_median": "Player vs sample median", "ability": "Ability", "player": "Player", "median": "Median", "delta": "Delta", "relative_count": "Relative count",
            "claim_limits": "Claim limits", "death_events": "death events", "death_limit": "The analysis has no death timestamp, killing ability, or responsibility attribution.",
            "damage_delta": "Damage delta", "damage_limit": "This unnormalized arithmetic delta is not an achievable improvement estimate.", "resource_events": "Resource events", "resource_limit": "This is an event count, not resource gain, overcap, or waste.",
            "evidence_layers": "Evidence layers", "log_facts": "Log facts", "log_fact_copy": "Casts, first-cast times, damage, healing, interrupts, resource events, and death counts come from the Complete Bundle.",
            "benchmark_comparison": "Benchmark comparison", "benchmark_copy": "Medians come from {samples} Reference Samples under the same hard conditions.", "no_advice": "No formal advice", "no_advice_copy": "The comparison artifact does not produce mechanic attribution or a coaching verdict.",
            "first_cast": "First cast", "median_short": "median", "unavailable": "Unavailable", "no_abilities": "No ability comparison is available.",
        }
    return {
        "theme": "颜色主题", "item_level": "装等", "anonymous": "匿名化数据",
        "damage": "伤害总量", "healing": "治疗量", "interrupts": "打断事件", "deaths": "死亡",
        "comparison_scope": "比较范围", "samples": "个样本", "low": "低置信度", "normal": "标准置信度", "hard_match": "硬条件匹配",
        "identity_evidence": "身份与证据", "specialization": "专精条件", "ranking_partition": "排名分区", "evidence_status": "证据状态", "bundle_verified": "Complete Bundle 已校验", "not_verified": "未校验",
        "ability_track": "关键技能施放轨", "player_vs_median": "玩家 vs 样本中位数", "ability": "技能", "player": "玩家", "median": "中位数", "delta": "差值", "relative_count": "相对次数",
        "claim_limits": "结论边界", "death_events": "次死亡", "death_limit": "当前 analysis 不包含死亡时间、致死技能或责任，不能推断死亡原因。",
        "damage_delta": "伤害差值", "damage_limit": "这是未归一化的算术差值，不是可实现提升值。", "resource_events": "资源事件", "resource_limit": "这里只表示资源事件条数，不表示获取量、溢出或浪费。",
        "evidence_layers": "证据分层", "log_facts": "日志事实", "log_fact_copy": "施放、首次施放时间、伤害、治疗、打断、资源事件和死亡计数来自 Complete Bundle。",
        "benchmark_comparison": "Benchmark 比较", "benchmark_copy": "中位数来自同一硬条件下的 {samples} 个 Reference Samples。", "no_advice": "尚无正式建议", "no_advice_copy": "comparison artifact 不产生机制归因或 coaching verdict。",
        "first_cast": "首次施放", "median_short": "中位", "unavailable": "不可用", "no_abilities": "没有可展示的技能比较。",
    }


def _guide_labels(locale: str) -> dict[str, str]:
    if locale == "en":
        return {
            "theme": "Color theme", "bosses": "Bosses", "chapters": "Boss chapters", "samples": "samples", "low": "Low", "normal": "Normal",
            "boundary": "Interpretation boundary", "missing": "This Guide Snapshot has no structured rotation, talent, gear, or prescriptive advice fields, so none are generated.", "boss_isolation": "Encounter Benchmarks from different Bosses are not mixed.",
            "confidence": "Evidence level", "anchors": "Mechanic time anchors", "patterns": "Observable high-ranked patterns", "not_recommendations": "whole-attempt medians, not recommendations",
            "ability": "Ability", "median_casts": "Median casts", "median_first_cast": "Median first cast", "interpretation": "Interpretation", "observed_only": "Describes samples only",
            "facts": "Log fact summary", "damage_median": "Median valid damage total", "damage_limit": "Not DPS or an achievable target", "target_id": "Target ID", "target_limit": "NPC name is not inferred across reports",
            "sources": "Sources", "encounter": "Encounter Profile", "specialization": "Specialization Profile", "no_sources": "No source summary is available.", "no_anchors": "No verified mechanic Spell time anchor.", "no_abilities": "No cast median is available.", "unavailable": "Unavailable",
        }
    return {
        "theme": "颜色主题", "bosses": "BOSSES", "chapters": "Boss 章节", "samples": "样本", "low": "低置信度", "normal": "标准置信度",
        "boundary": "解释边界", "missing": "当前 Guide Snapshot 没有结构化 rotation、天赋、装备或具体实战建议字段，因此本页不生成这些内容。", "boss_isolation": "不同 Boss 的 Encounter Benchmark 不混合。",
        "confidence": "证据等级", "anchors": "机制时间锚点", "patterns": "高分样本可观察模式", "not_recommendations": "整场中位数 · 非推荐次数",
        "ability": "技能", "median_casts": "施放中位数", "median_first_cast": "首次施放中位数", "interpretation": "解释边界", "observed_only": "只描述样本",
        "facts": "日志事实摘要", "damage_median": "有效伤害总量中位数", "damage_limit": "不是 DPS 或可实现目标", "target_id": "目标 ID", "target_limit": "不跨报告猜测 NPC 名称",
        "sources": "资料来源", "encounter": "Encounter Profile", "specialization": "Specialization Profile", "no_sources": "没有可展示的来源摘要。", "no_anchors": "暂无已验证的机制 Spell 时间锚点。", "no_abilities": "没有可展示的施放中位数。", "unavailable": "不可用",
    }


def _metric(label: str, value: str, class_name: str = "") -> str:
    return f'<div><small>{escape(label)}</small><b class="{class_name}">{escape(value)}</b></div>'


def _initials(value: str) -> str:
    parts = value.split()
    return "".join(part[0] for part in parts[:2]).upper() if parts else "?"


def _format_amount(value: float | int) -> str:
    absolute = abs(value)
    for threshold, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if absolute >= threshold:
            return f"{value / threshold:g}{suffix}"
    return f"{value:g}"


def _format_optional_amount(value: float | None, labels: dict[str, str]) -> str:
    return labels["unavailable"] if value is None else _format_amount(value)


def _format_optional_number(value: float | None, labels: dict[str, str]) -> str:
    return labels["unavailable"] if value is None else f"{value:g}"


def _format_optional_time(value: float | None, labels: dict[str, str]) -> str:
    return labels["unavailable"] if value is None else _format_time(round(value))


def _signed(value: float | None, labels: dict[str, str]) -> str:
    if value is None:
        return labels["unavailable"]
    return f"{value:+g}" if value else "0"


def _labels(locale: str) -> dict[str, str]:
    if locale == "en":
        return {
            "theme": "Color theme", "boss_attempt": "Boss Attempt", "result": "Result", "kill": "Kill", "wipe": "Wipe",
            "verified_anomalies": "Verified anomalies", "manual_review": "Manual review", "verified_anomalies_count": "verified anomalies", "manual_review_count": "signals for manual review", "reviewable": "Reviewable conclusion",
            "attempt_timeline": "Attempt pressure timeline", "successful_signals": "successful signals", "evidence_events": "evidence events",
            "mechanics": "Mechanic signals", "involved_players": "Involved players", "next_attempt": "Next-attempt checks",
            "trigger_count": "Triggers", "success_count": "Success", "failure_count": "Failure", "evidence_excerpt": "Minimal evidence excerpt",
            "anomalies": "anomalies", "review": "Manual review", "ok": "No anomaly", "unverified": "Pattern unverified", "none": "No involved players in excerpts", "full_attempt": "Full Boss Attempt",
        }
    return {
        "theme": "颜色主题", "boss_attempt": "Boss Attempt", "result": "当前结果", "kill": "击杀", "wipe": "灭团",
        "verified_anomalies": "已验证异常", "manual_review": "待人工裁决", "verified_anomalies_count": "个已验证异常", "manual_review_count": "个信号待人工裁决", "reviewable": "结论可复核",
        "attempt_timeline": "Attempt 压力轨迹", "successful_signals": "成功机制信号", "evidence_events": "证据事件",
        "mechanics": "机制压力", "involved_players": "涉及玩家", "next_attempt": "下一把验证",
        "trigger_count": "触发", "success_count": "成功", "failure_count": "失败", "evidence_excerpt": "最小事件证据",
        "anomalies": "个异常", "review": "需人工复核", "ok": "无异常", "unverified": "模式未验证", "none": "证据摘录未涉及玩家", "full_attempt": "完整 Boss Attempt",
    }


def _format_time(milliseconds: int) -> str:
    minutes, remainder = divmod(milliseconds, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{label} must be an object.")
    return value


def _fields(value: dict[str, Any], label: str, required: set[str]) -> None:
    missing = sorted(required - value.keys())
    unexpected = sorted(value.keys() - required)
    if missing:
        raise InputError(f"{label} is missing field: {missing[0]}.")
    if unexpected:
        raise InputError(f"{label} has unexpected field: {unexpected[0]}.")


def _list(value: Any, label: str, *, nonempty: bool = False, maximum: int) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value) or len(value) > maximum:
        qualifier = "a non-empty" if nonempty else "a"
        raise InputError(f"{label} must be {qualifier} list with at most {maximum} items.")
    return value


def _text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InputError(f"{label} must be non-empty text with at most {maximum} characters.")
    return value.strip()


def _integer(value: Any, label: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < (1 if positive else 0):
        qualifier = "positive " if positive else "non-negative "
        raise InputError(f"{label} must be a {qualifier}integer.")
    return value


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _optional_nonnegative_number(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if not _number(value) or value < 0:
        raise InputError(f"{label} must be null or a non-negative finite number.")
    return float(value)


def _digest(value: Any, label: str) -> str:
    digest = _text(value, label, 64).lower()
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise InputError(f"{label} must be a SHA-256 hex digest.")
    return digest


def _public_url(value: Any, label: str) -> str:
    source = _text(value, label, 1000)
    try:
        parsed = urlsplit(source)
        hostname = parsed.hostname
        parameters = parse_qsl(parsed.query, keep_blank_values=True) + parse_qsl(
            parsed.fragment, keep_blank_values=True
        )
    except ValueError as exc:
        raise InputError(f"{label} URL is malformed.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise InputError(f"{label} must be a public HTTP or HTTPS URL.")
    sensitive_names = {
        "accesstoken", "apikey", "auth", "authentication", "authorization",
        "clientsecret", "credential", "key", "secret", "signature", "token",
        "xamzcredential", "xamzsignature",
    }
    normalized_names = []
    for name, _ in parameters:
        decoded = name
        while (next_decoded := unquote(decoded)) != decoded:
            decoded = next_decoded
        normalized_names.append(re.sub(r"[^a-z0-9]", "", decoded.lower()))
    if any(name in sensitive_names for name in normalized_names):
        raise InputError(f"{label} must not contain credentials.")
    return source


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, bool)) or _number(value)


_CSS = """
*{box-sizing:border-box}body{margin:0;min-width:320px}.theme-radio{position:fixed;opacity:0;pointer-events:none}.report{--bg:#e5e1d8;--panel:#fbf8ee;--ink:#231f1a;--muted:#6f675b;--line:#918778;--accent:#284b75;--danger:#a82d25;--warn:#8a5b08;--ok:#3d6b50;--hero:#231f1a;--hero-ink:#fbf8ee;min-height:100vh;background:var(--bg);color:var(--ink);font-family:"Arial Narrow","Avenir Next Condensed",Arial,sans-serif}.shell{max-width:1580px;margin:auto;padding:20px 30px 40px}.theme-controls{position:fixed;z-index:5;top:16px;right:18px;display:flex;border:1px solid var(--line);background:var(--panel)}.theme-controls label{display:grid;place-items:center;width:34px;height:34px;border-right:1px solid var(--line);cursor:pointer;font-weight:700}.theme-controls label:last-child{border:0}#theme-auto:checked~.report label[for=theme-auto],#theme-light:checked~.report label[for=theme-light],#theme-dark:checked~.report label[for=theme-dark]{background:var(--accent);color:var(--panel)}#theme-light:checked~.report{--bg:#e5e1d8;--panel:#fbf8ee;--ink:#231f1a;--muted:#6f675b;--line:#918778;--accent:#284b75;--danger:#a82d25;--warn:#8a5b08;--ok:#3d6b50;--hero:#231f1a;--hero-ink:#fbf8ee}#theme-dark:checked~.report{--bg:#171716;--panel:#22211e;--ink:#eee9dc;--muted:#b1aa9b;--line:#655f55;--accent:#80aee0;--danger:#ff756d;--warn:#e4b766;--ok:#79bf91;--hero:#11110f;--hero-ink:#eee9dc}.masthead{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:16px;padding-right:105px}.mark{display:grid;grid-template-columns:repeat(2,12px);gap:3px}.mark i{width:12px;height:12px;background:var(--ink)}.mark i:nth-child(2),.mark i:nth-child(3){background:var(--accent)}h1{margin:0;font-size:clamp(24px,2.2vw,35px);line-height:1;letter-spacing:-.03em}.masthead p{margin:6px 0 0;color:var(--muted);font-size:13px}.attempt{text-align:right}.attempt small{display:block;color:var(--muted);font-size:11px;font-weight:700}.attempt b,code,time{font-family:"SFMono-Regular",Consolas,monospace}.hero{display:grid;grid-template-columns:260px 1fr;min-height:238px;margin-top:20px;border:1px solid var(--line);background:var(--panel)}.verdict{display:grid;align-content:space-between;padding:22px;border-right:1px solid var(--line);background:var(--hero);color:var(--hero-ink)}.verdict small{opacity:.7;font-weight:800}.verdict strong{display:block;color:#ff756d;font-size:60px;line-height:.9;letter-spacing:-.07em}.verdict p{margin:8px 0;color:var(--hero-ink);opacity:.78;line-height:1.5}.verdict span{border:1px solid var(--danger);padding:8px;color:#ff756d;font-size:12px;font-weight:800}.timeline{padding:24px 30px}.section-head{display:flex;justify-content:space-between;align-items:baseline;gap:16px}.section-head h2{margin:0;font-size:18px}.section-head code{color:var(--muted);font-size:11px}.phase-rail{position:relative;height:125px;margin-top:24px;border-bottom:2px solid var(--ink)}.phase{position:absolute;bottom:0;height:35px;padding:10px 8px;border-left:1px solid var(--line);background:color-mix(in srgb,var(--accent) 5%,transparent);color:var(--muted);font-size:11px;overflow:hidden;white-space:nowrap}.timeline-event{position:absolute;bottom:35px;width:2px;height:45px;background:var(--danger)}.timeline-event:nth-of-type(even){height:68px}.timeline-event:before{content:"";position:absolute;top:-4px;left:-4px;width:10px;height:10px;border-radius:50%;background:inherit}.timeline-event span{position:absolute;top:-8px;left:9px;width:135px;font-size:10px;font-style:normal;font-weight:750}.timeline-event.ok{background:var(--ok)}.timeline-event.warn{background:var(--warn)}.summary{display:grid;grid-template-columns:repeat(4,1fr);margin-top:12px;border:1px solid var(--line);background:var(--panel)}.summary div{display:grid;grid-template-columns:1fr auto;align-items:end;min-height:75px;padding:14px;border-right:1px solid var(--line)}.summary div:last-child{border:0}.summary small{color:var(--muted);font-weight:700}.summary b{font-size:28px}.bad,.anomaly,.danger{color:var(--danger)!important}.warning,.review,.warn{color:var(--warn)!important}.good,.ok{color:var(--ok)!important}.unverified,.info{color:var(--muted)!important}.workspace{display:grid;grid-template-columns:260px minmax(500px,1fr) 285px;gap:12px;margin-top:12px;align-items:start}.panel{border:1px solid var(--line);background:var(--panel)}.panel>h2,.mechanic-nav>h2{margin:0;padding:13px 15px;border-bottom:1px solid var(--line);font-size:15px}.mechanic-nav{position:sticky;top:12px}.mechanic-nav a{display:grid;grid-template-columns:8px 1fr;gap:10px;padding:12px 14px;border-bottom:1px solid color-mix(in srgb,var(--line) 55%,transparent);color:inherit;text-decoration:none}.mechanic-nav a:last-child{border:0}.mechanic-nav i{width:8px;height:8px;margin-top:4px;background:currentColor}.mechanic-nav b,.mechanic-nav small{display:block}.mechanic-nav b{font-size:13px}.mechanic-nav small{margin-top:3px;color:var(--muted);font-size:11px}.findings{display:grid;gap:12px}.finding{scroll-margin-top:12px}.finding-head{display:flex;justify-content:space-between;gap:16px;padding:17px 19px 0}.finding-head h2{margin:5px 0 0;font-size:24px}.status{font-size:11px;font-weight:800}.counts{margin:0;align-self:end;color:var(--muted);font-size:12px}.description{max-width:76ch;margin:13px 19px 18px;color:var(--muted);line-height:1.6}.event-chain{display:grid;grid-template-columns:80px 12px 1fr;padding:0 19px 18px}.event-chain time{padding:12px 7px 0 0;color:var(--muted);text-align:right;font-size:10px}.track{position:relative;border-left:2px solid currentColor}.track:before{content:"";position:absolute;top:15px;left:-5px;width:8px;height:8px;background:currentColor;transform:rotate(45deg)}.event-copy{margin:4px 0 7px;padding:9px 11px;background:var(--bg)}.event-copy>b,.event-copy>small{display:block}.event-copy>small{margin-top:3px;color:var(--muted)}.event-copy p{margin:5px 0;line-height:1.45}.event-copy details{margin-top:7px}.event-copy summary{cursor:pointer;color:var(--accent);font-size:12px;font-weight:700}.event-copy pre{overflow:auto;padding:9px;background:var(--panel);font:10px/1.5 "SFMono-Regular",Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}.participants{position:sticky;top:12px}.participant-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:14px}.participant-grid span{padding:10px 7px;border:1px solid var(--danger);color:var(--danger);font-size:11px;font-weight:800;text-align:center}.empty{padding:14px;color:var(--muted);font-size:12px}.actions{grid-column:2/4;display:grid;grid-template-columns:170px 1fr}.actions>h2{border:0;border-right:1px solid var(--line);font-size:20px}.actions>div{display:grid;grid-template-columns:repeat(3,1fr)}.actions>div>div{padding:14px;border-right:1px solid var(--line)}.actions>div>div:last-child{border:0}.actions b{color:var(--accent)}.actions p{margin:5px 0 0;font-size:13px;line-height:1.45}footer{display:flex;justify-content:space-between;gap:25px;margin-top:12px;padding:15px;border-left:4px solid var(--accent);background:var(--panel);color:var(--muted);font-size:12px}footer p{margin:0;max-width:80ch}footer code{white-space:nowrap;font-size:10px}@media(prefers-color-scheme:dark){#theme-auto:checked~.report{--bg:#171716;--panel:#22211e;--ink:#eee9dc;--muted:#b1aa9b;--line:#655f55;--accent:#80aee0;--danger:#ff756d;--warn:#e4b766;--ok:#79bf91;--hero:#11110f;--hero-ink:#eee9dc}}@media(max-width:1000px){.workspace{grid-template-columns:220px 1fr}.participants{display:none}.actions{grid-column:1/3}}@media(max-width:720px){.shell{padding:14px 12px 30px}.theme-controls{position:absolute;top:10px;right:10px}.masthead{grid-template-columns:auto 1fr;padding-right:100px}.attempt{grid-column:2;text-align:left}.hero,.workspace{grid-template-columns:1fr}.verdict{min-height:185px;border-right:0;border-bottom:1px solid var(--line)}.timeline{padding:20px 15px}.timeline-event span{display:none}.summary{grid-template-columns:1fr 1fr}.mechanic-nav{position:static}.actions{grid-column:1;grid-template-columns:1fr}.actions>h2{border-right:0;border-bottom:1px solid var(--line)}.actions>div{grid-template-columns:1fr}.actions>div>div{border-right:0;border-bottom:1px solid var(--line)}footer{display:block}footer code{display:block;margin-top:12px;white-space:normal}}@media(max-width:430px){.masthead{padding-right:0}.masthead>div:nth-child(2){padding-right:95px}.summary{grid-template-columns:1fr}.summary div{border-right:0;border-bottom:1px solid var(--line)}.finding-head{display:block}.counts{margin-top:9px}.event-chain{grid-template-columns:62px 10px 1fr;padding-inline:10px}}
"""


_COACHING_CSS = """
*{box-sizing:border-box}body{margin:0;min-width:320px}.theme-radio{position:fixed;opacity:0;pointer-events:none}.report{--bg:#e5e1d8;--paper:#fbf8ee;--ink:#231f1a;--muted:#6f675b;--line:#918778;--blue:#284b75;--red:#a82d25;--green:#3d6b50;min-height:100vh;background:var(--bg);color:var(--ink);font-family:"Arial Narrow","Avenir Next Condensed",Arial,sans-serif;overflow-wrap:anywhere}.theme-controls{position:fixed;z-index:5;top:16px;right:18px;display:flex;border:1px solid var(--line);background:var(--paper)}.theme-controls label{display:grid;place-items:center;width:34px;height:34px;border-right:1px solid var(--line);cursor:pointer;font-weight:700}.theme-controls label:last-child{border:0}#theme-auto:focus-visible~.report label[for=theme-auto],#theme-light:focus-visible~.report label[for=theme-light],#theme-dark:focus-visible~.report label[for=theme-dark]{outline:3px solid var(--blue);outline-offset:2px}#theme-auto:checked~.report label[for=theme-auto],#theme-light:checked~.report label[for=theme-light],#theme-dark:checked~.report label[for=theme-dark]{background:var(--blue);color:var(--paper)}#theme-dark:checked~.report{--bg:#171716;--paper:#22211e;--ink:#eee9dc;--muted:#b1aa9b;--line:#655f55;--blue:#80aee0;--red:#ff756d;--green:#79bf91}.p-shell,.g-shell{max-width:1580px;margin:auto;padding:20px 30px 40px}.mark{display:grid;grid-template-columns:repeat(2,12px);gap:3px}.mark i{width:12px;height:12px;background:var(--ink)}.mark i:nth-child(2),.mark i:nth-child(3){background:var(--blue)}.kicker{color:var(--blue);font-size:11px;font-weight:800;letter-spacing:.07em}.panel{border:1px solid var(--line);background:var(--paper)}.panel-title{display:flex;justify-content:space-between;align-items:center;min-height:44px;margin:0;padding:0 14px;border-bottom:1px solid var(--line);font-size:14px}.panel-title span{color:var(--muted);font:10px "SFMono-Regular",Consolas,monospace}.p-head,.g-head{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:15px;padding-right:105px}.p-head h1,.g-head h1{margin:0;font-size:clamp(25px,2.5vw,40px);line-height:1}.p-head p,.g-head p{margin:6px 0 0;color:var(--muted);font-size:13px}.p-id,.edition{text-align:right}.p-id b,.p-id span,.edition span,.edition small{display:block}.p-id b,code,time{font-family:"SFMono-Regular",Consolas,monospace}.player-strip{display:grid;grid-template-columns:240px 1fr 245px;margin-top:19px;border:1px solid var(--line);background:var(--paper)}.player-card{display:grid;grid-template-columns:64px 1fr;gap:14px;align-items:center;padding:20px;background:var(--ink);color:var(--paper)}.avatar{display:grid;place-items:center;width:64px;height:64px;border:1px solid currentColor;font:800 20px "SFMono-Regular",Consolas,monospace}.player-card h2{margin:0;font-size:22px}.player-card p{margin:5px 0 0;color:var(--muted);font-size:12px}.fact-ribbon{display:grid;grid-template-columns:repeat(4,1fr)}.fact-ribbon div{display:grid;align-content:center;padding:17px;border-right:1px solid var(--line)}.fact-ribbon small{color:var(--muted);font-weight:700}.fact-ribbon b{margin-top:7px;font:800 22px "SFMono-Regular",Consolas,monospace}.benchmark-seal{display:grid;align-content:center;padding:18px}.benchmark-seal strong{font-size:24px}.benchmark-seal p{margin:6px 0 0;color:var(--muted);font-size:12px;line-height:1.5}.p-grid{display:grid;grid-template-columns:250px minmax(560px,1fr) 300px;gap:11px;margin-top:11px;align-items:start}.scope-list{margin:0;padding:7px 14px 13px;list-style:none}.scope-list li{padding:10px 0;border-bottom:1px solid color-mix(in srgb,var(--line) 45%,transparent)}.scope-list li:last-child{border:0}.scope-list small,.scope-list b{display:block}.scope-list small{color:var(--muted);font-size:10px}.scope-list b{margin-top:4px;font-size:13px}.ability-board{padding-bottom:12px}.ability-head,.ability-row{display:grid;grid-template-columns:minmax(150px,1.3fr) 70px 70px 65px minmax(130px,1fr);gap:10px;align-items:center;padding:11px 14px}.ability-head{color:var(--muted);font-size:10px;font-weight:800;border-bottom:1px solid var(--line)}.ability-row{border-bottom:1px solid color-mix(in srgb,var(--line) 45%,transparent);font-family:"SFMono-Regular",Consolas,monospace}.ability-name b,.ability-name small{display:block}.ability-name b{font-family:"Arial Narrow",Arial,sans-serif}.ability-name small{margin-top:4px;color:var(--muted);font-size:10px}.cast-track{position:relative;height:18px;border-bottom:1px solid var(--line)}.cast-track i,.cast-track b{position:absolute;left:0;bottom:2px;height:6px}.cast-track i{width:var(--player);background:var(--blue)}.cast-track b{left:var(--median);width:2px;height:14px;background:var(--red)}.guard article{padding:14px;border-bottom:1px solid var(--line)}.guard article:last-child{border:0}.guard p{margin:7px 0 0;color:var(--muted);font-size:12px;line-height:1.5}.bad{color:var(--red)!important}.good{color:var(--green)!important}.evidence-lane{grid-column:1/4;display:grid;grid-template-columns:170px 1fr}.evidence-lane>h2{margin:0;padding:18px;border-right:1px solid var(--line);font-size:17px}.evidence-lane>div{display:grid;grid-template-columns:repeat(3,1fr)}.evidence-lane article{padding:15px;border-right:1px solid var(--line)}.evidence-lane article:last-child{border:0}.evidence-lane h3{margin:0;font-size:13px}.evidence-lane p{margin:7px 0 0;color:var(--muted);font-size:12px;line-height:1.5}.empty{padding:16px;color:var(--muted)}footer{display:flex;justify-content:space-between;gap:20px;margin-top:18px;padding-top:12px;border-top:1px solid var(--line);color:var(--muted);font-size:11px}.g-head{align-items:end;padding-bottom:17px;border-bottom:5px double var(--ink)}.g-head h1{font:500 clamp(32px,4.3vw,62px)/.95 Georgia,"Songti SC",serif;letter-spacing:-.045em}.edition strong{display:block;font:500 39px Georgia,serif}.guide-scope{display:flex;justify-content:space-between;gap:25px;padding:11px 0;border-bottom:1px solid var(--line);font-size:12px}.g-layout{display:grid;grid-template-columns:230px minmax(570px,1fr) 270px;gap:18px;margin-top:22px;align-items:start}.chapter-nav{position:sticky;top:15px;border-top:4px solid var(--blue)}.chapter-nav a{display:block;padding:14px;border-bottom:1px solid var(--line);color:inherit;text-decoration:none}.chapter-nav b,.chapter-nav small{display:block}.chapter-nav small{margin-top:5px;color:var(--muted)}.chapters{display:grid;gap:18px}.chapter{background:var(--paper);border:1px solid var(--line)}.chapter-lede{display:grid;grid-template-columns:1fr auto;gap:20px;padding:20px;border-bottom:1px solid var(--line)}.chapter-lede h2{margin:0;font:500 35px Georgia,"Songti SC",serif}.chapter-lede p{margin:7px 0 0;color:var(--muted);font-size:12px}.confidence{align-self:start;padding:12px;border:2px solid var(--red);color:var(--red);text-align:center}.confidence strong{display:block;font:700 25px Georgia,serif}.pattern-block{padding:18px 20px;border-bottom:1px solid var(--line)}.pattern-block:last-child{border:0}.pattern-block h3{display:flex;justify-content:space-between;margin:0 0 14px;font-size:16px}.pattern-block h3 span{color:var(--muted);font:10px "SFMono-Regular",Consolas,monospace}.anchor-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:0;padding:0;list-style:none}.anchor-list li{padding:12px;border-left:4px solid var(--blue);background:var(--bg)}.anchor-list time,.anchor-list b{display:block}.anchor-list b{margin-top:6px}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:10px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--muted);font-size:10px}.sources article{padding:12px 0;border-bottom:1px solid var(--line)}.sources article small{display:block;margin-top:4px;color:var(--blue)}.sources p{color:var(--muted);line-height:1.5}.sources a{color:var(--blue);overflow-wrap:anywhere}.audit{margin-top:14px;padding:12px;background:var(--bg);line-height:1.6}.guide-boundary{padding:15px;border-top:4px solid var(--red)}.guide-boundary h2{margin:0;font-size:16px}.guide-boundary p{color:var(--muted);font-size:12px;line-height:1.6}
@media(prefers-color-scheme:dark){#theme-auto:checked~.report{--bg:#171716;--paper:#22211e;--ink:#eee9dc;--muted:#b1aa9b;--line:#655f55;--blue:#80aee0;--red:#ff756d;--green:#79bf91}}@media(max-width:1050px){.p-grid,.g-layout{grid-template-columns:220px 1fr}.guard,.guide-boundary{grid-column:1/3}.evidence-lane{grid-column:1/3}.player-strip{grid-template-columns:220px 1fr}.benchmark-seal{display:none}}@media(max-width:720px){.theme-controls{top:10px;right:10px}.p-shell,.g-shell{padding:14px 12px 30px}.p-head,.g-head{grid-template-columns:auto 1fr;padding-right:100px}.p-id,.edition{grid-column:2;text-align:left}.player-strip{grid-template-columns:1fr}.fact-ribbon{grid-template-columns:1fr 1fr}.fact-ribbon div{border-top:1px solid var(--line)}.p-grid,.g-layout{grid-template-columns:1fr}.guard,.guide-boundary,.evidence-lane{grid-column:1}.ability-board{overflow-x:auto}.ability-head,.ability-row{min-width:650px}.evidence-lane{grid-template-columns:1fr}.evidence-lane>h2{border-right:0;border-bottom:1px solid var(--line)}.evidence-lane>div{grid-template-columns:1fr}.evidence-lane article{border-right:0;border-bottom:1px solid var(--line)}.chapter-nav{position:static}.guide-scope{display:block}.guide-scope span{display:block;margin-top:5px}footer{display:block}footer code{display:block;margin-top:8px}}@media(max-width:430px){.fact-ribbon{grid-template-columns:1fr}.chapter-lede{grid-template-columns:1fr}.confidence{justify-self:start}.g-head h1{font-size:36px}}
"""
