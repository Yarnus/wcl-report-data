from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .errors import DatasetError, InputError
from .dataset import validate_complete_bundle
from .storage import read_json, sha256_file


ANALYSIS_SCHEMA_VERSION = 3


def analyze_player(
    manifest_path: Path,
    index_path: Path,
    actor_id: int,
    *,
    partition_id: int | None = None,
) -> dict[str, Any]:
    manifest, events_path = validate_complete_bundle(manifest_path)
    index = _object(read_json(index_path), "Report Index")
    index_digest = hashlib.sha256(
        json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if manifest.get("report_index_sha256") != index_digest:
        raise DatasetError("Report Index does not match the Complete Bundle.")
    identity = _object(manifest.get("identity"), "Complete Bundle identity")
    index_identity = _object(index.get("report"), "Report Index report identity")
    if (identity.get("report_code"), identity.get("report_revision")) != (
        index_identity.get("code"), index_identity.get("revision")
    ):
        raise DatasetError("Complete Bundle and Report Index belong to different Report Revisions.")
    fights = index.get("fights")
    if not isinstance(fights, list):
        raise DatasetError("Report Index fights are malformed.")
    fight = next(
        (
            item
            for item in fights
            if isinstance(item, dict) and item.get("fight_id", item.get("id")) == identity.get("fight_id")
        ),
        None,
    )
    if fight is None:
        raise DatasetError("Complete Bundle Boss Attempt is absent from its Report Index.")
    participants = fight.get("participants")
    if not isinstance(participants, list):
        raise DatasetError("Boss Attempt participants are malformed.")
    player = next((item for item in participants if isinstance(item, dict) and item.get("actor_id") == actor_id), None)
    if player is None:
        raise InputError(f"Actor {actor_id} did not participate in this Boss Attempt.")
    actors = index.get("actors")
    owned_actor_ids = {actor_id}
    if isinstance(actors, list):
        owned_actor_ids.update(
            actor.get("id")
            for actor in actors
            if isinstance(actor, dict) and actor.get("petOwner") == actor_id and isinstance(actor.get("id"), int)
        )
    casts: Counter[str] = Counter()
    first_cast_ms: dict[str, float] = {}
    damage_by_ability: Counter[str] = Counter()
    damage_by_target: Counter[str] = Counter()
    healing_by_ability: Counter[str] = Counter()
    resource_events = 0
    interrupts = 0
    deaths = 0
    with gzip.open(events_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetError("Canonical Event stream contains invalid JSON.") from exc
            if not isinstance(event, dict):
                raise DatasetError("Canonical Event stream contains a non-object event.")
            source = event.get("source")
            target = event.get("target")
            from_player = isinstance(source, dict) and source.get("actor_id") in owned_actor_ids
            to_player = isinstance(target, dict) and target.get("actor_id") == actor_id
            event_type = event.get("type")
            ability = str(event.get("ability_id"))
            fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
            amount = _amount(fields)
            if from_player and event_type == "cast":
                casts[ability] += 1
                timestamp = event.get("fight_time_ms")
                if ability not in first_cast_ms and isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
                    first_cast_ms[ability] = float(timestamp)
            elif from_player and event_type == "damage":
                damage_by_ability[ability] += amount
                if isinstance(target, dict) and isinstance(target.get("actor_id"), int):
                    damage_by_target[str(target["actor_id"])] += amount
            elif from_player and event_type == "heal":
                healing_by_ability[ability] += amount
            elif from_player and event_type in {"resourcechange", "energize"}:
                resource_events += 1
            elif from_player and event_type == "interrupt":
                interrupts += 1
            if to_player and event_type == "death":
                deaths += 1
    result = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "identity": dict(identity),
        "player": dict(player),
        "evidence": {
            "manifest_path": str(manifest_path.resolve()),
            "manifest_sha256": sha256_file(manifest_path),
            "index_path": str(index_path.resolve()),
            "index_sha256": sha256_file(index_path),
        },
        "metrics": {
            "casts": dict(sorted(casts.items())),
            "first_cast_ms": dict(sorted(first_cast_ms.items())),
            "damage_by_ability": dict(sorted(damage_by_ability.items())),
            "damage_total": sum(damage_by_ability.values()),
            "damage_by_target": dict(sorted(damage_by_target.items())),
            "healing_by_ability": dict(sorted(healing_by_ability.items())),
            "healing_total": sum(healing_by_ability.values()),
            "resource_events": resource_events,
            "interrupts": interrupts,
            "deaths": deaths,
        },
    }
    if partition_id is not None:
        result["comparison_identity"] = {
            "game_version": _ranking_game_version(index_identity, partition_id),
            "partition_id": partition_id,
            "encounter_id": fight.get("encounter_id"),
            "difficulty_id": fight.get("difficulty"),
            "class_name": player.get("class"),
            "spec_name": player.get("spec"),
        }
    return result


def _amount(fields: dict[str, Any]) -> int:
    value = fields.get("amount")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return int(value)
    return 0


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DatasetError(f"{label} must be a JSON object.")
    return value


def _ranking_game_version(report: dict[str, Any], partition_id: int) -> str:
    if type(partition_id) is not int or partition_id <= 0:
        raise DatasetError("Personal Analysis ranking partition ID is malformed.")
    zone = report.get("zone")
    partitions = zone.get("partitions") if isinstance(zone, dict) else None
    if not isinstance(partitions, list) or not partitions:
        raise DatasetError("Report Index ranking partitions are malformed.")
    by_id: dict[int, dict[str, Any]] = {}
    for partition in partitions:
        if not isinstance(partition, dict):
            raise DatasetError("Report Index ranking partitions are malformed.")
        item_id = partition.get("id")
        name = partition.get("name")
        compact_name = partition.get("compactName")
        default = partition.get("default")
        if (
            type(item_id) is not int
            or item_id <= 0
            or item_id in by_id
            or not isinstance(name, str)
            or not name.strip()
            or compact_name is not None and not isinstance(compact_name, str)
            or not isinstance(default, bool)
        ):
            raise DatasetError("Report Index ranking partitions are malformed.")
        by_id[item_id] = partition
    partition = by_id.get(partition_id)
    if partition is None:
        raise DatasetError(f"Report Index has no ranking partition {partition_id}.")
    compact_name = partition["compactName"]
    return compact_name.strip() if isinstance(compact_name, str) and compact_name.strip() else partition["name"].strip()
