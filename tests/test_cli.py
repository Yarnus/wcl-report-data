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


class CliTests(unittest.TestCase):
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

    def test_query_ensures_ability_names_and_returns_their_location(self) -> None:
        args = create_parser().parse_args(["query", "/tmp/manifest.json"])
        names = {
            "mapping_path": "/tmp/ability-names.zhCN.json",
            "metadata_path": "/tmp/ability-names.zhCN.meta.json",
            "locale": "zhCN",
            "build": "12.1.0.69587",
            "ability_count": 2,
        }

        with (
            patch("wcl_raid_coach.__main__.ensure_ability_names", return_value=names) as ensure,
            patch("wcl_raid_coach.__main__.query_bundle", return_value={"events": []}),
        ):
            result = run(args)

        ensure.assert_called_once_with(args.data_root.resolve())
        self.assertEqual(result["ability_names"], names)

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
            document_path.write_text(json.dumps(mechanic_document()), encoding="utf-8")
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
            mapping_path.write_text(json.dumps({"1": "中文技能", "2": "中文机制"}), encoding="utf-8")
            benchmark_path = root / "benchmark.json"
            benchmark_path.write_text(
                json.dumps(
                    identify_benchmark(
                        {
                            "schema_version": 2,
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
                            "confidence": "low",
                            "stable_pattern_claims_allowed": True,
                            "mechanic_anchors": [{"ability_id": 2, "name": "English Mechanic", "observed_anchor_ms": 10000}],
                            "metrics": {"casts_median": {"1": 2}},
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


if __name__ == "__main__":
    unittest.main()
