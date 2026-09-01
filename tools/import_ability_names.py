from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).parents[1]
DEFAULT_MAPPING = ROOT / "references" / "ability-names.zhCN.json"
DEFAULT_METADATA = ROOT / "references" / "ability-names.zhCN.meta.json"


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import current zhCN ability names from a wow.export SpellName CSV."
    )
    parser.add_argument("csv", type=Path)
    parser.add_argument("--report-index", type=Path, action="append", default=[])
    parser.add_argument("--build", required=True)
    parser.add_argument("--locale", default="zhCN", choices=["zhCN"])
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    try:
        existing = _read_mapping(args.mapping)
        target_ids = set(existing) | _report_ability_ids(args.report_index)
        if not target_ids:
            raise ValueError("No existing or Report Index ability IDs were provided.")
        imported = _read_spell_names(args.csv, target_ids)
        missing = sorted(target_ids - imported.keys())
        if missing:
            raise ValueError(f"SpellName CSV is missing {len(missing)} required IDs: {missing[:20]}")

        changed = sorted(
            ability_id
            for ability_id, name in imported.items()
            if ability_id in existing and existing[ability_id] != name
        )
        added = sorted(imported.keys() - existing.keys())
        mapping = {str(ability_id): imported[ability_id] for ability_id in sorted(imported)}
        metadata = {
            "locale": args.locale,
            "build": args.build,
            "source": "wow.export SpellName.csv",
            "source_file": args.csv.name,
            "source_sha256": _sha256(args.csv),
            "ability_count": len(mapping),
        }
        _atomic_write_json(args.mapping, mapping)
        _atomic_write_json(args.metadata, metadata)
    except (OSError, UnicodeError, csv.Error, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "mapping": str(args.mapping),
                "metadata": str(args.metadata),
                "ability_count": len(mapping),
                "added_ids": added,
                "renamed_ids": changed,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _read_mapping(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Existing ability mapping must be a JSON object.")
    result: dict[int, str] = {}
    for raw_id, name in value.items():
        if not isinstance(raw_id, str) or not raw_id.isdigit() or int(raw_id) <= 0:
            raise ValueError(f"Invalid ability mapping ID: {raw_id!r}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Ability mapping {raw_id} has no name.")
        result[int(raw_id)] = name
    return result


def _report_ability_ids(paths: Sequence[Path]) -> set[int]:
    result: set[int] = set()
    for path in paths:
        index = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(index, dict) or not isinstance(index.get("abilities"), list):
            raise ValueError(f"Report Index has no abilities list: {path}")
        for ability in index["abilities"]:
            ability_id = ability.get("gameID") if isinstance(ability, dict) else None
            if isinstance(ability_id, int) and not isinstance(ability_id, bool) and ability_id > 0:
                result.add(ability_id)
    return result


def _read_spell_names(path: Path, target_ids: set[int]) -> dict[int, str]:
    result: dict[int, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(8192)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(handle, dialect=dialect)
        headers = {header.strip().lower(): header for header in reader.fieldnames or []}
        id_header = headers.get("id")
        name_header = headers.get("name_lang") or headers.get("name")
        if id_header is None or name_header is None:
            raise ValueError("SpellName CSV must contain ID and Name_lang columns.")
        for row in reader:
            raw_id = (row.get(id_header) or "").strip()
            if not raw_id.isdigit() or int(raw_id) not in target_ids:
                continue
            ability_id = int(raw_id)
            name = (row.get(name_header) or "").strip()
            if not name:
                raise ValueError(f"SpellName CSV has an empty name for ID {ability_id}.")
            if ability_id in result and result[ability_id] != name:
                raise ValueError(f"SpellName CSV has conflicting names for ID {ability_id}.")
            result[ability_id] = name
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
