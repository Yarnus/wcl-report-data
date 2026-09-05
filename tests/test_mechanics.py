from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from wcl_raid_coach.errors import ApiError, RevisionChangedError
from wcl_raid_coach.mechanic_rules import RAID_ENCOUNTERS, RULES, build_filter_expression, rules_for
from wcl_raid_coach.mechanics import MechanicReviewService, compact_mechanic_review, evaluate_rules
from wcl_raid_coach.models import ReportRef
from wcl_raid_coach.report_documents import create_mechanic_review_report


def report_fixture() -> dict:
    return {
        "code": "AbC123",
        "visibility": "public",
        "revision": 7,
        "startTime": 1_000,
        "endTime": 9_000,
        "archiveStatus": {"isArchived": False, "isAccessible": True},
        "zone": {
            "id": 53,
            "name": "The Venomous Abyss",
            "difficulties": [
                {"id": 3, "name": "Normal"},
                {"id": 4, "name": "Heroic"},
                {"id": 5, "name": "Mythic"},
            ],
            "encounters": [
                {"id": encounter_id, "name": name_en}
                for encounter_id, name_en, _name_zh in RAID_ENCOUNTERS
            ]
            + [{"id": 3379, "name": "Nymrissa Wavecaller"}],
        },
        "masterData": {
            "gameVersion": 1,
            "actors": [
                {"id": 10, "name": "Alpha", "type": "Player"},
                {"id": 11, "name": "Bravo", "type": "Player"},
                {"id": 12, "name": "Charlie", "type": "Player"},
                {"id": 13, "name": "Delta", "type": "Player"},
                {"id": 14, "name": "Echo", "type": "Player"},
                {"id": 15, "name": "Foxtrot", "type": "Player"},
            ],
            "abilities": [],
        },
        "fights": [
            {
                "id": 1,
                "encounterID": 3445,
                "name": "Entombed Sentinels",
                "startTime": 2_000,
                "endTime": 5_000,
                "kill": False,
                "inProgress": False,
                "difficulty": 4,
                "friendlyPlayers": [10, 11, 12, 13],
            },
            {
                "id": 2,
                "encounterID": 3379,
                "name": "Nymrissa Wavecaller",
                "startTime": 6_000,
                "endTime": 8_000,
                "kill": True,
                "inProgress": False,
                "difficulty": 4,
                "friendlyPlayers": [10, 11, 12, 13],
            },
        ],
    }


class FakeClient:
    def __init__(self, pages: dict[float, dict] | None = None) -> None:
        self.report = report_fixture()
        self.pages = pages or {2_000: {"data": [], "nextPageTimestamp": None}}
        self.revision = 7
        self.requests: list[tuple[str, int, float, float, str]] = []

    def fetch_report(self, code: str):
        return copy.deepcopy(self.report), None

    def fetch_mechanic_events_page(
        self, code: str, fight_id: int, start_time: float, end_time: float, filter_expression: str,
    ) -> dict:
        self.requests.append((code, fight_id, start_time, end_time, filter_expression))
        return copy.deepcopy(self.pages[start_time])

    def fetch_focused_events_page(
        self, code: str, fight_id: int, start_time: float, end_time: float, target_id: int
    ) -> dict:
        self.requests.append((code, fight_id, start_time, end_time, "focused", target_id))
        return copy.deepcopy(self.pages[start_time])

    def fetch_report_revision(self, code: str) -> int:
        return self.revision


class MechanicRuleTests(unittest.TestCase):
    def test_catalog_covers_the_official_eight_bosses_at_three_difficulties(self) -> None:
        self.assertEqual(len(RAID_ENCOUNTERS), 8)
        self.assertNotIn(3379, {item[0] for item in RAID_ENCOUNTERS})
        for encounter_id, _name_en, _name_zh in RAID_ENCOUNTERS:
            for difficulty_id in (3, 4, 5):
                self.assertTrue(rules_for(encounter_id, difficulty_id))

    def test_filter_expression_contains_rule_abilities_and_deaths(self) -> None:
        expression = build_filter_expression(rules_for(3445, 4))

        self.assertIn("ability.id = 1284590", expression)
        self.assertIn('type = "death"', expression)

    def test_mythic_ulatek_is_defined_but_event_patterns_are_unverified(self) -> None:
        rules = rules_for(3492, 5)

        self.assertTrue(rules)
        self.assertTrue(all(5 not in rule.verified_difficulties for rule in rules))

        result = evaluate_rules(
            3492,
            5,
            [{"timestamp": 2_100, "type": "damage", "targetID": 10, "abilityGameID": 1292403}],
            report_fixture()["masterData"]["actors"],
            2_000,
        )
        rule = next(item for item in result if item["rule_id"] == "ULATEK-WAVES")
        self.assertEqual(rule["anomaly_detection"], "event_pattern_unverified")
        self.assertIsNone(rule["summary"]["success_count"])
        self.assertIsNone(rule["summary"]["failure_count"])
        self.assertEqual(rule["anomalies"], [])

    def test_verified_difficulties_are_limited_to_each_rule_scope(self) -> None:
        for rule in RULES:
            self.assertLessEqual(set(rule.verified_difficulties), set(rule.difficulties))


class MechanicReviewServiceTests(unittest.TestCase):
    def test_compact_review_removes_raw_payloads_and_summarizes_pet_noise(self) -> None:
        review = {
            "action": "coach_mechanics",
            "selection_required": False,
            "evidence": {"event_count": 20},
            "mechanics": [{
                "rule_id": "TEST",
                "name_zh": "测试机制",
                "summary": {"failure_count": 3},
                "anomalies": [
                    {
                        "time_ms": 1_000.0,
                        "event_type": "damage",
                        "event_count": 1,
                        "actor": {"actor_id": 10, "name": "Alpha", "type": "Player"},
                        "raw_event": {"amount": 100},
                    },
                    {
                        "time_ms": 1_000.0,
                        "event_type": "damage",
                        "event_count": 2,
                        "actor": {"actor_id": 20, "name": "Pet", "type": "Pet"},
                        "raw_event": {"amount": 10},
                    },
                ],
            }],
        }

        compact = compact_mechanic_review(review)

        self.assertEqual(compact["output_mode"], "compact")
        mechanic = compact["mechanics"][0]
        self.assertEqual(mechanic["anomalies"], [{
            "time_ms": 1_000.0,
            "event_type": "damage",
            "event_count": 1,
            "actor": {"actor_id": 10, "name": "Alpha", "type": "Player"},
        }])
        self.assertEqual(mechanic["suppressed_anomalies"], {"pet_or_npc_records": 1, "event_count": 2})
        self.assertNotIn("raw_event", str(compact))

    def test_bare_report_lists_only_supported_boss_attempts(self) -> None:
        result = MechanicReviewService(FakeClient()).review(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123"))

        self.assertTrue(result["selection_required"])
        self.assertEqual([choice["fight_id"] for choice in result["fight_choices"]], [1])

    def test_selected_attempt_fetches_filtered_pages_in_memory(self) -> None:
        client = FakeClient()

        result = MechanicReviewService(client).review(
            ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
        )

        self.assertFalse(result["selection_required"])
        self.assertEqual(result["identity"]["report_revision"], 7)
        self.assertEqual(result["evidence"]["storage"], "process_memory")
        self.assertEqual(client.requests[0][2:4], (2_000.0, 5_000.0))
        self.assertIn("ability.id = 1284590", client.requests[0][4])

    def test_selected_attempt_rejects_a_revision_change(self) -> None:
        client = FakeClient()
        client.revision = 8

        with self.assertRaises(RevisionChangedError):
            MechanicReviewService(client).review(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            )

    def test_incomplete_pagination_and_revision_change_publish_no_report_artifacts(self) -> None:
        clients = [
            FakeClient({2_000: {"data": []}}),
            FakeClient(),
        ]
        clients[1].revision = 8
        for client in clients:
            with self.subTest(client=client), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with self.assertRaises((ApiError, RevisionChangedError)):
                    review = MechanicReviewService(client).review(
                        ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
                    )
                    create_mechanic_review_report(review, root, locale="en")
                self.assertFalse((root / "outputs").exists())

    def test_rules_use_the_report_difficulty_mapping_instead_of_global_ids(self) -> None:
        client = FakeClient()
        client.report["zone"]["difficulties"][1]["id"] = 14
        client.report["fights"][0]["difficulty"] = 14

        result = MechanicReviewService(client).review(
            ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
        )

        self.assertEqual(result["identity"]["difficulty_id"], 14)
        self.assertTrue(result["mechanics"])

    def test_rejects_boolean_revision_and_non_finite_fight_times(self) -> None:
        client = FakeClient()
        client.report["revision"] = True
        with self.assertRaises(ApiError):
            MechanicReviewService(client).review(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            )

        client.report["revision"] = 7
        client.report["fights"][0]["startTime"] = float("nan")
        with self.assertRaises(ApiError):
            MechanicReviewService(client).review(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            )

    def test_rejects_events_before_the_current_page_cursor(self) -> None:
        client = FakeClient(
            {
                2_000: {"data": [], "nextPageTimestamp": 3_000},
                3_000: {
                    "data": [
                        {"timestamp": 2_999, "type": "death", "abilityGameID": 0, "targetID": 10}
                    ],
                    "nextPageTimestamp": None,
                },
            }
        )

        with self.assertRaises(ApiError):
            MechanicReviewService(client).review(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            )

    def test_accepts_a_death_event_without_an_ability_id(self) -> None:
        client = FakeClient(
            {2_000: {"data": [{"timestamp": 3_000, "type": "death", "targetID": 10}], "nextPageTimestamp": None}}
        )

        result = MechanicReviewService(client).review(
            ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
        )

        self.assertEqual(result["evidence"]["event_count"], 1)

    def test_focused_evidence_fetches_only_the_player_window_and_sanitizes_events(self) -> None:
        client = FakeClient(
            {
                2_500: {
                    "data": [
                        {
                            "timestamp": 3_000,
                            "type": "damage",
                            "sourceID": 99,
                            "targetID": 10,
                            "abilityGameID": 1284941,
                            "amount": 123,
                            "hitPoints": 456,
                            "unknown": "not persisted",
                        }
                    ],
                    "nextPageTimestamp": None,
                }
            }
        )

        result = MechanicReviewService(client).focused_evidence(
            ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"),
            at_ms=1_000,
            window_ms=500,
            player_ids=[10],
        )

        self.assertEqual(client.requests[0][2:4], (2_500.0, 3_500.0))
        self.assertEqual(client.requests[0][4], "focused")
        self.assertEqual(client.requests[0][5], 10)
        self.assertEqual(result["evidence"]["class"], "focused_event_window")
        self.assertEqual(result["evidence"]["fetched_event_count"], 1)
        self.assertEqual(result["evidence"]["server_filter"], "target_id")
        self.assertEqual(result["window"], {"at_ms": 1_000.0, "from_ms": 500.0, "to_ms": 1_500.0})
        self.assertEqual(result["players"], [{"actor_id": 10, "name": "Alpha"}])
        self.assertEqual(result["events"], [{
            "fight_time_ms": 1_000.0,
            "type": "damage",
            "source_id": 99,
            "target_id": 10,
            "ability_id": 1284941,
            "amount": 123,
            "hit_points": 456,
        }])

    def test_focused_evidence_discards_window_events_unrelated_to_the_player(self) -> None:
        client = FakeClient(
            {
                2_500: {
                    "data": [
                        {"timestamp": 3_000, "type": "damage", "sourceID": 99, "targetID": 11, "abilityGameID": 1},
                        {"timestamp": 3_001, "type": "heal", "sourceID": 11, "targetID": 10, "abilityGameID": 2},
                    ],
                    "nextPageTimestamp": None,
                }
            }
        )

        result = MechanicReviewService(client).focused_evidence(
            ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"),
            at_ms=1_000,
            window_ms=500,
            player_ids=[10],
        )

        self.assertEqual(result["evidence"]["fetched_event_count"], 2)
        self.assertEqual(result["evidence"]["event_count"], 1)
        self.assertEqual(result["events"][0]["type"], "heal")

    def test_focused_evidence_rejects_non_participants(self) -> None:
        with self.assertRaisesRegex(Exception, "participant"):
            MechanicReviewService(FakeClient()).focused_evidence(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"),
                at_ms=1_000,
                window_ms=500,
                player_ids=[99],
            )

    def test_focused_evidence_rejects_a_non_focused_window(self) -> None:
        with self.assertRaisesRegex(Exception, "30000"):
            MechanicReviewService(FakeClient()).focused_evidence(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"),
                at_ms=1_000,
                window_ms=30_001,
                player_ids=[10],
            )

    def test_bare_report_rejects_a_malformed_boss_attempt(self) -> None:
        client = FakeClient()
        client.report["fights"][0]["startTime"] = float("nan")

        with self.assertRaises(ApiError):
            MechanicReviewService(client).review(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123")
            )

    def test_rejects_an_event_timestamp_too_large_for_finite_validation(self) -> None:
        client = FakeClient(
            {
                2_000: {
                    "data": [{"timestamp": 10**10_000, "type": "death", "targetID": 10}],
                    "nextPageTimestamp": None,
                }
            }
        )

        with self.assertRaises(ApiError):
            MechanicReviewService(client).review(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            )


class MechanicEvaluationTests(unittest.TestCase):
    def test_helical_toxins_reports_successful_pairs_and_one_failure_episode(self) -> None:
        events = [
            {"timestamp": 2_100 + actor, "type": "applydebuff", "targetID": actor, "abilityGameID": 1284590}
            for actor in (10, 11, 12, 13, 14, 15)
        ] + [
            {"timestamp": 3_000, "type": "removedebuff", "targetID": 10, "abilityGameID": 1284590},
            {"timestamp": 3_000, "type": "removedebuff", "targetID": 11, "abilityGameID": 1284590},
            {"timestamp": 4_000, "type": "damage", "targetID": 12, "abilityGameID": 1284941},
            {"timestamp": 4_010, "type": "damage", "targetID": 13, "abilityGameID": 1284941},
            {"timestamp": 4_020, "type": "damage", "targetID": 14, "abilityGameID": 1284941},
            {"timestamp": 4_030, "type": "damage", "targetID": 15, "abilityGameID": 1284941},
        ]

        result = evaluate_rules(3445, 4, events, report_fixture()["masterData"]["actors"], 2_000)
        rule = next(item for item in result if item["rule_id"] == "SENT-HELICAL")

        self.assertEqual(rule["summary"]["participants"], 6)
        self.assertEqual(rule["summary"]["trigger_count"], 6)
        self.assertEqual(rule["summary"]["success_count"], 2)
        self.assertEqual(rule["summary"]["failure_count"], 4)
        self.assertEqual(rule["summary"]["coincident_removal_pairs"], 1)
        self.assertEqual(rule["summary"]["failed_participants"], 4)
        self.assertEqual(rule["summary"]["failure_episodes"], 1)
        self.assertEqual(
            {item["actor"]["name"] for item in rule["anomalies"]},
            {"Charlie", "Delta", "Echo", "Foxtrot"},
        )

    def test_turbulent_gusts_reports_pairs_and_unpaired_removals(self) -> None:
        events = [
            {"timestamp": 2_100, "type": "applydebuff", "targetID": actor, "abilityGameID": 1285447}
            for actor in (10, 11, 12)
        ] + [
            {"timestamp": 2_500, "type": "removedebuff", "targetID": 10, "abilityGameID": 1285447},
            {"timestamp": 2_500, "type": "removedebuff", "targetID": 11, "abilityGameID": 1285447},
            {"timestamp": 8_100, "type": "removedebuff", "targetID": 12, "abilityGameID": 1285447},
        ]

        result = evaluate_rules(3420, 4, events, report_fixture()["masterData"]["actors"], 2_000)
        rule = next(item for item in result if item["rule_id"] == "SSZ-TURBULENT")

        self.assertEqual(rule["summary"]["coincident_removal_pairs"], 1)
        self.assertEqual(rule["summary"]["trigger_count"], 3)
        self.assertEqual(rule["summary"]["success_count"], 2)
        self.assertEqual(rule["summary"]["failure_count"], 1)
        self.assertEqual(rule["summary"]["unresolved_outcomes"], 1)
        self.assertEqual(rule["anomalies"][0]["actor"]["name"], "Charlie")
        self.assertEqual(rule["anomalies"][0]["outcome"], "aura_expired")
        self.assertEqual(rule["anomalies"][0]["raw_event"]["targetID"], 12)

    def test_turbulent_gusts_recognizes_death_during_the_aura(self) -> None:
        events = [
            {"timestamp": 2_100, "type": "applydebuff", "targetID": 10, "abilityGameID": 1285447},
            {"timestamp": 7_900, "type": "death", "targetID": 10},
        ]

        result = evaluate_rules(3420, 4, events, report_fixture()["masterData"]["actors"], 2_000)
        rule = next(item for item in result if item["rule_id"] == "SSZ-TURBULENT")

        self.assertEqual(rule["anomalies"][0]["outcome"], "death")
        self.assertEqual(rule["anomalies"][0]["raw_event"]["type"], "death")

    def test_turbulent_gusts_does_not_count_death_removals_as_successes(self) -> None:
        events = [
            {"timestamp": 2_100, "type": "applydebuff", "targetID": actor, "abilityGameID": 1285447}
            for actor in (10, 11)
        ] + [
            {"timestamp": 2_500, "type": "removedebuff", "targetID": actor, "abilityGameID": 1285447}
            for actor in (10, 11)
        ] + [
            {"timestamp": 2_500, "type": "death", "targetID": actor}
            for actor in (10, 11)
        ]

        result = evaluate_rules(3420, 4, events, report_fixture()["masterData"]["actors"], 2_000)
        rule = next(item for item in result if item["rule_id"] == "SSZ-TURBULENT")

        self.assertEqual(rule["summary"]["success_count"], 0)
        self.assertEqual(rule["summary"]["failure_count"], 2)
        self.assertEqual([item["outcome"] for item in rule["anomalies"]], ["death", "death"])

    def test_turbulent_gusts_does_not_blame_a_survivor_paired_with_a_death(self) -> None:
        events = [
            {"timestamp": 2_100, "type": "applydebuff", "targetID": actor, "abilityGameID": 1285447}
            for actor in (10, 11)
        ] + [
            {"timestamp": 2_500, "type": "removedebuff", "targetID": actor, "abilityGameID": 1285447}
            for actor in (10, 11)
        ] + [{"timestamp": 2_500, "type": "death", "targetID": 10}]

        result = evaluate_rules(3420, 4, events, report_fixture()["masterData"]["actors"], 2_000)
        rule = next(item for item in result if item["rule_id"] == "SSZ-TURBULENT")

        self.assertEqual(rule["summary"]["success_count"], 1)
        self.assertEqual(rule["summary"]["failure_count"], 1)
        self.assertEqual(rule["anomalies"][0]["actor"]["name"], "Alpha")
        self.assertEqual(rule["anomalies"][0]["outcome"], "death")

    def test_turbulent_gusts_does_not_pick_one_player_from_an_ambiguous_group(self) -> None:
        events = [
            {"timestamp": 2_100, "type": "applydebuff", "targetID": actor, "abilityGameID": 1285447}
            for actor in (10, 11, 12)
        ] + [
            {"timestamp": 2_500, "type": "removedebuff", "targetID": actor, "abilityGameID": 1285447}
            for actor in (10, 11, 12)
        ]

        result = evaluate_rules(3420, 4, events, report_fixture()["masterData"]["actors"], 2_000)
        rule = next(item for item in result if item["rule_id"] == "SSZ-TURBULENT")

        self.assertEqual(rule["anomalies"][0]["outcome"], "ambiguous_unpaired_removal")
        self.assertNotIn("actor", rule["anomalies"][0])
        self.assertEqual(len(rule["anomalies"][0]["actors"]), 3)

    def test_helical_failure_count_includes_repeated_participant_failures(self) -> None:
        events = []
        for timestamp in (2_100, 4_100):
            events.extend(
                {"timestamp": timestamp, "type": "applydebuff", "targetID": actor, "abilityGameID": 1284590}
                for actor in (10, 11, 12, 13)
            )
            events.extend(
                {"timestamp": timestamp + 1_000, "type": "damage", "targetID": actor, "abilityGameID": 1284941}
                for actor in (10, 11, 12, 13)
            )

        result = evaluate_rules(3445, 4, events, report_fixture()["masterData"]["actors"], 2_000)
        rule = next(item for item in result if item["rule_id"] == "SENT-HELICAL")

        self.assertEqual(rule["summary"]["failure_count"], 8)
        self.assertEqual(rule["summary"]["failed_participants"], 4)
        self.assertEqual(rule["summary"]["failure_episodes"], 2)


if __name__ == "__main__":
    unittest.main()
