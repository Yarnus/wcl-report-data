from __future__ import annotations

import unittest

from wcl_raid_coach.comparison import compare_player
from wcl_raid_coach.errors import InputError


IDENTITY = {"game_version": "retail", "partition_id": 2, "encounter_id": 1007, "difficulty_id": 4, "class_name": "DeathKnight", "spec_name": "Unholy"}


class ComparisonTests(unittest.TestCase):
    def test_compares_casts_but_prohibits_treating_damage_gap_as_improvement(self) -> None:
        target = {"comparison_identity": IDENTITY, "player": {"name": "Player"}, "metrics": {"damage_total": 100, "deaths": 0, "casts": {"1": 2}}}
        benchmark = {"identity": IDENTITY, "sample_count": 3, "confidence": "low", "stable_pattern_claims_allowed": True, "metrics": {"damage_total_median": 200, "casts_median": {"1": 3}}}
        result = compare_player(target, benchmark)
        self.assertEqual(result["metrics"]["cast_count_deltas"]["1"], -1)
        self.assertFalse(result["claim_limits"]["damage_delta_is_achievable_improvement"])

    def test_rejects_different_encounter_benchmark(self) -> None:
        target = {"comparison_identity": IDENTITY, "metrics": {}}
        benchmark = {"identity": IDENTITY | {"encounter_id": 1008}, "metrics": {}}
        with self.assertRaises(InputError):
            compare_player(target, benchmark)

    def test_rejects_non_object_inputs_as_domain_error(self) -> None:
        with self.assertRaises(InputError):
            compare_player([], {})


if __name__ == "__main__":
    unittest.main()
