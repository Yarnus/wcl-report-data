from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .errors import DatasetError
from .storage import atomic_write_compact_json, atomic_write_json, read_json


WAGO_URL = "https://wago.tools/db2/SpellName/csv?locale=zhCN"
MAPPING_NAME = "ability-names.zhCN.json"
METADATA_NAME = "ability-names.zhCN.meta.json"
MIN_COMPLETE_ROWS = 400_000


def ensure_ability_names(data_root: Path) -> dict[str, Any]:
    root = data_root.expanduser()
    mapping_path = root / MAPPING_NAME
    metadata_path = root / METADATA_NAME
    existing = _read_existing(mapping_path, metadata_path)
    if existing is not None:
        return _result(mapping_path, metadata_path, existing)

    try:
        with tempfile.TemporaryDirectory() as temporary:
            csv_path, source_file, build = _download(Path(temporary))
            mapping, source_row_count = _read_spell_names(csv_path)
            if source_row_count < MIN_COMPLETE_ROWS:
                raise ValueError(
                    f"Wago SpellName CSV has only {source_row_count} rows; expected a complete table."
                )
            temporary_mapping = Path(temporary) / MAPPING_NAME
            atomic_write_compact_json(temporary_mapping, mapping)
            metadata = {
                "locale": "zhCN",
                "build": build,
                "source": WAGO_URL,
                "source_file": source_file,
                "source_sha256": _sha256(csv_path),
                "source_row_count": source_row_count,
                "mapping_sha256": _sha256(temporary_mapping),
                "ability_count": len(mapping),
            }
            mapping_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_mapping.replace(mapping_path)
            atomic_write_json(metadata_path, metadata)
    except DatasetError:
        raise
    except (OSError, UnicodeError, csv.Error, json.JSONDecodeError, ValueError) as exc:
        raise DatasetError(f"Unable to initialize zhCN ability names: {exc}") from exc
    return _result(mapping_path, metadata_path, metadata)


def _read_existing(mapping_path: Path, metadata_path: Path) -> dict[str, Any] | None:
    if not mapping_path.exists() or not metadata_path.exists():
        return None
    try:
        mapping = read_json(mapping_path)
        metadata = read_json(metadata_path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(mapping, dict) or not isinstance(metadata, dict):
        return None
    if (
        metadata.get("locale") != "zhCN"
        or metadata.get("source") != WAGO_URL
        or metadata.get("ability_count") != len(mapping)
        or not isinstance(metadata.get("source_row_count"), int)
        or metadata["source_row_count"] < MIN_COMPLETE_ROWS
        or not isinstance(metadata.get("source_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", metadata["source_sha256"])
        or metadata.get("mapping_sha256") != _sha256(mapping_path)
    ):
        return None
    build = metadata.get("build")
    if not isinstance(build, str) or not re.fullmatch(r"\d+(?:\.\d+)+", build):
        return None
    source_file = metadata.get("source_file")
    if source_file != f"SpellName.{build}.csv":
        return None
    for ability_id, name in mapping.items():
        if (
            not isinstance(ability_id, str)
            or not ability_id.isdigit()
            or int(ability_id) <= 0
            or not isinstance(name, str)
            or not name
        ):
            return None
    return metadata


def _download(directory: Path) -> tuple[Path, str, str]:
    request = Request(WAGO_URL, headers={"User-Agent": "wcl-raid-coach ability names"})
    with urlopen(request, timeout=120) as response:
        source_file = response.headers.get_filename()
        match = re.fullmatch(r"SpellName\.(\d+(?:\.\d+)+)\.csv", source_file or "")
        if match is None:
            raise ValueError("Wago response does not identify a SpellName client build.")
        path = directory / source_file
        with path.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    return path, source_file, match.group(1)


def _read_spell_names(path: Path) -> tuple[dict[str, str], int]:
    result: dict[str, str] = {}
    source_row_count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = {header.strip().lower(): header for header in reader.fieldnames or []}
        id_header = headers.get("id")
        name_header = headers.get("name_lang") or headers.get("name")
        if id_header is None or name_header is None:
            raise ValueError("Wago SpellName CSV must contain ID and Name_lang columns.")
        for row in reader:
            source_row_count += 1
            raw_id = (row.get(id_header) or "").strip()
            name = (row.get(name_header) or "").strip()
            if not raw_id.isdigit() or int(raw_id) <= 0:
                raise ValueError(f"Wago SpellName CSV contains an invalid row for ID {raw_id!r}.")
            if not name:
                continue
            if raw_id in result and result[raw_id] != name:
                raise ValueError(f"Wago SpellName CSV has conflicting names for ID {raw_id}.")
            result[raw_id] = name
    if not result:
        raise ValueError("Wago SpellName CSV contains no ability names.")
    return result, source_row_count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _result(mapping_path: Path, metadata_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "mapping_path": str(mapping_path),
        "metadata_path": str(metadata_path),
        "locale": "zhCN",
        "build": metadata["build"],
        "ability_count": metadata["ability_count"],
    }
