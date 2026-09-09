from __future__ import annotations

import unittest
from unittest.mock import patch

from wcl_raid_coach.comparison import compare_player
from wcl_raid_coach.cohort import identify_benchmark
from wcl_raid_coach.errors import InputError


IDENTITY = {"game_version": "retail", "partition_id": 2, "encounter_id": 1007, "difficulty_id": 4, "class_name": "DeathKnight", "spec_name": "Unholy"}


class ComparisonTests(unittest.TestCase):
    def test_compares_casts_but_prohibits_treating_damage_gap_as_improvement(self) -> None:
        target = {"schema_version": 4, "comparison_identity": IDENTITY, "player": {"actor_id": 10, "name": "Player"}, "evidence": {"manifest_path": "/local/manifest.json", "index_path": "/local/report.json"}, "metrics": {"damage_total": 100, "deaths": 0, "casts": {"1": 2, "123": 9}, "player_casts": {"456": 2}, "duration_ms": 60000, "damage_per_minute": 100}}
        benchmark = identify_benchmark({"schema_version": 3, "cohort_id": "c" * 64, "identity": IDENTITY, "sample_count": 3, "reference_samples": [{}, {}, {}], "confidence": "low", "stable_pattern_claims_allowed": True, "metrics": {"damage_total_median": 200, "casts_median": {"1": 3, "123": 12}, "key_action_casts_median": {"456": 3}, "duration_ms_median": 120000, "damage_per_minute_median": 100, "key_action_casts_per_minute_median": {"456": 1.5}, "key_action_rate_sample_count": {"456": 3}}})
        with patch("wcl_raid_coach.comparison.analyze_player", return_value=target):
            result = compare_player(target, benchmark)
        self.assertEqual(result["metrics"]["cast_count_deltas"], {"456": -1})
        self.assertEqual(result["metrics"]["damage_total_delta"], -100)
        self.assertEqual(result["metrics"]["damage_per_minute_delta"], 0)
        self.assertEqual(result["metrics"]["key_action_casts_per_minute_deltas"], {"456": 0.5})
        self.assertEqual(result["metrics"]["key_action_player_casts_per_minute"], {"456": 2})
        self.assertEqual(result["metrics"]["key_action_reference_casts_per_minute_median"], {"456": 1.5})
        self.assertEqual(result["metrics"]["key_action_rate_sample_counts"], {"456": 3})
        self.assertFalse(result["claim_limits"]["damage_delta_is_achievable_improvement"])
        self.assertFalse(result["claim_limits"]["sample_medians_are_prescribed_casts"])
        self.assertFalse(result["claim_limits"]["normalization_corrects_unmatched_context"])
        self.assertIn("assignments", result["guardrails"]["unmatched_context"])
        target["metrics"]["duration_ms"] = None
        target["metrics"]["damage_per_minute"] = None
        with patch("wcl_raid_coach.comparison.analyze_player", return_value=target):
            unavailable = compare_player(target, benchmark)
        self.assertIsNone(unavailable["metrics"]["damage_per_minute_delta"])
        self.assertEqual(unavailable["metrics"]["key_action_casts_per_minute_deltas"], {"456": None})

    def test_rejects_different_encounter_benchmark(self) -> None:
        target = {"schema_version": 4, "comparison_identity": IDENTITY, "player": {"actor_id": 10},
                  "evidence": {"manifest_path": "/local/manifest.json", "index_path": "/local/report.json"}, "metrics": {}}
        for field, value in (("encounter_id", 1008), ("difficulty_id", 5), ("spec_name", "Frost"),
                             ("partition_id", 3), ("game_version", "other"), ("class_name", "Mage")):
            benchmark = identify_benchmark({"schema_version": 3, "cohort_id": "c" * 64,
                                            "identity": IDENTITY | {field: value}, "sample_count": 3,
                                            "reference_samples": [{}, {}, {}], "metrics": {}})
            with self.subTest(field=field), patch("wcl_raid_coach.comparison.analyze_player", return_value=target):
                with self.assertRaisesRegex(InputError, "hard conditions"):
                    compare_player(target, benchmark)

    def test_compares_profile_declared_action_when_every_count_is_zero(self) -> None:
        target = {"schema_version": 4, "comparison_identity": IDENTITY, "player": {"actor_id": 10},
                  "evidence": {"manifest_path": "/local/manifest.json", "index_path": "/local/report.json"},
                  "metrics": {"damage_total": 0, "damage_per_minute": 0, "healing_per_minute": 0,
                              "duration_ms": 60000, "deaths": 0, "player_casts": {}}}
        benchmark = identify_benchmark({
            "schema_version": 3, "cohort_id": "c" * 64, "identity": IDENTITY,
            "sample_count": 3, "confidence": "low", "stable_pattern_claims_allowed": True,
            "reference_samples": [{}, {}, {}],
            "metrics": {"damage_total_median": 0, "damage_per_minute_median": 0,
                        "healing_per_minute_median": 0, "key_action_casts_median": {"456": 0},
                        "key_action_casts_per_minute_median": {"456": 0},
                        "key_action_rate_sample_count": {"456": 3}},
        })
        with patch("wcl_raid_coach.comparison.analyze_player", return_value=target):
            metrics = compare_player(target, benchmark)["metrics"]
        self.assertEqual(metrics["cast_count_deltas"], {"456": 0})
        self.assertEqual(metrics["key_action_player_casts_per_minute"], {"456": 0})
        self.assertEqual(metrics["key_action_reference_casts_per_minute_median"], {"456": 0})
        self.assertEqual(metrics["key_action_casts_per_minute_deltas"], {"456": 0})
        self.assertEqual(metrics["key_action_rate_sample_counts"], {"456": 3})

    def test_rejects_non_object_inputs_as_domain_error(self) -> None:
        with self.assertRaises(InputError):
            compare_player([], {})

    def test_comparison_requires_verified_analysis_evidence(self) -> None:
        benchmark = identify_benchmark({
            "schema_version": 3, "cohort_id": "c" * 64, "identity": IDENTITY,
            "sample_count": 3, "reference_samples": [{}, {}, {}],
        })
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
        benchmark = identify_benchmark({
            "schema_version": 3, "cohort_id": "c" * 64, "identity": IDENTITY,
            "sample_count": 3, "reference_samples": [{}, {}, {}],
        })

        with self.assertRaisesRegex(InputError, "unsupported schema version"):
            compare_player(target, benchmark)

    def test_rejects_self_hashed_float_benchmark_sample_count(self) -> None:
        target = {"schema_version": 4, "comparison_identity": IDENTITY}
        benchmark = identify_benchmark({
            "schema_version": 3, "cohort_id": "c" * 64, "identity": IDENTITY,
            "sample_count": 11.0, "reference_samples": [{} for _ in range(11)],
        })

        with self.assertRaisesRegex(InputError, "3 to 10"):
            compare_player(target, benchmark)


if __name__ == "__main__":
    unittest.main()
