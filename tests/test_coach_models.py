from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wcl_raid_coach.coach_models import CoachRequest, EncounterDesignator, parse_specialization, specialization_role
from wcl_raid_coach.coach_tasks import CoachTaskStore
from wcl_raid_coach.errors import InputError


class CoachModelTests(unittest.TestCase):
    def test_normalizes_unholy_dk_and_encounter_designators(self) -> None:
        request = CoachRequest(
            content_type="retail_raid",
            mode="raid_guide",
            specialization=parse_specialization("邪 DK"),
            encounter_designators=(EncounterDesignator.parse("h7"), EncounterDesignator.parse("H8")),
        )

        self.assertEqual(request.specialization.spec_name, "Unholy")
        self.assertEqual(request.as_dict()["encounter_designators"][0]["value"], "H7")

    def test_rejects_ambiguous_specialization(self) -> None:
        with self.assertRaises(InputError):
            parse_specialization("DK")

    def test_normalizes_healer_and_tank_roles(self) -> None:
        healer = parse_specialization("戒律牧")
        tank = parse_specialization("熊德")
        self.assertEqual(specialization_role(healer.class_name, healer.spec_name), "healer")
        self.assertEqual(specialization_role(tank.class_name, tank.spec_name), "tank")

    def test_request_fingerprint_is_stable(self) -> None:
        request = CoachRequest(content_type="retail_raid", mode="raid_guide", encounter_designators=(EncounterDesignator.parse("H7"),))
        self.assertEqual(request.fingerprint(), request.fingerprint())
        self.assertNotEqual(request.fingerprint(context={"partition_id": 1}), request.fingerprint(context={"partition_id": 2}))

    def test_task_store_resumes_same_request(self) -> None:
        request = CoachRequest(content_type="retail_raid", mode="raid_guide", encounter_designators=(EncounterDesignator.parse("H7"),))
        with tempfile.TemporaryDirectory() as directory:
            store = CoachTaskStore(Path(directory))
            first = store.create_or_resume(request)
            second = store.create_or_resume(request)

        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(second["status"], "pending_confirmation")

    def test_task_store_requires_explicit_confirmation(self) -> None:
        request = CoachRequest(content_type="retail_raid", mode="raid_guide", encounter_designators=(EncounterDesignator.parse("H7"),))
        with tempfile.TemporaryDirectory() as directory:
            store = CoachTaskStore(Path(directory))
            task = store.create_or_resume(request)
            confirmed = store.confirm(task["task_id"])
        self.assertEqual(confirmed["status"], "confirmed")

    def test_task_store_records_partial_multi_encounter_progress(self) -> None:
        request = CoachRequest(content_type="retail_raid", mode="raid_guide", encounter_designators=(EncounterDesignator.parse("H7"), EncounterDesignator.parse("H8")))
        with tempfile.TemporaryDirectory() as directory:
            store = CoachTaskStore(Path(directory))
            task = store.create_or_resume(request)
            store.confirm(task["task_id"])
            artifact = Path(directory) / "h7.json"
            artifact.write_text("{}", encoding="utf-8")
            partial = store.record_encounter(task["task_id"], designator="H7", status="completed", artifacts={"benchmark": str(artifact)})
            blocked = store.record_encounter(task["task_id"], designator="H8", status="blocked", blocker="wcl_rate_limit")
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(blocked["status"], "partial")
        self.assertEqual(blocked["encounters"][1]["blocker"], "wcl_rate_limit")


if __name__ == "__main__":
    unittest.main()
