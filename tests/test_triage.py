import unittest
from unittest.mock import patch

from tests.test_mechanics import FakeClient
from wcl_raid_coach.errors import ApiError, InputError, RateLimitError, RevisionChangedError
from wcl_raid_coach.mechanics import MechanicReviewService, compact_mechanic_review, _triage_selection
from wcl_raid_coach.models import ReportRef


REF = ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")


class TriageTests(unittest.TestCase):
    def test_both_phases_paginate_and_final_revision_is_required(self):
        client = FakeClient({
            2000: {"data": [{"timestamp": 2100, "type": "damage", "targetID": 10,
                             "abilityGameID": 1284941}], "nextPageTimestamp": 2500},
            2500: {"data": [], "nextPageTimestamp": None},
        })
        result = MechanicReviewService(client).triage(REF)
        self.assertEqual(result["mechanics"]["evidence"]["page_count"], 2)
        self.assertEqual(result["windows"][0]["evidence"]["page_count"], 2)
        self.assertEqual(len(client.requests), 4)
        with patch.object(client, "fetch_report_revision", side_effect=[7, 7, 8]):
            with self.assertRaises(RevisionChangedError):
                MechanicReviewService(client).triage(REF)

    def test_ties_time_limits_and_grouping_follow_compact_policy(self):
        def actor(actor_id):
            return {"actor_id": actor_id, "name": str(actor_id), "type": "Player"}
        mechanic = {
            "validation_status": "verified", "anomaly_detection": "enabled", "scope": "target",
            "anomalies": [{"time_ms": time, "actor": actor(actor_id)}
                          for time in (400, 300, 200, 100) for actor_id in (13, 12, 11, 10)],
        }
        compact = compact_mechanic_review({"mechanics": [mechanic, mechanic | {"scope": "team"}]})
        candidates, requests = _triage_selection(compact)
        self.assertEqual([item["actor_id"] for item in candidates], [10, 11, 12])
        self.assertTrue(all(item["record_count"] == 4 for item in candidates))
        self.assertEqual(len(requests), 9)
        self.assertEqual({time for time, _, _ in requests}, {100, 200, 300})
        self.assertTrue(all(len(players) == 1 for _, players, _ in requests))
        grouped = mechanic | {"anomalies": [{"time_ms": 100, "actors": [actor(10), actor(11)]}]}
        _, requests = _triage_selection(compact_mechanic_review({"mechanics": [grouped]}))
        self.assertEqual(requests, [(100, [10, 11], False)])
        for change in ({"scope": "team"}, {"validation_status": "unverified"}, {"anomaly_detection": "disabled"}):
            self.assertEqual(_triage_selection(compact_mechanic_review({"mechanics": [mechanic | change]})), ([], []))

    def test_focused_failure_or_revision_change_never_returns_combined_success(self):
        for failure in (ApiError("EOF"), RateLimitError("cooldown"), RevisionChangedError("changed")):
            client = FakeClient({2000: {"data": [
                {"timestamp": 2100, "type": "damage", "targetID": 10, "abilityGameID": 1284941},
            ], "nextPageTimestamp": None}})
            with patch.object(client, "fetch_focused_events_page", side_effect=failure):
                with self.assertRaises(type(failure)):
                    MechanicReviewService(client).triage(REF)

    def test_death_followup_extends_missing_predeath_window_once(self):
        client = FakeClient()
        service = MechanicReviewService(client)
        actor = {"actor_id": 10, "name": "Alpha", "type": "Player"}
        review = {"identity": {"report_code": "AbC123", "report_revision": 7, "fight_id": 1},
                  "evidence_identity": "identity", "mechanics": [{
                      "validation_status": "verified", "anomaly_detection": "enabled", "scope": "target",
                      "anomalies": [{"actors": [actor, actor | {"actor_id": 11}], "time_ms": 20000}],
                  }]}
        window = {"window": {"from_ms": 10000}, "evidence": {"truncated": False},
                  "events": [{"type": "death", "target_id": 10, "fight_time_ms": 15000},
                             {"type": "death", "target_id": 11, "fight_time_ms": 16000}]}
        with patch.object(service, "review", return_value=review), patch.object(
            service, "focused_evidence", return_value=window,
        ) as focused:
            result = service.triage(REF)
        self.assertEqual(len(result["windows"]), 3)
        self.assertEqual([call.kwargs["at_ms"] for call in focused.call_args_list], [20000, 15000, 16000])
        self.assertEqual(focused.call_args.kwargs["player_ids"], [11])

    def test_matches_separate_commands_with_one_metadata_request(self):
        client = FakeClient({2000: {"data": [
            {"timestamp": 2100, "type": "damage", "targetID": 10, "sourceID": 99,
             "abilityGameID": 1284941, "amount": 20},
        ], "nextPageTimestamp": None}})
        service = MechanicReviewService(client)
        compact = compact_mechanic_review(service.review(REF))
        expected = service.focused_evidence(REF, at_ms=100, window_ms=10000,
                                          player_ids=[10], expected_identity=compact["evidence_identity"])
        with patch.object(client, "fetch_report", wraps=client.fetch_report) as metadata:
            result = service.triage(REF)
        self.assertEqual(metadata.call_count, 1)
        self.assertEqual(result["mechanics"], compact)
        self.assertEqual([candidate["actor_id"] for candidate in result["candidates"]], [10])
        self.assertEqual(result["windows"], [expected])
        self.assertIsNone(result["judgment"])
        self.assertIsNone(result["causal_attribution"])

    def test_no_candidate_skips_windows_and_ambiguous_selection_is_rejected(self):
        client = FakeClient()
        result = MechanicReviewService(client).triage(REF)
        self.assertEqual(result["status"], "no_supported_candidate")
        self.assertEqual(result["windows"], [])
        self.assertFalse(any("focused" in request for request in client.requests))
        for suffix in ("", "#fight=last"):
            with self.assertRaises(InputError):
                MechanicReviewService(client).triage(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123" + suffix))

    def test_revision_change_between_phases_rejects_result_before_focused_fetch(self):
        client = FakeClient({2000: {"data": [
            {"timestamp": 2100, "type": "damage", "targetID": 10, "abilityGameID": 1284941},
        ], "nextPageTimestamp": None}})
        with patch.object(client, "fetch_report_revision", side_effect=[7, 8]):
            with self.assertRaises(RevisionChangedError):
                MechanicReviewService(client).triage(REF)
        self.assertFalse(any("focused" in request for request in client.requests))
