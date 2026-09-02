from __future__ import annotations

import unittest

from wcl_raid_coach.coach_context import resolve_current_raid
from wcl_raid_coach.coach_models import EncounterDesignator
from wcl_raid_coach.errors import ApiError, InputError


class CoachContextTests(unittest.TestCase):
    def test_resolves_designators_from_the_only_current_zone(self) -> None:
        zones = [
            {"id": 40, "name": "Old Raid", "frozen": True, "encounters": []},
            {
                "id": 42,
                "name": "Current Raid",
                "frozen": False,
                "difficulties": [{"id": 3, "name": "Normal"}, {"id": 4, "name": "Heroic"}],
                "partitions": [
                    {"id": 1, "name": "Pre-Patch", "default": False},
                    {"id": 2, "name": "Current", "compactName": "12.1", "default": True},
                ],
                "encounters": [{"id": 1000 + index, "name": f"Boss {index}"} for index in range(1, 9)],
            },
        ]

        context = resolve_current_raid(
            zones,
            (EncounterDesignator.parse("H7"), EncounterDesignator.parse("H8")),
        )

        self.assertEqual(context["zone"], {"id": 42, "name": "Current Raid"})
        self.assertEqual(context["partition"]["id"], 2)
        self.assertEqual(context["game_version"], "12.1")
        self.assertEqual(context["encounters"][0]["encounter_id"], 1007)
        self.assertEqual(context["encounters"][1]["encounter_name"], "Boss 8")

    def test_refuses_to_guess_between_current_zones(self) -> None:
        zones = [
            {"id": 1, "name": "One", "frozen": False, "difficulties": [{"id": 4, "name": "Heroic"}]},
            {"id": 2, "name": "Two", "frozen": False, "difficulties": [{"id": 4, "name": "Heroic"}]},
        ]
        with self.assertRaises(ApiError):
            resolve_current_raid(zones, (EncounterDesignator.parse("H7"),))

    def test_rejects_designator_outside_zone_order(self) -> None:
        zones = [{
            "id": 1,
            "name": "Current",
            "frozen": False,
            "difficulties": [{"id": 4, "name": "Heroic"}],
            "partitions": [{"id": 2, "name": "Current", "compactName": "12.1", "default": True}],
            "encounters": [{"id": 10, "name": "Only Boss"}],
        }]
        with self.assertRaises(InputError):
            resolve_current_raid(zones, (EncounterDesignator.parse("H7"),))


if __name__ == "__main__":
    unittest.main()
