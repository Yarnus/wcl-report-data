from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .ability_names import ensure_ability_names
from .api import WclClient
from .config import default_cache_root, default_data_root, resolve_credentials
from .dataset import DatasetService, DatasetStore, query_bundle
from .errors import InputError, WclReportDataError
from .models import ReportRef


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InputError(message)


def create_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="wcl-report-data", description="Prepare revisioned WCL raid datasets.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-root", type=Path, default=default_data_root())
    parser.add_argument("--cache-root", type=Path, default=default_cache_root())
    parser.add_argument("--env-file", type=Path, help="Read WCL credentials from this .env file.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor", help="Check credentials, storage, and WCL connectivity.")

    inspect = commands.add_parser("inspect", help="Create or refresh a report index.")
    inspect.add_argument("url")

    prepare = commands.add_parser("prepare", help="Prepare one or more complete Boss Fight Bundles.")
    prepare.add_argument("url")
    selection = prepare.add_mutually_exclusive_group()
    selection.add_argument("--fight", dest="fight_ids", type=int, action="append")
    selection.add_argument("--encounter", dest="encounter_id", type=int)
    selection.add_argument("--all-boss-fights", action="store_true")

    query = commands.add_parser("query", help="Filter canonical events from a complete Fight Bundle.")
    query.add_argument("manifest", type=Path)
    query.add_argument("--type", dest="event_types", action="append")
    query.add_argument("--source-id", type=int)
    query.add_argument("--target-id", type=int)
    query.add_argument("--ability-id", type=int)
    query.add_argument("--from-ms", type=float)
    query.add_argument("--to-ms", type=float)
    query.add_argument("--cursor", type=int)
    query.add_argument("--limit", type=int, default=200)

    dataset = commands.add_parser("dataset", help="Manage prepared datasets.")
    dataset_commands = dataset.add_subparsers(dest="dataset_command", required=True)
    dataset_commands.add_parser("list")
    remove = dataset_commands.add_parser("remove")
    remove.add_argument("report_code")
    remove.add_argument("--revision", type=int)
    remove.add_argument("--confirm", action="store_true")

    cache = commands.add_parser("cache", help="Manage resumable raw-page cache.")
    cache_commands = cache.add_subparsers(dest="cache_command", required=True)
    cache_commands.add_parser("status")
    clear = cache_commands.add_parser("clear")
    clear.add_argument("--confirm", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = create_parser().parse_args(argv)
        result = run(args)
        _print_json({"ok": True} | result)
        return 0
    except WclReportDataError as exc:
        _print_json({"ok": False, "error": exc.code, "message": str(exc)})
        return 1
    except (OSError, json.JSONDecodeError) as exc:
        _print_json({"ok": False, "error": "dataset_io_error", "message": str(exc)})
        return 1


def run(args: argparse.Namespace) -> dict[str, Any]:
    store = DatasetStore(args.data_root, args.cache_root)
    if args.command == "query":
        ability_names = _ensure_ability_names(store)
        result = query_bundle(
            args.manifest,
            event_types=set(args.event_types) if args.event_types else None,
            source_id=args.source_id,
            target_id=args.target_id,
            ability_id=args.ability_id,
            from_ms=args.from_ms,
            to_ms=args.to_ms,
            cursor=args.cursor,
            limit=args.limit,
        )
        return result | {"ability_names": ability_names}
    if args.command == "dataset":
        if args.dataset_command == "list":
            return {"action": "dataset_list"} | store.list_datasets()
        if not args.confirm:
            raise InputError("dataset remove requires --confirm.")
        return {"action": "dataset_remove"} | store.remove_dataset(args.report_code, args.revision)
    if args.command == "cache":
        if args.cache_command == "status":
            return {"action": "cache_status"} | store.cache_status()
        if not args.confirm:
            raise InputError("cache clear requires --confirm.")
        return {"action": "cache_clear"} | store.clear_cache()

    credentials = resolve_credentials(env_files=[args.env_file] if args.env_file else None)
    client = WclClient(credentials)
    if args.command == "doctor":
        if sys.version_info < (3, 11):
            raise InputError("Python 3.11 or newer is required.")
        _verify_writable(args.data_root)
        _verify_writable(args.cache_root)
        rate_limit = client.rate_limit()
        return {
            "action": "doctor",
            "version": __version__,
            "python": platform.python_version(),
            "credential_source": credentials.source,
            "data_root": str(args.data_root),
            "cache_root": str(args.cache_root),
            "wcl_api": "reachable",
            "rate_limit": rate_limit,
        }

    service = DatasetService(client, store)
    ref = ReportRef.parse(args.url)
    if args.command == "inspect":
        ability_names = _ensure_ability_names(store)
        return service.inspect(ref) | {"ability_names": ability_names}
    if args.command == "prepare":
        ability_names = _ensure_ability_names(store)
        return service.prepare(
            ref,
            fight_ids=args.fight_ids,
            encounter_id=args.encounter_id,
            all_boss_fights=args.all_boss_fights,
        ) | {"ability_names": ability_names}
    raise InputError(f"Unsupported command: {args.command}")


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _ensure_ability_names(store: DatasetStore) -> dict[str, Any]:
    with store.ability_names_lock():
        return ensure_ability_names(store.data_root)


def _verify_writable(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".wcl-report-data-doctor.", dir=path)
    try:
        os.close(descriptor)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
