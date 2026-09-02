from __future__ import annotations

import csv
import hashlib
import http.client
import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .errors import DatasetError
from .storage import atomic_write_compact_json, atomic_write_json, read_json


WAGO_BASE_URL = "https://wago.tools/db2"
MAPPING_NAME = "content-names.zhCN.json"
METADATA_NAME = "content-names.zhCN.meta.json"
RAID_MAP_ID = 3004
RAID_DIFFICULTY_IDS = (3, 4, 5)
MYTHIC_PLUS_MAP_IDS = (2773, 725, 2830, 658, 2805, 2811, 2915, 2874)
CONTENT_MAP_IDS = (RAID_MAP_ID, *MYTHIC_PLUS_MAP_IDS)
EXPECTED_ENCOUNTER_COUNTS = {
    3004: 8,
    2773: 4,
    725: 4,
    2830: 3,
    658: 3,
    2805: 4,
    2811: 4,
    2915: 3,
    2874: 3,
}
MIN_NPC_COUNT = 84

SOURCE_URLS = {
    "map_zhCN": f"{WAGO_BASE_URL}/Map/csv?locale=zhCN",
    "encounter_enUS": f"{WAGO_BASE_URL}/DungeonEncounter/csv?locale=enUS",
    "encounter_zhCN": f"{WAGO_BASE_URL}/DungeonEncounter/csv?locale=zhCN",
    "journal_zhCN": f"{WAGO_BASE_URL}/JournalEncounter/csv?locale=zhCN",
    "creature_enUS": f"{WAGO_BASE_URL}/JournalEncounterCreature/csv?locale=enUS",
    "creature_zhCN": f"{WAGO_BASE_URL}/JournalEncounterCreature/csv?locale=zhCN",
}


def ensure_content_names(data_root: Path) -> dict[str, Any]:
    root = data_root.expanduser()
    mapping_path = root / MAPPING_NAME
    metadata_path = root / METADATA_NAME
    existing = _read_existing(mapping_path, metadata_path)
    if existing is not None:
        return _result(mapping_path, metadata_path, existing)

    try:
        with tempfile.TemporaryDirectory() as temporary:
            downloaded: dict[str, tuple[Path, str]] = {}
            builds: set[str] = set()
            for key, url in SOURCE_URLS.items():
                path, build = _download(Path(temporary), key, url)
                downloaded[key] = (path, build)
                builds.add(build)
            if len(builds) != 1:
                raise ValueError(f"Wago content tables use different client builds: {sorted(builds)}")
            build = builds.pop()

            map_names = _read_map_names(downloaded["map_zhCN"][0])
            encounter_en = _read_encounters(downloaded["encounter_enUS"][0])
            encounter_zh = _read_encounters(downloaded["encounter_zhCN"][0])
            encounters = _join_encounters(encounter_en, encounter_zh)
            current_encounter_ids = set(encounters)
            journal_ids = _read_journal_ids(downloaded["journal_zhCN"][0], current_encounter_ids)
            npc_en = _read_creatures(downloaded["creature_enUS"][0], journal_ids)
            npc_zh = _read_creatures(downloaded["creature_zhCN"][0], journal_ids)
            npcs, npc_names_by_encounter = _join_creatures(npc_en, npc_zh)

            missing_maps = set(CONTENT_MAP_IDS) - set(map_names)
            if missing_maps:
                raise ValueError(f"Wago Map table is missing current map IDs: {sorted(missing_maps)}")
            encounter_counts = {
                map_id: sum(item["map_id"] == map_id for item in encounters.values())
                for map_id in CONTENT_MAP_IDS
            }
            if encounter_counts != EXPECTED_ENCOUNTER_COUNTS:
                raise ValueError(
                    f"Wago DungeonEncounter counts do not match current content: {encounter_counts}"
                )
            missing_encounters = {
                encounter_id
                for encounter_id, item in encounters.items()
                if item["map_id"] in CONTENT_MAP_IDS
                and not item["name_zh"]
            }
            if missing_encounters:
                raise ValueError(
                    f"Wago DungeonEncounter table is missing zhCN names: {sorted(missing_encounters)}"
                )
            missing_journals = current_encounter_ids - set(journal_ids.values())
            if missing_journals:
                raise ValueError(
                    f"Wago JournalEncounter table is missing current Encounter IDs: {sorted(missing_journals)}"
                )
            missing_npcs = current_encounter_ids - {
                item["encounter_id"] for item in npcs.values()
            }
            if missing_npcs:
                raise ValueError(
                    f"Wago JournalEncounterCreature table is missing current Encounter IDs: {sorted(missing_npcs)}"
                )
            if len(npcs) < MIN_NPC_COUNT:
                raise ValueError(
                    f"Wago JournalEncounterCreature table has only {len(npcs)} current NPCs; expected at least {MIN_NPC_COUNT}."
                )

            mapping = {
                "schema_version": 1,
                "locale": "zhCN",
                "build": build,
                "sources": dict(SOURCE_URLS),
                "scope": {
                    "raid": {"map_id": RAID_MAP_ID, "difficulty_ids": list(RAID_DIFFICULTY_IDS)},
                    "mythic_plus_map_ids": list(MYTHIC_PLUS_MAP_IDS),
                },
                "maps": {str(map_id): map_names[map_id] for map_id in CONTENT_MAP_IDS},
                "encounters": {
                    str(encounter_id): item
                    for encounter_id, item in sorted(encounters.items())
                    if item["map_id"] in CONTENT_MAP_IDS
                },
                "npcs": {str(npc_id): item for npc_id, item in sorted(npcs.items())},
                "npc_names_by_encounter": {
                    str(encounter_id): dict(sorted(names.items()))
                    for encounter_id, names in sorted(npc_names_by_encounter.items())
                },
            }
            temporary_mapping = Path(temporary) / MAPPING_NAME
            atomic_write_compact_json(temporary_mapping, mapping)
            metadata = {
                "locale": "zhCN",
                "build": build,
                "sources": dict(SOURCE_URLS),
                "source_files": {key: path.name for key, (path, _) in downloaded.items()},
                "source_sha256": {key: _sha256(path) for key, (path, _) in downloaded.items()},
                "mapping_sha256": _sha256(temporary_mapping),
                "map_count": len(mapping["maps"]),
                "encounter_count": len(mapping["encounters"]),
                "npc_count": len(mapping["npcs"]),
            }
            mapping_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_mapping.replace(mapping_path)
            atomic_write_json(metadata_path, metadata)
    except DatasetError:
        raise
    except (
        OSError,
        UnicodeError,
        csv.Error,
        http.client.HTTPException,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise DatasetError(f"Unable to initialize zhCN content names: {exc}") from exc
    return _result(mapping_path, metadata_path, metadata)


def load_content_names(path: Path) -> dict[str, Any]:
    try:
        value = read_json(path)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DatasetError(f"Unable to read zhCN content names: {path}") from exc
    if not _valid_mapping(value):
        raise DatasetError("zhCN content names mapping is malformed.")
    return value


def localize_encounter(mapping: dict[str, Any], encounter_id: Any, fallback: str) -> str:
    encounters = mapping.get("encounters")
    item = encounters.get(str(encounter_id)) if isinstance(encounters, dict) else None
    name = item.get("name_zh") if isinstance(item, dict) else None
    return name if isinstance(name, str) and name.strip() else fallback


def localize_npc(mapping: dict[str, Any], encounter_id: Any, name: str) -> str:
    names_by_encounter = mapping.get("npc_names_by_encounter")
    names = names_by_encounter.get(str(encounter_id)) if isinstance(names_by_encounter, dict) else None
    localized = names.get(name) if isinstance(names, dict) else None
    return localized if isinstance(localized, str) and localized.strip() else name


def _read_existing(mapping_path: Path, metadata_path: Path) -> dict[str, Any] | None:
    if not mapping_path.exists() or not metadata_path.exists():
        return None
    try:
        mapping = load_content_names(mapping_path)
        metadata = read_json(metadata_path)
    except (DatasetError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    build = metadata.get("build")
    if (
        metadata.get("locale") != "zhCN"
        or metadata.get("sources") != SOURCE_URLS
        or not _valid_source_hashes(metadata.get("source_sha256"))
        or not isinstance(build, str)
        or not re.fullmatch(r"\d+(?:\.\d+)+", build)
        or metadata.get("mapping_sha256") != _sha256(mapping_path)
        or metadata.get("map_count") != len(mapping["maps"])
        or metadata.get("encounter_count") != len(mapping["encounters"])
        or metadata.get("npc_count") != len(mapping["npcs"])
    ):
        return None
    if mapping.get("locale") != "zhCN" or mapping.get("build") != build:
        return None
    if mapping.get("scope") != {
        "raid": {"map_id": RAID_MAP_ID, "difficulty_ids": list(RAID_DIFFICULTY_IDS)},
        "mythic_plus_map_ids": list(MYTHIC_PLUS_MAP_IDS),
    } or set(mapping["maps"]) != {str(map_id) for map_id in CONTENT_MAP_IDS}:
        return None
    return metadata


def _download(directory: Path, key: str, url: str) -> tuple[Path, str]:
    table = {
        "map_zhCN": "Map",
        "encounter_enUS": "DungeonEncounter",
        "encounter_zhCN": "DungeonEncounter",
        "journal_zhCN": "JournalEncounter",
        "creature_enUS": "JournalEncounterCreature",
        "creature_zhCN": "JournalEncounterCreature",
    }[key]
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "wcl-raid-coach content names"})
            with urlopen(request, timeout=120) as response:
                source_file = response.headers.get_filename()
                match = re.fullmatch(rf"{re.escape(table)}\.(\d+(?:\.\d+)+)\.csv", source_file or "")
                if match is None:
                    raise ValueError(f"Wago response does not identify a {table} client build.")
                path = directory / f"{key}.{source_file}"
                with path.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
            return path, match.group(1)
        except (OSError, TimeoutError, http.client.HTTPException):
            if attempt == 2:
                raise
            time.sleep(1)
    raise AssertionError("Wago download retry loop exited unexpectedly.")


def _read_map_names(path: Path) -> dict[int, dict[str, str]]:
    result: dict[int, dict[str, str]] = {}
    for row in _rows(path):
        raw_id = row.get("ID")
        if not isinstance(raw_id, str) or not raw_id.strip().isdigit():
            continue
        map_id = int(raw_id)
        if map_id not in CONTENT_MAP_IDS:
            continue
        name = (row.get("MapName_lang") or "").strip()
        if not name:
            raise ValueError(f"Wago Map table has no zhCN name for map {map_id}.")
        result[map_id] = {"name_zh": name}
    return result


def _read_encounters(path: Path) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in _rows(path):
        raw_map_id = row.get("MapID")
        if not isinstance(raw_map_id, str) or not raw_map_id.strip().isdigit():
            continue
        map_id = int(raw_map_id)
        if map_id not in CONTENT_MAP_IDS:
            continue
        encounter_id = _positive_id(row.get("ID"), "DungeonEncounter ID")
        name = (row.get("Name_lang") or "").strip()
        if encounter_id in result and result[encounter_id]["name"] != name:
            raise ValueError(f"Wago DungeonEncounter table has conflicting names for ID {encounter_id}.")
        result[encounter_id] = {"map_id": map_id, "name": name}
    return result


def _join_encounters(
    english: dict[int, dict[str, Any]], chinese: dict[int, dict[str, Any]]
) -> dict[int, dict[str, Any]]:
    if set(english) != set(chinese):
        raise ValueError("Wago DungeonEncounter locales contain different Encounter IDs.")
    result = {}
    for encounter_id, item in english.items():
        localized = chinese.get(encounter_id)
        if localized is None or localized["map_id"] != item["map_id"]:
            raise ValueError(f"Wago DungeonEncounter locales do not match for ID {encounter_id}.")
        result[encounter_id] = {
            "map_id": item["map_id"],
            "name_en": item["name"],
            "name_zh": localized["name"],
        }
    return result


def _read_journal_ids(path: Path, encounter_ids: set[int]) -> dict[int, int]:
    result: dict[int, int] = {}
    for row in _rows(path):
        encounter_id = row.get("DungeonEncounterID")
        if not isinstance(encounter_id, str) or not encounter_id.isdigit() or int(encounter_id) not in encounter_ids:
            continue
        journal_id = _positive_id(row.get("ID"), "JournalEncounter ID")
        if int(encounter_id) in result and result[int(encounter_id)] != journal_id:
            raise ValueError(f"Wago JournalEncounter has multiple rows for Encounter ID {encounter_id}.")
        result[int(encounter_id)] = journal_id
    return {journal_id: encounter_id for encounter_id, journal_id in result.items()}


def _read_creatures(path: Path, journal_ids: dict[int, int]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in _rows(path):
        journal_id = row.get("JournalEncounterID")
        if not isinstance(journal_id, str) or not journal_id.isdigit() or int(journal_id) not in journal_ids:
            continue
        creature_id = _positive_id(row.get("ID"), "JournalEncounterCreature ID")
        result[creature_id] = {
            "journal_encounter_id": int(journal_id),
            "encounter_id": journal_ids[int(journal_id)],
            "name": (row.get("Name_lang") or "").strip(),
        }
    return result


def _join_creatures(
    english: dict[int, dict[str, Any]], chinese: dict[int, dict[str, Any]]
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, str]]]:
    records: dict[int, dict[str, Any]] = {}
    names_by_encounter: dict[int, dict[str, str]] = {}
    if set(english) != set(chinese):
        raise ValueError("Wago JournalEncounterCreature locales contain different NPC IDs.")
    for creature_id, item in english.items():
        localized = chinese.get(creature_id)
        if localized is None or localized["encounter_id"] != item["encounter_id"]:
            raise ValueError(f"Wago JournalEncounterCreature locales do not match for ID {creature_id}.")
        if not item["name"] or not localized["name"]:
            raise ValueError(f"Wago JournalEncounterCreature has no localized name for ID {creature_id}.")
        names = names_by_encounter.setdefault(item["encounter_id"], {})
        previous = names.get(item["name"])
        if previous is not None and previous != localized["name"]:
            raise ValueError(f"Wago JournalEncounterCreature has conflicting names for {item['name']}.")
        names[item["name"]] = localized["name"]
        records[creature_id] = {
            "journal_encounter_id": item["journal_encounter_id"],
            "encounter_id": item["encounter_id"],
            "name_en": item["name"],
            "name_zh": localized["name"],
        }
    return records, names_by_encounter


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _positive_id(value: Any, label: str) -> int:
    if not isinstance(value, str) or not value.strip().isdigit() or int(value) <= 0:
        raise ValueError(f"Wago table contains an invalid {label}: {value!r}.")
    return int(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_source_hashes(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == set(SOURCE_URLS) and all(
        isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
        for digest in value.values()
    )


def _valid_mapping(value: Any) -> bool:
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("schema_version"), int)
        or isinstance(value["schema_version"], bool)
        or value["schema_version"] != 1
        or value.get("locale") != "zhCN"
        or not isinstance(value.get("build"), str)
        or not re.fullmatch(r"\d+(?:\.\d+)+", value["build"])
        or value.get("scope")
        != {
            "raid": {"map_id": RAID_MAP_ID, "difficulty_ids": list(RAID_DIFFICULTY_IDS)},
            "mythic_plus_map_ids": list(MYTHIC_PLUS_MAP_IDS),
        }
    ):
        return False
    maps = value.get("maps")
    encounters = value.get("encounters")
    npcs = value.get("npcs")
    names_by_encounter = value.get("npc_names_by_encounter")
    if (
        not isinstance(maps, dict)
        or set(maps) != {str(map_id) for map_id in CONTENT_MAP_IDS}
        or any(
            not isinstance(item, dict) or not _nonempty_text(item.get("name_zh"))
            for item in maps.values()
        )
        or not isinstance(encounters, dict)
        or not isinstance(npcs, dict)
        or not isinstance(names_by_encounter, dict)
    ):
        return False
    encounter_ids: set[int] = set()
    encounter_counts = {map_id: 0 for map_id in CONTENT_MAP_IDS}
    for encounter_id, item in encounters.items():
        if (
            not _positive_key(encounter_id)
            or not isinstance(item, dict)
            or item.get("map_id") not in CONTENT_MAP_IDS
            or not _nonempty_text(item.get("name_en"))
            or not _nonempty_text(item.get("name_zh"))
        ):
            return False
        encounter_ids.add(int(encounter_id))
        encounter_counts[item["map_id"]] += 1
    if encounter_counts != EXPECTED_ENCOUNTER_COUNTS or len(npcs) < MIN_NPC_COUNT:
        return False
    expected_names: dict[str, dict[str, str]] = {}
    for npc_id, item in npcs.items():
        if (
            not _positive_key(npc_id)
            or not isinstance(item, dict)
            or not isinstance(item.get("journal_encounter_id"), int)
            or isinstance(item["journal_encounter_id"], bool)
            or item["journal_encounter_id"] <= 0
            or item.get("encounter_id") not in encounter_ids
            or not _nonempty_text(item.get("name_en"))
            or not _nonempty_text(item.get("name_zh"))
        ):
            return False
        encounter_names = expected_names.setdefault(str(item["encounter_id"]), {})
        previous = encounter_names.get(item["name_en"])
        if previous is not None and previous != item["name_zh"]:
            return False
        encounter_names[item["name_en"]] = item["name_zh"]
    return names_by_encounter == expected_names and set(expected_names) == {
        str(encounter_id) for encounter_id in encounter_ids
    }


def _positive_key(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value) is not None


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _result(mapping_path: Path, metadata_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "mapping_path": str(mapping_path),
        "metadata_path": str(metadata_path),
        "locale": "zhCN",
        "build": metadata["build"],
        "mapping_sha256": metadata["mapping_sha256"],
        "map_count": metadata["map_count"],
        "encounter_count": metadata["encounter_count"],
        "npc_count": metadata["npc_count"],
    }
