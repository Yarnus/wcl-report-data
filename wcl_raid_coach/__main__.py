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
from .analysis import analyze_player
from .ability_names import ensure_ability_names
from .content_names import RAID_DIFFICULTY_IDS, ensure_content_names, load_content_names, localize_encounter
from .api import WclClient
from .config import default_cache_root, default_data_root, resolve_credentials
from .dataset import DatasetService, DatasetStore, query_bundle
from .errors import InputError, WclRaidCoachError
from .coach_models import CoachRequest, EncounterDesignator, parse_specialization
from .coach_context import resolve_current_raid
from .coach_tasks import CoachTaskStore
from .cohort import build_benchmark, extract_ranking_candidates, identify_benchmark, identify_cohort, validate_analysis_membership
from .comparison import compare_player
from .models import ReportRef
from .mechanics import MechanicReviewService
from .guides import create_guide_snapshot
from .profiles import ProfileStore
from .report_documents import (
    assemble_raid_guide_document,
    create_mechanic_review_report,
    render_report_document,
    validate_report_document,
)
from .storage import atomic_write_json, read_json


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InputError(message)


def create_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="wcl-raid-coach", description="Prepare WCL raid evidence and coaching artifacts.")
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

    coach = commands.add_parser("coach", help="Create and inspect unified coaching tasks.")
    coach_commands = coach.add_subparsers(dest="coach_command", required=True)
    resolve = coach_commands.add_parser("resolve", help="Normalize a coaching request before confirmation.")
    resolve.add_argument("--spec", help="Specialization, for example 'Unholy DK' or '邪 DK'.")
    resolve.add_argument("--encounter", dest="encounter_designators", action="append", default=[])
    resolve.add_argument("--mode", choices=("raid_guide", "personal_review", "report_data"), default="raid_guide")
    resolve.add_argument("--report-url")
    resolve.add_argument("--fight-id", type=int)
    resolve.add_argument("--source-id", type=int)
    resolve.add_argument("--sample-goal", type=int, default=10)
    coach_commands.add_parser("status", help="List persisted coaching tasks.")
    confirm = coach_commands.add_parser("confirm", help="Confirm a resolved Coach Request.")
    confirm.add_argument("task_id")
    record = coach_commands.add_parser("record", help="Record one encounter's resumable task state.")
    record.add_argument("task_id")
    record.add_argument("--encounter", required=True)
    record.add_argument("--status", choices=("pending", "in_progress", "completed", "blocked"), required=True)
    record.add_argument("--artifact", action="append", default=[], help="Artifact as name=path.")
    record.add_argument("--blocker")
    review = coach_commands.add_parser("review", help="Calculate player facts from a Complete Bundle.")
    review.add_argument("manifest", type=Path)
    review.add_argument("--index", type=Path, required=True)
    review.add_argument("--source-id", type=int, required=True)
    review.add_argument("--partition-id", type=int)
    review.add_argument("--output", type=Path)
    mechanics = coach_commands.add_parser(
        "mechanics", help="Review observable raid mechanics from an in-memory Mechanic Evidence Set."
    )
    mechanics.add_argument("url")
    mechanics.add_argument("--encounter", help="Optional Encounter Designator used to list matching Boss Attempts.")
    mechanics.add_argument(
        "--report", action="store_true",
        help="Persist a sanitized source and render a Mechanic Review Report Document.",
    )
    mechanics.add_argument("--locale", choices=("zh-CN", "en"), default="zh-CN")
    render = coach_commands.add_parser("render", help="Render a validated Report Document as self-contained HTML.")
    render.add_argument("document", type=Path)
    guide_report = coach_commands.add_parser(
        "guide-report", help="Assemble and render a Raid Guide Report Document from one Guide Snapshot."
    )
    guide_report.add_argument("snapshot", type=Path)
    candidates = coach_commands.add_parser("candidates", help="Discover content-addressed recent ranking candidates.")
    candidates.add_argument("--encounter-id", type=int, required=True)
    candidates.add_argument("--difficulty-id", type=int, required=True)
    candidates.add_argument("--partition-id", type=int, required=True)
    candidates.add_argument("--game-version", required=True)
    candidates.add_argument("--class-name", required=True)
    candidates.add_argument("--spec-name", required=True)
    candidates.add_argument("--page", type=int, default=1)
    candidates.add_argument("--sample-goal", type=int, default=10)
    candidates.add_argument("--output", type=Path)
    profile = coach_commands.add_parser("profile", help="Validate and store a sourced Profile.")
    profile.add_argument("path", type=Path)
    benchmark = coach_commands.add_parser("benchmark", help="Aggregate content-addressed Reference Sample analyses.")
    benchmark.add_argument("analyses", nargs="+", type=Path)
    benchmark.add_argument("--cohort", type=Path, required=True)
    benchmark.add_argument("--encounter-profile", type=Path, required=True)
    benchmark.add_argument("--specialization-profile", type=Path, required=True)
    benchmark.add_argument("--output", type=Path, required=True)
    guide = coach_commands.add_parser("guide", help="Create an immutable Chinese Guide Snapshot.")
    guide.add_argument("benchmarks", nargs="+", type=Path)
    guide.add_argument("--spec-display-name", required=True)
    compare = coach_commands.add_parser("compare", help="Compare one player analysis with an Encounter Benchmark.")
    compare.add_argument("analysis", type=Path)
    compare.add_argument("benchmark", type=Path)
    compare.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = create_parser().parse_args(argv)
        result = run(args)
        _print_json({"ok": True} | result)
        return 0
    except WclRaidCoachError as exc:
        _print_json({"ok": False, "error": exc.code, "message": str(exc)})
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _print_json({"ok": False, "error": "dataset_io_error", "message": str(exc)})
        return 1


def run(args: argparse.Namespace) -> dict[str, Any]:
    store = DatasetStore(args.data_root, args.cache_root)
    if args.command == "coach":
        if args.coach_command == "mechanics":
            credentials = resolve_credentials(env_files=[args.env_file] if args.env_file else None)
            review = MechanicReviewService(WclClient(credentials)).review(
                ReportRef.parse(args.url),
                encounter_designator=(
                    EncounterDesignator.parse(args.encounter) if args.encounter else None
                ),
            )
            if not args.report:
                return review
            return create_mechanic_review_report(review, store.data_root, locale=args.locale)
        if args.coach_command == "render":
            return {
                "action": "coach_render",
                "report": render_report_document(
                    read_json(args.document), store.data_root / "outputs" / "reports"
                ),
            }
        if args.coach_command == "guide-report":
            document = assemble_raid_guide_document(read_json(args.snapshot), args.snapshot)
            report = render_report_document(document, store.data_root / "outputs" / "reports")
            return {
                "action": "coach_guide_report",
                "document": validate_report_document(document),
                "report": report,
            }
        task_store = CoachTaskStore(args.data_root)
        if args.coach_command == "status":
            return {"action": "coach_status", "tasks": task_store.list_tasks()}
        if args.coach_command == "confirm":
            return {"action": "coach_confirm", "task": task_store.confirm(args.task_id)}
        if args.coach_command == "record":
            artifacts = {}
            for item in args.artifact:
                if "=" not in item:
                    raise InputError("--artifact must use name=path.")
                name, path = item.split("=", 1)
                if not name or not path:
                    raise InputError("--artifact must use non-empty name=path.")
                artifacts[name] = path
            task = task_store.record_encounter(
                args.task_id,
                designator=EncounterDesignator.parse(args.encounter).as_dict()["value"],
                status=args.status,
                artifacts=artifacts,
                blocker=args.blocker,
            )
            return {"action": "coach_record", "task": task}
        if args.coach_command == "review":
            result = {
                "action": "coach_review",
                "evidence_class": "log_fact",
                "analysis": analyze_player(
                    args.manifest,
                    args.index,
                    args.source_id,
                    partition_id=args.partition_id,
                ),
            }
            if args.output:
                atomic_write_json(args.output, result["analysis"])
                result["analysis_path"] = str(args.output)
            return result
        if args.coach_command == "candidates":
            credentials = resolve_credentials(env_files=[args.env_file] if args.env_file else None)
            client = WclClient(credentials)
            if not 1 <= args.sample_goal <= 10:
                raise InputError("--sample-goal must be between 1 and 10.")
            game_version: str | int = (
                int(args.game_version) if args.game_version.isdigit() else args.game_version
            )
            page = args.page
            discovered = {"eligible_recent_candidates": [], "unverified_recency_candidates": [], "rejected_candidates": []}
            while len(discovered["eligible_recent_candidates"]) < args.sample_goal:
                rankings = client.fetch_rankings(
                    encounter_id=args.encounter_id,
                    difficulty_id=args.difficulty_id,
                    partition_id=args.partition_id,
                    class_name=args.class_name,
                    spec_name=args.spec_name,
                    page=page,
                )
                batch = extract_ranking_candidates(rankings)
                resolved_candidates = []
                for candidate in batch["eligible_recent_candidates"]:
                    if candidate.get("source_id") is None:
                        source_id = client.resolve_candidate_source(candidate)
                        if source_id is None:
                            batch["rejected_candidates"].append(
                                candidate | {"reason": "source_identity_not_unique"}
                            )
                            continue
                        candidate = candidate | {
                            "source_id": source_id,
                            "url": f"https://www.warcraftlogs.com/reports/{candidate['report_code']}#fight={candidate['fight_id']}&source={source_id}",
                        }
                    resolved_candidates.append(candidate)
                batch["eligible_recent_candidates"] = resolved_candidates
                for field in discovered:
                    discovered[field].extend(batch[field])
                if rankings.get("hasMorePages") is not True:
                    break
                page += 1
            discovered["eligible_recent_candidates"] = discovered["eligible_recent_candidates"][: args.sample_goal]
            cohort = identify_cohort(
                {
                    "schema_version": 2,
                    "filters": {
                        "encounter_id": args.encounter_id,
                        "game_version": game_version,
                        "difficulty_id": args.difficulty_id,
                        "partition_id": args.partition_id,
                        "class_name": args.class_name,
                        "spec_name": args.spec_name,
                        "recency": "recent_14_days",
                    },
                    **discovered,
                }
            )
            result = {"action": "coach_candidates", "cohort": cohort}
            if args.output:
                atomic_write_json(args.output, cohort)
                result["cohort_path"] = str(args.output)
            return result
        if args.coach_command == "profile":
            path = ProfileStore(args.data_root).store(read_json(args.path))
            return {"action": "coach_profile_store", "profile_path": str(path)}
        if args.coach_command == "benchmark":
            analyses = [read_json(path) for path in args.analyses]
            if any(not isinstance(item, dict) for item in analyses):
                raise InputError("Every Reference Sample analysis must be a JSON object.")
            cohort = read_json(args.cohort)
            if not isinstance(cohort, dict):
                raise InputError("Ranking Cohort must be a JSON object.")
            validate_analysis_membership(analyses, cohort)
            filters = cohort.get("filters")
            if not isinstance(filters, dict):
                raise InputError("Ranking Cohort filters are missing.")
            expected = {
                field: filters.get(field)
                for field in ("game_version", "partition_id", "encounter_id", "difficulty_id", "class_name", "spec_name")
            }
            encounter_profile = read_json(args.encounter_profile)
            specialization_profile = read_json(args.specialization_profile)
            result = identify_benchmark(
                build_benchmark(
                    analyses,
                    encounter_profile,
                    specialization_profile,
                    expected,
                    cohort_id=cohort["cohort_id"],
                )
            )
            atomic_write_json(args.output, result)
            return {"action": "coach_benchmark", "benchmark_path": str(args.output), "benchmark": result}
        if args.coach_command == "guide":
            benchmarks = [read_json(path) for path in args.benchmarks]
            ability_names_info = _ensure_ability_names(store)
            ability_names = read_json(Path(ability_names_info["mapping_path"]))
            if not isinstance(ability_names, dict) or any(
                not isinstance(key, str) or not isinstance(value, str) for key, value in ability_names.items()
            ):
                raise InputError("zhCN ability names mapping is malformed.")
            content_names_info = _ensure_content_names(store)
            content_names = load_content_names(Path(content_names_info["mapping_path"]))
            result = create_guide_snapshot(
                benchmarks,
                specialization_name=args.spec_display_name,
                output_dir=args.data_root / "guides",
                ability_names=ability_names,
                ability_names_build=ability_names_info["build"],
                encounter_names=_encounter_names(content_names),
                content_names_build=content_names_info["build"],
                content_names_sha256=content_names_info["mapping_sha256"],
            )
            return {"action": "coach_guide", "guide": result, "content_names": content_names_info}
        if args.coach_command == "compare":
            result = compare_player(read_json(args.analysis), read_json(args.benchmark))
            response = {"action": "coach_compare", "comparison": result}
            if args.output:
                atomic_write_json(args.output, result)
                response["comparison_path"] = str(args.output)
            return response
        report_ref = ReportRef.parse(args.report_url) if args.report_url else None
        if args.mode == "raid_guide" and (not args.spec or not args.encounter_designators):
            raise InputError("A raid guide resolve requires --spec and at least one --encounter.")
        if args.mode != "raid_guide" and report_ref is None:
            raise InputError(f"{args.mode} resolve requires --report-url.")
        request = CoachRequest(
            content_type="retail_raid",
            mode=args.mode,
            specialization=parse_specialization(args.spec) if args.spec else None,
            encounter_designators=tuple(
                EncounterDesignator.parse(value) for value in args.encounter_designators
            ),
            report_code=report_ref.code if report_ref else None,
            fight_id=report_ref.fight if report_ref and isinstance(report_ref.fight, int) else args.fight_id,
            source_id=report_ref.source_hint if report_ref else args.source_id,
            sample_goal=args.sample_goal,
        )
        if args.mode == "raid_guide":
            credentials = resolve_credentials(env_files=[args.env_file] if args.env_file else None)
            client = WclClient(credentials)
            content_names_info = _ensure_content_names(store)
            content_names = load_content_names(Path(content_names_info["mapping_path"]))
            context = resolve_current_raid(
                client.fetch_raid_zones(),
                request.encounter_designators,
                _encounter_names(content_names),
            )
        else:
            context = {"report": report_ref.as_dict() if report_ref else None}
        task = task_store.create_or_resume(request, context=context)
        result = {"action": "coach_resolve", "confirmation_required": True, "task": task}
        if args.mode == "raid_guide":
            result["content_names"] = content_names_info
        return result
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
        content_names_info = _ensure_content_names(store)
        content_names = load_content_names(Path(content_names_info["mapping_path"]))
        result = _localize_inspection(service.inspect(ref), content_names)
        return result | {"ability_names": ability_names, "content_names": content_names_info}
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


def _ensure_content_names(store: DatasetStore) -> dict[str, Any]:
    with store.content_names_lock():
        return ensure_content_names(store.data_root)


def _encounter_names(mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    encounters = mapping.get("encounters")
    if not isinstance(encounters, dict):
        raise InputError("zhCN content names encounters mapping is malformed.")
    return encounters


def _localize_inspection(result: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    localized = dict(result)
    for field in ("selected_fight",):
        choice = localized.get(field)
        if isinstance(choice, dict):
            localized[field] = _localize_fight_choice(choice, mapping)
    for field in ("encounter_choices", "fight_choices"):
        choices = localized.get(field)
        if isinstance(choices, list):
            localized[field] = [
                _localize_fight_choice(choice, mapping) if isinstance(choice, dict) else choice
                for choice in choices
            ]
    return localized


def _localize_fight_choice(choice: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    difficulty = choice.get("difficulty")
    if difficulty is not None and difficulty not in RAID_DIFFICULTY_IDS:
        return choice
    encounter_id = choice.get("encounter_id")
    name = choice.get("name")
    if not isinstance(name, str):
        return choice
    localized = localize_encounter(mapping, encounter_id, name)
    if localized == name:
        return choice
    return dict(choice) | {"name": localized, "name_en": name}


def _verify_writable(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".wcl-raid-coach-doctor.", dir=path)
    try:
        os.close(descriptor)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
