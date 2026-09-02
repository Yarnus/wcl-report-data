from __future__ import annotations

import unittest

from wcl_raid_coach.errors import InputError
from wcl_raid_coach.profiles import validate_profile


SOURCE = {
    "url": "https://example.com/guide",
    "title": "Guide",
    "accessed_at": "2026-09-02T00:00:00Z",
    "quote_summary": "Priority targets define useful damage.",
    "content_hash": "a" * 64,
}


class ProfileTests(unittest.TestCase):
    def test_validates_encounter_profile_and_assigns_stable_identity(self) -> None:
        value = {
            "kind": "encounter",
            "identity": {"game_version": "retail", "partition_id": 2, "encounter_id": 1007, "difficulty_id": 4},
            "eligibility": {"priority_target_ids": [10], "excluded_target_ids": [20]},
            "phases": [{"id": 1, "name": "Phase 1"}],
            "mechanic_anchors": [{"ability_id": 1, "name": "Mechanic"}],
            "sources": [SOURCE],
        }
        first = validate_profile(value)
        second = validate_profile(value)
        self.assertEqual(first["profile_id"], second["profile_id"])

    def test_rejects_encounter_profile_without_eligibility_rules(self) -> None:
        value = {
            "kind": "encounter",
            "identity": {"game_version": "retail", "partition_id": 2, "encounter_id": 1007, "difficulty_id": 4},
            "phases": [{"id": 1}],
            "mechanic_anchors": [{"ability_id": 1}],
            "sources": [SOURCE],
        }
        with self.assertRaises(InputError):
            validate_profile(value)

    def test_rejects_an_encounter_profile_with_a_malformed_mechanic_anchor(self) -> None:
        value = {
            "kind": "encounter",
            "identity": {"game_version": "retail", "partition_id": 2, "encounter_id": 1007, "difficulty_id": 4},
            "eligibility": {"priority_target_ids": [10], "excluded_target_ids": [20]},
            "phases": [{"id": 1, "name": "Phase 1"}],
            "mechanic_anchors": [{"ability_id": True, "name": "Mechanic"}],
            "sources": [SOURCE],
        }
        with self.assertRaises(InputError):
            validate_profile(value)


if __name__ == "__main__":
    unittest.main()
