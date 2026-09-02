from __future__ import annotations

from typing import Any, Iterable

from .coach_models import EncounterDesignator
from .errors import ApiError, InputError


def resolve_current_raid(
    zones: Iterable[dict[str, Any]], designators: tuple[EncounterDesignator, ...]
) -> dict[str, Any]:
    current = [
        zone
        for zone in zones
        if zone.get("frozen") is False
        and isinstance(zone.get("difficulties"), list)
        and sum(
            1
            for difficulty in zone["difficulties"]
            if isinstance(difficulty, dict) and str(difficulty.get("name", "")).casefold() == "heroic"
        ) == 1
    ]
    if len(current) != 1:
        raise ApiError(f"WCL returned {len(current)} current Retail raid zones; exactly one is required.")
    zone = current[0]
    zone_id = _integer(zone, "id", "current raid zone")
    zone_name = _text(zone, "name", "current raid zone")
    difficulties = _object_list(zone.get("difficulties"), "current raid difficulties")
    heroic = [item for item in difficulties if str(item.get("name", "")).casefold() == "heroic"]
    if len(heroic) != 1:
        raise ApiError("WCL current raid metadata did not contain exactly one Heroic difficulty.")
    difficulty = {"id": _integer(heroic[0], "id", "Heroic difficulty"), "name": "Heroic"}
    partitions = _object_list(zone.get("partitions"), "current raid partitions")
    defaults = [item for item in partitions if item.get("default") is True]
    if len(defaults) != 1:
        raise ApiError("WCL current raid metadata did not contain exactly one default partition.")
    partition = {
        "id": _integer(defaults[0], "id", "default partition"),
        "name": _text(defaults[0], "name", "default partition"),
        "compact_name": defaults[0].get("compactName"),
    }
    game_version = defaults[0].get("compactName") or defaults[0].get("name")
    if not isinstance(game_version, str) or not game_version.strip():
        raise ApiError("WCL current raid default partition has no game-version label.")
    encounters = _object_list(zone.get("encounters"), "current raid encounters")
    resolved = []
    seen: set[str] = set()
    for designator in designators:
        value = designator.as_dict()["value"]
        if value in seen:
            raise InputError(f"Duplicate Encounter Designator: {value}.")
        seen.add(value)
        if designator.difficulty_code != "H":
            raise InputError("Raid Guide currently supports Heroic Encounter Designators only.")
        if designator.position > len(encounters):
            raise InputError(
                f"{value} is outside the current raid's {len(encounters)}-encounter WCL ordering."
            )
        encounter = encounters[designator.position - 1]
        resolved.append(
            {
                "designator": value,
                "encounter_id": _integer(encounter, "id", value),
                "encounter_name": _text(encounter, "name", value),
                "difficulty": difficulty,
            }
        )
    return {
        "game_version": game_version,
        "zone": {"id": zone_id, "name": zone_name},
        "partition": partition,
        "encounters": resolved,
    }


def _object_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ApiError(f"WCL returned malformed {label}.")
    return value


def _integer(value: dict[str, Any], key: str, label: str) -> int:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ApiError(f"WCL returned an invalid {key} for {label}.")
    return result


def _text(value: dict[str, Any], key: str, label: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ApiError(f"WCL returned an invalid {key} for {label}.")
    return result
