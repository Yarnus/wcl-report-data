from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wcl_raid_coach.errors import InputError
from wcl_raid_coach.guides import create_guide_snapshot
from wcl_raid_coach.cohort import identify_benchmark


ABILITY_NAMES = {"1": "中文技能"}
CONTENT_NAMES = {
    "1007": {"map_id": 3004, "name_en": "Boss 7", "name_zh": "中文首领七"},
    "1008": {"map_id": 3004, "name_en": "Boss 8", "name_zh": "中文首领八"},
}
CONTENT_ARGS = {
    "encounter_names": CONTENT_NAMES,
    "content_names_build": "12.1.0.69587",
    "content_names_sha256": "a" * 64,
}


def benchmark(encounter_id: int) -> dict:
    return identify_benchmark({
        "schema_version": 2,
        "cohort_id": "c" * 64,
        "identity": {"game_version": "retail", "encounter_id": encounter_id, "difficulty_id": 4, "partition_id": 2, "class_name": "DeathKnight", "spec_name": "Unholy"},
        "encounter_profile_id": f"profile-{encounter_id}",
        "specialization_profile_id": "spec-profile",
        "sources": {"encounter": [], "specialization": []},
        "sample_count": 3,
        "confidence": "low",
        "stable_pattern_claims_allowed": True,
        "mechanic_anchors": [{"ability_id": 1, "name": "Mechanic", "observed_anchor_ms": 10000}],
        "metrics": {"damage_total_median": 200, "casts_median": {"1": 2}},
    })


class GuideTests(unittest.TestCase):
    def test_creates_one_snapshot_with_two_separate_encounter_chapters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = create_guide_snapshot(
                [benchmark(1007), benchmark(1008)],
                specialization_name="邪恶死亡骑士",
                output_dir=Path(directory),
                ability_names=ABILITY_NAMES,
                ability_names_build="test",
                **CONTENT_ARGS,
            )
            markdown = Path(snapshot["markdown_path"]).read_text(encoding="utf-8")
        self.assertEqual(len(snapshot["chapters"]), 2)
        self.assertIn("中文首领七", markdown)
        self.assertIn("中文首领八", markdown)
        self.assertIn("日志事实", markdown)
        self.assertIn("资料结论", markdown)
        self.assertIn("推断", markdown)
        self.assertIn("中文技能", markdown)
        self.assertNotIn("Mechanic", markdown)
        self.assertEqual(snapshot["chapters"][0]["mechanic_anchors"][0]["name_zh"], "中文技能")
        self.assertEqual(snapshot["chapters"][0]["encounter_name_en"], "Boss 7")
        self.assertEqual(snapshot["chapters"][0]["benchmark_id"], benchmark(1007)["benchmark_id"])
        self.assertEqual(snapshot["content_names_build"], "12.1.0.69587")
        self.assertEqual(snapshot["content_names_sha256"], "a" * 64)
        self.assertEqual(snapshot["render_schema_version"], 2)

    def test_refuses_case_study_as_stable_guide(self) -> None:
        value = benchmark(1007) | {"sample_count": 2, "stable_pattern_claims_allowed": False}
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(InputError):
            create_guide_snapshot([value], specialization_name="邪恶死亡骑士", output_dir=Path(directory), ability_names=ABILITY_NAMES, ability_names_build="test", **CONTENT_ARGS)

    def test_rejects_an_unmapped_mechanic_spell(self) -> None:
        value = identify_benchmark(
            benchmark(1007) | {"mechanic_anchors": [{"ability_id": 999, "name": "Unknown"}]}
        )
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(InputError, "zhCN"):
            create_guide_snapshot([value], specialization_name="邪恶死亡骑士", output_dir=Path(directory), ability_names=ABILITY_NAMES, ability_names_build="test", **CONTENT_ARGS)

    def test_rejects_an_encounter_outside_the_content_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(InputError, "content-name"):
            create_guide_snapshot(
                [benchmark(1007)],
                specialization_name="邪恶死亡骑士",
                output_dir=Path(directory),
                ability_names=ABILITY_NAMES,
                encounter_names={},
                content_names_build="test",
                content_names_sha256="a" * 64,
            )

    def test_rejects_a_mythic_plus_encounter_in_a_raid_guide(self) -> None:
        names = {"1007": CONTENT_NAMES["1007"] | {"map_id": 2773}}
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(InputError, "current-raid"):
            create_guide_snapshot(
                [benchmark(1007)],
                specialization_name="邪恶死亡骑士",
                output_dir=Path(directory),
                ability_names=ABILITY_NAMES,
                encounter_names=names,
                content_names_build="test",
                content_names_sha256="a" * 64,
            )

    def test_rejects_a_raid_difficulty_outside_the_content_scope(self) -> None:
        value = benchmark(1007)
        value["identity"] = value["identity"] | {"difficulty_id": 1}
        value = identify_benchmark(value)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(InputError, "scope"):
            create_guide_snapshot(
                [value],
                specialization_name="邪恶死亡骑士",
                output_dir=Path(directory),
                ability_names=ABILITY_NAMES,
                ability_names_build="test",
                **CONTENT_ARGS,
            )

    def test_reuses_immutable_snapshot_without_overwriting_created_at(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = create_guide_snapshot([benchmark(1007)], specialization_name="邪恶死亡骑士", output_dir=Path(directory), ability_names=ABILITY_NAMES, ability_names_build="test", **CONTENT_ARGS)
            second = create_guide_snapshot([benchmark(1007)], specialization_name="邪恶死亡骑士", output_dir=Path(directory), ability_names=ABILITY_NAMES, ability_names_build="test", **CONTENT_ARGS)
        self.assertEqual(first["created_at"], second["created_at"])

    def test_refuses_benchmarks_from_different_partitions(self) -> None:
        other = benchmark(1008)
        other["identity"] = other["identity"] | {"partition_id": 3}
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(InputError):
            create_guide_snapshot([benchmark(1007), other], specialization_name="邪恶死亡骑士", output_dir=Path(directory), ability_names=ABILITY_NAMES, ability_names_build="test", **CONTENT_ARGS)

    def test_rejects_modified_snapshot_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = create_guide_snapshot([benchmark(1007)], specialization_name="邪恶死亡骑士", output_dir=Path(directory), ability_names=ABILITY_NAMES, ability_names_build="test", **CONTENT_ARGS)
            Path(snapshot["markdown_path"]).write_text("modified", encoding="utf-8")
            with self.assertRaises(InputError):
                create_guide_snapshot([benchmark(1007)], specialization_name="邪恶死亡骑士", output_dir=Path(directory), ability_names=ABILITY_NAMES, ability_names_build="test", **CONTENT_ARGS)


if __name__ == "__main__":
    unittest.main()
