from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wcl_raid_coach.errors import InputError
from wcl_raid_coach.guides import create_guide_snapshot
from wcl_raid_coach.cohort import sign_benchmark


def benchmark(encounter_id: int) -> dict:
    return sign_benchmark({
        "identity": {"game_version": "retail", "encounter_id": encounter_id, "difficulty_id": 4, "partition_id": 2, "class_name": "DeathKnight", "spec_name": "Unholy"},
        "encounter_profile_id": f"profile-{encounter_id}",
        "specialization_profile_id": "spec-profile",
        "sources": {"encounter": [], "specialization": []},
        "sample_count": 3,
        "confidence": "low",
        "stable_pattern_claims_allowed": True,
        "metrics": {"damage_total_median": 200, "casts_median": {"1": 2}},
    }, "secret")


class GuideTests(unittest.TestCase):
    def test_creates_one_snapshot_with_two_separate_encounter_chapters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = create_guide_snapshot([benchmark(1007), benchmark(1008)], specialization_name="邪恶死亡骑士", output_dir=Path(directory), signing_key="secret")
            markdown = Path(snapshot["markdown_path"]).read_text(encoding="utf-8")
        self.assertEqual(len(snapshot["chapters"]), 2)
        self.assertIn("Encounter 1007", markdown)
        self.assertIn("Encounter 1008", markdown)
        self.assertIn("日志事实", markdown)
        self.assertIn("资料结论", markdown)
        self.assertIn("推断", markdown)

    def test_refuses_case_study_as_stable_guide(self) -> None:
        value = benchmark(1007) | {"sample_count": 2, "stable_pattern_claims_allowed": False}
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(InputError):
            create_guide_snapshot([value], specialization_name="邪恶死亡骑士", output_dir=Path(directory), signing_key="secret")

    def test_reuses_immutable_snapshot_without_overwriting_created_at(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = create_guide_snapshot([benchmark(1007)], specialization_name="邪恶死亡骑士", output_dir=Path(directory), signing_key="secret")
            second = create_guide_snapshot([benchmark(1007)], specialization_name="邪恶死亡骑士", output_dir=Path(directory), signing_key="secret")
        self.assertEqual(first["created_at"], second["created_at"])

    def test_refuses_benchmarks_from_different_partitions(self) -> None:
        other = benchmark(1008)
        other["identity"] = other["identity"] | {"partition_id": 3}
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(InputError):
            create_guide_snapshot([benchmark(1007), other], specialization_name="邪恶死亡骑士", output_dir=Path(directory), signing_key="secret")

    def test_rejects_modified_snapshot_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot = create_guide_snapshot([benchmark(1007)], specialization_name="邪恶死亡骑士", output_dir=Path(directory), signing_key="secret")
            Path(snapshot["markdown_path"]).write_text("modified", encoding="utf-8")
            with self.assertRaises(InputError):
                create_guide_snapshot([benchmark(1007)], specialization_name="邪恶死亡骑士", output_dir=Path(directory), signing_key="secret")


if __name__ == "__main__":
    unittest.main()
