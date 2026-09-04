from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

from wcl_raid_coach.cohort import build_benchmark, extract_ranking_candidates, identify_benchmark, identify_cohort, validate_analysis_membership, verify_benchmark, verify_cohort
from wcl_raid_coach.errors import InputError
from wcl_raid_coach.storage import sha256_file


PROFILE = {
    "kind": "encounter",
    "identity": {"game_version": "retail", "partition_id": 2, "encounter_id": 1007, "difficulty_id": 4},
    "eligibility": {"priority_target_ids": [20], "excluded_target_ids": [30]},
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
            "identity": {"report_code": f"ABC{suffix}", "report_revision": 1, "fight_id": int(suffix)},
            "player": {"actor_id": 10, "name": "Player"},
            "evidence": {"manifest_path": f"/tmp/manifest-{suffix}.json", "manifest_sha256": "hash", "index_path": f"/tmp/index-{suffix}.json", "index_sha256": "hash"},
            "comparison_identity": expected,
            "metrics": metrics,
        }

    def test_extracts_only_recent_candidates_with_complete_identity(self) -> None:
        payload = {"rankings": [
            {"reportCode": "ABC", "fightID": 7, "sourceID": 10, "startTime": "2026-09-01T00:00:00Z"},
            {"reportCode": "OLD", "fightID": 8, "sourceID": 11, "startTime": "2026-07-01T00:00:00Z"},
            {"reportCode": "MISS", "fightID": 9},
        ]}
        result = extract_ranking_candidates(payload, now=datetime(2026, 9, 2, tzinfo=timezone.utc))
        self.assertEqual([item["report_code"] for item in result["eligible_recent_candidates"]], ["ABC"])
        self.assertEqual(len(result["rejected_candidates"]), 1)
        self.assertIsNone(result["unverified_recency_candidates"][0]["source_id"])

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
        benchmark = identify_benchmark({"schema_version": 2, "identity": EXPECTED})
        with self.assertRaisesRegex(InputError, "Ranking Cohort content ID"):
            verify_benchmark(benchmark)

    def test_content_addressed_benchmark_rejects_edits(self) -> None:
        benchmark = identify_benchmark({"schema_version": 2, "cohort_id": "c" * 64, "identity": dict(EXPECTED), "sample_count": 3})
        verify_benchmark(benchmark)
        self.assertRegex(benchmark["benchmark_id"], r"^[0-9a-f]{64}$")
        self.assertNotIn("signature", benchmark)
        benchmark["sample_count"] = 4
        with self.assertRaises(InputError):
            verify_benchmark(benchmark)

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

    def test_rejects_mixed_encounter_samples(self) -> None:
        analyses = [self.analysis({"deaths": 0, "damage_total": 100, "damage_by_target": {"20": 100}, "casts": {}}, EXPECTED | {"encounter_id": 1008}, str(index)) for index in range(1, 4)]
        with self.assertRaises(InputError):
            build_benchmark(analyses, PROFILE, SPEC_PROFILE, EXPECTED, cohort_id="c" * 64)

    def test_healer_samples_require_healing_but_not_priority_target_damage(self) -> None:
        expected = EXPECTED | {"class_name": "Priest", "spec_name": "Discipline"}
        analyses = [self.analysis({"deaths": 0, "damage_total": 0, "healing_total": healing, "damage_by_target": {}, "casts": {}}, expected, str(index)) for index, healing in enumerate((100, 200, 300), 1)]
        healer_profile = SPEC_PROFILE | {"identity": SPEC_PROFILE["identity"] | {"class_name": "Priest", "spec_name": "Discipline"}}
        benchmark = build_benchmark(analyses, PROFILE, healer_profile, expected, cohort_id="c" * 64)
        self.assertEqual(benchmark["role"], "healer")


if __name__ == "__main__":
    unittest.main()
