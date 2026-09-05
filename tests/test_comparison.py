from __future__ import annotations

import unittest
from unittest.mock import patch

from wcl_raid_coach.comparison import compare_player
from wcl_raid_coach.cohort import identify_benchmark
from wcl_raid_coach.errors import InputError


IDENTITY = {"game_version": "retail", "partition_id": 2, "encounter_id": 1007, "difficulty_id": 4, "class_name": "DeathKnight", "spec_name": "Unholy"}


class ComparisonTests(unittest.TestCase):
    def test_compares_casts_but_prohibits_treating_damage_gap_as_improvement(self) -> None:
        target = {"schema_version": 3, "comparison_identity": IDENTITY, "player": {"actor_id": 10, "name": "Player"}, "evidence": {"manifest_path": "/local/manifest.json", "index_path": "/local/report.json"}, "metrics": {"damage_total": 100, "deaths": 0, "casts": {"1": 2}}}
        benchmark = identify_benchmark({"schema_version": 2, "cohort_id": "c" * 64, "identity": IDENTITY, "sample_count": 3, "confidence": "low", "stable_pattern_claims_allowed": True, "metrics": {"damage_total_median": 200, "casts_median": {"1": 3}}})
        with patch("wcl_raid_coach.comparison.analyze_player", return_value=target):
            result = compare_player(target, benchmark)
        self.assertEqual(result["metrics"]["cast_count_deltas"]["1"], -1)
        self.assertFalse(result["claim_limits"]["damage_delta_is_achievable_improvement"])

    def test_rejects_different_encounter_benchmark(self) -> None:
        target = {"comparison_identity": IDENTITY, "metrics": {}}
        benchmark = identify_benchmark({"schema_version": 2, "cohort_id": "c" * 64, "identity": IDENTITY | {"encounter_id": 1008}, "metrics": {}})
        with self.assertRaises(InputError):
            compare_player(target, benchmark)

    def test_rejects_non_object_inputs_as_domain_error(self) -> None:
        with self.assertRaises(InputError):
            compare_player([], {})

    def test_comparison_requires_verified_analysis_evidence(self) -> None:
        benchmark = identify_benchmark({"schema_version": 2, "cohort_id": "c" * 64, "identity": IDENTITY})
        target = {"comparison_identity": IDENTITY, "metrics": {}}
        with self.assertRaises(InputError):
            compare_player(target, benchmark)

    def test_rejects_persisted_personal_analysis_schema_2(self) -> None:
        target = {
            "schema_version": 2,
            "comparison_identity": IDENTITY,
            "player": {"actor_id": 10},
            "evidence": {"manifest_path": "/local/manifest.json", "index_path": "/local/report.json"},
            "metrics": {},
        }
        benchmark = identify_benchmark({"schema_version": 2, "cohort_id": "c" * 64, "identity": IDENTITY})

        with self.assertRaisesRegex(InputError, "unsupported schema version"):
            compare_player(target, benchmark)


if __name__ == "__main__":
    unittest.main()
