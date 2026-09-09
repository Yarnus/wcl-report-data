from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests import test_cohort as cohort_fixtures
from wcl_raid_coach.cohort import build_benchmark, identify_benchmark, identify_cohort
from wcl_raid_coach.errors import InputError
from wcl_raid_coach.__main__ import main
from wcl_raid_coach.personal_workflow import (
    _content_id,
    _persist_content_artifact,
    initialize_personal_review,
    orchestrate_personal_review,
    verify_personal_workflow,
)
from wcl_raid_coach.profiles import validate_profile


class StepClock:
    def __init__(self, step: float = 0.01) -> None:
        self.value = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.value
        self.value += self.step
        return value


class PersonalWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = cohort_fixtures.CohortTests()

    def setup_files(self, root: Path, count: int = 5) -> tuple[Path, Path, Path, Path, list[Path]]:
        analysis = self.helper.analysis({"damage_total": 10, "damage_by_target": {"20": 10}}, suffix="9")
        analysis_path = root / "player.json"
        analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
        encounter = validate_profile(cohort_fixtures.PROFILE)
        specialization = validate_profile(cohort_fixtures.SPEC_PROFILE)
        encounter_path = root / "encounter.json"
        specialization_path = root / "specialization.json"
        encounter_path.write_text(json.dumps(encounter), encoding="utf-8")
        specialization_path.write_text(json.dumps(specialization), encoding="utf-8")
        candidates = [
            {"report_code": f"ABC{i}", "fight_id": i, "source_id": 10}
            for i in range(1, count + 1)
        ]
        cohort = identify_cohort({
            "schema_version": 2, "filters": cohort_fixtures.EXPECTED,
            "pagination": {"exhausted": False},
            "eligible_recent_candidates": candidates,
            "unverified_recency_candidates": [], "rejected_candidates": [],
        })
        cohort_path = root / "cohort.json"
        cohort_path.write_text(json.dumps(cohort), encoding="utf-8")
        references = []
        for index in range(1, count + 1):
            value = self.helper.analysis({
                "deaths": 0, "damage_total": index * 100,
                "damage_by_target": {"20": index * 100}, "casts": {},
            }, suffix=str(index))
            value["evidence"]["manifest_sha256"] = "0" * 64
            value["evidence"]["index_sha256"] = "0" * 64
            path = root / f"reference-{index}.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            references.append(path)
        return analysis_path, cohort_path, encounter_path, specialization_path, references

    def invoke(self, files, root: Path, **kwargs):
        analysis, cohort, encounter, specialization, references = files
        defaults = {
            "reference_analysis_paths": references[:2], "benchmark_paths": [],
            "candidate_rejections": [], "blockers": [], "clock": StepClock(),
        }
        defaults.update(kwargs)
        clock = defaults["clock"]
        defaults.setdefault("wall_clock", lambda: 1_000_000 + clock.value)
        if defaults.get("previous_workflow_path") is None:
            origin = initialize_personal_review(
                "ABC9", 9, 10, root / "outputs",
                clock=clock, wall_clock=defaults["wall_clock"],
            )
            defaults["previous_workflow_path"] = Path(origin["workflow_path"])
        analysis_value = json.loads(analysis.read_text(encoding="utf-8")) if analysis.is_file() else None
        analysis_ref = {
            "path": str(analysis.resolve()),
            "sha256": hashlib.sha256(analysis.read_bytes()).hexdigest(),
        } if analysis.is_file() else None
        with (
            patch("wcl_raid_coach.personal_workflow._optional_analysis", return_value=(analysis_value, analysis_ref)),
            patch("wcl_raid_coach.personal_workflow.verify_analysis_evidence"),
            patch("wcl_raid_coach.personal_workflow.validate_analysis_membership"),
            patch("wcl_raid_coach.personal_workflow._verify_refs_current"),
        ):
            return orchestrate_personal_review(
                analysis, cohort, encounter, specialization, root / "outputs", **defaults
            )

    def test_content_artifact_reuse_requires_exact_canonical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            body = {"schema_version": 1, "artifact_type": "test", "value": 1}
            persisted = _persist_content_artifact(directory, body, "artifact_id", "test artifact")
            path = Path(persisted["path"])
            path.write_text(json.dumps(persisted["artifact"]), encoding="utf-8")

            with self.assertRaisesRegex(InputError, "invalid identity"):
                _persist_content_artifact(directory, body, "artifact_id", "test artifact")

    def test_full_assembly_rejects_reference_evidence_changed_after_workflow(self) -> None:
        from tests.test_advice import advice_setup, real_complete_bundle_analysis
        from wcl_raid_coach.comparison import compare_player
        from wcl_raid_coach.personal_workflow import finalize_personal_review_delivery
        from wcl_raid_coach.report_documents import (
            assemble_personal_review_document,
            render_report_document,
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, mapping, metadata, _, encounter, specialization = advice_setup(root)
            target_path, target = real_complete_bundle_analysis(root / "target", 7)
            references = [
                real_complete_bundle_analysis(root / f"reference-{fight_id}", fight_id)
                for fight_id in (8, 9, 10)
            ]
            cohort = identify_cohort({
                "schema_version": 2,
                "filters": target["comparison_identity"],
                "pagination": {
                    "first_page": 1, "last_page": 1,
                    "has_more_pages": False, "truncated": False, "exhausted": True,
                },
                "eligible_recent_candidates": [
                    {
                        "report_code": value["identity"]["report_code"],
                        "fight_id": value["identity"]["fight_id"],
                        "source_id": value["player"]["actor_id"],
                    }
                    for _, value in references
                ],
                "unverified_recency_candidates": [],
                "rejected_candidates": [],
            })
            cohort_path = root / "cohort.json"
            cohort_path.write_text(json.dumps(cohort), encoding="utf-8")
            workflow = orchestrate_personal_review(
                target_path, cohort_path, encounter, specialization, root / "outputs",
                reference_analysis_paths=[path for path, _ in references], benchmark_paths=[],
                candidate_rejections=[], blockers=[],
                previous_workflow_path=Path(initialize_personal_review(
                    target["identity"]["report_code"], target["identity"]["fight_id"],
                    target["player"]["actor_id"], root / "outputs",
                )["workflow_path"]),
            )
            benchmark_path = Path(workflow["workflow"]["artifacts"]["encounter_benchmark"]["path"])
            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
            comparison_path = root / "comparison.json"
            comparison_path.write_text(json.dumps(compare_player(target, benchmark)), encoding="utf-8")
            document = assemble_personal_review_document(
                target_path, benchmark_path, comparison_path,
                workflow_path=Path(workflow["workflow_path"]),
                workflow_registry_dir=root / "outputs" / "personal-workflows",
                ability_names_path=mapping,
                ability_names_metadata_path=metadata,
            )
            report = render_report_document(
                document, root / "outputs" / "reports",
                workflow_registry_dir=root / "outputs" / "personal-workflows",
            )
            stale_index = Path(references[0][1]["evidence"]["index_path"])
            stale_index.write_text(stale_index.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            with self.assertRaisesRegex(InputError, "changed|hash|provenance"):
                assemble_personal_review_document(
                    target_path, benchmark_path, comparison_path,
                    workflow_path=Path(workflow["workflow_path"]),
                    workflow_registry_dir=root / "outputs" / "personal-workflows",
                    ability_names_path=mapping,
                    ability_names_metadata_path=metadata,
                )
            with self.assertRaisesRegex(InputError, "changed|hash|provenance"):
                render_report_document(
                    document, root / "outputs" / "other-reports",
                    workflow_registry_dir=root / "outputs" / "personal-workflows",
                )
            with self.assertRaisesRegex(InputError, "changed|hash|provenance"):
                finalize_personal_review_delivery(
                    Path(workflow["workflow_path"]), report, root / "outputs"
                )

    def test_builds_after_three_qualified_and_replaces_a_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            rejected = json.loads(files[4][0].read_text(encoding="utf-8"))
            rejected["metrics"]["deaths"] = 1
            files[4][0].write_text(json.dumps(rejected), encoding="utf-8")
            result = self.invoke(files, root, reference_analysis_paths=files[4][:4])["workflow"]
        self.assertEqual(result["completion_state"], "comparison_ready")
        self.assertEqual(result["qualified_reference_samples"], 3)
        self.assertIn("player_death", [item.get("reason") for item in result["candidate_progress"]])

    def test_ten_qualified_samples_are_preserved_by_benchmark_and_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root, count=10)
            clock = StepClock()
            first = self.invoke(files, root, reference_analysis_paths=files[4], clock=clock)
            benchmark_path = Path(first["workflow"]["artifacts"]["encounter_benchmark"]["path"])
            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
            with patch("wcl_raid_coach.personal_workflow.verify_benchmark_for_cohort"):
                second = self.invoke(
                    files, root, reference_analysis_paths=[], clock=clock,
                    previous_workflow_path=Path(first["workflow_path"]),
                )["workflow"]

        self.assertEqual(len(first["workflow"]["artifacts"]["reference_analyses"]), 10)
        self.assertEqual(len(benchmark["reference_samples"]), 10)
        self.assertEqual(benchmark["sample_count"], 10)
        self.assertEqual(benchmark["confidence"], "normal")
        self.assertEqual(len(second["artifacts"]["reference_analyses"]), 10)
        self.assertEqual(second["qualified_reference_samples"], 10)
        self.assertTrue(second["benchmark_reused"])
        self.assertEqual(second["budget"]["target_seconds"], 30.0)
        self.assertLess(second["budget"]["elapsed_seconds"], 30.0)

    def test_workflow_rejects_eleven_qualified_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root, count=11)
            with self.assertRaisesRegex(InputError, "maximum of 10"):
                self.invoke(files, root, reference_analysis_paths=files[4])

    def test_workflow_rejects_malformed_reference_analysis_containers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflow = self.invoke(self.setup_files(root), root)["workflow"]
            for malformed in (None, {}, [None], [{"path": None, "sha256": "a" * 64}]):
                body = dict(workflow)
                body.pop("workflow_id")
                body["artifacts"] = dict(body["artifacts"])
                body["artifacts"]["reference_analyses"] = malformed
                body["workflow_id"] = _content_id(body)
                with self.subTest(malformed=malformed), self.assertRaises(InputError):
                    verify_personal_workflow(body)

    def test_cli_returns_json_input_error_for_null_reference_analyses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            result = self.invoke(files, root)
            body = dict(result["workflow"])
            body.pop("workflow_id")
            body["artifacts"] = dict(body["artifacts"])
            body["artifacts"]["reference_analyses"] = None
            body["workflow_id"] = _content_id(body)
            workflow_path = root / "outputs" / "personal-workflows" / f'{body["workflow_id"]}.json'
            workflow_path.write_text(json.dumps(body), encoding="utf-8")
            workflow_ref = {
                "path": str(workflow_path.resolve()),
                "sha256": hashlib.sha256(workflow_path.read_bytes()).hexdigest(),
            }
            index_path = workflow_path.parent / "index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["artifacts"][body["workflow_id"]] = workflow_ref
            index_path.write_text(json.dumps(index), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                status = main([
                    "--data-root", str(root), "coach", "personal-workflow", str(files[0]),
                    "--cohort", str(files[1]), "--encounter-profile", str(files[2]),
                    "--specialization-profile", str(files[3]),
                    "--previous-workflow", str(workflow_path),
                ])
            response = json.loads(output.getvalue())

        self.assertEqual(status, 1)
        self.assertEqual(response["error"], "invalid_input")

    def test_cli_returns_json_input_error_for_malformed_cohort_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            cohort = json.loads(files[1].read_text(encoding="utf-8"))
            cohort.pop("cohort_id")
            cohort["pagination"] = None
            cohort["cohort_id"] = hashlib.sha256(json.dumps(
                cohort, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()
            files[1].write_text(json.dumps(cohort), encoding="utf-8")
            origin = initialize_personal_review("ABC9", 9, 10, root / "outputs")
            output = io.StringIO()
            with redirect_stdout(output):
                status = main([
                    "--data-root", str(root), "coach", "personal-workflow", str(files[0]),
                    "--cohort", str(files[1]), "--encounter-profile", str(files[2]),
                    "--specialization-profile", str(files[3]),
                    "--previous-workflow", origin["workflow_path"],
                ])
            response = json.loads(output.getvalue())

        self.assertEqual(status, 1)
        self.assertEqual(response["error"], "invalid_input")

    def test_budget_is_monotonic_and_checked_before_optional_candidate_scheduling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            result = self.invoke(
                files, root, reference_analysis_paths=[], clock=StepClock(60)
            )["workflow"]
        self.assertEqual(result["completion_state"], "partial_ready")
        self.assertIn("budget_exhausted", result["blockers"])
        self.assertIsNone(result["next_ranking_candidate"])
        self.assertGreater(result["budget"]["elapsed_seconds"], 0)
        self.assertGreater(result["stage_timings_seconds"]["selection"], 0)

    def test_scheduling_uses_candidate_identity_not_progress_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            result = self.invoke(
                files, root, reference_analysis_paths=[files[4][0]],
                candidate_rejections=[("ABC3:3:10", "player_death")],
            )["workflow"]
        self.assertEqual(result["next_ranking_candidate"]["report_code"], "ABC2")

    def test_rejections_resume_remaining_candidates_from_same_complete_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root, count=4)
            cohort = json.loads(files[1].read_text(encoding="utf-8"))
            cohort["pagination"] = {
                "first_page": 4, "last_page": 4, "has_more_pages": True,
                "truncated": False, "target_reached": True, "exhausted": False,
            }
            cohort = identify_cohort(cohort)
            files[1].write_text(json.dumps(cohort), encoding="utf-8")
            first = self.invoke(
                files, root, reference_analysis_paths=[],
                candidate_rejections=[("ABC1:1:10", "player_death"), ("ABC2:2:10", "player_death")],
            )
            second = self.invoke(
                files, root, reference_analysis_paths=[],
                candidate_rejections=[("ABC3:3:10", "player_death")],
                previous_workflow_path=Path(first["workflow_path"]),
            )["workflow"]

        self.assertEqual(first["workflow"]["next_ranking_candidate"]["report_code"], "ABC3")
        self.assertEqual(second["next_ranking_candidate"]["report_code"], "ABC4")

    def test_does_not_claim_page_exhaustion_without_cohort_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root, count=2)
            result = self.invoke(files, root)["workflow"]
        self.assertEqual(result["completion_state"], "partial_ready")
        self.assertIn("ranking_cohort_refresh_required", result["blockers"])
        self.assertNotIn("ranking_page_exhausted", result["blockers"])

    def test_missing_player_analysis_preserves_progress_without_bundle_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            files[0].unlink()
            checkpoint = root / "checkpoint.json"
            checkpoint.write_text("{}", encoding="utf-8")
            result = self.invoke(files, root, progress_paths=[checkpoint])["workflow"]
        self.assertEqual(result["completion_state"], "blocked")
        self.assertFalse(result["report_available"])
        self.assertIsNone(result["artifacts"]["personal_analysis"])
        self.assertEqual(result["artifacts"]["progress"][0]["path"], str(checkpoint.resolve()))
        self.assertEqual(result["stage_progress"], {
            "retrieval": "in_progress", "agent_synthesis": "unavailable",
            "validation": "pending", "rendering": "pending",
        })

    def test_initial_workflow_requires_only_selected_identity_and_continuation_includes_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clock = StepClock()
            wall_clock = lambda: 1_000_000 + clock.value
            initial = initialize_personal_review(
                "ABC9", 9, 10, root / "outputs", clock=clock, wall_clock=wall_clock
            )
            self.assertIsNone(initial["workflow"]["artifacts"]["ranking_cohort"])
            self.assertIsNone(initial["workflow"]["artifacts"]["personal_analysis"])
            clock.value = 75
            continued = self.invoke(
                self.setup_files(root), root, reference_analysis_paths=[], clock=clock,
                wall_clock=wall_clock, previous_workflow_path=Path(initial["workflow_path"]),
            )["workflow"]

        self.assertEqual(continued["selected_identity"], {
            "report_code": "ABC9", "fight_id": 9, "actor_id": 10,
        })
        self.assertGreaterEqual(continued["budget"]["elapsed_seconds"], 75)

    def test_continuation_rejects_analysis_for_different_selected_player(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            initial = initialize_personal_review("ABC9", 9, 11, root / "outputs")
            with self.assertRaisesRegex(InputError, "selected WCL Report, Boss Attempt, and player"):
                self.invoke(
                    files, root, reference_analysis_paths=[],
                    previous_workflow_path=Path(initial["workflow_path"]),
                )

    def test_reuse_budget_follows_deep_validated_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            encounter = json.loads(files[2].read_text(encoding="utf-8"))
            specialization = json.loads(files[3].read_text(encoding="utf-8"))
            analyses = [json.loads(path.read_text(encoding="utf-8")) for path in files[4][:3]]
            cohort = json.loads(files[1].read_text(encoding="utf-8"))
            benchmark = identify_benchmark(build_benchmark(
                analyses, encounter, specialization, cohort_fixtures.EXPECTED,
                cohort_id=cohort["cohort_id"],
            ))
            benchmark_path = root / "benchmark.json"
            benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")
            with patch("wcl_raid_coach.personal_workflow.verify_benchmark_for_cohort"):
                result = self.invoke(
                    files, root, reference_analysis_paths=[], benchmark_paths=[benchmark_path]
                )["workflow"]
        self.assertTrue(result["benchmark_reused"])
        self.assertEqual(result["budget"]["target_seconds"], 30.0)

    def test_benchmark_from_another_cohort_cannot_select_reuse_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            encounter = json.loads(files[2].read_text(encoding="utf-8"))
            specialization = json.loads(files[3].read_text(encoding="utf-8"))
            analyses = [json.loads(path.read_text(encoding="utf-8")) for path in files[4][:3]]
            benchmark = identify_benchmark(build_benchmark(
                analyses, encounter, specialization, cohort_fixtures.EXPECTED,
                cohort_id="c" * 64,
            ))
            benchmark_path = root / "other-benchmark.json"
            benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")
            result = self.invoke(
                files, root, reference_analysis_paths=[], benchmark_paths=[benchmark_path]
            )["workflow"]
        self.assertFalse(result["benchmark_reused"])
        self.assertEqual(result["budget"]["target_seconds"], 180.0)

    def test_previous_workflow_keeps_actual_monotonic_budget_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            clock = StepClock()
            first = self.invoke(files, root, reference_analysis_paths=[], clock=clock)
            clock.value = 170
            second = self.invoke(
                files, root, reference_analysis_paths=[], clock=clock,
                previous_workflow_path=Path(first["workflow_path"]),
            )["workflow"]
        self.assertEqual(second["completion_state"], "partial_ready")
        self.assertIn("budget_exhausted", second["blockers"])
        self.assertGreaterEqual(second["budget"]["elapsed_seconds"], 170)

    def test_clock_reset_preserves_progress_but_stops_optional_acquisition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            first_clock = StepClock()
            first_clock.value = 100
            first = self.invoke(
                files, root, reference_analysis_paths=[], clock=first_clock,
                candidate_rejections=[("ABC1:1:10", "player_death")],
            )
            second = self.invoke(
                files, root, reference_analysis_paths=[], clock=StepClock(),
                wall_clock=lambda: 2_000_000,
                previous_workflow_path=Path(first["workflow_path"]),
            )["workflow"]
        self.assertEqual(second["completion_state"], "partial_ready")
        self.assertIn("timing_continuity_unavailable", second["blockers"])
        self.assertEqual(second["candidate_progress"][0]["candidate_id"], "ABC1:1:10")

    def test_api_failure_records_blocker_and_stops_optional_scheduling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            checkpoint = root / "checkpoint.json"
            checkpoint.write_text("{}", encoding="utf-8")
            result = self.invoke(
                files, root, reference_analysis_paths=[], progress_paths=[checkpoint],
                blockers=["wcl_api_failure"],
            )["workflow"]
        self.assertIn("wcl_api_failure", result["blockers"])
        self.assertIsNone(result["next_ranking_candidate"])
        self.assertEqual(result["artifacts"]["progress"][0]["path"], str(checkpoint.resolve()))

    def test_workflow_invocation_timing_includes_workflow_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self.invoke(
                self.setup_files(root), root, reference_analysis_paths=[], clock=StepClock()
            )
        self.assertEqual(result["invocation_timing"]["status"], "measured")
        self.assertEqual(result["workflow"]["clock"]["clock_source"], "deterministic_injected")
        self.assertEqual(result["invocation_timing"]["wcl_network_measurement"], "not_measured")
        self.assertGreater(
            result["invocation_timing"]["elapsed_seconds"],
            result["workflow"]["budget"]["elapsed_seconds"],
        )
        self.assertEqual(result["invocation_timing"]["measured_through"], "workflow_artifact_persisted")

    def test_changed_benchmark_snapshot_is_rejected_before_workflow_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            encounter = json.loads(files[2].read_text(encoding="utf-8"))
            specialization = json.loads(files[3].read_text(encoding="utf-8"))
            cohort = json.loads(files[1].read_text(encoding="utf-8"))
            analyses = [json.loads(path.read_text(encoding="utf-8")) for path in files[4][:3]]
            benchmark = identify_benchmark(build_benchmark(
                analyses, encounter, specialization, cohort_fixtures.EXPECTED,
                cohort_id=cohort["cohort_id"],
            ))
            benchmark_path = root / "benchmark.json"
            benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")

            def mutate(*_args):
                benchmark_path.write_text(json.dumps(benchmark | {"changed": True}), encoding="utf-8")

            with (
                patch("wcl_raid_coach.personal_workflow.verify_benchmark_for_cohort", side_effect=mutate),
                self.assertRaisesRegex(Exception, "changed during workflow validation"),
            ):
                self.invoke(
                    files, root, reference_analysis_paths=[], benchmark_paths=[benchmark_path]
                )

    def test_previous_workflow_requires_registered_canonical_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            first = self.invoke(files, root, reference_analysis_paths=[])
            external = root / "rewritten.json"
            external.write_bytes(Path(first["workflow_path"]).read_bytes())
            with self.assertRaisesRegex(InputError, "registered workflow artifact location"):
                self.invoke(files, root, reference_analysis_paths=[], previous_workflow_path=external)

    def test_previous_workflow_restores_validated_benchmark_and_reuse_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.setup_files(root)
            encounter = json.loads(files[2].read_text(encoding="utf-8"))
            specialization = json.loads(files[3].read_text(encoding="utf-8"))
            cohort = json.loads(files[1].read_text(encoding="utf-8"))
            analyses = [json.loads(path.read_text(encoding="utf-8")) for path in files[4][:3]]
            benchmark = identify_benchmark(build_benchmark(analyses, encounter, specialization, cohort_fixtures.EXPECTED, cohort_id=cohort["cohort_id"]))
            benchmark_path = root / "benchmark.json"
            benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")
            clock = StepClock()
            with patch("wcl_raid_coach.personal_workflow.verify_benchmark_for_cohort"):
                first = self.invoke(files, root, reference_analysis_paths=[], benchmark_paths=[benchmark_path], clock=clock)
                second = self.invoke(files, root, reference_analysis_paths=[], benchmark_paths=[], clock=clock, previous_workflow_path=Path(first["workflow_path"]))["workflow"]
        self.assertTrue(second["benchmark_reused"])
        self.assertEqual(second["budget"]["target_seconds"], 30.0)


if __name__ == "__main__":
    unittest.main()
