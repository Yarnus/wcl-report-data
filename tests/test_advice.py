from __future__ import annotations

import json
import hashlib
import gzip
import io
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch

from tests.test_report_documents import personal_document
from wcl_raid_coach.advice import create_coaching_advice, verify_coaching_advice
from wcl_raid_coach.analysis import analyze_player
from wcl_raid_coach.cohort import build_benchmark, identify_benchmark, identify_cohort
from wcl_raid_coach.comparison import compare_player
from wcl_raid_coach.errors import InputError
from wcl_raid_coach.report_documents import (
    assemble_partial_personal_review_document,
    assemble_personal_review_document,
    render_report_document,
)
from wcl_raid_coach.profiles import validate_profile
from wcl_raid_coach.personal_workflow import (
    finalize_personal_review_delivery,
    initialize_personal_review,
    orchestrate_personal_review,
)
from wcl_raid_coach.storage import sha256_file


def advice_setup(root: Path) -> tuple[dict[str, Path], Path, Path, Path, Path, Path]:
    document = personal_document(root)
    refs = {item["kind"]: Path(item["path"]) for item in document["source_artifacts"]}
    analysis = json.loads(refs["personal_analysis"].read_text(encoding="utf-8"))
    benchmark = json.loads(refs["encounter_benchmark"].read_text(encoding="utf-8"))
    encounter_profile = validate_profile({
        "kind": "encounter", "identity": {"game_version": "12.1", "partition_id": 2, "encounter_id": 1007, "difficulty_id": 4},
        "eligibility": {"priority_target_ids": [], "excluded_target_ids": []},
        "phases": [{"id": 1}], "mechanic_anchors": [{"ability_id": 2, "name": "Mechanic"}],
        "sources": [],
    } | {"sources": [{
        "title": "Current encounter guide", "url": "https://example.com/encounter", "accessed_at": "2026-09-07T00:00:00+00:00",
        "quote_summary": "Keep the selected action aligned with the mechanic window.", "content_hash": "c" * 64,
    }]})
    specialization_profile = validate_profile({
        "kind": "specialization", "identity": {"game_version": "12.1", "partition_id": 2, "class_name": "DeathKnight", "spec_name": "Unholy"},
        "abilities": [{"id": 2, "action_type": "player_cast"}], "resources": [{}], "cooldown_relationships": [{}], "role_guardrails": [{}],
        "sources": [{
                "title": "Current specialization guide",
                "url": "https://example.com/current-guide",
                "accessed_at": "2026-09-07T00:00:00+00:00",
                "quote_summary": "Keep the selected cooldown aligned with useful uptime.",
                "content_hash": "a" * 64,
            }],
    })
    benchmark |= {
        "encounter_profile_id": encounter_profile["profile_id"],
        "specialization_profile_id": specialization_profile["profile_id"],
        "sources": {"encounter": encounter_profile["sources"], "specialization": specialization_profile["sources"]},
    }
    benchmark = identify_benchmark(benchmark)
    comparison = compare_player(analysis, benchmark)
    refs["encounter_benchmark"].write_text(json.dumps(benchmark), encoding="utf-8")
    refs["comparison"].write_text(json.dumps(comparison), encoding="utf-8")
    mapping_path = refs["ability_names"]
    mapping_path.write_text(json.dumps({"2": "本地化技能"}), encoding="utf-8")
    metadata_path = refs["ability_names_metadata"]
    metadata_path.write_text(json.dumps({
        "build": "12.1.0.69587", "mapping_sha256": sha256_file(mapping_path),
    }), encoding="utf-8")
    draft = {
        "schema_version": 2,
        "locale": "zh-CN",
        "items": [{
            "dimension": "output",
            "evidence_class": "experience_based",
            "action": {"kind": "use_ability", "ability_id": 2},
            "conditions": ["effective_window", "mechanic_safe"],
            "verification_goal": "check_ability_usage",
            "ability_ids": [2],
            "fact_references": [{
                "source": "personal_analysis", "path": "/metrics/damage_total", "value": 150,
            }],
            "guidance_references": [{"profile_kind": "specialization", "source_index": 0}],
        }],
    }
    draft_path = root / "advice-draft.json"
    draft_path.write_text(json.dumps(draft), encoding="utf-8")
    encounter_path = root / "encounter-profile.json"
    specialization_path = root / "specialization-profile.json"
    encounter_path.write_text(json.dumps(encounter_profile), encoding="utf-8")
    specialization_path.write_text(json.dumps(specialization_profile), encoding="utf-8")
    return refs, mapping_path, metadata_path, draft_path, encounter_path, specialization_path


def workflow_origin(analysis_path: Path, output_dir: Path) -> Path:
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    result = initialize_personal_review(
        analysis["identity"]["report_code"], analysis["identity"]["fight_id"],
        analysis["player"]["actor_id"], output_dir,
    )
    return Path(result["workflow_path"])


def real_complete_bundle_analysis(root: Path, fight_id: int) -> tuple[Path, dict]:
    from tests.test_analysis import AnalysisTests

    manifest_path, index_path = AnalysisTests().make_bundle(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["fights"][0] |= {
        "fight_id": fight_id, "name": "石棺哨兵", "kill": False, "boss_percentage": 32.7,
    }
    index["abilities"].append({"gameID": 2, "name": "Interrupt", "type": 1, "icon": "spell"})
    index_path.write_text(json.dumps(index), encoding="utf-8")

    events_path = manifest_path.parent / manifest["events_file"]
    with gzip.open(events_path, "rt", encoding="utf-8") as handle:
        events = [json.loads(line) for line in handle]
    events = [event for event in events if event["type"] != "death"]
    canonical = "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events).encode()
    with gzip.open(events_path, "wb") as handle:
        handle.write(canonical)
    raw_path = Path(manifest["raw_pages"][0]["path"])
    with gzip.open(raw_path, "wt", encoding="utf-8") as handle:
        json.dump({"data": events, "nextPageTimestamp": None}, handle)
    manifest["identity"]["fight_id"] = fight_id
    manifest["event_count"] = len(events)
    manifest["canonical_events_sha256"] = hashlib.sha256(canonical).hexdigest()
    manifest["events_file_sha256"] = hashlib.sha256(events_path.read_bytes()).hexdigest()
    manifest["raw_pages"][0] |= {
        "events": len(events), "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
    }
    manifest["report_index_sha256"] = hashlib.sha256(
        json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    analysis = analyze_player(manifest_path, index_path, 10, partition_id=2)
    analysis_path = root / "analysis.json"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
    return analysis_path, analysis


class AdviceTests(unittest.TestCase):
    def test_local_selected_player_delivery_uses_three_complete_reference_bundles(self) -> None:
        from wcl_raid_coach.__main__ import main

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, _, _, encounter_profile, specialization_profile = advice_setup(root)
            target_path, target = real_complete_bundle_analysis(root / "target", 7)
            reference_paths = []
            reference_analyses = []
            for fight_id in (8, 9, 10):
                path, value = real_complete_bundle_analysis(root / f"reference-{fight_id}", fight_id)
                reference_paths.append(path)
                reference_analyses.append(value)

            cohort = identify_cohort({
                "schema_version": 2,
                "filters": target["comparison_identity"],
                "pagination": {
                    "first_page": 1, "last_page": 1,
                    "has_more_pages": False, "truncated": False, "exhausted": True,
                },
                "eligible_recent_candidates": [
                    {"report_code": value["identity"]["report_code"], "fight_id": value["identity"]["fight_id"], "source_id": 10}
                    for value in reference_analyses
                ],
                "unverified_recency_candidates": [], "rejected_candidates": [],
            })
            cohort_path = root / "cohort.json"
            cohort_path.write_text(json.dumps(cohort), encoding="utf-8")
            data_root = root / "data"
            mapping_path = data_root / "ability-names.zhCN.json"
            mapping_path.parent.mkdir(parents=True)
            mapping_path.write_text(json.dumps({"2": "本地化技能"}), encoding="utf-8")
            (data_root / "ability-names.zhCN.meta.json").write_text(json.dumps({
                "locale": "zhCN", "source": "https://wago.tools/db2/SpellName/csv?locale=zhCN",
                "source_file": "SpellName.12.1.0.69587.csv", "source_sha256": "a" * 64,
                "source_row_count": 400000, "build": "12.1.0.69587", "ability_count": 1,
                "mapping_sha256": sha256_file(mapping_path),
            }), encoding="utf-8")
            workflow = orchestrate_personal_review(
                target_path, cohort_path, encounter_profile, specialization_profile, data_root / "outputs",
                reference_analysis_paths=reference_paths, benchmark_paths=[],
                candidate_rejections=[], blockers=[],
                previous_workflow_path=workflow_origin(target_path, data_root / "outputs"),
            )
            workflow_value = workflow["workflow"]
            benchmark_path = Path(workflow_value["artifacts"]["encounter_benchmark"]["path"])
            benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
            comparison_path = root / "comparison.json"
            comparison_path.write_text(json.dumps(compare_player(target, benchmark)), encoding="utf-8")

            draft = json.loads((root / "advice-draft.json").read_text(encoding="utf-8"))
            draft["items"] = [
                {
                    "dimension": "output", "evidence_class": "event_supported",
                    "action": {"kind": "review_fact", "ability_id": None},
                    "conditions": ["effective_window"], "verification_goal": "compare_next_attempt",
                    "ability_ids": [], "fact_references": [{
                        "source": "personal_analysis", "path": "/metrics/damage_total", "value": target["metrics"]["damage_total"],
                    }], "guidance_references": [],
                },
                {
                    "dimension": "survival", "evidence_class": "event_supported",
                    "action": {"kind": "review_fact", "ability_id": None},
                    "conditions": ["mechanic_safe"], "verification_goal": "check_event_fact",
                    "ability_ids": [], "fact_references": [{
                        "source": "personal_analysis", "path": "/metrics/deaths", "value": target["metrics"]["deaths"],
                    }], "guidance_references": [],
                },
                {
                    "dimension": "mechanics", "evidence_class": "experience_based",
                    "action": {"kind": "use_ability", "ability_id": 2},
                    "conditions": ["mechanic_safe", "next_attempt"], "verification_goal": "check_ability_usage",
                    "ability_ids": [2], "fact_references": [],
                    "guidance_references": [{"profile_kind": "encounter", "source_index": 0}],
                },
                {
                    "dimension": "team_contribution", "evidence_class": "event_supported",
                    "action": {"kind": "review_fact", "ability_id": None},
                    "conditions": ["target_available"], "verification_goal": "check_event_fact",
                    "ability_ids": [], "fact_references": [{
                        "source": "personal_analysis", "path": "/metrics/interrupts", "value": target["metrics"]["interrupts"],
                    }], "guidance_references": [],
                },
            ]
            draft_path = root / "full-advice-draft.json"
            draft_path.write_text(json.dumps(draft), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                status = main([
                    "--data-root", str(data_root), "--cache-root", str(root / "cache"),
                    "coach", "personal-report", str(target_path), str(benchmark_path), str(comparison_path),
                    "--workflow", str(workflow["workflow_path"]), "--advice", str(draft_path),
                    "--encounter-profile", str(encounter_profile),
                    "--specialization-profile", str(specialization_profile), "--locale", "zh-CN",
                ])
            result = json.loads(output.getvalue())
            self.assertEqual(status, 0, result)
            html = Path(result["report"]["html_path"]).read_text(encoding="utf-8")
            report_index = json.loads(Path(result["report"]["index_path"]).read_text(encoding="utf-8"))
            reuse = orchestrate_personal_review(
                target_path, cohort_path, encounter_profile, specialization_profile, data_root / "outputs",
                reference_analysis_paths=[], benchmark_paths=[benchmark_path],
                candidate_rejections=[], blockers=[],
                previous_workflow_path=Path(workflow["workflow_path"]),
            )["workflow"]
            workflow_index = json.loads(
                (data_root / "outputs" / "personal-workflows" / "index.json").read_text(encoding="utf-8")
            )
            delivery_path = Path(result["delivery"]["path"])
            finalization = json.loads(delivery_path.read_text(encoding="utf-8"))
            delivery_artifact = json.loads(
                Path(finalization["delivery"]["path"]).read_text(encoding="utf-8")
            )

            self.assertEqual(status, 0)
            self.assertEqual(workflow_value["completion_state"], "comparison_ready")
            self.assertEqual(workflow_value["qualified_reference_samples"], 3)
            self.assertEqual(
                workflow_value["clock"]["clock_source"],
                "local_monotonic_and_wall_clock",
            )
            self.assertEqual(len(result["document"]["advice"]), 4)
            self.assertEqual(
                {item["dimension"] for item in result["document"]["advice"]},
                {"output", "survival", "mechanics", "team_contribution"},
            )
            self.assertEqual(
                {item["kind"] for item in result["document"]["source_artifacts"]},
                {
                    "personal_analysis", "encounter_benchmark", "comparison",
                    "personal_review_workflow",
                    "ability_names", "ability_names_metadata", "coaching_advice",
                },
            )
            self.assertIn(workflow_value["workflow_id"], workflow_index["artifacts"])
            self.assertEqual(
                workflow_value["artifacts"]["ranking_cohort"]["path"], str(cohort_path.resolve())
            )
            self.assertEqual(
                workflow_value["artifacts"]["encounter_profile"]["path"], str(encounter_profile.resolve())
            )
            self.assertEqual(
                workflow_value["artifacts"]["specialization_profile"]["path"],
                str(specialization_profile.resolve()),
            )
            advice_sources = json.loads(
                Path(result["advice"]["path"]).read_text(encoding="utf-8")
            )["source_artifacts"]
            self.assertEqual(
                {
                    "personal_analysis", "encounter_benchmark", "comparison",
                    "encounter_profile", "specialization_profile",
                },
                set(advice_sources),
            )
            self.assertEqual(result["delivery"]["artifact"]["status"], "delivered")
            self.assertTrue(result["delivery"]["artifact"]["timing"]["continuity_available"])
            self.assertEqual(
                result["delivery"]["artifact"]["timing"]["clock_source"],
                "local_monotonic_and_wall_clock",
            )
            self.assertEqual(
                finalization["artifact_type"], "personal_review_delivery_finalization"
            )
            self.assertEqual(
                finalization["delivery"]["sha256"],
                sha256_file(Path(finalization["delivery"]["path"])),
            )
            self.assertEqual(
                delivery_artifact["timing"]["measured_through"],
                "rendered_html_and_index_verified",
            )
            self.assertEqual(
                finalization["timing"]["measured_through"],
                "rendered_html_index_and_delivery_artifact_persisted",
            )
            self.assertEqual(finalization["stage_progress"]["agent_synthesis"], "unavailable")
            self.assertIsNone(finalization["timing"]["target_met"])
            self.assertEqual(report_index["render"]["html_sha256"], sha256_file(Path(result["report"]["html_path"])))
            self.assertEqual(report_index["render"]["html_file"], Path(result["report"]["html_path"]).name)
            self.assertNotIn("<script src=", html)
            self.assertNotIn("<link rel=", html)
            self.assertIn('id="dimension-output"', html)
            self.assertIn('id="dimension-survival"', html)
            self.assertIn('id="dimension-mechanics"', html)
            self.assertIn('id="dimension-team_contribution"', html)
            self.assertTrue(reuse["benchmark_reused"])
            self.assertEqual(reuse["budget"]["target_seconds"], 30.0)

    def test_integrated_advice_covers_all_four_dimensions_in_final_html(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, mapping, metadata, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            analysis = json.loads(refs["personal_analysis"].read_text(encoding="utf-8"))
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["items"] = [
                {
                    "dimension": "output",
                    "evidence_class": "event_supported",
                    "action": {"kind": "review_fact", "ability_id": None},
                    "conditions": ["effective_window"],
                    "verification_goal": "compare_next_attempt",
                    "ability_ids": [],
                    "fact_references": [{
                        "source": "personal_analysis", "path": "/metrics/damage_total",
                        "value": analysis["metrics"]["damage_total"],
                    }],
                    "guidance_references": [],
                },
                {
                    "dimension": "survival",
                    "evidence_class": "event_supported",
                    "action": {"kind": "review_fact", "ability_id": None},
                    "conditions": ["mechanic_safe"],
                    "verification_goal": "check_event_fact",
                    "ability_ids": [],
                    "fact_references": [{
                        "source": "personal_analysis", "path": "/metrics/deaths",
                        "value": analysis["metrics"]["deaths"],
                    }],
                    "guidance_references": [],
                },
                {
                    "dimension": "mechanics",
                    "evidence_class": "experience_based",
                    "action": {"kind": "use_ability", "ability_id": 2},
                    "conditions": ["mechanic_safe", "next_attempt"],
                    "verification_goal": "check_ability_usage",
                    "ability_ids": [2],
                    "fact_references": [],
                    "guidance_references": [{"profile_kind": "encounter", "source_index": 0}],
                },
                {
                    "dimension": "team_contribution",
                    "evidence_class": "event_supported",
                    "action": {"kind": "review_fact", "ability_id": None},
                    "conditions": ["target_available"],
                    "verification_goal": "check_event_fact",
                    "ability_ids": [],
                    "fact_references": [{
                        "source": "personal_analysis", "path": "/metrics/interrupts",
                        "value": analysis["metrics"]["interrupts"],
                    }],
                    "guidance_references": [],
                },
            ]
            advice = create_coaching_advice(
                draft, refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                root / "advice", encounter_profile, specialization_profile,
            )
            with patch("wcl_raid_coach.personal_workflow.validate_comparison_workflow"):
                document = assemble_personal_review_document(
                    refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                    workflow_path=refs["personal_review_workflow"],
                    workflow_registry_dir=root / "outputs" / "personal-workflows",
                    ability_names_path=mapping, ability_names_metadata_path=metadata,
                    advice_path=Path(advice["path"]), locale="zh-CN",
                )
                report = render_report_document(document, root / "outputs" / "reports", workflow_registry_dir=root / "outputs" / "personal-workflows")
            html = Path(report["html_path"]).read_text(encoding="utf-8")

        self.assertEqual(
            {item["dimension"] for item in document["advice"]},
            {"output", "survival", "mechanics", "team_contribution"},
        )
        self.assertIn("输出", html)
        self.assertIn("生存", html)
        self.assertIn("机制", html)
        self.assertIn("团队贡献", html)
        self.assertIn("经验性且有条件", html)

    def test_partial_delivery_with_one_qualified_reference_has_no_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, mapping, metadata, _, encounter_profile, specialization_profile = advice_setup(root)
            analysis = json.loads(refs["personal_analysis"].read_text(encoding="utf-8"))
            manifest_path = Path(analysis["evidence"]["manifest_path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            events_path = manifest_path.parent / manifest["events_file"]
            with gzip.open(events_path, "rt", encoding="utf-8") as handle:
                events = []
                for line in handle:
                    event = json.loads(line)
                    if event["type"] != "death":
                        events.append(event)
            canonical = "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events).encode()
            with gzip.open(events_path, "wb") as handle:
                handle.write(canonical)
            raw_path = Path(manifest["raw_pages"][0]["path"])
            with gzip.open(raw_path, "wt", encoding="utf-8") as handle:
                json.dump({"data": events, "nextPageTimestamp": None}, handle)
            manifest["event_count"] = len(events)
            manifest["canonical_events_sha256"] = hashlib.sha256(canonical).hexdigest()
            manifest["events_file_sha256"] = hashlib.sha256(events_path.read_bytes()).hexdigest()
            manifest["raw_pages"][0] |= {
                "events": len(events), "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            analysis = analyze_player(
                manifest_path, Path(analysis["evidence"]["index_path"]), analysis["player"]["actor_id"],
                partition_id=analysis["comparison_identity"]["partition_id"],
            )
            refs["personal_analysis"].write_text(json.dumps(analysis), encoding="utf-8")
            cohort = identify_cohort({
                "schema_version": 2,
                "filters": analysis["comparison_identity"],
                "pagination": {"exhausted": False},
                "eligible_recent_candidates": [{
                    "report_code": analysis["identity"]["report_code"],
                    "fight_id": analysis["identity"]["fight_id"],
                    "source_id": analysis["player"]["actor_id"],
                }],
                "unverified_recency_candidates": [], "rejected_candidates": [],
            })
            cohort_path = root / "cohort.json"
            cohort_path.write_text(json.dumps(cohort), encoding="utf-8")
            workflow = orchestrate_personal_review(
                refs["personal_analysis"], cohort_path, encounter_profile, specialization_profile,
                root / "outputs", reference_analysis_paths=[refs["personal_analysis"]],
                benchmark_paths=[], candidate_rejections=[], blockers=[],
                previous_workflow_path=workflow_origin(refs["personal_analysis"], root / "outputs"),
            )
            document = assemble_partial_personal_review_document(
                refs["personal_analysis"], encounter_profile, specialization_profile,
                workflow_path=Path(workflow["workflow_path"]), ability_names_path=mapping,
                workflow_registry_dir=root / "outputs" / "personal-workflows",
                ability_names_metadata_path=metadata, locale="zh-CN",
            )
            report = render_report_document(document, root / "outputs" / "reports", workflow_registry_dir=root / "outputs" / "personal-workflows")
            delivery = finalize_personal_review_delivery(
                Path(workflow["workflow_path"]), report, root / "outputs",
            )

        self.assertEqual(workflow["workflow"]["completion_state"], "partial_ready")
        self.assertEqual(document["comparison"], {
            "status": "unavailable", "reason": "insufficient_reference_samples",
            "qualified_sample_count": 1,
        })
        self.assertNotIn("encounter_benchmark", {item["kind"] for item in document["source_artifacts"]})
        self.assertEqual(delivery["artifact"]["status"], "delivered")

    def test_partial_review_uses_direct_profile_provenance_without_a_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, mapping, metadata, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            advice = create_coaching_advice(
                json.loads(draft_path.read_text(encoding="utf-8")), refs["personal_analysis"],
                None, None, root / "advice", encounter_profile, specialization_profile,
            )
            analysis = json.loads(refs["personal_analysis"].read_text(encoding="utf-8"))
            cohort = identify_cohort({
                "schema_version": 2, "filters": analysis["comparison_identity"],
                "pagination": {
                    "first_page": 1, "last_page": 1,
                    "has_more_pages": False, "truncated": False, "exhausted": True,
                }, "eligible_recent_candidates": [],
            })
            cohort_path = root / "cohort.json"
            cohort_path.write_text(json.dumps(cohort), encoding="utf-8")
            workflow = orchestrate_personal_review(
                refs["personal_analysis"], cohort_path, encounter_profile, specialization_profile,
                root / "outputs", reference_analysis_paths=[], benchmark_paths=[],
                candidate_rejections=[], blockers=[],
                previous_workflow_path=workflow_origin(refs["personal_analysis"], root / "outputs"),
            )
            document = assemble_partial_personal_review_document(
                refs["personal_analysis"], encounter_profile, specialization_profile,
                workflow_path=Path(workflow["workflow_path"]), ability_names_path=mapping,
                workflow_registry_dir=root / "outputs" / "personal-workflows",
                ability_names_metadata_path=metadata, advice_path=Path(advice["path"]),
                locale="zh-CN",
            )
            report = render_report_document(document, root / "outputs" / "reports", workflow_registry_dir=root / "outputs" / "personal-workflows")
            delivery = finalize_personal_review_delivery(
                Path(workflow["workflow_path"]), report, root / "outputs"
            )
            html = Path(report["html_path"]).read_text(encoding="utf-8")
            forged = dict(workflow["workflow"])
            forged.pop("workflow_id")
            forged["qualified_reference_samples"] = 1
            forged["workflow_id"] = hashlib.sha256(json.dumps(
                forged, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()
            forged_dir = root / "external" / "personal-workflows"
            forged_dir.mkdir(parents=True)
            forged_path = forged_dir / f'{forged["workflow_id"]}.json'
            forged_path.write_text(json.dumps(forged), encoding="utf-8")
            forged_ref = {"path": str(forged_path.resolve()), "sha256": sha256_file(forged_path)}
            (forged_dir / "index.json").write_text(json.dumps({
                "schema_version": 1,
                "artifact_type": "personal_review_workflow_index",
                "artifacts": {forged["workflow_id"]: forged_ref},
            }), encoding="utf-8")
            with self.assertRaisesRegex(InputError, "workflow path does not match its content ID"):
                assemble_partial_personal_review_document(
                    refs["personal_analysis"], encounter_profile, specialization_profile,
                    workflow_path=forged_path, ability_names_path=mapping,
                    workflow_registry_dir=root / "outputs" / "personal-workflows",
                    ability_names_metadata_path=metadata, locale="zh-CN",
                )

        self.assertEqual(document["comparison"], {
            "status": "unavailable", "reason": "insufficient_reference_samples",
            "qualified_sample_count": 0,
        })
        self.assertNotIn("encounter_benchmark", {item["kind"] for item in document["source_artifacts"]})
        self.assertIn("未聚合 Encounter Benchmark", html)
        self.assertEqual(delivery["artifact"]["status"], "delivered")
        self.assertIsNone(delivery["target_met"])

    def test_comparison_ready_review_renders_and_finalizes_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, mapping, metadata, _, _, _ = advice_setup(root)
            artifact_refs = {
                kind: {"path": str(refs[kind].resolve()), "sha256": sha256_file(refs[kind])}
                for kind in ("personal_analysis", "encounter_benchmark")
            }
            artifact_refs |= {
                "requested_personal_analysis_path": str(refs["personal_analysis"].resolve()),
                "ranking_cohort": None,
                "encounter_profile": None,
                "specialization_profile": None,
                "reference_analyses": [],
                "benchmark_reference_evidence": [],
                "previous_workflow": None,
                "progress": [],
            }
            workflow_body = {
                "schema_version": 2,
                "artifact_type": "personal_review_workflow",
                "selected_identity": {"report_code": "ABC", "fight_id": 7, "actor_id": 10},
                "workflow_started_monotonic_seconds": 10.0,
                "clock": {
                    "wall_minus_monotonic_seconds": 1_000_000.0,
                    "session_marker": hashlib.sha256(b"1000000").hexdigest()[:16],
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
                "stage_timings_seconds": {"selection": 0.1, "player_evidence": 0.1},
                "stage_progress": {
                    "retrieval": "completed", "agent_synthesis": "in_progress",
                    "validation": "pending", "rendering": "pending",
                },
                "artifacts": artifact_refs,
                "benchmark_reused": False,
            }
            workflow_id = hashlib.sha256(json.dumps(
                workflow_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()
            workflow = workflow_body | {"workflow_id": workflow_id}
            workflow_dir = (root / "outputs" / "personal-workflows").resolve()
            workflow_dir.mkdir(parents=True)
            workflow_path = workflow_dir / f"{workflow_id}.json"
            workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
            workflow_ref = {"path": str(workflow_path), "sha256": sha256_file(workflow_path)}
            (workflow_dir / "index.json").write_text(json.dumps({
                "schema_version": 1,
                "artifact_type": "personal_review_workflow_index",
                "artifacts": {workflow_id: workflow_ref},
            }), encoding="utf-8")

            with (
                patch("wcl_raid_coach.personal_workflow.validate_comparison_workflow"),
            ):
                document = assemble_personal_review_document(
                    refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                    workflow_path=workflow_path, ability_names_path=mapping,
                    workflow_registry_dir=root / "outputs" / "personal-workflows",
                    ability_names_metadata_path=metadata, locale="zh-CN",
                )
                report = render_report_document(document, root / "outputs" / "reports", workflow_registry_dir=root / "outputs" / "personal-workflows")
                delivery = finalize_personal_review_delivery(
                    workflow_path, report, root / "outputs",
                    clock=lambda: 12.0, wall_clock=lambda: 1_000_012.0,
                )
            index = json.loads(Path(report["index_path"]).read_text(encoding="utf-8"))
            workflow_source = next(
                item for item in index["document"]["source_artifacts"]
                if item["kind"] == "personal_review_workflow"
            )
            html_exists = Path(report["html_path"]).is_file()

        self.assertEqual(workflow_source, {"kind": "personal_review_workflow", **workflow_ref})
        self.assertTrue(html_exists)
        self.assertEqual(delivery["artifact"]["completion_status"], "comparison_ready")
        self.assertEqual(delivery["artifact"]["status"], "delivered")

    def test_delivery_replay_reuses_delivery_and_addresses_finalization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, mapping, metadata, _, encounter, specialization = advice_setup(root)
            analysis = json.loads(refs["personal_analysis"].read_text(encoding="utf-8"))
            cohort = identify_cohort({"schema_version": 2, "filters": analysis["comparison_identity"], "pagination": {"first_page": 1, "last_page": 1, "has_more_pages": False, "truncated": False, "exhausted": True}, "eligible_recent_candidates": []})
            cohort_path = root / "cohort.json"
            cohort_path.write_text(json.dumps(cohort), encoding="utf-8")
            workflow = orchestrate_personal_review(refs["personal_analysis"], cohort_path, encounter, specialization, root / "outputs", reference_analysis_paths=[], benchmark_paths=[], candidate_rejections=[], blockers=[], previous_workflow_path=workflow_origin(refs["personal_analysis"], root / "outputs"))
            document = assemble_partial_personal_review_document(refs["personal_analysis"], encounter, specialization, workflow_path=Path(workflow["workflow_path"]), workflow_registry_dir=root / "outputs" / "personal-workflows", ability_names_path=mapping, ability_names_metadata_path=metadata)
            report = render_report_document(document, root / "outputs" / "reports", workflow_registry_dir=root / "outputs" / "personal-workflows")
            timing = {"clock": lambda: 10.0, "wall_clock": lambda: 1_000_000.0}
            first = finalize_personal_review_delivery(Path(workflow["workflow_path"]), report, root / "outputs", **timing)
            second = finalize_personal_review_delivery(Path(workflow["workflow_path"]), report, root / "outputs", **timing)
            self.assertEqual(first["artifact"]["delivery"]["path"], second["artifact"]["delivery"]["path"])
            self.assertEqual(Path(first["path"]).stem, first["artifact"]["finalization_id"])
            finalization_path = Path(first["path"])
            finalization_path.write_text(
                json.dumps(json.loads(finalization_path.read_text(encoding="utf-8"))),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(InputError, "Existing Personal Review delivery finalization"):
                finalize_personal_review_delivery(Path(workflow["workflow_path"]), report, root / "outputs", **timing)

    def test_delivery_rejects_tampered_index_with_stale_document_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, mapping, metadata, _, encounter, specialization = advice_setup(root)
            analysis = json.loads(refs["personal_analysis"].read_text(encoding="utf-8"))
            cohort = identify_cohort({
                "schema_version": 2,
                "filters": analysis["comparison_identity"],
                "pagination": {
                    "first_page": 1, "last_page": 1,
                    "has_more_pages": False, "truncated": False, "exhausted": True,
                },
                "eligible_recent_candidates": [],
            })
            cohort_path = root / "cohort.json"
            cohort_path.write_text(json.dumps(cohort), encoding="utf-8")
            workflow = orchestrate_personal_review(
                refs["personal_analysis"], cohort_path, encounter, specialization,
                root / "outputs", reference_analysis_paths=[], benchmark_paths=[],
                candidate_rejections=[], blockers=[],
                previous_workflow_path=workflow_origin(refs["personal_analysis"], root / "outputs"),
            )
            document = assemble_partial_personal_review_document(
                refs["personal_analysis"], encounter, specialization,
                workflow_path=Path(workflow["workflow_path"]),
                workflow_registry_dir=root / "outputs" / "personal-workflows",
                ability_names_path=mapping, ability_names_metadata_path=metadata,
            )
            report = render_report_document(document, root / "outputs" / "reports", workflow_registry_dir=root / "outputs" / "personal-workflows")
            index_path = Path(report["index_path"])
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["document"]["scope_note"] = "tampered"
            index_path.write_text(json.dumps(index), encoding="utf-8")

            with self.assertRaisesRegex(InputError, "canonical identity"):
                finalize_personal_review_delivery(
                    Path(workflow["workflow_path"]), report, root / "outputs"
                )
            self.assertFalse((root / "outputs" / "personal-deliveries").exists())

    def test_delivery_finalization_failure_retains_immutable_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, mapping, metadata, _, encounter, specialization = advice_setup(root)
            analysis = json.loads(refs["personal_analysis"].read_text(encoding="utf-8"))
            cohort = identify_cohort({"schema_version": 2, "filters": analysis["comparison_identity"], "pagination": {"first_page": 1, "last_page": 1, "has_more_pages": False, "truncated": False, "exhausted": True}, "eligible_recent_candidates": []})
            cohort_path = root / "cohort.json"
            cohort_path.write_text(json.dumps(cohort), encoding="utf-8")
            workflow = orchestrate_personal_review(refs["personal_analysis"], cohort_path, encounter, specialization, root / "outputs", reference_analysis_paths=[], benchmark_paths=[], candidate_rejections=[], blockers=[], previous_workflow_path=workflow_origin(refs["personal_analysis"], root / "outputs"))
            document = assemble_partial_personal_review_document(refs["personal_analysis"], encounter, specialization, workflow_path=Path(workflow["workflow_path"]), workflow_registry_dir=root / "outputs" / "personal-workflows", ability_names_path=mapping, ability_names_metadata_path=metadata)
            report = render_report_document(document, root / "outputs" / "reports", workflow_registry_dir=root / "outputs" / "personal-workflows")
            with patch("wcl_raid_coach.personal_workflow._persist_finalization", side_effect=OSError("write failed")):
                with self.assertRaises(OSError):
                    finalize_personal_review_delivery(Path(workflow["workflow_path"]), report, root / "outputs")
            deliveries = list((root / "outputs" / "personal-deliveries").glob("*.json"))
            self.assertEqual(len(deliveries), 1)
            self.assertEqual(json.loads(deliveries[0].read_text(encoding="utf-8"))["artifact_type"], "personal_review_delivery")

    def test_partial_advice_rejects_fact_source_not_present_in_partial_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, _, _, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["items"][0]["fact_references"][0]["source"] = "encounter_benchmark"
            with self.assertRaisesRegex(InputError, "source is unavailable"):
                create_coaching_advice(
                    draft, refs["personal_analysis"], None, None, root / "advice",
                    encounter_profile, specialization_profile,
                )

    def test_validates_persists_and_renders_sourced_advice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, mapping, metadata, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            result = create_coaching_advice(
                json.loads(draft_path.read_text(encoding="utf-8")),
                refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                root / "outputs" / "advice",
                encounter_profile, specialization_profile,
            )
            with patch("wcl_raid_coach.personal_workflow.validate_comparison_workflow"):
                document = assemble_personal_review_document(
                    refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                    workflow_path=refs["personal_review_workflow"],
                    workflow_registry_dir=root / "outputs" / "personal-workflows",
                    ability_names_path=mapping, ability_names_metadata_path=metadata,
                    advice_path=Path(result["path"]), locale="zh-CN",
                )
                report = render_report_document(document, root / "outputs" / "reports", workflow_registry_dir=root / "outputs" / "personal-workflows")
            html = Path(report["html_path"]).read_text(encoding="utf-8")

        self.assertIn("使用所选技能", html)
        self.assertIn("本地化技能 (Spell 2)", html)
        self.assertIn("Current specialization guide", html)
        self.assertIn("建议正文正确性仍需人工判断", html)

    def test_rejects_altered_fact_reference_and_numeric_prose(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, _, _, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["items"][0]["fact_references"][0]["value"] = 9
            with self.assertRaisesRegex(InputError, "does not match"):
                create_coaching_advice(
                    draft, refs["personal_analysis"], refs["encounter_benchmark"],
                    refs["comparison"], root / "advice", encounter_profile, specialization_profile,
                )
            draft["items"][0]["fact_references"][0]["value"] = 150
            draft["items"][0]["action"] = "Cast this 2 times."
            with self.assertRaisesRegex(InputError, "action"):
                create_coaching_advice(
                    draft, refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                    root / "advice", encounter_profile, specialization_profile,
                )

    def test_action_spell_must_be_one_of_the_item_ability_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, _, _, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["items"][0]["action"]["ability_id"] = 999999
            draft["items"][0]["ability_ids"] = [2]
            with self.assertRaisesRegex(InputError, "listed in ability_ids"):
                create_coaching_advice(
                    draft, refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                    root / "advice", encounter_profile, specialization_profile,
                )

    def test_event_supported_advice_rejects_dimension_evidence_exploits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, _, _, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["items"][0] |= {
                "dimension": "mechanics", "evidence_class": "event_supported",
                "action": {"kind": "review_fact", "ability_id": None},
                "ability_ids": [], "guidance_references": [],
            }
            analysis = json.loads(refs["personal_analysis"].read_text(encoding="utf-8"))
            for path, value in (
                ("/identity/report_code", analysis["identity"]["report_code"]),
                ("/metrics/damage_total", analysis["metrics"]["damage_total"]),
            ):
                with self.subTest(path=path):
                    draft["items"][0]["fact_references"] = [{
                        "source": "personal_analysis", "path": path, "value": value,
                    }]
                    with self.assertRaisesRegex(InputError, "Mechanic Review evidence"):
                        create_coaching_advice(
                            draft, refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                            root / "advice", encounter_profile, specialization_profile,
                        )

    def test_event_supported_advice_rejects_unrelated_and_mismatched_ability_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, _, _, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            item = draft["items"][0]
            item["evidence_class"] = "event_supported"
            item["guidance_references"] = []
            item["action"] = {"kind": "review_fact", "ability_id": None}
            item["dimension"] = "survival"
            with self.assertRaisesRegex(InputError, "not eligible for its dimension"):
                create_coaching_advice(
                    draft, refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                    root / "advice", encounter_profile, specialization_profile,
                )

            item["dimension"] = "output"
            item["action"] = {"kind": "use_ability", "ability_id": 2}
            with self.assertRaisesRegex(InputError, "matching ability fact"):
                create_coaching_advice(
                    draft, refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                    root / "advice", encounter_profile, specialization_profile,
                )
            comparison = json.loads(refs["comparison"].read_text(encoding="utf-8"))
            item["fact_references"] = [{
                "source": "comparison", "path": "/metrics/cast_count_deltas/2",
                "value": comparison["metrics"]["cast_count_deltas"]["2"],
            }]
            self.assertEqual(create_coaching_advice(
                draft, refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                root / "advice", encounter_profile, specialization_profile,
            )["artifact"]["items"][0]["action"]["ability_id"], 2)

    def test_ability_actions_require_profile_player_cast_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, _, _, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            profile = json.loads(specialization_profile.read_text(encoding="utf-8"))
            profile.pop("profile_id")
            for kind, ability in (
                ("use_ability", {"id": 3, "name": "Pet attack", "action_type": "owned_actor"}),
                ("observe_pattern", {"id": 123, "name": "Birth", "action_type": "internal"}),
                ("adjust_timing", {"id": 4, "name": "Automatic", "action_type": "automatic"}),
            ):
                with self.subTest(kind=kind, action_type=ability["action_type"]):
                    candidate = validate_profile(profile | {"abilities": [ability]})
                    specialization_profile.write_text(json.dumps(candidate), encoding="utf-8")
                    draft["items"][0]["action"] = {"kind": kind, "ability_id": ability["id"]}
                    draft["items"][0]["ability_ids"] = [ability["id"]]
                    with self.assertRaisesRegex(InputError, "player_cast"):
                        create_coaching_advice(
                            draft, refs["personal_analysis"], None, None, root / "advice",
                            encounter_profile, specialization_profile,
                        )

    def test_all_advice_ability_ids_require_profile_player_cast_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, _, _, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            profile = json.loads(specialization_profile.read_text(encoding="utf-8"))
            profile.pop("profile_id")
            profile["abilities"].append({"id": 123, "name": "Internal", "action_type": "internal"})
            specialization_profile.write_text(
                json.dumps(validate_profile(profile)), encoding="utf-8"
            )
            item = draft["items"][0]
            item["action"] = {"kind": "review_fact", "ability_id": None}
            item["ability_ids"] = [123]
            for evidence_class in ("event_supported", "experience_based"):
                with self.subTest(evidence_class=evidence_class):
                    item["evidence_class"] = evidence_class
                    item["guidance_references"] = (
                        [] if evidence_class == "event_supported"
                        else [{"profile_kind": "specialization", "source_index": 0}]
                    )
                    with self.assertRaisesRegex(InputError, "player_cast"):
                        create_coaching_advice(
                            draft, refs["personal_analysis"], None, None, root / "advice",
                            encounter_profile, specialization_profile,
                        )

    def test_event_supported_ability_action_rejects_owned_aggregate_damage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, _, _, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            analysis = json.loads(refs["personal_analysis"].read_text(encoding="utf-8"))
            profile = json.loads(specialization_profile.read_text(encoding="utf-8"))
            profile.pop("profile_id")
            specialization_profile.write_text(json.dumps(validate_profile(
                profile | {"abilities": [{"id": 3, "name": "Pet attack", "action_type": "player_cast"}]}
            )), encoding="utf-8")
            draft["items"][0] |= {
                "evidence_class": "event_supported",
                "action": {"kind": "use_ability", "ability_id": 3},
                "ability_ids": [3], "guidance_references": [],
                "fact_references": [{
                    "source": "personal_analysis", "path": "/metrics/damage_by_ability/3",
                    "value": analysis["metrics"]["damage_by_ability"]["3"],
                }],
            }
            with self.assertRaisesRegex(InputError, "direct-player"):
                create_coaching_advice(
                    draft, refs["personal_analysis"], None, None, root / "advice",
                    encounter_profile, specialization_profile,
                )

    def test_rejects_missing_zhcn_ability_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, mapping, metadata, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            advice = create_coaching_advice(
                json.loads(draft_path.read_text(encoding="utf-8")),
                refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                root / "advice",
                encounter_profile, specialization_profile,
            )
            mapping.write_text("{}", encoding="utf-8")
            metadata.write_text(json.dumps({
                "build": "12.1.0.69587", "mapping_sha256": sha256_file(mapping),
            }), encoding="utf-8")
            with (
                patch("wcl_raid_coach.personal_workflow.validate_comparison_workflow"),
                self.assertRaisesRegex(InputError, "no zhCN SpellName mapping"),
            ):
                assemble_personal_review_document(
                    refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                    workflow_path=refs["personal_review_workflow"],
                    workflow_registry_dir=root / "outputs" / "personal-workflows",
                    ability_names_path=mapping, ability_names_metadata_path=metadata,
                    advice_path=Path(advice["path"]), locale="zh-CN",
                )

    def test_rejects_modified_persisted_advice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, _, _, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            result = create_coaching_advice(
                json.loads(draft_path.read_text(encoding="utf-8")),
                refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                root / "advice",
                encounter_profile, specialization_profile,
            )
            artifact = result["artifact"] | {"locale": "en"}
            sources = {kind: json.loads(path.read_text(encoding="utf-8")) for kind, path in refs.items() if kind in {
                "personal_analysis", "encounter_benchmark", "comparison",
            }}
            with self.assertRaisesRegex(InputError, "content ID"):
                verify_coaching_advice(artifact, sources)

    def test_reuse_rejects_semantically_equal_noncanonical_advice_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, _, _, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            result = create_coaching_advice(
                draft, refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                root / "advice", encounter_profile, specialization_profile,
            )
            path = Path(result["path"])
            path.write_text(json.dumps(result["artifact"]), encoding="utf-8")

            with self.assertRaisesRegex(InputError, "invalid identity"):
                create_coaching_advice(
                    draft, refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                    root / "advice", encounter_profile, specialization_profile,
                )

    def test_rejects_profile_content_that_does_not_match_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, _, _, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            profile = json.loads(encounter_profile.read_text(encoding="utf-8"))
            profile["sources"][0]["quote_summary"] = "different local content"
            encounter_profile.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(InputError, "Profile"):
                create_coaching_advice(
                    json.loads(draft_path.read_text(encoding="utf-8")),
                    refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                    root / "advice", encounter_profile, specialization_profile,
                )

    def test_rejects_declared_profile_id_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, _, _, encounter_profile, _ = advice_setup(root)
            profile = json.loads(encounter_profile.read_text(encoding="utf-8"))
            profile["profile_id"] = "0" * 64
            encounter_profile.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(InputError, "profile_id"):
                create_coaching_advice(
                    json.loads((root / "advice-draft.json").read_text(encoding="utf-8")),
                    root / "personal-analysis.json", root / "benchmark.json", root / "comparison.json",
                    root / "advice", encounter_profile, root / "specialization-profile.json",
                )

    def test_direct_verification_converts_missing_profile_to_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, _, _, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            result = create_coaching_advice(
                json.loads(draft_path.read_text(encoding="utf-8")), refs["personal_analysis"],
                refs["encounter_benchmark"], refs["comparison"], root / "advice",
                encounter_profile, specialization_profile,
            )
            artifact = result["artifact"]
            artifact["source_artifacts"]["encounter_profile"]["path"] = str(root / "missing-profile.json")
            body = dict(artifact)
            body.pop("advice_id")
            artifact["advice_id"] = hashlib.sha256(
                json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            with self.assertRaisesRegex(InputError, "missing or unreadable"):
                verify_coaching_advice(artifact, {
                    kind: json.loads(refs[kind].read_text(encoding="utf-8"))
                    for kind in ("personal_analysis", "encounter_benchmark", "comparison")
                })

    def test_direct_verification_rejects_malformed_source_containers_as_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            refs, _, _, draft_path, encounter_profile, specialization_profile = advice_setup(root)
            result = create_coaching_advice(
                json.loads(draft_path.read_text(encoding="utf-8")), refs["personal_analysis"],
                refs["encounter_benchmark"], refs["comparison"], root / "advice",
                encounter_profile, specialization_profile,
            )
            valid_sources = {
                kind: json.loads(refs[kind].read_text(encoding="utf-8"))
                for kind in ("personal_analysis", "encounter_benchmark", "comparison")
            }
            malformed_refs = (None, False, 1, [], "bad", {
                kind: [] for kind in result["artifact"]["source_artifacts"]
            })
            for source_artifacts in malformed_refs:
                with self.subTest(source_artifacts=source_artifacts):
                    artifact = json.loads(json.dumps(result["artifact"]))
                    artifact["source_artifacts"] = source_artifacts
                    body = dict(artifact)
                    body.pop("advice_id")
                    artifact["advice_id"] = hashlib.sha256(
                        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest()
                    with self.assertRaises(InputError):
                        verify_coaching_advice(artifact, dict(valid_sources))

            for malformed in (None, False, 1, [], "bad"):
                with self.subTest(source_value=malformed):
                    sources = dict(valid_sources)
                    sources["personal_analysis"] = malformed
                    with self.assertRaises(InputError):
                        verify_coaching_advice(result["artifact"], sources)


if __name__ == "__main__":
    unittest.main()
