from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_analysis
from tests.test_cohort import EXPECTED
from wcl_raid_coach.analysis import analyze_player
from wcl_raid_coach.cohort import identify_benchmark
from wcl_raid_coach.comparison import compare_player
from wcl_raid_coach.errors import InputError
from wcl_raid_coach.guides import create_guide_snapshot
from wcl_raid_coach.report_documents import (
    assemble_personal_review_document,
    create_mechanic_review_report,
    assemble_raid_guide_document,
    render_report_document,
    sanitize_mechanic_review,
    validate_report_document,
)
from wcl_raid_coach.storage import sha256_file


def _write_source(root: Path, name: str, value: object) -> dict[str, str]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": sha256_file(path)}


def mechanic_source() -> dict:
    return {
        "action": "coach_mechanics",
        "selection_required": False,
        "identity": {
            "report_code": "AbC123", "report_revision": 7, "fight_id": 17,
            "encounter_id": 1007, "difficulty_id": 4,
        },
        "boss_attempt": {
            "name_en": "Sarcophagus Sentinel", "name_zh": "石棺哨兵",
            "difficulty": "Heroic", "kill": False, "start_time": 1000,
            "end_time": 343318,
        },
        "ruleset": {
            "version": "2026.09.1", "selection_policy": "latest",
            "sources": ["https://example.com/mechanics"],
        },
        "evidence": {
            "class": "mechanic_evidence_set", "storage": "process_memory",
            "filter_expression": "type = 'damage'", "event_count": 184,
            "page_count": 1, "pagination_terminated": True,
            "report_revision_checked_before_and_after": True,
        },
        "mechanics": [
            {
                "rule_id": "helical", "name_en": "Helical Toxin", "name_zh": "螺旋毒素",
                "validation_status": "verified", "expectation": "Pair safely.",
                "ability_ids": [1284941], "anomaly_detection": "enabled",
                "summary": {"trigger_count": 18, "success_count": 14, "failure_count": 2},
                "anomalies": [
                    {"time_ms": 138440, "event_type": "damage", "ability_id": 1284941,
                     "actor": {"actor_id": 3, "name": "Player 03", "type": "Player"},
                     "raw_event": {"timestamp": 139440, "type": "damage", "abilityGameID": 1284941}}
                ],
            },
            {
                "rule_id": "collapse", "name_en": "Crypt Collapse", "name_zh": "墓穴崩塌",
                "validation_status": "event_pattern_unverified", "expectation": "Review manually.",
                "ability_ids": [2], "anomaly_detection": "event_pattern_unverified",
                "summary": {"trigger_count": 8, "success_count": None, "failure_count": None},
                "anomalies": [],
            },
        ],
        "judgment": None,
        "causal_attribution": None,
    }


def mechanic_document(source_root: Path | None = None) -> dict:
    review = mechanic_source()
    review["phases"] = [
        {"name_en": "Phase one", "name_zh": "阶段一", "start_ms": 0, "end_ms": 120000},
        {"name_en": "Phase two", "name_zh": "阶段二", "start_ms": 120000, "end_ms": 342318},
    ]
    source_value = sanitize_mechanic_review(review)
    source_value["mechanics"][0]["conclusion"]["zh"] = "事件确认异常，但不裁定责任。<img src=x onerror=alert(1)>"
    source = (
        _write_source(source_root, "mechanic-review.json", source_value)
        if source_root is not None else {"path": "/work/mechanic-review.json", "sha256": "a" * 64}
    )
    return {
        "schema_version": 1,
        "document_type": "mechanic_review",
        "locale": "zh-CN",
        "title": "石棺哨兵机制复盘",
        "subtitle": "Heroic Boss Attempt 17",
        "source_artifacts": [
            {
                "kind": "mechanic_review",
                **source,
            }
        ],
        "identity": {
            "report_code": "AbC123",
            "report_revision": 7,
            "fight_id": 17,
            "encounter_name": "石棺哨兵",
            "difficulty_name": "Heroic",
            "duration_ms": 342318,
            "outcome": "wipe",
            "boss_percentage": None,
        },
        "ruleset": {
            "version": "2026.09.1",
            "selection_policy": "latest",
            "sources": ["https://example.com/mechanics"],
        },
        "evidence": {"event_count": 184, "storage": "minimal_excerpts"},
        "phases": [
            {"name": "阶段一", "start_ms": 0, "end_ms": 120000},
            {"name": "阶段二", "start_ms": 120000, "end_ms": 342318},
        ],
        "mechanics": [
            {
                "name": "螺旋毒素",
                "status": "anomaly",
                "trigger_count": 18,
                "success_count": 14,
                "failure_count": 2,
                "description": source_value["mechanics"][0]["conclusion"]["zh"],
                "events": [
                    {
                        "fight_time_ms": 138440,
                        "tone": "danger",
                        "title": "螺旋毒素",
                        "description": "damage 事件支持该结论（ability 1284941）",
                        "participants": ["Player 03"],
                        "evidence_excerpt": {
                            "event_type": "damage",
                            "ability_id": 1284941,
                        },
                    },
                ],
            },
            {
                "name": "墓穴崩塌",
                "status": "unverified",
                "trigger_count": 8,
                "success_count": None,
                "failure_count": None,
                "description": source_value["mechanics"][1]["conclusion"]["zh"],
                "events": [],
            },
        ],
        "actions": [],
        "scope_note": source_value["scope_note"]["zh"],
    }


def personal_document(source_root: Path | None = None) -> dict:
    sources = {
        kind: {"path": f"/work/{kind}.json", "sha256": character * 64}
        for kind, character in (
            ("personal_analysis", "a"), ("encounter_benchmark", "b"), ("comparison", "c"),
            ("ability_names", "d"), ("ability_names_metadata", "e"),
        )
    }
    if source_root is not None:
        manifest, index = test_analysis.AnalysisTests().make_bundle(source_root)
        index_value = json.loads(index.read_text(encoding="utf-8"))
        index_value["fights"][0] |= {
            "name": "石棺哨兵", "kill": False, "boss_percentage": 32.7,
        }
        index.write_text(json.dumps(index_value), encoding="utf-8")
        manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
        manifest_value["report_index_sha256"] = hashlib.sha256(
            json.dumps(index_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        manifest.write_text(json.dumps(manifest_value), encoding="utf-8")
        analysis = analyze_player(manifest, index, 10, partition_id=2)
        benchmark = identify_benchmark({
            "schema_version": 2, "cohort_id": "c" * 64,
            "identity": analysis["comparison_identity"], "sample_count": 3,
            "confidence": "low", "stable_pattern_claims_allowed": True,
            "metrics": {"damage_total_median": 200, "casts_median": {"1": 2},
                        "first_cast_ms_median": {"1": 80}},
        })
        comparison = compare_player(analysis, benchmark)
        sources = {
            "personal_analysis": _write_source(source_root, "personal-analysis.json", analysis),
            "encounter_benchmark": _write_source(source_root, "benchmark.json", benchmark),
            "comparison": _write_source(source_root, "comparison.json", comparison),
        }
        mapping = _write_source(source_root, "ability-names.zhCN.json", {})
        metadata = _write_source(source_root, "ability-names.zhCN.meta.json", {
            "build": "12.1.0.69587", "mapping_sha256": mapping["sha256"],
        })
        sources |= {"ability_names": mapping, "ability_names_metadata": metadata}
    return {
        "schema_version": 1,
        "document_type": "personal_review",
        "locale": "zh-CN",
        "title": "Player · 个人复盘",
        "subtitle": "Complete Bundle 日志事实 + 同条件 Encounter Benchmark",
        "source_artifacts": [
            {"kind": kind, **source} for kind, source in sources.items()
        ],
        "identity": {
            "report_code": "ABC", "report_revision": 1, "fight_id": 7,
            "encounter_name": "石棺哨兵", "difficulty_name": "Heroic",
            "duration_ms": 1000, "outcome": "wipe", "boss_percentage": 32.7,
        },
        "player": {
            "actor_id": 10,
            "name": "Player",
            "class_name": "DeathKnight",
            "spec_name": "Unholy",
            "item_level": None,
            "anonymous": False,
        },
        "comparison": {
            "game_version": "12.1",
            "partition_id": 2,
            "encounter_id": 1007,
            "difficulty_id": 4,
            "class_name": "DeathKnight",
            "spec_name": "Unholy",
            "benchmark_id": benchmark["benchmark_id"] if source_root is not None else "b" * 64,
            "sample_count": 3,
            "confidence": "low",
        },
        "metrics": {
            "damage_total": 150,
            "healing_total": 0,
            "interrupts": 1,
            "deaths": 1,
            "resource_events": 0,
            "damage_total_delta": -50,
        },
        "abilities": [
            {
                "ability_id": 1,
                "name": "Ability",
                "wcl_name": "Ability",
                "ability_names_build": None,
                "player_casts": 1,
                "median_casts": 2.0,
                "player_first_cast_ms": 100,
                "median_first_cast_ms": 80.0,
            }
        ],
        "scope_note": "仅展示已校验日志事实和同硬条件样本比较；不提供机制归因、死亡原因、建议或可实现提升声明。",
    }


def raid_guide_document(source_root: Path | None = None) -> dict:
    snapshot_id = "8f4c" + "0" * 60
    source = {"path": "/work/guide-snapshot.json", "sha256": "a" * 64}
    encounter_profile_id = "e17a" + "0" * 60
    specialization_profile_id = "a94c" + "0" * 60
    if source_root is not None:
        benchmark = identify_benchmark({
            "schema_version": 2, "cohort_id": "c" * 64, "identity": EXPECTED | {"game_version": "12.1"},
            "encounter_profile_id": encounter_profile_id,
            "specialization_profile_id": specialization_profile_id,
            "sources": {"encounter": [{"title": "Source <title>", "url": "https://example.com/encounter", "quote_summary": "机制来源摘要。"}], "specialization": []},
            "sample_count": 3, "confidence": "low", "stable_pattern_claims_allowed": True,
            "mechanic_anchors": [{"ability_id": 1, "name": "Mechanic", "observed_anchor_ms": 18000}],
            "metrics": {"damage_total_median": 266800000, "casts_median": {"1": 1},
                        "first_cast_ms_median": {"1": 1300}, "damage_by_target_median": {"20": 188200000}},
        })
        snapshot = create_guide_snapshot(
            [benchmark], specialization_name="邪恶死亡骑士", output_dir=source_root / "guides",
            ability_names={"1": "亡者大军"}, ability_names_build="12.1.0.69587",
            encounter_names={"1007": {"map_id": 3004, "name_en": "Boss 7", "name_zh": "中文首领七"}},
            content_names_build="12.1.0.69587", content_names_sha256="d" * 64,
        )
        snapshot_id = snapshot["snapshot_id"]
        source = {"path": snapshot["index_path"], "sha256": sha256_file(Path(snapshot["index_path"]))}
    return {
        "schema_version": 1,
        "document_type": "raid_guide",
        "locale": "zh-CN",
        "title": "邪恶死亡骑士高分日志战术手册",
        "subtitle": "按 Boss 隔离的可观察模式与来源审计",
        "source_artifacts": [
            {
                "kind": "guide_snapshot",
                **source,
            }
        ],
        "identity": {
            "game_version": "12.1",
            "partition_id": 2,
            "difficulty_name": "Heroic",
            "class_name": "DeathKnight",
            "spec_name": "Unholy",
        },
        "specialization": "邪恶死亡骑士",
        "snapshot_id": snapshot_id,
        "ability_names_build": "12.1.0.69587",
        "chapters": [
            {
                "encounter_id": 1007,
                "encounter_name": "中文首领七",
                "benchmark_id": benchmark["benchmark_id"] if source_root is not None else "b" * 64,
                "sample_count": 3,
                "confidence": "low",
                "damage_total_median": 266800000.0,
                "abilities": [
                    {"name": "亡者大军", "median_casts": 1.0, "median_first_cast_ms": 1300.0}
                ],
                "target_damage": [{"target_id": 20, "median_amount": 188200000.0}],
                "mechanic_anchors": [
                    {"name": "亡者大军", "observed_anchor_ms": 18000.0}
                ],
                "encounter_profile_id": "e17a" + "0" * 60,
                "specialization_profile_id": "a94c" + "0" * 60,
                "sources": [
                    {
                        "kind": "encounter",
                        "title": "Source <title>",
                        "url": "https://example.com/encounter",
                        "quote_summary": "机制来源摘要。",
                    }
                ],
            }
        ],
        "scope_note": "日志事实不等于官方推荐或可实现提升。",
    }


class ReportDocumentTests(unittest.TestCase):
    def test_assembles_real_shaped_personal_artifacts_through_html_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_document = personal_document(root)
            refs = {item["kind"]: Path(item["path"]) for item in source_document["source_artifacts"]}
            index_path = Path(json.loads(refs["personal_analysis"].read_text(encoding="utf-8"))["evidence"]["index_path"])
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["abilities"].append({"gameID": 2, "name": "Fallback Ability", "type": 1, "icon": "spell"})
            index_path.write_text(json.dumps(index), encoding="utf-8")
            manifest_path = Path(json.loads(refs["personal_analysis"].read_text(encoding="utf-8"))["evidence"]["manifest_path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["report_index_sha256"] = hashlib.sha256(
                json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            analysis = analyze_player(manifest_path, index_path, 10, partition_id=2)
            benchmark = json.loads(refs["encounter_benchmark"].read_text(encoding="utf-8"))
            benchmark["metrics"]["casts_median"]["2"] = 3
            benchmark["metrics"]["first_cast_ms_median"]["2"] = 250
            benchmark = identify_benchmark(benchmark)
            comparison = compare_player(analysis, benchmark)
            refs["personal_analysis"].write_text(json.dumps(analysis), encoding="utf-8")
            refs["encounter_benchmark"].write_text(json.dumps(benchmark), encoding="utf-8")
            refs["comparison"].write_text(json.dumps(comparison), encoding="utf-8")
            mapping_path = refs["ability_names"]
            mapping_path.write_text(json.dumps({"1": "本地化技能"}), encoding="utf-8")
            metadata_path = refs["ability_names_metadata"]
            metadata_path.write_text(json.dumps({
                "build": "12.1.0.69587", "mapping_sha256": sha256_file(mapping_path),
            }), encoding="utf-8")

            document = assemble_personal_review_document(
                refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                ability_names_path=mapping_path,
                ability_names_metadata_path=metadata_path,
                locale="zh-CN",
            )
            result = render_report_document(document, root / "outputs" / "reports")
            report_index = json.loads(Path(result["index_path"]).read_text(encoding="utf-8"))
            html = Path(result["html_path"]).read_text(encoding="utf-8")

            self.assertEqual(document["player"]["actor_id"], 10)
            self.assertEqual(document["comparison"]["benchmark_id"], benchmark["benchmark_id"])
            self.assertEqual(document["comparison"]["game_version"], "12.1")
            self.assertEqual(document["abilities"], [
                {
                    "ability_id": 1, "name": "本地化技能", "wcl_name": "Ability",
                    "ability_names_build": "12.1.0.69587", "player_casts": 1,
                    "median_casts": 2.0, "player_first_cast_ms": 100.0,
                    "median_first_cast_ms": 80.0,
                },
                {
                    "ability_id": 2, "name": "Fallback Ability", "wcl_name": "Fallback Ability",
                    "ability_names_build": None, "player_casts": 0,
                    "median_casts": 3.0, "player_first_cast_ms": None,
                    "median_first_cast_ms": 250.0,
                },
            ])
            self.assertIn("本地化技能", html)
            self.assertIn("Fallback Ability", html)
            self.assertIn("Actor 10", html)
            self.assertIn(benchmark["benchmark_id"][:12], html)
            self.assertIn("Spell 1", html)
            self.assertEqual(report_index["document"], validate_report_document(document))
            self.assertEqual(result, render_report_document(document, root / "outputs" / "reports"))
            serialized = json.dumps(report_index["document"])
            for forbidden in ("recommendation", "advice", "death_cause", "mechanic_attribution", "achievable_improvement"):
                self.assertNotIn(forbidden, serialized)

            changed = json.loads(json.dumps(document))
            changed["abilities"][0]["name"] = "调用方伪造名称"
            with self.assertRaisesRegex(InputError, "ability claims"):
                render_report_document(changed, root / "other-reports")

    def test_personal_assembler_rejects_mismatched_or_malformed_sources(self) -> None:
        mutations = (
            ("personal_analysis", lambda value: value["player"].__setitem__("actor_id", 11), "Actor 11"),
            ("personal_analysis", lambda value: value["identity"].__setitem__("fight_id", 8), "Complete Bundle"),
            ("encounter_benchmark", lambda value: value["identity"].__setitem__("partition_id", 3), "content ID"),
            ("encounter_benchmark", lambda value: value.__setitem__("sample_count", 4), "content ID"),
            ("comparison", lambda value: value["identity"].__setitem__("class_name", "Mage"), "Comparison"),
        )
        for kind, mutate, message in mutations:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source_document = personal_document(root)
                refs = {item["kind"]: Path(item["path"]) for item in source_document["source_artifacts"]}
                value = json.loads(refs[kind].read_text(encoding="utf-8"))
                mutate(value)
                refs[kind].write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaisesRegex(InputError, message):
                    assemble_personal_review_document(
                        refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                        ability_names_path=refs["ability_names"],
                        ability_names_metadata_path=refs["ability_names_metadata"], locale="en",
                    )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_document = personal_document(root)
            refs = {item["kind"]: Path(item["path"]) for item in source_document["source_artifacts"]}
            refs["comparison"].write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(InputError, "valid UTF-8 JSON"):
                assemble_personal_review_document(
                    refs["personal_analysis"], refs["encounter_benchmark"], refs["comparison"],
                    ability_names_path=refs["ability_names"],
                    ability_names_metadata_path=refs["ability_names_metadata"], locale="en",
                )

    def test_completed_review_creates_sanitized_source_document_html_and_index(self) -> None:
        review = mechanic_source()
        review["mechanics"][0]["anomalies"][0]["raw_events"] = [
            {"timestamp": 139440, "type": "damage", "arbitraryWclField": {"secret": True}}
        ]
        review["mechanics"][0]["anomalies"][0]["aura_application_raw_event"] = {
            "timestamp": 130000, "type": "applydebuff"
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = create_mechanic_review_report(review, root, locale="zh-CN")
            source_path = Path(result["source"]["path"])
            source = json.loads(source_path.read_text(encoding="utf-8"))
            index = json.loads(Path(result["report"]["index_path"]).read_text(encoding="utf-8"))
            html = Path(result["report"]["html_path"]).read_text(encoding="utf-8")

            self.assertEqual(source_path.parent, (root / "outputs" / "mechanic-reviews").resolve())
            self.assertEqual(source_path.stem, result["source"]["sha256"])
            self.assertEqual(source["artifact_type"], "mechanic_review")
            self.assertEqual(source["identity"]["report_revision"], 7)
            self.assertEqual(source["mechanics"][0]["counts"], {
                "trigger_count": 18, "success_count": 14, "failure_count": 2,
            })
            self.assertEqual(source["mechanics"][0]["events"][0]["participants"], ["Player 03"])
            self.assertEqual(source["mechanics"][0]["events"][0]["evidence_excerpt"], {
                "event_type": "damage", "ability_id": 1284941,
            })
            serialized = json.dumps(source)
            for forbidden in (
                "raw_event", "raw_events", "aura_application_raw_event",
                "filter_expression", "judgment", "causal_attribution", "arbitraryWclField",
            ):
                self.assertNotIn(forbidden, serialized)
            self.assertEqual(index["document"]["source_artifacts"][0], {
                "kind": "mechanic_review", "path": str(source_path),
                "sha256": result["source"]["sha256"],
            })
            self.assertEqual(index["document"]["document_id"], result["report"]["document_id"])
            self.assertIn("螺旋毒素", html)

            repeated = create_mechanic_review_report(review, root, locale="zh-CN")
            self.assertEqual(result, repeated)

    def test_render_failure_removes_new_mechanic_source_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch(
                "wcl_raid_coach.report_documents.render_report_document",
                side_effect=InputError("render failed"),
            ):
                with self.assertRaisesRegex(InputError, "render failed"):
                    create_mechanic_review_report(mechanic_source(), root, locale="en")

            self.assertFalse((root / "outputs" / "mechanic-reviews").exists())

    def test_renders_content_addressed_self_contained_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "outputs" / "reports"
            result = render_report_document(mechanic_document(Path(temporary)), output_dir)
            html_path = Path(result["html_path"])
            index_path = Path(result["index_path"])
            html = html_path.read_text(encoding="utf-8")
            index = json.loads(index_path.read_text(encoding="utf-8"))

            self.assertEqual(html_path.parent, output_dir.resolve())
            self.assertEqual(hashlib.sha256(html.encode()).hexdigest(), result["html_sha256"])
            self.assertEqual(html_path.stem, result["html_sha256"])
            self.assertEqual(index_path.stem, result["html_sha256"])
            self.assertEqual(index["document"]["document_id"], result["document_id"])
            self.assertEqual(index["render"]["html_sha256"], result["html_sha256"])
            self.assertEqual(index["render"]["renderer_schema_version"], 1)
            self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
            self.assertNotIn("<img src=x", html)
            self.assertNotIn("<script", html.lower())
            self.assertNotIn("<link", html.lower())
            self.assertNotIn("@import", html.lower())

            repeated = render_report_document(mechanic_document(Path(temporary)), output_dir)
            self.assertEqual(result, repeated)

    def test_rejects_unknown_fields_and_nested_evidence(self) -> None:
        document = mechanic_document()
        del document["title"]
        with self.assertRaisesRegex(InputError, "title"):
            validate_report_document(document)

        document = mechanic_document()
        document["judgment"] = "Player 03 failed"
        with self.assertRaisesRegex(InputError, "unexpected field"):
            validate_report_document(document)

        document = mechanic_document()
        document["mechanics"][0]["events"][0]["evidence_excerpt"] = {
            "note": {"type": "damage"}
        }
        with self.assertRaisesRegex(InputError, "scalar"):
            validate_report_document(document)

        document = mechanic_document()
        document["mechanics"][0]["events"][0]["evidence_excerpt"] = {"raw_event": "{}"}
        with self.assertRaisesRegex(InputError, "unsupported field"):
            validate_report_document(document)

    def test_refuses_to_overwrite_a_damaged_render(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "reports"
            result = render_report_document(mechanic_document(Path(temporary)), output_dir)
            Path(result["html_path"]).write_text("damaged", encoding="utf-8")

            with self.assertRaisesRegex(InputError, "invalid identity"):
                render_report_document(mechanic_document(Path(temporary)), output_dir)

    def test_rejects_a_source_artifact_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            document = mechanic_document(Path(temporary))
            document["source_artifacts"][0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(InputError, "source artifact"):
                render_report_document(document, Path(temporary))

    def test_rejects_correctly_hashed_source_kind_substitution_and_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = mechanic_document(root)
            unrelated = _write_source(root, "unrelated.json", {"schema_version": 2, "cohort_id": "c" * 64})
            document["source_artifacts"][0] |= unrelated
            with self.assertRaisesRegex(InputError, "mechanic_review"):
                render_report_document(document, root / "reports")

            malformed = root / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            document["source_artifacts"][0] |= {"path": str(malformed), "sha256": sha256_file(malformed)}
            with self.assertRaisesRegex(InputError, "valid UTF-8 JSON"):
                render_report_document(document, root / "reports")

    def test_rejects_mechanic_source_identity_and_ruleset_mismatches(self) -> None:
        mutations = (
            (lambda source: source["identity"].__setitem__("report_revision", 8), "Report Revision"),
            (lambda source: source["identity"].__setitem__("fight_id", 18), "Boss Attempt"),
            (lambda source: source["identity"].__setitem__("difficulty_name", "Mythic"), "difficulty"),
            (lambda source: source["ruleset"].__setitem__("version", "stale"), "ruleset"),
        )
        for mutate, message in mutations:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                document = mechanic_document(root)
                source = sanitize_mechanic_review(mechanic_source())
                mutate(source)
                document["source_artifacts"][0] |= _write_source(root, "changed.json", source)
                with self.assertRaisesRegex(InputError, message):
                    render_report_document(document, root / "reports")

    def test_rejects_mechanic_narrative_not_derived_from_the_source(self) -> None:
        mutations = (
            lambda document: document.__setitem__("title", "Player 03 caused the wipe"),
            lambda document: document.__setitem__("scope_note", "Player 03 is responsible."),
            lambda document: document["actions"].append({
                "title": "Assign blame", "description": "Treat the event as wipe causality."
            }),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                document = mechanic_document(root)
                mutate(document)
                with self.assertRaisesRegex(InputError, "narrative"):
                    render_report_document(document, root / "reports")

    def test_personal_review_requires_verified_comparison_and_matching_claims(self) -> None:
        mutations = (
            ("personal_analysis", lambda value: value["identity"].__setitem__("report_revision", 2), "Complete Bundle evidence"),
            ("personal_analysis", lambda value: value["player"].__setitem__("name", "Other"), "Complete Bundle evidence"),
            ("encounter_benchmark", lambda value: value.__setitem__("sample_count", 4), "content ID"),
            ("comparison", lambda value: value["identity"].__setitem__("partition_id", 3), "Comparison"),
        )
        for kind, mutate, message in mutations:
            with self.subTest(kind=kind, message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                document = personal_document(root)
                source_ref = next(item for item in document["source_artifacts"] if item["kind"] == kind)
                source = json.loads(Path(source_ref["path"]).read_text(encoding="utf-8"))
                mutate(source)
                source_ref |= _write_source(root, f"changed-{kind}.json", source)
                with self.assertRaisesRegex(InputError, message):
                    render_report_document(document, root / "reports")

        document = personal_document()
        document["source_artifacts"] = [
            source for source in document["source_artifacts"] if source["kind"] != "comparison"
        ]
        with self.assertRaisesRegex(InputError, "incomplete"):
            validate_report_document(document)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = personal_document(root)
            document["player"]["name"] = "Other"
            with self.assertRaisesRegex(InputError, "player"):
                render_report_document(document, root / "reports")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = personal_document(root)
            document["player"]["anonymous"] = True
            with self.assertRaisesRegex(InputError, "player"):
                render_report_document(document, root / "reports")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = personal_document(root)
            document["identity"]["fight_id"] = 8
            with self.assertRaisesRegex(InputError, "Boss Attempt"):
                render_report_document(document, root / "reports")

    def test_personal_review_converts_recomputation_parser_errors_to_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = personal_document(root)
            with patch("wcl_raid_coach.comparison.analyze_player", side_effect=KeyError("secret-field")):
                with self.assertRaisesRegex(InputError, "could not be verified"):
                    render_report_document(document, root / "reports")

    def test_rejects_stale_analysis_schema_and_snapshot_identity_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = personal_document(root)
            analysis_ref = next(item for item in document["source_artifacts"] if item["kind"] == "personal_analysis")
            analysis = json.loads(Path(analysis_ref["path"]).read_text(encoding="utf-8"))
            analysis["schema_version"] = 2
            analysis_ref |= _write_source(root, "schema-2-analysis.json", analysis)
            with self.assertRaisesRegex(InputError, "unsupported schema version"):
                render_report_document(document, root / "reports")

        mutations = (
            (lambda document: document.__setitem__("snapshot_id", "0" * 64), "Snapshot"),
            (lambda document: document["identity"].__setitem__("partition_id", 3), "hard conditions"),
            (lambda document: document["chapters"][0].__setitem__("benchmark_id", "0" * 64), "chapter"),
            (lambda document: document["chapters"][0].__setitem__("encounter_profile_id", "0" * 64), "Profile"),
            (lambda document: document["chapters"][0].__setitem__("sample_count", 4), "chapter"),
            (lambda document: document["chapters"][0]["abilities"][0].__setitem__("name", "Invented"), "ability names"),
        )
        for mutate, message in mutations:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                document = raid_guide_document(root)
                mutate(document)
                with self.assertRaisesRegex(InputError, message):
                    render_report_document(document, root / "reports")

    def test_rejects_modified_guide_snapshot_content_id_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = raid_guide_document(root)
            source_ref = document["source_artifacts"][0]
            snapshot = json.loads(Path(source_ref["path"]).read_text(encoding="utf-8"))
            snapshot["specialization"] = "changed"
            source_ref |= _write_source(root, "changed-snapshot.json", snapshot)
            with self.assertRaisesRegex(InputError, "content ID"):
                render_report_document(document, root / "reports")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = raid_guide_document(root)
            source_ref = document["source_artifacts"][0]
            snapshot = json.loads(Path(source_ref["path"]).read_text(encoding="utf-8"))
            Path(snapshot["markdown_path"]).write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(InputError, "Markdown"):
                render_report_document(document, root / "reports")

    def test_rejects_boolean_identity_and_inconsistent_status(self) -> None:
        document = mechanic_document()
        document["identity"]["fight_id"] = True
        with self.assertRaisesRegex(InputError, "fight_id"):
            validate_report_document(document)

        document = mechanic_document()
        document["mechanics"][0]["failure_count"] = 0
        with self.assertRaisesRegex(InputError, "anomaly"):
            validate_report_document(document)

    def test_accepts_ordinary_public_source_urls(self) -> None:
        urls = [
            "https://example.com/clientSecret/guide?locale=en#overview",
            "http://example.com/source?token_count=3&signature_algorithm=sha256",
            "https://example.com/source?authentication_method=public&author=guide",
        ]
        for url in urls:
            with self.subTest(url=url):
                mechanic = mechanic_document()
                mechanic["ruleset"]["sources"] = [url]
                self.assertEqual(validate_report_document(mechanic)["ruleset"]["sources"], [url])

                guide = raid_guide_document()
                guide["chapters"][0]["sources"][0]["url"] = url
                self.assertEqual(
                    validate_report_document(guide)["chapters"][0]["sources"][0]["url"],
                    url,
                )

    def test_rejects_malformed_or_credential_bearing_source_urls(self) -> None:
        document = mechanic_document()
        document["ruleset"]["sources"] = ["https://["]
        with self.assertRaisesRegex(InputError, "malformed"):
            validate_report_document(document)

        credential_urls = [
            "https://example.com/source?clientSecret=secret",
            "https://example.com/source?ACCESS-TOKEN=secret",
            "https://example.com/source?api.key=secret",
            "https://example.com/source?X-Amz-Credential=secret",
            "https://example.com/source?X_Amz_Signature=secret",
            "https://example.com/source?signature=secret",
            "https://example.com/source?authorization=secret",
            "https://example.com/source?safe=yes&auth=secret&auth=secret-again",
            "https://example.com/source#token=secret",
            "https://example.com/source#%61ccess%2Dtoken=secret",
        ]
        for url in credential_urls:
            with self.subTest(url=url):
                document = mechanic_document()
                document["ruleset"]["sources"] = [url]
                with self.assertRaisesRegex(InputError, "credentials"):
                    validate_report_document(document)

                document = raid_guide_document()
                document["chapters"][0]["sources"][0]["url"] = url
                with self.assertRaisesRegex(InputError, "credentials"):
                    validate_report_document(document)

    def test_rejects_source_url_user_information(self) -> None:
        for url in (
            "https://user@example.com/source",
            "https://user:secret@example.com/source",
            "https://@example.com/source",
        ):
            with self.subTest(url=url):
                document = mechanic_document()
                document["ruleset"]["sources"] = [url]
                with self.assertRaisesRegex(InputError, "public HTTP or HTTPS"):
                    validate_report_document(document)

    def test_renders_personal_review_without_inventing_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = render_report_document(personal_document(Path(temporary)), Path(temporary) / "reports")
            html = Path(result["html_path"]).read_text(encoding="utf-8")

        self.assertIn("Player", html)
        self.assertIn("Ability", html)
        self.assertIn("不是可实现提升值", html)
        self.assertNotIn("<script", html.lower())

        document = personal_document()
        document["recommendations"] = ["Use cooldowns earlier"]
        with self.assertRaisesRegex(InputError, "unexpected field"):
            validate_report_document(document)

        document = personal_document()
        document["comparison"]["spec_name"] = "Frost"
        with self.assertRaisesRegex(InputError, "do not match"):
            validate_report_document(document)

    def test_renders_raid_guide_from_snapshot_fields_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = render_report_document(raid_guide_document(Path(temporary)), Path(temporary) / "reports")
            html = Path(result["html_path"]).read_text(encoding="utf-8")

        self.assertIn("中文首领七", html)
        self.assertIn("亡者大军", html)
        self.assertIn("Source &lt;title&gt;", html)
        self.assertNotIn("<script", html.lower())

        document = raid_guide_document()
        document["chapters"][0]["rotation"] = "Invented rotation"
        with self.assertRaisesRegex(InputError, "unexpected field"):
            validate_report_document(document)

    def test_assembles_multi_boss_raid_guide_without_cross_chapter_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            benchmarks = []
            for encounter_id, ability_id, target_id, amount, source_name, cohort_id in (
                (1007, 1, 70, 7000, "Boss Seven source", "c" * 64),
                (1008, 2, 80, 8000, "Boss Eight source", "d" * 64),
            ):
                benchmarks.append(identify_benchmark({
                    "schema_version": 2,
                    "cohort_id": cohort_id,
                    "identity": EXPECTED | {"game_version": "12.1", "encounter_id": encounter_id},
                    "encounter_profile_id": f"{encounter_id:064x}",
                    "specialization_profile_id": "a" * 64,
                    "sources": {
                        "encounter": [{
                            "title": source_name,
                            "url": f"https://example.com/{encounter_id}",
                            "quote_summary": f"Encounter {encounter_id} evidence.",
                        }],
                        "specialization": [],
                    },
                    "sample_count": 3,
                    "confidence": "low",
                    "stable_pattern_claims_allowed": True,
                    "mechanic_anchors": [{
                        "ability_id": ability_id,
                        "name": f"Mechanic {ability_id}",
                        "observed_anchor_ms": encounter_id,
                    }],
                    "metrics": {
                        "damage_total_median": amount,
                        "casts_median": {str(ability_id): ability_id},
                        "first_cast_ms_median": {str(ability_id): ability_id * 100},
                        "damage_by_target_median": {str(target_id): amount - 1},
                    },
                }))
            snapshot = create_guide_snapshot(
                benchmarks,
                specialization_name="邪恶死亡骑士",
                output_dir=root / "guides",
                ability_names={"1": "技能一", "2": "技能二"},
                ability_names_build="12.1.0.69587",
                encounter_names={
                    "1007": {"map_id": 3004, "name_en": "Boss Seven", "name_zh": "首领七"},
                    "1008": {"map_id": 3004, "name_en": "Boss Eight", "name_zh": "首领八"},
                },
                content_names_build="12.1.0.69587",
                content_names_sha256="d" * 64,
            )
            snapshot_path = Path(snapshot["index_path"])
            document = assemble_raid_guide_document(snapshot, snapshot_path)
            result = render_report_document(document, root / "outputs" / "reports")
            index = json.loads(Path(result["index_path"]).read_text(encoding="utf-8"))
            html = Path(result["html_path"]).read_text(encoding="utf-8")

            chapters = index["document"]["chapters"]
            self.assertEqual(index["document"]["snapshot_id"], snapshot["snapshot_id"])
            self.assertEqual(index["document"]["source_artifacts"][0]["sha256"], sha256_file(snapshot_path))
            self.assertEqual(index["document"]["identity"], {
                "game_version": "12.1",
                "partition_id": 2,
                "difficulty_name": "Heroic",
                "class_name": "DeathKnight",
                "spec_name": "Unholy",
            })
            self.assertEqual([chapter["encounter_id"] for chapter in chapters], [1007, 1008])
            self.assertEqual(chapters[0]["benchmark_id"], benchmarks[0]["benchmark_id"])
            self.assertEqual(chapters[1]["benchmark_id"], benchmarks[1]["benchmark_id"])
            self.assertEqual(chapters[0]["encounter_profile_id"], f"{1007:064x}")
            self.assertEqual(chapters[1]["encounter_profile_id"], f"{1008:064x}")
            self.assertEqual(chapters[0]["specialization_profile_id"], "a" * 64)
            self.assertEqual((chapters[0]["sample_count"], chapters[0]["confidence"]), (3, "low"))
            self.assertEqual(chapters[0]["damage_total_median"], 7000.0)
            self.assertEqual(chapters[1]["target_damage"], [{"target_id": 80, "median_amount": 7999.0}])
            self.assertEqual(chapters[0]["abilities"], [{"name": "技能一", "median_casts": 1.0, "median_first_cast_ms": 100.0}])
            self.assertEqual(chapters[1]["abilities"], [{"name": "技能二", "median_casts": 2.0, "median_first_cast_ms": 200.0}])
            self.assertEqual(chapters[0]["mechanic_anchors"], [{"name": "技能一", "observed_anchor_ms": 1007.0}])
            self.assertEqual(chapters[0]["sources"][0]["title"], "Boss Seven source")
            self.assertEqual(chapters[1]["sources"][0]["title"], "Boss Eight source")
            self.assertEqual(chapters[1]["sources"][0]["url"], "https://example.com/1008")
            self.assertIn("技能一", html)
            self.assertIn("技能二", html)
            self.assertFalse({"rotation", "talents", "gear", "phase_strategy", "recommendations", "achievable_target"} & index["document"].keys())
            self.assertEqual(result, render_report_document(document, root / "outputs" / "reports"))

            leaked = json.loads(json.dumps(document))
            leaked["chapters"][0]["abilities"] = leaked["chapters"][1]["abilities"]
            with self.assertRaisesRegex(InputError, "ability names or metrics"):
                render_report_document(leaked, root / "other-reports")

            leaked = json.loads(json.dumps(document))
            leaked["chapters"][0]["sources"] = leaked["chapters"][1]["sources"]
            with self.assertRaisesRegex(InputError, "Profile sources"):
                render_report_document(leaked, root / "other-reports")


if __name__ == "__main__":
    unittest.main()
