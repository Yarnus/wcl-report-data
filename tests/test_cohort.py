from __future__ import annotations

import hashlib
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

from wcl_raid_coach.cohort import build_benchmark, extract_ranking_candidates, identify_benchmark, identify_cohort, validate_analysis_membership, verify_benchmark, verify_benchmark_for_cohort, verify_cohort
from wcl_raid_coach.errors import InputError
from wcl_raid_coach.storage import sha256_file


PROFILE = {
    "kind": "encounter",
    "identity": {"game_version": "retail", "partition_id": 2, "encounter_id": 1007, "difficulty_id": 4},
    "eligibility": {"priority_target_ids": [20], "excluded_target_ids": [30], "target_id_type": "npc_game_id"},
    "phases": [{"id": 1, "name": "Phase 1"}],
    "mechanic_anchors": [{"ability_id": 1, "name": "Mechanic"}],
    "sources": [{"url": "https://example.com", "title": "Guide", "accessed_at": "2026-09-02T00:00:00Z", "quote_summary": "Target 20 is priority.", "content_hash": "a" * 64}],
}
SPEC_PROFILE = {
    "kind": "specialization",
    "identity": {"game_version": "retail", "partition_id": 2, "class_name": "DeathKnight", "spec_name": "Unholy"},
    "abilities": [{"id": 1, "name": "Cooldown"}],
    "resources": [{"name": "Runic Power"}],
    "cooldown_relationships": [{"ability_id": 1, "relation": "priority_target"}],
    "role_guardrails": [{"rule": "no_death"}],
    "sources": [{"url": "https://example.com/spec", "title": "Spec Guide", "accessed_at": "2026-09-02T00:00:00Z", "quote_summary": "Use cooldown on priority targets.", "content_hash": "b" * 64}],
}
EXPECTED = {"game_version": "retail", "partition_id": 2, "encounter_id": 1007, "difficulty_id": 4, "class_name": "DeathKnight", "spec_name": "Unholy"}


class CohortTests(unittest.TestCase):
    def analysis(self, metrics: dict, expected: dict = EXPECTED, suffix: str = "1") -> dict:
        return {
            "schema_version": 4,
            "identity": {"report_code": f"ABC{suffix}", "report_revision": 1, "fight_id": int(suffix)},
            "player": {"actor_id": 10, "name": "Player"},
            "evidence": {"manifest_path": f"/tmp/manifest-{suffix}.json", "manifest_sha256": "hash", "index_path": f"/tmp/index-{suffix}.json", "index_sha256": "hash"},
            "comparison_identity": expected,
            "metrics": {"damage_by_npc": metrics.get("damage_by_target", {})} | metrics,
        }

    def test_extracts_only_recent_candidates_with_complete_identity(self) -> None:
        payload = {"rankings": [
            {"reportCode": "ABC", "fightID": 7, "sourceID": 10, "startTime": "2026-09-01T00:00:00Z", "score": 99},
            {"reportCode": "OLD", "fightID": 8, "sourceID": 11, "startTime": "2026-07-01T00:00:00Z", "score": 98},
            {"reportCode": "MISS", "fightID": 9, "score": 97},
        ]}
        result = extract_ranking_candidates(payload, now=datetime(2026, 9, 2, tzinfo=timezone.utc))
        self.assertEqual([item["report_code"] for item in result["eligible_recent_candidates"]], ["ABC"])
        self.assertEqual(len(result["rejected_candidates"]), 1)
        self.assertIsNone(result["unverified_recency_candidates"][0]["source_id"])

    def test_duplicate_ranking_identity_keeps_first_classification(self) -> None:
        payload = {"rankings": [
            {"reportCode": "ABC", "fightID": 7, "sourceID": 10, "startTime": "2026-09-01T00:00:00Z", "score": 99},
            {"reportCode": "ABC", "fightID": 7, "sourceID": 10, "startTime": "2026-07-01T00:00:00Z", "score": 1},
        ]}
        result = extract_ranking_candidates(payload, now=datetime(2026, 9, 2, tzinfo=timezone.utc))
        self.assertEqual(len(result["eligible_recent_candidates"]), 1)
        self.assertEqual(result["eligible_recent_candidates"][0]["score"], 99)
        self.assertEqual(result["rejected_candidates"][0]["reason"], "duplicate_identity")

    def test_rejects_non_json_ranking_candidate_numbers(self) -> None:
        for field in ("rank", "rankPercent"):
            for value in (float("nan"), float("inf"), float("-inf"), True, "99"):
                with self.subTest(field=field, value=value):
                    candidate = {
                        "reportCode": "ABC", "fightID": 7, "sourceID": 10,
                        "startTime": "2026-09-01T00:00:00Z", "rankPercent": 99,
                    }
                    candidate[field] = value
                    with self.assertRaises(InputError):
                        extract_ranking_candidates(
                            {"rankings": [candidate]},
                            now=datetime(2026, 9, 2, tzinfo=timezone.utc),
                        )

    def test_canonical_cohort_rejects_non_finite_nested_floats(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(InputError):
                identify_cohort({
                    "schema_version": 2,
                    "filters": {"minimum_score": value},
                    "eligible_recent_candidates": [],
                })
        for field, value in (("rank", True), ("score", False), ("score", "99")):
            with self.subTest(field=field, value=value), self.assertRaises(InputError):
                identify_cohort({
                    "schema_version": 2,
                    "eligible_recent_candidates": [{field: value}],
                })

    def test_content_addressed_cohort_rejects_edits(self) -> None:
        cohort = identify_cohort({"schema_version": 2, "filters": dict(EXPECTED), "candidates": []})
        verify_cohort(cohort)
        self.assertRegex(cohort["cohort_id"], r"^[0-9a-f]{64}$")
        self.assertNotIn("signature", cohort)
        cohort["filters"]["encounter_id"] = 1008
        with self.assertRaises(InputError):
            verify_cohort(cohort)

    def test_rejects_legacy_hmac_artifacts(self) -> None:
        with self.assertRaisesRegex(InputError, "schema version"):
            verify_cohort({"schema_version": 1, "signature": "a" * 64})
        with self.assertRaisesRegex(InputError, "schema version"):
            verify_benchmark({"schema_version": 1, "signature": "a" * 64})

    def test_rejects_malformed_content_addressed_artifact_identity(self) -> None:
        with self.assertRaisesRegex(InputError, "schema version"):
            verify_cohort({"schema_version": 2.0, "cohort_id": "a" * 64})
        benchmark = identify_benchmark({"schema_version": 3, "identity": EXPECTED})
        with self.assertRaisesRegex(InputError, "Ranking Cohort content ID"):
            verify_benchmark(benchmark)

    def test_cohort_rejects_malformed_nested_containers_with_recomputed_id(self) -> None:
        malformed = (
            ("filters", None), ("filters", []),
            ("pagination", None), ("pagination", []),
            ("eligible_recent_candidates", None), ("eligible_recent_candidates", {}),
            ("unverified_recency_candidates", [None]),
            ("rejected_candidates", [[]]),
        )
        for field, value in malformed:
            with self.subTest(field=field, value=value):
                body = {"schema_version": 2, field: value}
                cohort_id = hashlib.sha256(json.dumps(
                    body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()).hexdigest()
                with self.assertRaises(InputError):
                    verify_cohort(body | {"cohort_id": cohort_id})
                with self.assertRaises(InputError):
                    identify_cohort(body)

    def test_cohort_rejects_malformed_pagination_scalars(self) -> None:
        for field, value in (
            ("first_page", 0), ("last_page", True),
            ("has_more_pages", None), ("truncated", []),
            ("target_reached", 1), ("exhausted", "false"),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(InputError):
                identify_cohort({"schema_version": 2, "pagination": {field: value}})

    def test_cohort_rejects_inconsistent_pagination_with_recomputed_id(self) -> None:
        invalid = (
            {"first_page": 2, "last_page": 1},
            {"first_page": 1},
            {"exhausted": True},
            {"first_page": 1, "last_page": 1, "truncated": False, "exhausted": True},
            {"first_page": 1, "last_page": 1, "has_more_pages": False, "exhausted": True},
            {"has_more_pages": True, "truncated": False, "exhausted": True},
            {"has_more_pages": False, "truncated": False, "exhausted": False},
            {"last_page": 4, "next_page": 4},
            {"last_page": 4, "next_page": 5, "resume_page": 6},
            {"last_page": 4, "next_page": 5, "exhausted": True},
        )
        for pagination in invalid:
            with self.subTest(pagination=pagination):
                body = {"schema_version": 2, "pagination": pagination}
                cohort_id = hashlib.sha256(json.dumps(
                    body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()).hexdigest()
                with self.assertRaises(InputError):
                    verify_cohort(body | {"cohort_id": cohort_id})

    def test_content_addressed_benchmark_rejects_edits(self) -> None:
        benchmark = identify_benchmark({
            "schema_version": 3, "cohort_id": "c" * 64,
            "identity": dict(EXPECTED), "sample_count": 3,
            "reference_samples": [{}, {}, {}],
        })
        verify_benchmark(benchmark)
        self.assertRegex(benchmark["benchmark_id"], r"^[0-9a-f]{64}$")
        self.assertNotIn("signature", benchmark)
        benchmark["sample_count"] = 4
        with self.assertRaises(InputError):
            verify_benchmark(benchmark)

    def test_benchmark_sample_count_requires_matching_bounded_integer(self) -> None:
        benchmark = identify_benchmark({
            "schema_version": 3, "cohort_id": "c" * 64,
            "sample_count": 10, "reference_samples": [{} for _ in range(10)],
            "confidence": "normal",
        })
        verify_benchmark(benchmark)
        self.assertEqual(benchmark["confidence"], "normal")

        forged = identify_benchmark(
            benchmark | {"sample_count": 11.0, "reference_samples": [{} for _ in range(11)]}
        )
        with self.assertRaisesRegex(InputError, "3 to 10"):
            verify_benchmark(forged)

    def test_reuse_rebuilds_benchmark_from_current_cohort_evidence(self) -> None:
        analyses = [self.analysis({
            "deaths": 0, "damage_total": damage,
            "damage_by_target": {"20": damage}, "casts": {},
        }, suffix=str(index)) for index, damage in enumerate((100, 200, 300), 1)]
        cohort = identify_cohort({
            "schema_version": 2,
            "eligible_recent_candidates": [
                {"report_code": f"ABC{index}", "fight_id": index, "source_id": 10}
                for index in range(1, 4)
            ],
        })
        benchmark = identify_benchmark(build_benchmark(
            analyses, PROFILE, SPEC_PROFILE, EXPECTED, cohort_id=cohort["cohort_id"]
        ))
        with (
            patch("wcl_raid_coach.cohort.analyze_player", side_effect=analyses),
            patch("wcl_raid_coach.cohort.validate_analysis_membership"),
        ):
            verify_benchmark_for_cohort(benchmark, cohort, PROFILE, SPEC_PROFILE)
        forged = identify_benchmark(benchmark | {
            "metrics": benchmark["metrics"] | {"damage_total_median": 999}
        })
        with (
            patch("wcl_raid_coach.cohort.analyze_player", side_effect=analyses),
            patch("wcl_raid_coach.cohort.validate_analysis_membership"),
            self.assertRaisesRegex(InputError, "validated Reference Samples"),
        ):
            verify_benchmark_for_cohort(forged, cohort, PROFILE, SPEC_PROFILE)

    def test_analysis_must_belong_to_content_addressed_recent_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            index = Path(directory) / "index.json"
            manifest.write_text("{}", encoding="utf-8")
            index.write_text("{}", encoding="utf-8")
            analysis = self.analysis({"deaths": 0}, suffix="7")
            analysis["identity"]["report_code"] = "ABC"
            analysis["evidence"] = {"manifest_path": str(manifest), "manifest_sha256": sha256_file(manifest), "index_path": str(index), "index_sha256": sha256_file(index)}
            cohort = identify_cohort({"schema_version": 2, "eligible_recent_candidates": [{"report_code": "ABC", "fight_id": 7, "source_id": 10}]})
            with patch("wcl_raid_coach.cohort.analyze_player", return_value=analysis):
                validate_analysis_membership([analysis], cohort)
            other = analysis | {"identity": analysis["identity"] | {"report_code": "OTHER"}}
            with self.assertRaises(InputError):
                validate_analysis_membership([other], cohort)

    def test_rejects_persisted_personal_analysis_schema_2(self) -> None:
        analysis = self.analysis({"deaths": 0})
        analysis["schema_version"] = 2
        cohort = identify_cohort({"schema_version": 2, "eligible_recent_candidates": []})

        with self.assertRaisesRegex(InputError, "unsupported schema version"):
            validate_analysis_membership([analysis], cohort)

    def test_builds_one_encounter_benchmark_from_three_safe_samples(self) -> None:
        analyses = []
        for index, damage in enumerate((100, 200, 300), 1):
            analyses.append(self.analysis({"deaths": 0, "damage_total": damage, "damage_by_target": {"20": damage}, "casts": {"1": 2}, "first_cast_ms": {"1": 100}}, suffix=str(index)))
        benchmark = build_benchmark(analyses, PROFILE, SPEC_PROFILE, EXPECTED, cohort_id="c" * 64)
        self.assertEqual(benchmark["sample_count"], 3)
        self.assertEqual(benchmark["metrics"]["damage_total_median"], 200)
        self.assertEqual(benchmark["confidence"], "low")
        self.assertEqual(benchmark["mechanic_anchors"], PROFILE["mechanic_anchors"])
        self.assertEqual(benchmark["cohort_id"], "c" * 64)

    def test_direct_benchmark_rejects_eleven_qualified_samples(self) -> None:
        analyses = [self.analysis({
            "deaths": 0, "damage_total": index,
            "damage_by_target": {"20": index}, "casts": {},
        }, suffix=str(index)) for index in range(1, 12)]

        with self.assertRaisesRegex(InputError, "maximum of 10"):
            build_benchmark(
                analyses, PROFILE, SPEC_PROFILE, EXPECTED, cohort_id="c" * 64
            )

    def test_rejects_mixed_encounter_samples(self) -> None:
        analyses = [self.analysis({"deaths": 0, "damage_total": 100, "damage_by_target": {"20": 100}, "casts": {}}, EXPECTED | {"encounter_id": 1008}, str(index)) for index in range(1, 4)]
        with self.assertRaises(InputError):
            build_benchmark(analyses, PROFILE, SPEC_PROFILE, EXPECTED, cohort_id="c" * 64)

    def test_normalizes_each_sample_and_counts_absent_actions_as_zero(self) -> None:
        analyses = [self.analysis({
            "damage_total": damage, "damage_by_target": {"20": damage},
            "duration_ms": duration, "casts": {"456": count},
            "player_casts": {"456": count} if count else {},
            "player_first_cast_ms": {"456": 100} if count else {},
        }, suffix=str(i)) for i, (damage, duration, count) in enumerate(
            ((100, 60000, 0), (900, 180000, 6), (400, 120000, 8)), 1)]
        spec = SPEC_PROFILE | {"abilities": [{"id": 456, "action_type": "player_cast"}]}
        result = build_benchmark(analyses, PROFILE, spec, EXPECTED, cohort_id="c" * 64)
        self.assertEqual(result["metrics"]["damage_per_minute_median"], 200)
        self.assertEqual(result["metrics"]["duration_ms_median"], 120000)
        self.assertEqual(result["metrics"]["key_action_casts_per_minute_median"], {"456": 2})
        self.assertEqual(result["metrics"]["key_action_rate_sample_count"], {"456": 3})
        self.assertEqual(result["metrics"]["key_action_casts_median"], {"456": 6})
        self.assertNotIn("damage_by_target_median", result["metrics"])

    def test_missing_durations_do_not_become_zero_rates(self) -> None:
        analyses = [self.analysis({"damage_total": 100, "damage_by_target": {"20": 100},
                                   "duration_ms": duration, "casts": {}} , suffix=str(i))
                    for i, duration in enumerate((None, 0, True), 1)]
        result = build_benchmark(analyses, PROFILE, SPEC_PROFILE, EXPECTED, cohort_id="c" * 64)
        self.assertIsNone(result["metrics"]["damage_per_minute_median"])
        self.assertEqual(result["metrics"]["rate_sample_count"], 0)

    def test_report_local_target_ids_cannot_satisfy_npc_eligibility(self) -> None:
        analyses = [self.analysis({"damage_total": 100, "damage_by_target": {"20": 100},
                                   "damage_by_npc": {"999": 100}, "casts": {}}, suffix=str(i))
                    for i in range(1, 4)]
        with self.assertRaisesRegex(InputError, "Fewer than three"):
            build_benchmark(analyses, PROFILE, SPEC_PROFILE, EXPECTED, cohort_id="c" * 64)

    def test_partial_denominators_keep_independent_rate_coverage(self) -> None:
        analyses = [self.analysis({
            "damage_total": damage, "damage_by_target": {"20": damage}, "healing_total": healing,
            "duration_ms": duration, "casts": {"456": 2}, "player_casts": {"456": 2},
        }, suffix=str(i)) for i, (damage, healing, duration) in enumerate(
            ((100, None, 60000), (900, 1000, None), (400, 400, 120000)), 1)]
        spec = SPEC_PROFILE | {"abilities": [{"id": 456, "action_type": "player_cast"}]}
        result = build_benchmark(analyses, PROFILE, spec, EXPECTED, cohort_id="c" * 64)
        metrics = result["metrics"]
        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(metrics["damage_total_median"], 400)
        self.assertEqual(metrics["duration_ms_median"], 90000)
        self.assertEqual(metrics["damage_per_minute_median"], 150)
        self.assertEqual(metrics["rate_sample_count"], 2)
        self.assertEqual(metrics["healing_per_minute_median"], 200)
        self.assertEqual(metrics["healing_rate_sample_count"], 1)
        self.assertEqual(metrics["key_action_casts_per_minute_median"], {"456": 1.5})
        self.assertIsNone(result["reference_samples"][1]["damage_per_minute"])

    def test_key_actions_require_declared_direct_player_casts(self) -> None:
        analyses = [self.analysis({
            "damage_total": 100, "damage_by_target": {"20": 100}, "duration_ms": 60000,
            "casts": {"1": 10, "123": 5, "456": 2, "789": 4},
            "player_casts": {"456": 2, "789": 4}, "owned_actor_casts": {"123": 5},
        }, suffix=str(i)) for i in range(1, 4)]
        spec = SPEC_PROFILE | {"abilities": [
            {"id": 1, "name": "Melee", "action_type": "automatic"},
            {"id": 123, "name": "Birth", "action_type": "internal"},
            {"id": 456, "name": "Action", "action_type": "player_cast"},
            {"id": 789, "name": "Automatic", "action_type": "automatic"},
        ]}
        result = build_benchmark(analyses, PROFILE, spec, EXPECTED, cohort_id="c" * 64)
        self.assertEqual(result["metrics"]["key_action_casts_median"], {"456": 2})
        self.assertEqual(result["metrics"]["casts_median"], analyses[0]["metrics"]["casts"])
        undeclared = build_benchmark(analyses, PROFILE, SPEC_PROFILE, EXPECTED, cohort_id="c" * 64)
        self.assertEqual(undeclared["metrics"]["key_action_casts_median"], {})

    def test_profile_declared_key_action_is_retained_when_all_samples_are_zero(self) -> None:
        analyses = [self.analysis({
            "damage_total": 100, "damage_by_target": {"20": 100}, "duration_ms": 60000,
            "casts": {}, "player_casts": {}, "player_first_cast_ms": {},
        }, suffix=str(i)) for i in range(1, 4)]
        spec = SPEC_PROFILE | {"abilities": [{"id": 456, "action_type": "player_cast"}]}
        metrics = build_benchmark(analyses, PROFILE, spec, EXPECTED, cohort_id="c" * 64)["metrics"]
        self.assertEqual(metrics["key_action_casts_median"], {"456": 0})
        self.assertEqual(metrics["key_action_casts_per_minute_median"], {"456": 0})
        self.assertEqual(metrics["key_action_rate_sample_count"], {"456": 3})
        self.assertEqual(metrics["key_action_first_cast_ms_median"], {"456": None})

    def test_rejects_ambiguous_target_identity_and_previous_benchmark_schema(self) -> None:
        with self.assertRaisesRegex(InputError, "target_id_type"):
            build_benchmark([], PROFILE | {"eligibility": {"priority_target_ids": [20], "excluded_target_ids": []}},
                            SPEC_PROFILE, EXPECTED, cohort_id="c" * 64)
        with self.assertRaisesRegex(InputError, "schema version"):
            verify_benchmark(identify_benchmark({"schema_version": 2, "cohort_id": "c" * 64}))

    def test_healer_samples_require_healing_but_not_priority_target_damage(self) -> None:
        expected = EXPECTED | {"class_name": "Priest", "spec_name": "Discipline"}
        analyses = [self.analysis({"deaths": 0, "damage_total": 0, "healing_total": healing, "damage_by_target": {}, "casts": {}}, expected, str(index)) for index, healing in enumerate((100, 200, 300), 1)]
        healer_profile = SPEC_PROFILE | {"identity": SPEC_PROFILE["identity"] | {"class_name": "Priest", "spec_name": "Discipline"}}
        benchmark = build_benchmark(analyses, PROFILE, healer_profile, expected, cohort_id="c" * 64)
        self.assertEqual(benchmark["role"], "healer")


if __name__ == "__main__":
    unittest.main()
