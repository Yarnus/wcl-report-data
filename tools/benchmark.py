"""Repeatable offline workflow baselines; run with python -m tools.benchmark."""
from __future__ import annotations

import argparse
import copy
import gzip
import io
import json
import platform
import statistics
import subprocess
import tempfile
import time
from contextlib import ExitStack
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from tests.test_advice import advice_setup, real_complete_bundle_analysis, workflow_origin
from tests.test_dataset import report_fixture
from tests.test_cohort import PROFILE, SPEC_PROFILE
from tests.test_mechanics import report_fixture as mechanic_report
from wcl_raid_coach import api, diagnostics
from wcl_raid_coach.__main__ import create_parser, run
from wcl_raid_coach.cohort import identify_cohort, verify_benchmark_for_cohort
from wcl_raid_coach.comparison import compare_player
from wcl_raid_coach.content_names import EXPECTED_ENCOUNTER_COUNTS, SOURCE_URLS
from wcl_raid_coach.profiles import validate_profile
from wcl_raid_coach.personal_workflow import orchestrate_personal_review, finalize_personal_review_delivery
from wcl_raid_coach.report_documents import assemble_personal_review_document, render_report_document
from wcl_raid_coach.storage import atomic_write_json, read_json


class Response(io.BytesIO):
    def __init__(self, body, *, filename=None, compressed=False):
        super().__init__(gzip.compress(body, mtime=0) if compressed else body)
        self.headers = Message()
        if filename:
            self.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        if compressed:
            self.headers["Content-Encoding"] = "gzip"


def wago_tables():
    encounters = [(5000 + index, map_id) for index, map_id in enumerate(
        map_id for map_id, count in EXPECTED_ENCOUNTER_COUNTS.items() for _ in range(count)
    )]
    tables = {
        "map_zhCN": "ID,MapName_lang\n" + "".join(f"{key},Map {key}\n" for key in EXPECTED_ENCOUNTER_COUNTS),
        "journal_zhCN": "ID,DungeonEncounterID\n" + "".join(f"{key},{key}\n" for key, _ in encounters),
    }
    for locale in ("enUS", "zhCN"):
        tables[f"encounter_{locale}"] = "ID,MapID,Name_lang\n" + "".join(
            f"{key},{map_id},Boss {key}\n" for key, map_id in encounters
        )
        tables[f"creature_{locale}"] = "ID,JournalEncounterID,Name_lang\n" + "".join(
            f"{index * 3 + offset + 1},{key},NPC {index * 3 + offset + 1}\n"
            for index, (key, _) in enumerate(encounters) for offset in range(3)
        )
    return tables


class Transport:
    def __init__(self, *, mechanics=False):
        self.report = mechanic_report() if mechanics else report_fixture()
        self.tables = wago_tables()
        self.spent = 0

    def __call__(self, request, **kwargs):
        url = request.full_url
        if url.startswith("https://wago.tools/"):
            table = url.split("/db2/")[1].split("/")[0]
            if table == "SpellName":
                body = "ID,Name_lang\n" + "".join(f"{index},Spell {index}\n" for index in range(1, 400001))
            else:
                key = next(key for key, value in SOURCE_URLS.items() if value == url)
                body = self.tables[key]
            return Response(body.encode(), filename=f"{table}.12.1.0.69587.csv")
        if url == api.TOKEN_URL:
            return Response(b'{"access_token":"offline","expires_in":3600}')
        if url != api.API_URL:
            raise AssertionError("Unexpected benchmark HTTP endpoint")
        payload = json.loads(request.data)
        query, variables = payload["query"], payload["variables"]
        self.spent += 1
        data = {"rateLimitData": {"limitPerHour": 3600, "pointsSpentThisHour": self.spent, "pointsResetIn": 3600}}
        if query == api.REPORT_QUERY:
            report = copy.deepcopy(self.report)
            report["code"] = variables["code"]
            if variables["code"].startswith("Guide"):
                report["fights"][0]["encounterID"] = int(variables["code"][5:9])
                report["fights"][0]["difficulty"] = 4
                report["zone"]["difficulties"].append({"id": 4, "name": "Heroic", "sizes": [20]})
            data["reportData"] = {"report": report}
        elif query == api.REVISION_QUERY:
            data["reportData"] = {"report": {"revision": self.report["revision"]}}
        elif query in (api.EVENT_QUERY, api.MECHANIC_EVENT_QUERY, api.FOCUSED_EVENT_QUERY):
            events = [{
                "timestamp": variables["startTime"], "type": "damage", "sourceID": 10,
                "targetID": 10, "abilityGameID": 1284941, "amount": 100,
            }]
            data["reportData"] = {"report": {"events": {"data": events, "nextPageTimestamp": None}}}
        elif query == api.RANKINGS_QUERY:
            data["worldData"] = {"encounter": {"characterRankings": {"rankings": [
                {"reportCode": f"Guide{variables['encounterID']}R{i}", "fightID": 1,
                 "sourceID": 10, "startTime": int(time.time() * 1000), "score": 99}
                for i in range(3)
            ], "hasMorePages": False}}}
        elif query != api.RATE_LIMIT_QUERY:
            raise AssertionError("Unexpected benchmark GraphQL operation")
        return Response(json.dumps({"data": data}).encode(), compressed=True)


def command(root, *args):
    return run(create_parser().parse_args([
        "--data-root", str(root / "data"), "--cache-root", str(root / "cache"), *args,
    ]))


def personal(root):
    _, mapping, metadata, _, encounter, specialization = advice_setup(root)
    target_path, target = real_complete_bundle_analysis(root / "target", 7)
    references = [real_complete_bundle_analysis(root / f"reference-{i}", i) for i in (8, 9, 10)]
    cohort = identify_cohort({
        "schema_version": 2, "filters": target["comparison_identity"],
        "pagination": {"first_page": 1, "last_page": 1, "has_more_pages": False, "truncated": False, "exhausted": True},
        "eligible_recent_candidates": [{"report_code": value["identity"]["report_code"],
                                         "fight_id": value["identity"]["fight_id"], "source_id": 10} for _, value in references],
        "unverified_recency_candidates": [], "rejected_candidates": [],
    })
    cohort_path = atomic_write_json(root / "cohort.json", cohort)

    def execute():
        workflow = orchestrate_personal_review(
            target_path, cohort_path, encounter, specialization, root / "outputs",
            reference_analysis_paths=[path for path, _ in references], benchmark_paths=[],
            candidate_rejections=[], blockers=[], previous_workflow_path=workflow_origin(target_path, root / "outputs"),
        )
        benchmark_path = Path(workflow["workflow"]["artifacts"]["encounter_benchmark"]["path"])
        comparison_path = atomic_write_json(root / "comparison.json", compare_player(target, read_json(benchmark_path)))
        document = assemble_personal_review_document(
            target_path, benchmark_path, comparison_path, workflow_path=Path(workflow["workflow_path"]),
            workflow_registry_dir=root / "outputs" / "personal-workflows",
            ability_names_path=mapping, ability_names_metadata_path=metadata,
        )
        report = render_report_document(document, root / "outputs" / "reports",
                                        workflow_registry_dir=root / "outputs" / "personal-workflows")
        finalize_personal_review_delivery(Path(workflow["workflow_path"]), report, root / "outputs")
    return execute


SCENARIOS = ("first_inspect", "cold_prepare", "cached_prepare", "mechanics_followups", "triage", "personal_existing", "multi_boss_guide")


def scenario(root, name):
    url = "https://www.warcraftlogs.com/reports/AbC123#fight=1"
    if name == "first_inspect":
        return lambda: command(root, "inspect", url)
    if name in ("cold_prepare", "cached_prepare"):
        if name == "cached_prepare":
            command(root, "prepare", url)
        return lambda: command(root, "prepare", url)
    if name == "mechanics_followups":
        def execute():
            review = command(root, "coach", "mechanics", url, "--compact")
            command(root, "coach", "evidence", url, "--at-ms", "0", "--player-id", "10",
                    "--expected-identity", review["evidence_identity"])
        return execute
    if name == "triage":
        return lambda: command(root, "coach", "triage", url)
    if name == "personal_existing":
        return personal(root)
    def guide():
        specialization = validate_profile(SPEC_PROFILE | {
            "identity": {"game_version": "12.1", "partition_id": 2, "class_name": "Warrior", "spec_name": "Protection"},
            "abilities": [{"id": 7001, "action_type": "player_cast"}],
        })
        specialization_path = atomic_write_json(root / "specialization.json", specialization)
        chapters = []
        for encounter_id in (5000, 5001):
            encounter = validate_profile(PROFILE | {
                "identity": {"game_version": "12.1", "partition_id": 2, "encounter_id": encounter_id, "difficulty_id": 4},
                "eligibility": {"priority_target_ids": [], "excluded_target_ids": []},
                "mechanic_anchors": [{"ability_id": 7001, "name": "Mechanic"}],
            })
            encounter_path = atomic_write_json(root / f"encounter-{encounter_id}.json", encounter)
            cohort_path = root / f"cohort-{encounter_id}.json"
            cohort = command(root, "coach", "candidates", "--encounter-id", str(encounter_id),
                             "--difficulty-id", "4", "--partition-id", "2", "--game-version", "12.1",
                             "--class-name", "Warrior", "--spec-name", "Protection", "--output", str(cohort_path))["cohort"]
            analyses = []
            for index, candidate in enumerate(cohort["eligible_recent_candidates"]):
                prepared = command(root, "prepare", candidate["url"])
                analysis_path = root / f"analysis-{encounter_id}-{index}.json"
                command(root, "coach", "review", prepared["bundles"][0]["manifest_path"],
                        "--index", prepared["index_path"], "--source-id", "10", "--partition-id", "2",
                        "--output", str(analysis_path))
                analyses.append(str(analysis_path))
            benchmark_path = root / f"benchmark-{encounter_id}.json"
            command(root, "coach", "benchmark", *analyses, "--cohort", str(cohort_path),
                    "--encounter-profile", str(encounter_path), "--specialization-profile", str(specialization_path),
                    "--output", str(benchmark_path))
            chapters.append((benchmark_path, cohort, encounter))
        for reuse in (False, True):
            if reuse:
                for path, cohort, encounter in chapters:
                    verify_benchmark_for_cohort(read_json(path), cohort, encounter, specialization)
            snapshot = command(root, "coach", "guide", *(str(path) for path, _, _ in chapters),
                               "--spec-display-name", "Protection")["guide"]
            command(root, "coach", "guide-report", snapshot["index_path"])
    return guide


def measure(name):
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        root = Path(directory)
        stack.enter_context(patch("wcl_raid_coach.api_schedule.coordination_root", return_value=root / "coordination"))
        transport = Transport(mechanics=name in ("mechanics_followups", "triage"))
        for module in ("api", "ability_names", "content_names"):
            stack.enter_context(patch(f"wcl_raid_coach.{module}.urlopen", side_effect=transport))
        from wcl_raid_coach.config import Credentials
        stack.enter_context(patch("wcl_raid_coach.__main__.resolve_credentials", return_value=Credentials("offline", "offline", "fixture")))
        execute = scenario(root, name)
        with diagnostics.collect() as measurements:
            wall, cpu = time.monotonic(), time.process_time()
            execute()
            elapsed, cpu_elapsed = time.monotonic() - wall, time.process_time() - cpu
        return {"wall_seconds": elapsed, "cpu_seconds": cpu_elapsed, "diagnostics": measurements.snapshot()}


def numeric_leaves(value, prefix=""):
    result = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            result.update(numeric_leaves(item, name))
        elif type(item) in (int, float):
            result[name] = item
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--scenario", choices=SCENARIOS, action="append")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    result = {"mode": "offline_synthetic_http", "python": platform.python_version(),
              "platform": platform.platform(), "repetitions": args.repetitions,
              "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "worktree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
              "live_scenarios_measured": [], "scenarios": {}}
    for name in args.scenario or SCENARIOS:
        runs = [measure(name) for _ in range(args.repetitions)]
        leaves = [numeric_leaves(run) for run in runs]
        result["scenarios"][name] = {"runs": runs, "medians": {
            key: statistics.median(run[key] for run in leaves) for key in leaves[0]
        }}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
