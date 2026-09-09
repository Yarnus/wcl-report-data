from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from wcl_raid_coach.__main__ import create_parser, main, run
from wcl_raid_coach.cohort import identify_benchmark
from wcl_raid_coach.errors import InputError, RevisionChangedError
from wcl_raid_coach.personal_workflow import initialize_personal_review


def comparison_ready_workflow(root: Path, analysis: Path, benchmark: Path) -> Path:
    from wcl_raid_coach.personal_workflow import _persist_result

    root = root.resolve()

    def ref(path: Path) -> dict[str, str]:
        path = path.resolve()
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    result = _persist_result(root / "data" / "outputs", {
        "schema_version": 2,
        "artifact_type": "personal_review_workflow",
        "selected_identity": {"report_code": "ABC", "fight_id": 7, "actor_id": 10},
        "workflow_started_monotonic_seconds": 0.0,
        "clock": {
            "wall_minus_monotonic_seconds": 0.0,
            "session_marker": "0" * 16,
            "baseline_tolerance_seconds": 1.0,
            "continuity_available": True,
        },
        "completion_state": "comparison_ready",
        "report_available": True,
        "player_evidence_complete": True,
        "comparison_available": True,
        "reference_sample_target": 3,
        "qualified_reference_samples": 3,
        "candidate_progress": [],
        "next_ranking_candidate": None,
        "blockers": [],
        "budget": {
            "target_seconds": 180.0,
            "elapsed_seconds": 1.0,
            "validation_render_reserve_seconds": 20.0,
            "optional_acquisition_open": True,
            "kind": "measured_soft_target",
        },
        "stage_timings_seconds": {"selection": 0.1, "player_evidence": 0.1, "benchmark_build": 0.1},
        "stage_progress": {
            "retrieval": "completed", "agent_synthesis": "in_progress",
            "validation": "pending", "rendering": "pending",
        },
        "artifacts": {
            "requested_personal_analysis_path": str(analysis.resolve()),
            "personal_analysis": ref(analysis),
            "ranking_cohort": None,
            "encounter_profile": None,
            "specialization_profile": None,
            "reference_analyses": [],
            "benchmark_reference_evidence": [],
            "encounter_benchmark": ref(benchmark),
            "previous_workflow": None,
            "progress": [],
        },
        "benchmark_reused": False,
    })
    return Path(result["workflow_path"])


class CliTests(unittest.TestCase):
    def test_personal_workflow_init_requires_no_analysis_cohort_or_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with redirect_stdout(output):
                status = main([
                    "--data-root", temporary, "coach", "personal-workflow-init",
                    "https://www.warcraftlogs.com/reports/ABC123#fight=7&source=42",
                ])
            response = json.loads(output.getvalue())

        self.assertEqual(status, 0, response)
        self.assertEqual(response["workflow"]["selected_identity"], {
            "report_code": "ABC123", "fight_id": 7, "actor_id": 42,
        })
        self.assertIsNone(response["workflow"]["artifacts"]["ranking_cohort"])
        self.assertIsNone(response["workflow"]["artifacts"]["personal_analysis"])

    def test_personal_workflow_rejects_caller_supplied_timing_flags(self) -> None:
        with self.assertRaisesRegex(InputError, "unrecognized arguments"):
            create_parser().parse_args([
                "coach", "personal-workflow", "analysis.json",
                "--cohort", "cohort.json", "--encounter-profile", "encounter.json",
                "--specialization-profile", "specialization.json",
                "--previous-workflow", "workflow.json",
                "--elapsed-seconds", "1", "--stage-timing", "selection=1",
            ])

    def test_candidates_records_proven_terminal_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = create_parser().parse_args([
                "--data-root", str(Path(temporary) / "data"),
                "--cache-root", str(Path(temporary) / "cache"),
                "coach", "candidates", "--encounter-id", "1", "--difficulty-id", "2",
                "--partition-id", "3", "--game-version", "retail",
                "--class-name", "Mage", "--spec-name", "Arcane",
            ])
            with (
                patch("wcl_raid_coach.__main__.resolve_credentials", return_value=object()),
                patch("wcl_raid_coach.__main__.WclClient") as client_type,
            ):
                client_type.return_value.fetch_rankings.return_value = {
                    "rankings": [], "hasMorePages": False,
                }
                result = run(args)
        self.assertEqual(result["cohort"]["pagination"], {
            "first_page": 1, "last_page": 1, "has_more_pages": False,
            "truncated": False, "target_reached": False, "exhausted": True,
        })

    def test_candidates_preserves_complete_deduplicated_page_after_goal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = create_parser().parse_args([
                "--data-root", str(Path(temporary) / "data"),
                "--cache-root", str(Path(temporary) / "cache"),
                "coach", "candidates", "--encounter-id", "1", "--difficulty-id", "2",
                "--partition-id", "3", "--game-version", "retail", "--sample-goal", "2", "--page", "4",
                "--class-name", "Mage", "--spec-name", "Arcane",
            ])
            candidates = [
                {"reportCode": code, "fightID": index, "sourceID": 10 + index,
                 "startTime": "2026-09-01T00:00:00Z"}
                for index, code in enumerate(("ABC", "DEF", "GHI", "JKL"), 1)
            ]
            with (
                patch("wcl_raid_coach.__main__.resolve_credentials", return_value=object()),
                patch("wcl_raid_coach.__main__.WclClient") as client_type,
            ):
                client_type.return_value.fetch_rankings.return_value = {
                    "rankings": candidates, "hasMorePages": True,
                }
                result = run(args)
        self.assertEqual(
            [item["report_code"] for item in result["cohort"]["eligible_recent_candidates"]],
            ["ABC", "DEF", "GHI", "JKL"],
        )
        self.assertEqual(result["cohort"]["pagination"], {
            "first_page": 4, "last_page": 4, "has_more_pages": True,
            "truncated": False, "target_reached": True, "exhausted": False,
        })

    def test_candidates_deduplicates_overlapping_ranking_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = create_parser().parse_args([
                "--data-root", str(Path(temporary) / "data"),
                "--cache-root", str(Path(temporary) / "cache"),
                "coach", "candidates", "--encounter-id", "1", "--difficulty-id", "2",
                "--partition-id", "3", "--game-version", "retail", "--sample-goal", "3",
                "--class-name", "Mage", "--spec-name", "Arcane",
            ])
            candidates = [
                {"reportCode": code, "fightID": index, "name": f"Player {index}",
                 "startTime": "2026-09-01T00:00:00Z"}
                for index, code in enumerate(("ABC", "DEF", "GHI"), 1)
            ]
            with (
                patch("wcl_raid_coach.__main__.resolve_credentials", return_value=object()),
                patch("wcl_raid_coach.__main__.WclClient") as client_type,
            ):
                client_type.return_value.fetch_rankings.side_effect = [
                    {"rankings": candidates[:2], "hasMorePages": True},
                    {"rankings": candidates[1:], "hasMorePages": False},
                ]
                client_type.return_value.resolve_candidate_source.side_effect = [11, 12, 13]
                result = run(args)

        self.assertEqual(
            [item["report_code"] for item in result["cohort"]["eligible_recent_candidates"]],
            ["ABC", "DEF", "GHI"],
        )
        self.assertEqual(result["cohort"]["pagination"]["last_page"], 2)
        self.assertTrue(result["cohort"]["pagination"]["exhausted"])
        self.assertEqual(client_type.return_value.resolve_candidate_source.call_count, 3)

    def test_personal_report_requires_workflow_before_loading_artifacts(self) -> None:
        with self.assertRaisesRegex(InputError, "required: --workflow"):
            create_parser().parse_args([
                "coach", "personal-report", "analysis.json", "benchmark.json", "comparison.json",
            ])

    def test_personal_report_rejects_external_workflow_before_creating_artifacts_without_advice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            external = initialize_personal_review(
                "ABC", 7, 10, root / "external"
            )
            args = create_parser().parse_args([
                "--data-root", str(root / "data"), "coach", "personal-report",
                "analysis.json", "--workflow", external["workflow_path"],
                "--encounter-profile", "encounter.json",
                "--specialization-profile", "specialization.json",
            ])

            with patch("wcl_raid_coach.__main__._ensure_ability_names") as ensure_names:
                with self.assertRaisesRegex(InputError, "workflow path"):
                    run(args)

            ensure_names.assert_not_called()
            self.assertFalse((root / "data" / "ability-names.zhCN.json").exists())
            self.assertFalse((root / "data" / "outputs" / "reports").exists())

    def test_partial_personal_report_returns_finalized_delivery_timing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = create_parser().parse_args([
                "--data-root", str(root / "data"), "--cache-root", str(root / "cache"),
                "coach", "personal-report", "analysis.json", "--workflow", "workflow.json",
                "--encounter-profile", "encounter.json", "--specialization-profile", "spec.json",
            ])
            report = {
                "document_id": "a" * 64, "html_path": "report.html",
                "html_sha256": "b" * 64, "index_path": "report.json",
            }
            delivery = {"elapsed_seconds": 12.5, "target_met": True}
            with (
                patch("wcl_raid_coach.__main__.validate_partial_workflow"),
                patch("wcl_raid_coach.__main__._ensure_ability_names", return_value={"mapping_path": "names.json", "metadata_path": "metadata.json"}),
                patch("wcl_raid_coach.__main__.assemble_partial_personal_review_document", return_value={"document": True}),
                patch("wcl_raid_coach.__main__.validate_report_document", return_value={"document": True}),
                patch("wcl_raid_coach.__main__.render_report_document", return_value=report),
                patch("wcl_raid_coach.__main__.finalize_personal_review_delivery", return_value=delivery),
            ):
                result = run(args)
        self.assertEqual(result["delivery"], delivery)

    def test_comparison_ready_personal_report_returns_finalized_delivery_timing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = create_parser().parse_args([
                "--data-root", str(root / "data"), "--cache-root", str(root / "cache"),
                "coach", "personal-report", "analysis.json", "benchmark.json", "comparison.json",
                "--workflow", "workflow.json",
            ])
            delivery = {"artifact": {"status": "delivered"}, "elapsed_seconds": 12.5, "target_met": True}
            with (
                patch("wcl_raid_coach.__main__.validate_comparison_workflow"),
                patch("wcl_raid_coach.__main__._ensure_ability_names", return_value={"mapping_path": "names.json", "metadata_path": "metadata.json"}),
                patch("wcl_raid_coach.__main__.assemble_personal_review_document", return_value={"document": True}) as assemble,
                patch("wcl_raid_coach.__main__.validate_report_document", return_value={"document": True}),
                patch("wcl_raid_coach.__main__.render_report_document", return_value={"document_id": "a" * 64, "html_path": "report.html", "html_sha256": "b" * 64, "index_path": "report.json"}),
                patch("wcl_raid_coach.__main__.finalize_personal_review_delivery", return_value=delivery),
            ):
                result = run(args)
        self.assertEqual(result["delivery"], delivery)
        self.assertEqual(assemble.call_args.kwargs["workflow_path"], Path("workflow.json"))

    def test_parser_accepts_explicit_env_file(self) -> None:
        args = create_parser().parse_args(["--env-file", "/actual/workspace/.env", "doctor"])

        self.assertEqual(args.env_file, Path("/actual/workspace/.env"))

    def test_prepare_parser_accepts_explicit_batch_selection(self) -> None:
        args = create_parser().parse_args(
            [
                "prepare",
                "https://www.warcraftlogs.com/reports/AbC123",
                "--fight",
                "1",
                "--fight",
                "2",
            ]
        )

        self.assertEqual(args.fight_ids, [1, 2])

    def test_dataset_list_is_structured_and_does_not_require_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "--data-root",
                        str(Path(temporary) / "data"),
                        "--cache-root",
                        str(Path(temporary) / "cache"),
                        "dataset",
                        "list",
                    ]
                )

        result = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["reports"], [])

    def test_invalid_env_file_encoding_returns_a_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env"
            env_file.write_bytes(b"WCL_CLIENT_ID=\xff\n")
            output = io.StringIO()

            without_credentials = {
                "WCL_CLIENT_ID": "",
                "WCL_CLIENT_SECRET": "",
                "WCL_ID": "",
                "WCL_SECRET": "",
            }
            with patch.dict("os.environ", without_credentials), redirect_stdout(output):
                status = main(["--env-file", str(env_file), "doctor"])

        result = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "credentials_unavailable")

    def test_query_works_without_mappings_or_network(self) -> None:
        from tests.test_analysis import AnalysisTests
        with tempfile.TemporaryDirectory() as directory:
            manifest, _ = AnalysisTests().make_bundle(Path(directory))
            args = create_parser().parse_args(["--data-root", directory, "query", str(manifest)])
            with patch("wcl_raid_coach.ability_names.urlopen", side_effect=AssertionError("No display download")):
                result = run(args)
            self.assertEqual(result["matched"], 5)
            self.assertNotIn("ability_names", result)

    def test_inspect_and_batch_prepare_do_not_download_names(self) -> None:
        from tools.benchmark import Transport, command
        from tests.test_api import isolated_schedule
        from wcl_raid_coach.config import Credentials
        from wcl_raid_coach.diagnostics import collect
        transport = Transport()
        transport.report["fights"][2]["inProgress"] = False
        with tempfile.TemporaryDirectory() as directory, isolated_schedule(), patch(
            "wcl_raid_coach.api.urlopen", side_effect=transport
        ), patch("wcl_raid_coach.__main__.resolve_credentials", return_value=Credentials("test", "test", "fixture")), patch(
            "wcl_raid_coach.ability_names.urlopen", side_effect=AssertionError("No display download")
        ), patch("wcl_raid_coach.content_names.urlopen", side_effect=AssertionError("No display download")):
            root = Path(directory)
            result = command(root, "inspect", "https://www.warcraftlogs.com/reports/AbC123")
            self.assertIsNone(result["content_names"])
            self.assertNotIn("ability_names", result)
            self.assertEqual(result["fight_choices"][0]["name"], "Test Boss")
            with collect() as metrics:
                prepared = command(root, "prepare", "https://www.warcraftlogs.com/reports/AbC123", "--fight", "1", "--fight", "3")
            self.assertEqual(len(prepared["bundles"]), 2)
            self.assertEqual(metrics.snapshot()["network"]["ReportIndex"]["attempts"], 1)
            self.assertNotIn("ability_names", prepared)

    def test_inspect_returns_choices_while_content_mapping_lock_is_busy(self):
        from tools.benchmark import Transport, command
        from tests.test_api import isolated_schedule
        from wcl_raid_coach.dataset import DatasetStore
        from wcl_raid_coach.errors import DatasetError

        with tempfile.TemporaryDirectory() as temporary, isolated_schedule(), patch(
            "wcl_raid_coach.api.urlopen", side_effect=Transport()
        ), patch("wcl_raid_coach.__main__.resolve_credentials"), patch.object(
            DatasetStore, "content_names_lock", side_effect=DatasetError("busy")
        ) as lock:
            result = command(Path(temporary), "inspect", "https://www.warcraftlogs.com/reports/AbC123")
        self.assertIsNone(result["content_names"])
        self.assertTrue(result["fight_choices"])
        lock.assert_called_once_with(timeout_seconds=0)

    def test_coach_resolve_creates_a_confirmable_unholy_guide_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = io.StringIO()
            zones = [{
                "id": 42,
                "name": "Current Raid",
                "frozen": False,
                "difficulties": [{"id": 4, "name": "Heroic"}],
                "partitions": [{"id": 2, "name": "Current", "compactName": "12.1", "default": True}],
                "encounters": [{"id": 1000 + index, "name": f"Boss {index}"} for index in range(1, 9)],
            }]
            with (
                patch("wcl_raid_coach.__main__.resolve_credentials"),
                patch("wcl_raid_coach.__main__.WclClient") as client,
                patch(
                    "wcl_raid_coach.__main__._ensure_content_names",
                    return_value={"mapping_path": "/tmp/content-names.json", "build": "12.1.0.69587"},
                ),
                patch(
                    "wcl_raid_coach.__main__.load_content_names",
                    return_value={
                        "encounters": {
                            "1007": {"map_id": 3004, "name_en": "Boss 7", "name_zh": "中文首领七"},
                            "1008": {"map_id": 3004, "name_en": "Boss 8", "name_zh": "中文首领八"},
                        }
                    },
                ),
                redirect_stdout(output),
            ):
                client.return_value.fetch_raid_zones.return_value = zones
                status = main(
                    [
                        "--data-root",
                        str(Path(temporary) / "data"),
                        "--cache-root",
                        str(Path(temporary) / "cache"),
                        "coach",
                        "resolve",
                        "--spec",
                        "邪 DK",
                        "--encounter",
                        "H7",
                        "--encounter",
                        "H8",
                    ]
                )

        result = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(result["task"]["request"]["specialization"]["spec_name"], "Unholy")
        self.assertEqual(result["task"]["status"], "pending_confirmation")
        self.assertEqual(result["task"]["context"]["encounters"][1]["encounter_name"], "中文首领八")
        self.assertEqual(result["task"]["context"]["encounters"][1]["encounter_name_en"], "Boss 8")

    def test_personal_review_defaults_to_three_without_changing_candidate_default(self) -> None:
        personal = create_parser().parse_args([
            "coach", "resolve", "--mode", "personal_review",
            "--report-url", "https://www.warcraftlogs.com/reports/AbC123#fight=7&source=10",
        ])
        candidates = create_parser().parse_args([
            "coach", "candidates", "--game-version", "12.1", "--encounter-id", "1",
            "--difficulty-id", "4", "--partition-id", "2", "--class-name", "Mage",
            "--spec-name", "Fire",
        ])
        with tempfile.TemporaryDirectory() as temporary:
            personal.data_root = Path(temporary) / "data"
            result = run(personal)

        self.assertEqual(result["task"]["request"]["sample_goal"], 3)
        self.assertEqual(candidates.sample_goal, 10)

    def test_coach_review_labels_complete_bundle_analysis_as_log_fact(self) -> None:
        args = create_parser().parse_args(
            ["coach", "review", "/tmp/manifest.json", "--index", "/tmp/report.json", "--source-id", "10"]
        )
        with (
            patch("wcl_raid_coach.__main__.resolve_credentials"),
            patch("wcl_raid_coach.__main__.analyze_player", return_value={"metrics": {"deaths": 0}}),
        ):
            result = run(args)
        self.assertEqual(result["evidence_class"], "log_fact")
        self.assertEqual(result["analysis"]["metrics"]["deaths"], 0)

    def test_coach_review_does_not_resolve_wcl_credentials(self) -> None:
        args = create_parser().parse_args(
            ["coach", "review", "/tmp/manifest.json", "--index", "/tmp/report.json", "--source-id", "10"]
        )
        with (
            patch("wcl_raid_coach.__main__.resolve_credentials") as resolve,
            patch("wcl_raid_coach.__main__.analyze_player", return_value={"metrics": {}}),
        ):
            run(args)

        resolve.assert_not_called()

    def test_coach_review_resolves_production_report_partition_labels(self) -> None:
        from tests.test_analysis import AnalysisTests

        for compact_name, expected in (("12.1", "12.1"), (None, "Current Season")):
            with self.subTest(compact_name=compact_name), tempfile.TemporaryDirectory() as temporary:
                manifest, index = AnalysisTests().make_bundle(Path(temporary))
                value = json.loads(index.read_text(encoding="utf-8"))
                value["report"]["zone"]["partitions"][0]["compactName"] = compact_name
                index.write_text(json.dumps(value), encoding="utf-8")
                manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
                manifest_value["report_index_sha256"] = hashlib.sha256(
                    json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                manifest.write_text(json.dumps(manifest_value), encoding="utf-8")
                output = io.StringIO()

                with redirect_stdout(output):
                    status = main(
                        [
                            "coach", "review", str(manifest), "--index", str(index),
                            "--source-id", "10", "--partition-id", "2",
                        ]
                    )

                result = json.loads(output.getvalue())
                self.assertEqual(status, 0)
                self.assertEqual(result["analysis"]["comparison_identity"]["game_version"], expected)

    def test_coach_review_unknown_partition_returns_structured_domain_error(self) -> None:
        from tests.test_analysis import AnalysisTests

        with tempfile.TemporaryDirectory() as temporary:
            manifest, index = AnalysisTests().make_bundle(Path(temporary))
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "coach", "review", str(manifest), "--index", str(index),
                        "--source-id", "10", "--partition-id", "99",
                    ]
                )

        result = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(result["error"], "dataset_error")
        self.assertIn("ranking partition", result["message"])

    def test_coach_review_malformed_partitions_return_structured_domain_error(self) -> None:
        from tests.test_analysis import AnalysisTests

        with tempfile.TemporaryDirectory() as temporary:
            helper = AnalysisTests()
            manifest, index = helper.make_bundle(Path(temporary))
            helper.replace_partitions(
                manifest,
                index,
                [{"id": True, "name": "Current", "compactName": "12.1", "default": True}],
            )
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "coach", "review", str(manifest), "--index", str(index),
                        "--source-id", "10", "--partition-id", "2",
                    ]
                )

        result = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(result["error"], "dataset_error")
        self.assertIn("ranking partitions are malformed", result["message"])

    def test_coach_mechanics_uses_the_in_memory_review_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "data"
            cache_root = Path(temporary) / "cache"
            args = create_parser().parse_args(
                [
                    "--data-root",
                    str(data_root),
                    "--cache-root",
                    str(cache_root),
                    "coach",
                    "mechanics",
                    "https://www.warcraftlogs.com/reports/AbC123",
                    "--encounter",
                    "H2",
                ]
            )
            with (
                patch("wcl_raid_coach.__main__.resolve_credentials"),
                patch("wcl_raid_coach.__main__.WclClient"),
                patch("wcl_raid_coach.__main__.MechanicReviewService") as service,
            ):
                service.return_value.review.return_value = {
                    "action": "coach_mechanics",
                    "selection_required": True,
                    "fight_choices": [],
                }
                result = run(args)

            self.assertFalse(data_root.exists())
            self.assertFalse(cache_root.exists())

        request = service.return_value.review.call_args
        self.assertEqual(request.args[0].code, "AbC123")
        self.assertEqual(request.kwargs["encounter_designator"].as_dict()["value"], "H2")
        self.assertTrue(result["selection_required"])

    def test_coach_mechanics_compact_returns_sanitized_summary(self) -> None:
        args = create_parser().parse_args([
            "coach", "mechanics", "https://www.warcraftlogs.com/reports/AbC123#fight=1", "--compact",
        ])
        review = {"action": "coach_mechanics", "selection_required": False, "mechanics": []}
        with (
            patch("wcl_raid_coach.__main__.resolve_credentials"),
            patch("wcl_raid_coach.__main__.WclClient"),
            patch("wcl_raid_coach.__main__.MechanicReviewService") as service,
            patch("wcl_raid_coach.__main__.compact_mechanic_review", return_value={"output_mode": "compact"}) as compact,
        ):
            service.return_value.review.return_value = review
            result = run(args)

        compact.assert_called_once_with(review)
        self.assertEqual(result["output_mode"], "compact")

    def test_coach_evidence_passes_the_focused_window(self) -> None:
        args = create_parser().parse_args([
            "coach", "evidence", "https://www.warcraftlogs.com/reports/AbC123#fight=1",
            "--at-ms", "1000", "--window-ms", "500", "--player-id", "10",
            "--expected-identity", "AbC123:7:1",
        ])
        with (
            patch("wcl_raid_coach.__main__.resolve_credentials"),
            patch("wcl_raid_coach.__main__.WclClient"),
            patch("wcl_raid_coach.__main__.MechanicReviewService") as service,
        ):
            service.return_value.focused_evidence.return_value = {"action": "coach_evidence"}
            result = run(args)

        request = service.return_value.focused_evidence.call_args
        self.assertEqual(request.kwargs, {
            "at_ms": 1000.0, "window_ms": 500.0, "player_ids": [10],
            "expected_identity": "AbC123:7:1",
        })
        self.assertEqual(result["action"], "coach_evidence")

    def test_coach_mechanics_report_returns_structured_artifact_paths(self) -> None:
        from tests.test_report_documents import mechanic_source

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = io.StringIO()
            with (
                patch("wcl_raid_coach.__main__.resolve_credentials"),
                patch("wcl_raid_coach.__main__.WclClient"),
                patch("wcl_raid_coach.__main__.MechanicReviewService") as service,
                redirect_stdout(output),
            ):
                service.return_value.review.return_value = mechanic_source()
                status = main([
                    "--data-root", str(root / "data"),
                    "--cache-root", str(root / "cache"),
                    "coach", "mechanics",
                    "https://www.warcraftlogs.com/reports/AbC123#fight=17",
                    "--report", "--locale", "en",
                ])
            result = json.loads(output.getvalue())

            self.assertEqual(status, 0)
            self.assertTrue(result["ok"])
            self.assertEqual(result["action"], "coach_mechanic_report")
            self.assertNotIn("mechanics", result)
            self.assertTrue(Path(result["source"]["path"]).is_file())
            self.assertTrue(Path(result["report"]["html_path"]).is_file())

    def test_coach_mechanics_report_failure_is_a_structured_domain_error(self) -> None:
        output = io.StringIO()
        with (
            patch("wcl_raid_coach.__main__.resolve_credentials"),
            patch("wcl_raid_coach.__main__.WclClient"),
            patch("wcl_raid_coach.__main__.MechanicReviewService") as service,
            redirect_stdout(output),
        ):
            service.return_value.review.side_effect = RevisionChangedError("revision changed")
            status = main([
                "coach", "mechanics",
                "https://www.warcraftlogs.com/reports/AbC123#fight=17", "--report",
            ])
        result = json.loads(output.getvalue())

        self.assertEqual(status, 1)
        self.assertEqual(result["error"], "report_revision_changed")

    def test_invalid_coach_profile_encoding_returns_a_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "profile.json"
            profile.write_bytes(b"{\xff")
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(["coach", "profile", str(profile)])

        result = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "dataset_io_error")

    def test_coach_render_writes_html_without_credentials(self) -> None:
        from tests.test_report_documents import mechanic_document

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document_path = root / "document.json"
            document_path.write_text(json.dumps(mechanic_document(root)), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "--data-root",
                        str(root / "data"),
                        "--cache-root",
                        str(root / "cache"),
                        "coach",
                        "render",
                        str(document_path),
                    ]
                )

            result = json.loads(output.getvalue())

        self.assertEqual(status, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "coach_render")
        self.assertIn(str(Path("outputs") / "reports"), result["report"]["html_path"])

    def test_coach_render_returns_structured_schema_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            document_path = Path(temporary) / "document.json"
            document_path.write_text("{}", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(["coach", "render", str(document_path)])

        result = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(result["error"], "invalid_input")

    def test_coach_render_returns_input_error_for_a_malformed_source(self) -> None:
        from tests.test_report_documents import mechanic_document

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = mechanic_document(root)
            source = Path(document["source_artifacts"][0]["path"])
            source.write_text("{", encoding="utf-8")
            document["source_artifacts"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            document_path = root / "document.json"
            document_path.write_text(json.dumps(document), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(["coach", "render", str(document_path)])

        result = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(result["error"], "invalid_input")

    def test_coach_render_returns_structured_error_without_echoing_url_secret(self) -> None:
        from tests.test_report_documents import mechanic_document

        secret = "must-not-appear-in-stdout"
        with tempfile.TemporaryDirectory() as temporary:
            document = mechanic_document()
            document["ruleset"]["sources"] = [
                f"https://example.com/source?X-Amz-Signature={secret}"
            ]
            document_path = Path(temporary) / "document.json"
            document_path.write_text(json.dumps(document), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(["coach", "render", str(document_path)])

        result = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(result["error"], "invalid_input")
        self.assertNotIn(secret, output.getvalue())

    def test_coach_guide_uses_zhcn_spell_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_root = root / "data"
            cache_root = root / "cache"
            mapping_path = data_root / "ability-names.zhCN.json"
            mapping_path.parent.mkdir(parents=True)
            mapping_path.write_text(json.dumps({"2": "中文机制", "3": "中文技能"}), encoding="utf-8")
            benchmark_path = root / "benchmark.json"
            benchmark_path.write_text(
                json.dumps(
                    identify_benchmark(
                        {
                            "schema_version": 3,
                            "cohort_id": "c" * 64,
                            "identity": {
                                "game_version": "retail",
                                "partition_id": 2,
                                "encounter_id": 1007,
                                "difficulty_id": 4,
                                "class_name": "DeathKnight",
                                "spec_name": "Unholy",
                            },
                            "sample_count": 3,
                            "reference_samples": [{}, {}, {}],
                            "confidence": "low",
                            "stable_pattern_claims_allowed": True,
                            "mechanic_anchors": [{"ability_id": 2, "name": "English Mechanic", "observed_anchor_ms": 10000}],
                            "metrics": {"key_action_casts_median": {"3": 2}},
                        }
                    )
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with (
                patch(
                    "wcl_raid_coach.__main__._ensure_ability_names",
                    return_value={"mapping_path": str(mapping_path), "build": "12.1.0.69587"},
                ),
                patch(
                    "wcl_raid_coach.__main__._ensure_content_names",
                    return_value={
                        "mapping_path": str(root / "content-names.json"),
                        "build": "12.1.0.69587",
                        "mapping_sha256": "a" * 64,
                    },
                ),
                patch(
                    "wcl_raid_coach.__main__.load_content_names",
                    return_value={
                        "encounters": {
                            "1007": {"map_id": 3004, "name_en": "Boss 7", "name_zh": "中文首领七"}
                        }
                    },
                ),
                redirect_stdout(output),
            ):
                status = main(
                    [
                        "--data-root",
                        str(data_root),
                        "--cache-root",
                        str(cache_root),
                        "coach",
                        "guide",
                        str(benchmark_path),
                        "--spec-display-name",
                        "邪恶死亡骑士",
                    ]
                )

            result = json.loads(output.getvalue())
            markdown = Path(result["guide"]["markdown_path"]).read_text(encoding="utf-8")

        self.assertEqual(status, 0)
        self.assertIn("中文技能", markdown)
        self.assertIn("中文机制", markdown)
        self.assertNotIn("English Mechanic", markdown)

    def test_coach_guide_report_assembles_and_renders_a_snapshot(self) -> None:
        from tests.test_report_documents import raid_guide_document

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = raid_guide_document(root)
            snapshot_path = document["source_artifacts"][0]["path"]
            output = io.StringIO()
            with redirect_stdout(output):
                status = main([
                    "--data-root", str(root / "data"),
                    "--cache-root", str(root / "cache"),
                    "coach", "guide-report", snapshot_path,
                ])
            result = json.loads(output.getvalue())

        self.assertEqual(status, 0)
        self.assertEqual(result["action"], "coach_guide_report")
        self.assertEqual(result["report"]["document_id"], result["document"]["document_id"])

    def test_coach_personal_report_assembles_and_renders_three_artifacts(self) -> None:
        from tests.test_report_documents import personal_document

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_document = personal_document(root)
            refs = {item["kind"]: item["path"] for item in source_document["source_artifacts"]}
            workflow = comparison_ready_workflow(
                root, Path(refs["personal_analysis"]), Path(refs["encounter_benchmark"])
            )
            mapping_path = root / "ability-names.zhCN.json"
            mapping_path.write_text(json.dumps({"2": "本地化技能"}), encoding="utf-8")
            metadata_path = root / "ability-names.zhCN.meta.json"
            metadata_path.write_text(json.dumps({
                "build": "12.1.0.69587", "mapping_sha256": hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
            }), encoding="utf-8")
            output = io.StringIO()
            with (
                patch("wcl_raid_coach.__main__._ensure_ability_names", return_value={
                    "mapping_path": str(mapping_path), "metadata_path": str(metadata_path),
                    "build": "12.1.0.69587",
                }),
                patch("wcl_raid_coach.personal_workflow.validate_comparison_workflow"),
                redirect_stdout(output),
            ):
                status = main([
                    "--data-root", str(root / "data"), "--cache-root", str(root / "cache"),
                    "coach", "personal-report", refs["personal_analysis"],
                    refs["encounter_benchmark"], refs["comparison"],
                    "--workflow", str(workflow), "--locale", "zh-CN",
                ])
            result = json.loads(output.getvalue())
            html_exists = Path(result["report"]["html_path"]).is_file()

        self.assertEqual(status, 0)
        self.assertEqual(result["action"], "coach_personal_report")
        self.assertEqual(result["document"]["abilities"][0]["ability_id"], 2)
        self.assertEqual(result["document"]["abilities"][0]["name"], "本地化技能")
        self.assertTrue(html_exists)

    def test_coach_personal_report_validates_persists_and_renders_advice(self) -> None:
        from tests.test_advice import advice_setup

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, mapping, metadata, draft, encounter_profile, specialization_profile = advice_setup(root)
            workflow = comparison_ready_workflow(
                root, refs["personal_analysis"], refs["encounter_benchmark"]
            )
            output = io.StringIO()
            with (
                patch("wcl_raid_coach.__main__._ensure_ability_names", return_value={
                    "mapping_path": str(mapping), "metadata_path": str(metadata),
                    "build": "12.1.0.69587",
                }),
                patch("wcl_raid_coach.personal_workflow.validate_comparison_workflow"),
                redirect_stdout(output),
            ):
                status = main([
                    "--data-root", str(root / "data"), "--cache-root", str(root / "cache"),
                    "coach", "personal-report", str(refs["personal_analysis"]),
                    str(refs["encounter_benchmark"]), str(refs["comparison"]),
                    "--workflow", str(workflow),
                    "--advice", str(draft), "--encounter-profile", str(encounter_profile),
                    "--specialization-profile", str(specialization_profile), "--locale", "zh-CN",
                ])
            result = json.loads(output.getvalue())
            advice_exists = Path(result["advice"]["path"]).is_file()
            html = Path(result["report"]["html_path"]).read_text(encoding="utf-8")

        self.assertEqual(status, 0)
        self.assertEqual(result["action"], "coach_personal_report")
        self.assertTrue(advice_exists)
        self.assertEqual(len(result["document"]["advice"]), 1)
        self.assertIn("本地化技能", html)

    def test_coach_personal_report_rejects_malformed_advice_as_input_error(self) -> None:
        from tests.test_advice import advice_setup

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, mapping, metadata, draft, encounter_profile, specialization_profile = advice_setup(root)
            draft.write_text("{", encoding="utf-8")
            output = io.StringIO()
            with (
                patch("wcl_raid_coach.__main__._ensure_ability_names", return_value={
                    "mapping_path": str(mapping), "metadata_path": str(metadata),
                    "build": "12.1.0.69587",
                }),
                redirect_stdout(output),
            ):
                status = main([
                    "--data-root", str(root / "data"), "--cache-root", str(root / "cache"),
                    "coach", "personal-report", str(refs["personal_analysis"]),
                    str(refs["encounter_benchmark"]), str(refs["comparison"]),
                    "--workflow", str(root / "missing-workflow.json"),
                    "--advice", str(draft), "--encounter-profile", str(encounter_profile),
                    "--specialization-profile", str(specialization_profile), "--locale", "zh-CN",
                ])
            result = json.loads(output.getvalue())

        self.assertEqual(status, 1)
        self.assertEqual(result["error"], "invalid_input")
        self.assertIn("valid UTF-8 JSON", result["message"])

    def test_personal_report_retains_immutable_advice_when_render_fails(self) -> None:
        from tests.test_advice import advice_setup

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, mapping, metadata, draft, encounter_profile, specialization_profile = advice_setup(root)
            workflow = comparison_ready_workflow(
                root, refs["personal_analysis"], refs["encounter_benchmark"]
            )
            output = io.StringIO()
            with (
                patch("wcl_raid_coach.__main__._ensure_ability_names", return_value={
                    "mapping_path": str(mapping), "metadata_path": str(metadata), "build": "12.1.0.69587",
                }),
                patch("wcl_raid_coach.__main__.render_report_document", side_effect=InputError("render failed")),
                patch("wcl_raid_coach.personal_workflow.validate_comparison_workflow"),
                redirect_stdout(output),
            ):
                status = main([
                    "--data-root", str(root / "data"), "--cache-root", str(root / "cache"),
                    "coach", "personal-report", str(refs["personal_analysis"]), str(refs["encounter_benchmark"]),
                    str(refs["comparison"]), "--workflow", str(workflow), "--advice", str(draft),
                    "--encounter-profile", str(encounter_profile), "--specialization-profile", str(specialization_profile),
                ])
            result = json.loads(output.getvalue())
            advice_dir = root / "data" / "outputs" / "advice"
            self.assertEqual(status, 1)
            self.assertEqual(result["message"], "render failed")
            artifacts = list(advice_dir.glob("*.json"))
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(json.loads(artifacts[0].read_text(encoding="utf-8"))["artifact_type"], "coaching_advice")


if __name__ == "__main__":
    unittest.main()
