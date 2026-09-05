from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from wcl_raid_coach.errors import InputError
from wcl_raid_coach.report_documents import render_report_document, validate_report_document


def mechanic_document() -> dict:
    source = Path(__file__)
    return {
        "schema_version": 1,
        "document_type": "mechanic_review",
        "locale": "zh-CN",
        "title": "石棺哨兵机制复盘",
        "subtitle": "Heroic Boss Attempt 17",
        "source_artifacts": [
            {
                "kind": "mechanic_review",
                "path": str(source),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
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
            "boss_percentage": 32.7,
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
                "description": "事件确认异常，但不裁定责任。<img src=x onerror=alert(1)>",
                "events": [
                    {
                        "fight_time_ms": 138440,
                        "tone": "danger",
                        "title": "Player 03 + Player 11",
                        "description": "四名相邻玩家随后受到机制伤害。",
                        "participants": ["Player 03", "Player 11"],
                        "evidence_excerpt": {
                            "event_type": "damage",
                            "ability_id": 1284941,
                        },
                    },
                    {
                        "fight_time_ms": 307315,
                        "tone": "ok",
                        "title": "Player 02 + Player 09",
                        "description": "配对信号完整。",
                        "participants": ["Player 02", "Player 09"],
                        "evidence_excerpt": None,
                    },
                ],
            },
            {
                "name": "墓穴崩塌",
                "status": "review",
                "trigger_count": 8,
                "success_count": None,
                "failure_count": None,
                "description": "日志不足以自动裁决。",
                "events": [],
            },
        ],
        "actions": [
            {"title": "配对确认", "description": "点名后两秒内口头确认搭档。"}
        ],
        "scope_note": "异常不表示玩家责任、表现评价或灭团因果。",
    }


def personal_document() -> dict:
    source = Path(__file__)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return {
        "schema_version": 1,
        "document_type": "personal_review",
        "locale": "zh-CN",
        "title": "Player 07 · 个人复盘",
        "subtitle": "Complete Bundle 日志事实 + 同条件 Encounter Benchmark",
        "source_artifacts": [
            {"kind": "personal_analysis", "path": str(source), "sha256": digest},
            {"kind": "encounter_benchmark", "path": str(source), "sha256": digest},
        ],
        "identity": mechanic_document()["identity"],
        "player": {
            "name": "Player <07>",
            "class_name": "DeathKnight",
            "spec_name": "Unholy",
            "item_level": 684.0,
            "anonymous": True,
        },
        "comparison": {
            "game_version": "12.1",
            "partition_id": 2,
            "encounter_id": 1007,
            "difficulty_id": 4,
            "class_name": "DeathKnight",
            "spec_name": "Unholy",
            "sample_count": 8,
            "confidence": "low",
        },
        "metrics": {
            "damage_total": 248600000,
            "healing_total": 3800000,
            "interrupts": 2,
            "deaths": 1,
            "resource_events": 146,
            "damage_total_delta": -18200000,
        },
        "abilities": [
            {
                "name": "黑暗突变",
                "player_casts": 7,
                "median_casts": 8.0,
                "player_first_cast_ms": 4200,
                "median_first_cast_ms": 3800.0,
            }
        ],
        "scope_note": "伤害差值不是可实现提升值；死亡计数不提供死亡原因。",
    }


def raid_guide_document() -> dict:
    source = Path(__file__)
    return {
        "schema_version": 1,
        "document_type": "raid_guide",
        "locale": "zh-CN",
        "title": "邪恶死亡骑士高分日志战术手册",
        "subtitle": "按 Boss 隔离的可观察模式与来源审计",
        "source_artifacts": [
            {
                "kind": "guide_snapshot",
                "path": str(source),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
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
        "snapshot_id": "8f4c" + "0" * 60,
        "ability_names_build": "12.1.0.69587",
        "chapters": [
            {
                "encounter_id": 1007,
                "encounter_name": "中文首领七",
                "sample_count": 8,
                "confidence": "low",
                "damage_total_median": 266800000.0,
                "abilities": [
                    {"name": "亡者大军", "median_casts": 1.0, "median_first_cast_ms": 1300.0}
                ],
                "target_damage": [{"target_id": 20, "median_amount": 188200000.0}],
                "mechanic_anchors": [
                    {"name": "中文机制一", "observed_anchor_ms": 18000.0}
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
    def test_renders_content_addressed_self_contained_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "outputs" / "reports"
            result = render_report_document(mechanic_document(), output_dir)
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

            repeated = render_report_document(mechanic_document(), output_dir)
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
            result = render_report_document(mechanic_document(), output_dir)
            Path(result["html_path"]).write_text("damaged", encoding="utf-8")

            with self.assertRaisesRegex(InputError, "invalid identity"):
                render_report_document(mechanic_document(), output_dir)

    def test_rejects_a_source_artifact_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            document = mechanic_document()
            document["source_artifacts"][0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(InputError, "source artifact"):
                render_report_document(document, Path(temporary))

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
            result = render_report_document(personal_document(), Path(temporary))
            html = Path(result["html_path"]).read_text(encoding="utf-8")

        self.assertIn("Player &lt;07&gt;", html)
        self.assertIn("黑暗突变", html)
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
            result = render_report_document(raid_guide_document(), Path(temporary))
            html = Path(result["html_path"]).read_text(encoding="utf-8")

        self.assertIn("中文首领七", html)
        self.assertIn("中文机制一", html)
        self.assertIn("Source &lt;title&gt;", html)
        self.assertNotIn("<script", html.lower())

        document = raid_guide_document()
        document["chapters"][0]["rotation"] = "Invented rotation"
        with self.assertRaisesRegex(InputError, "unexpected field"):
            validate_report_document(document)


if __name__ == "__main__":
    unittest.main()
