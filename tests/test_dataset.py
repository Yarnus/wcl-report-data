from __future__ import annotations

import copy
import gzip
import hashlib
import json
import multiprocessing
import os
import tempfile
import threading
import unittest
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch

from wcl_raid_coach.dataset import DatasetService, DatasetStore, query_bundle
from wcl_raid_coach.errors import ApiError, DatasetError, InputError, RevisionChangedError
from wcl_raid_coach.models import ReportRef


def report_fixture() -> dict:
    return {
        "code": "AbC123",
        "title": "Team Raid",
        "visibility": "public",
        "revision": 3,
        "startTime": 1_700_000_000_000,
        "endTime": 1_700_000_020_000,
        "archiveStatus": {"isArchived": False, "isAccessible": True},
        "zone": {
            "id": 42,
            "name": "Test Raid",
            "difficulties": [{"id": 5, "name": "Mythic", "sizes": [20]}],
            "encounters": [
                {"id": 4001, "name": "First Boss"},
                {"id": 5001, "name": "Test Boss"},
            ],
        },
        "masterData": {
            "logVersion": 99,
            "gameVersion": 1,
            "lang": "en",
            "actors": [
                {"id": 10, "gameID": 1, "name": "Tank", "server": "Realm", "type": "Player", "subType": "Warrior", "petOwner": None},
                {"id": 11, "gameID": 2, "name": "Healer", "server": "Realm", "type": "Player", "subType": "Priest", "petOwner": None},
                {"id": 100, "gameID": 9001, "name": "Boss", "server": None, "type": "NPC", "subType": "Boss", "petOwner": None},
            ],
            "abilities": [
                {"gameID": 7001, "name": "Heavy Hit", "type": 1, "icon": "spell"},
                {"gameID": 7002, "name": "Heal", "type": 2, "icon": "heal"},
            ],
        },
        "fights": [
            {
                "id": 1,
                "encounterID": 5001,
                "name": "Test Boss",
                "startTime": 1_000,
                "endTime": 5_000,
                "kill": False,
                "inProgress": False,
                "difficulty": 5,
                "size": 2,
                "friendlyPlayers": [10, 11],
                "friendlySpecs": ["Protection", "Holy"],
                "friendlyItemLevels": [600, 601],
                "phaseTransitions": [{"id": 1, "startTime": 1_000}],
            },
            {
                "id": 2,
                "encounterID": 0,
                "name": "Trash",
                "startTime": 6_000,
                "endTime": 7_000,
                "kill": False,
                "inProgress": False,
                "difficulty": None,
                "size": None,
                "friendlyPlayers": [10, 11],
                "friendlySpecs": ["Protection", "Holy"],
                "friendlyItemLevels": [600, 601],
                "phaseTransitions": [],
            },
            {
                "id": 3,
                "encounterID": 5001,
                "name": "Test Boss",
                "startTime": 8_000,
                "endTime": 10_000,
                "kill": False,
                "inProgress": True,
                "difficulty": 5,
                "size": 2,
                "friendlyPlayers": [10, 11],
                "friendlySpecs": ["Protection", "Holy"],
                "friendlyItemLevels": [600, 601],
                "phaseTransitions": [],
            },
        ],
    }


class FakeClient:
    def __init__(self, pages: dict[float | None, dict] | None = None) -> None:
        self.report = report_fixture()
        self.pages = pages or {}
        self.page_starts: list[float | None] = []
        self.page_ranges: list[tuple[float | None, float]] = []
        self.fail_at: float | None | object = object()
        self.revision = 3

    def fetch_report(self, code: str) -> tuple[dict, dict]:
        if code != "AbC123":
            raise AssertionError(code)
        return copy.deepcopy(self.report), {
            "limitPerHour": 3600,
            "pointsSpentThisHour": 10,
            "pointsResetIn": 100,
        }

    def fetch_events_page(
        self,
        code: str,
        fight_id: int,
        start_time: float | None,
        end_time: float,
        limit: int = 10_000,
    ) -> dict:
        self.page_starts.append(start_time)
        self.page_ranges.append((start_time, end_time))
        if start_time == self.fail_at:
            raise ApiError("temporary failure")
        return copy.deepcopy(self.pages[start_time])

    def fetch_report_revision(self, code: str) -> int:
        return self.revision


class BlockingClient(FakeClient):
    def __init__(self, pages: dict[float | None, dict]) -> None:
        super().__init__(pages)
        self.page_requested = threading.Event()
        self.resume = threading.Event()

    def fetch_events_page(
        self,
        code: str,
        fight_id: int,
        start_time: float | None,
        end_time: float,
        limit: int = 10_000,
    ) -> dict:
        self.page_requested.set()
        self.resume.wait(timeout=5)
        return super().fetch_events_page(code, fight_id, start_time, end_time, limit)


def _hold_prepare_lock(data_root: str, cache_root: str, ready, resume) -> None:
    store = DatasetStore(Path(data_root), Path(cache_root))
    with store.prepare_lock("AbC123"):
        ready.set()
        resume.wait(timeout=5)


def event_pages() -> dict[float | None, dict]:
    return {
        1_000: {
            "data": [
                {
                    "timestamp": 1_100,
                    "type": "damage",
                    "sourceID": 100,
                    "sourceInstance": 1,
                    "targetID": 10,
                    "abilityGameID": 7001,
                    "amount": 100,
                    "absorbed": 20,
                    "hitPoints": 900,
                    "killingAbilityGameID": 7001,
                    "killerInstance": 2,
                    "healerInstance": 3,
                    "targetResources": {"hitPoints": 900, "maxHitPoints": 1_000},
                    "mystery": "kept only in raw page",
                }
            ],
            "nextPageTimestamp": 2_000,
        },
        2_000: {
            "data": [
                {
                    "timestamp": 2_100,
                    "type": "heal",
                    "sourceID": 11,
                    "targetID": 10,
                    "abilityGameID": 7002,
                    "amount": 80,
                    "overheal": 5,
                }
            ],
            "nextPageTimestamp": None,
        },
    }


def _capture_error(errors: list[Exception], function, *args) -> None:
    try:
        function(*args)
    except Exception as exc:
        errors.append(exc)


class DatasetTests(unittest.TestCase):
    def make_service(self, temporary: str, client: FakeClient) -> DatasetService:
        root = Path(temporary)
        return DatasetService(client, DatasetStore(root / "data", root / "cache"))

    def test_inspect_persists_team_index_without_source_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.make_service(temporary, FakeClient())
            result = service.inspect(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1&source=10")
            )
            index = json.loads(Path(result["index_path"]).read_text(encoding="utf-8"))

        self.assertEqual(result["selected_fight_id"], 1)
        self.assertEqual(result["input_reference"]["source_hint"], 10)
        self.assertNotIn("input_reference", index)
        self.assertNotIn("encounters", index["report"]["zone"])
        self.assertEqual(
            result["encounter_choices"],
            [
                {"ordinal": 1, "encounter_id": 4001, "name": "First Boss"},
                {"ordinal": 2, "encounter_id": 5001, "name": "Test Boss"},
            ],
        )
        self.assertEqual([item["actor_id"] for item in index["fights"][0]["participants"]], [10, 11])
        self.assertEqual(index["fights"][1]["kind"], "trash")
        self.assertFalse(index["fights"][2]["packable"])

    def test_inspect_resolves_difficulty_name_from_report_zone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = FakeClient()
            client.report["zone"]["difficulties"] = [
                {"id": 4, "name": "Heroic", "sizes": [10, 20]},
                {"id": 5, "name": "Mythic", "sizes": [20]},
            ]
            client.report["fights"][0]["difficulty"] = 4
            service = self.make_service(temporary, client)
            result = service.inspect(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            )

        self.assertEqual(result["selected_fight"]["difficulty"], 4)
        self.assertEqual(result["selected_fight"]["difficulty_name"], "Heroic")
        self.assertEqual(result["fight_choices"][0]["difficulty_name"], "Heroic")

    def test_encounter_choices_do_not_change_the_immutable_report_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = FakeClient()
            service = self.make_service(temporary, client)
            ref = ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123")
            first = service.inspect(ref)
            client.report["zone"]["encounters"].reverse()
            second = service.inspect(ref)

        self.assertEqual(first["index_path"], second["index_path"])
        self.assertEqual(first["encounter_choices"][0]["encounter_id"], 4001)
        self.assertEqual(second["encounter_choices"][0]["encounter_id"], 5001)

    def test_inspect_rejects_a_report_code_that_does_not_match_the_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = FakeClient()
            client.report["code"] = "../Other456"
            service = self.make_service(temporary, client)

            with self.assertRaisesRegex(ApiError, "does not match requested report"):
                service.inspect(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123"))

            self.assertFalse((Path(temporary) / "data" / "Other456").exists())

    def test_last_selects_actual_last_fight_without_rewriting_its_meaning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = FakeClient()
            client.report["fights"][-1]["endTime"] = 500
            service = self.make_service(temporary, client)
            result = service.inspect(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=last")
            )

        self.assertEqual(result["selected_fight_id"], 3)
        self.assertEqual(result["selected_fight"]["unpackable_reason"], "in_progress")

    def test_prepare_publishes_complete_bundle_and_query_filters_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = FakeClient(event_pages())
            service = self.make_service(temporary, client)
            result = service.prepare(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1&source=10")
            )
            manifest_path = Path(result["bundles"][0]["manifest_path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            queried = query_bundle(manifest_path, event_types={"damage"}, limit=200)

            with gzip.open(manifest_path.parent / manifest["events_file"], "rt", encoding="utf-8") as handle:
                canonical = [json.loads(line) for line in handle]

            raw_path = Path(manifest["raw_pages"][0]["path"])
            with gzip.open(raw_path, "rt", encoding="utf-8") as handle:
                raw = json.load(handle)

        self.assertTrue(manifest["complete"])
        self.assertEqual(manifest["event_count"], 2)
        self.assertEqual(manifest["unknown_fields"], {"mystery": 1})
        self.assertNotIn("mystery", canonical[0]["fields"])
        self.assertEqual(canonical[0]["fields"]["hitPoints"], 900)
        self.assertEqual(canonical[0]["fields"]["killingAbilityGameID"], 7001)
        self.assertEqual(canonical[0]["fields"]["killerInstance"], 2)
        self.assertEqual(canonical[0]["fields"]["healerInstance"], 3)
        self.assertEqual(canonical[0]["fight_time_ms"], 100)
        self.assertEqual(raw["data"][0]["mystery"], "kept only in raw page")
        self.assertEqual(queried["matched"], 1)
        self.assertEqual(queried["events"][0]["target"]["actor_id"], 10)
        self.assertFalse(queried["truncated"])

    def test_prepare_resumes_from_last_complete_raw_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = FakeClient(event_pages())
            first.fail_at = 2_000
            service = self.make_service(temporary, first)
            ref = ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")

            with self.assertRaises(ApiError):
                service.prepare(ref)

            second = FakeClient(event_pages())
            service = self.make_service(temporary, second)
            result = service.prepare(ref)

        self.assertEqual(first.page_starts, [1_000, 2_000])
        self.assertEqual(first.page_ranges, [(1_000, 5_000), (2_000, 5_000)])
        self.assertEqual(second.page_starts, [2_000])
        self.assertEqual(second.page_ranges, [(2_000, 5_000)])
        self.assertEqual(result["bundles"][0]["event_count"], 2)

    def test_relative_store_roots_remain_stable_after_working_directory_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            other_directory = workspace / "other"
            other_directory.mkdir()
            first = FakeClient(event_pages())
            first.fail_at = 2_000
            ref = ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")

            with chdir(workspace):
                store = DatasetStore(Path("data"), Path("cache"))
                with self.assertRaises(ApiError):
                    DatasetService(first, store).prepare(ref)

            second = FakeClient(event_pages())
            with chdir(other_directory):
                result = DatasetService(second, store).prepare(ref)

        self.assertEqual(second.page_starts, [2_000])
        self.assertEqual(result["bundles"][0]["event_count"], 2)

    def test_prepare_rejects_a_pagination_cursor_that_moves_backwards(self) -> None:
        pages = {
            1_000: {"data": [{"timestamp": 1_100, "type": "cast"}], "nextPageTimestamp": 900},
            900: {"data": [{"timestamp": 1_200, "type": "cast"}], "nextPageTimestamp": None},
        }
        with tempfile.TemporaryDirectory() as temporary:
            service = self.make_service(temporary, FakeClient(pages))

            with self.assertRaisesRegex(ApiError, "did not advance"):
                service.prepare(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"))

    def test_prepare_rejects_a_non_finite_pagination_cursor(self) -> None:
        pages = {
            1_000: {
                "data": [{"timestamp": 1_100, "type": "cast"}],
                "nextPageTimestamp": float("nan"),
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            service = self.make_service(temporary, FakeClient(pages))

            with self.assertRaisesRegex(ApiError, "invalid nextPageTimestamp"):
                service.prepare(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"))

    def test_prepare_rejects_an_event_page_without_a_pagination_cursor(self) -> None:
        pages = {1_000: {"data": [{"timestamp": 1_100, "type": "cast"}]}}
        with tempfile.TemporaryDirectory() as temporary:
            service = self.make_service(temporary, FakeClient(pages))

            with self.assertRaisesRegex(ApiError, "nextPageTimestamp"):
                service.prepare(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"))

    def test_prepare_rejects_events_outside_the_boss_attempt_range(self) -> None:
        pages = {
            1_000: {"data": [{"timestamp": 5_001, "type": "cast"}], "nextPageTimestamp": None}
        }
        with tempfile.TemporaryDirectory() as temporary:
            service = self.make_service(temporary, FakeClient(pages))

            with self.assertRaisesRegex(ApiError, "outside Boss Attempt range"):
                service.prepare(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"))

    def test_prepare_rejects_a_non_finite_event_timestamp(self) -> None:
        pages = {
            1_000: {
                "data": [{"timestamp": float("nan"), "type": "cast"}],
                "nextPageTimestamp": None,
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            service = self.make_service(temporary, FakeClient(pages))

            with self.assertRaisesRegex(ApiError, "finite numeric timestamp"):
                service.prepare(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"))

    def test_dataset_remove_rejects_a_report_being_prepared(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = BlockingClient(event_pages())
            service = self.make_service(temporary, client)
            ref = ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            errors: list[Exception] = []
            thread = threading.Thread(target=lambda: _capture_error(errors, service.prepare, ref))
            thread.start()
            self.assertTrue(client.page_requested.wait(timeout=5))

            try:
                with self.assertRaisesRegex(DatasetError, "currently being prepared"):
                    service.store.remove_dataset("AbC123")
            finally:
                client.resume.set()
                thread.join(timeout=5)

            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)

    def test_cache_clear_rejects_cache_being_used_by_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = BlockingClient(event_pages())
            service = self.make_service(temporary, client)
            ref = ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            errors: list[Exception] = []
            thread = threading.Thread(target=lambda: _capture_error(errors, service.prepare, ref))
            thread.start()
            self.assertTrue(client.page_requested.wait(timeout=5))

            try:
                with self.assertRaisesRegex(DatasetError, "cache is currently in use"):
                    service.store.clear_cache()
            finally:
                client.resume.set()
                thread.join(timeout=5)

            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)

    @unittest.skipIf(os.name == "nt", "Windows CRT byte-range locks are exclusive.")
    def test_prepare_locks_for_different_reports_can_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = DatasetStore(root / "data", root / "cache")

            with store.prepare_lock("AbC123"), store.prepare_lock("Other456"):
                pass

    def test_concurrent_import_roots_do_not_race_cache_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stores = [
                DatasetStore(root / "data", root / "cache"),
                DatasetStore(root / "data", root / "cache"),
            ]
            marker_write_started = threading.Event()
            resume_marker_write = threading.Event()
            guard = threading.Lock()
            blocked = False
            errors: list[Exception] = []
            original_dump = json.dump

            def blocking_dump(value, handle, *args, **kwargs):
                nonlocal blocked
                should_block = False
                if isinstance(value, dict) and value.get("owner") == "wcl-raid-coach":
                    with guard:
                        if not blocked:
                            blocked = True
                            should_block = True
                if should_block:
                    marker_write_started.set()
                    resume_marker_write.wait(timeout=5)
                return original_dump(value, handle, *args, **kwargs)

            with patch("wcl_raid_coach.storage.json.dump", side_effect=blocking_dump):
                first = threading.Thread(
                    target=lambda: _capture_error(errors, stores[0].import_root, "AbC123", 3, 1)
                )
                second = threading.Thread(
                    target=lambda: _capture_error(errors, stores[1].import_root, "Other456", 3, 1)
                )
                first.start()
                self.assertTrue(marker_write_started.wait(timeout=5))
                second.start()
                second.join(timeout=0.1)
                resume_marker_write.set()
                first.join(timeout=5)
                second.join(timeout=5)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertFalse(errors)
            self.assertTrue((root / "cache" / "raw" / DatasetStore.CACHE_MARKER).is_file())

    def test_prepare_lock_coordinates_destructive_operations_across_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            context = multiprocessing.get_context("spawn")
            ready = context.Event()
            resume = context.Event()
            process = context.Process(
                target=_hold_prepare_lock,
                args=(str(root / "data"), str(root / "cache"), ready, resume),
            )
            process.start()
            self.assertTrue(ready.wait(timeout=5))
            store = DatasetStore(root / "data", root / "cache")

            try:
                with self.assertRaisesRegex(DatasetError, "currently being prepared"):
                    store.remove_dataset("AbC123")
                with self.assertRaisesRegex(DatasetError, "cache is currently in use"):
                    store.clear_cache()
            finally:
                resume.set()
                process.join(timeout=5)

            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)

    def test_empty_persistent_lock_files_do_not_block_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = DatasetStore(root / "data", root / "cache")
            report_lock = root / "data" / ".locks" / "AbC123-operations.lock"
            cache_lock = root / "cache" / ".locks" / "operations.lock"
            report_lock.parent.mkdir(parents=True)
            cache_lock.parent.mkdir(parents=True)
            report_lock.touch()
            cache_lock.touch()

            with store.prepare_lock("AbC123"):
                pass

    def test_obsolete_checkpoint_is_discarded_and_downloaded_again(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = DatasetStore(root / "data", root / "cache")
            import_root = store.import_root("AbC123", 3, 1)
            import_root.mkdir(parents=True, exist_ok=True)
            (import_root / "checkpoint.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "report_code": "AbC123",
                        "revision": 3,
                        "fight_id": 1,
                        "next_page_timestamp": None,
                        "pages": [],
                        "event_count": 0,
                        "done": True,
                    }
                ),
                encoding="utf-8",
            )
            client = FakeClient(event_pages())
            service = DatasetService(client, store)

            result = service.prepare(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"))

        self.assertEqual(client.page_ranges, [(1_000, 5_000), (2_000, 5_000)])
        self.assertEqual(result["bundles"][0]["event_count"], 2)

    def test_current_checkpoint_cannot_claim_completion_without_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = DatasetStore(root / "data", root / "cache")
            import_root = store.import_root("AbC123", 3, 1)
            import_root.mkdir(parents=True, exist_ok=True)
            (import_root / "checkpoint.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "collection_protocol_version": 2,
                        "report_code": "AbC123",
                        "revision": 3,
                        "fight_id": 1,
                        "range_start_time": 1_000.0,
                        "range_end_time": 5_000.0,
                        "next_page_timestamp": 1_000.0,
                        "seen_cursors": [],
                        "pages": [],
                        "event_count": 0,
                        "done": True,
                    }
                ),
                encoding="utf-8",
            )
            service = DatasetService(FakeClient(event_pages()), store)

            with self.assertRaisesRegex(DatasetError, "completion state"):
                service.prepare(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"))

    def test_prepare_converts_invalid_checkpoint_text_to_a_dataset_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = DatasetStore(root / "data", root / "cache")
            import_root = store.import_root("AbC123", 3, 1)
            import_root.mkdir(parents=True, exist_ok=True)
            (import_root / "checkpoint.json").write_bytes(b"\xff")
            service = DatasetService(FakeClient(event_pages()), store)

            with self.assertRaisesRegex(DatasetError, "valid UTF-8 JSON"):
                service.prepare(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"))

    def test_current_checkpoint_cannot_claim_completion_before_the_final_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = FakeClient(event_pages())
            first.fail_at = 2_000
            service = self.make_service(temporary, first)
            ref = ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            with self.assertRaises(ApiError):
                service.prepare(ref)
            checkpoint_path = (
                Path(temporary) / "cache" / "raw" / "AbC123" / "3" / "1" / "checkpoint.json"
            )
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["done"] = True
            checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

            with self.assertRaisesRegex(DatasetError, "completion state"):
                self.make_service(temporary, FakeClient(event_pages())).prepare(ref)

    def test_checkpoint_metadata_must_match_the_raw_page_pagination_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = FakeClient(event_pages())
            first.fail_at = 2_000
            ref = ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            with self.assertRaises(ApiError):
                self.make_service(temporary, first).prepare(ref)
            checkpoint_path = (
                Path(temporary) / "cache" / "raw" / "AbC123" / "3" / "1" / "checkpoint.json"
            )
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["pages"][0]["next_page_timestamp"] = None
            checkpoint["next_page_timestamp"] = 1_000.0
            checkpoint["seen_cursors"] = []
            checkpoint["done"] = True
            checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

            with self.assertRaisesRegex(DatasetError, "pagination state"):
                self.make_service(temporary, FakeClient(event_pages())).prepare(ref)

    def test_revision_change_never_publishes_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = FakeClient(event_pages())
            client.revision = 4
            service = self.make_service(temporary, client)

            with self.assertRaises(RevisionChangedError):
                service.prepare(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"))

            fight_dir = Path(temporary) / "data" / "reports" / "AbC123" / "revisions" / "3" / "fights" / "1"
            self.assertFalse((fight_dir / "manifest.json").exists())

    def test_same_revision_index_is_immutable_across_input_hints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.make_service(temporary, FakeClient())
            first = service.inspect(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1&source=10")
            )
            index_path = Path(first["index_path"])
            original = index_path.read_bytes()
            second = service.inspect(
                ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1&source=11")
            )
            after = index_path.read_bytes()

        self.assertEqual(original, after)
        self.assertEqual(second["input_reference"]["source_hint"], 11)

    def test_rejects_mythic_plus_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = FakeClient()
            client.report["fights"] = [client.report["fights"][0]]
            client.report["fights"][0]["keystoneLevel"] = 12
            service = self.make_service(temporary, client)

            with self.assertRaises(InputError):
                service.inspect(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123"))

    def test_accepts_raid_report_with_mythic_plus_fights(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = FakeClient()
            mythic_plus = copy.deepcopy(client.report["fights"][0])
            mythic_plus.update(
                {
                    "id": 4,
                    "encounterID": 61877,
                    "name": "Test Dungeon",
                    "difficulty": 10,
                    "size": 5,
                    "keystoneLevel": 12,
                }
            )
            client.report["fights"].append(mythic_plus)
            service = self.make_service(temporary, client)

            result = service.inspect(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123"))
            index = json.loads(Path(result["index_path"]).read_text(encoding="utf-8"))

        self.assertEqual([choice["fight_id"] for choice in result["fight_choices"]], [1, 3])
        unsupported = next(fight for fight in index["fights"] if fight["fight_id"] == 4)
        self.assertFalse(unsupported["packable"])
        self.assertEqual(unsupported["unpackable_reason"], "mythic_plus")

    def test_rejects_non_keystone_dungeon_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = FakeClient()
            client.report["zone"]["difficulties"] = [{"id": 2, "name": "Heroic", "sizes": [5]}]
            service = self.make_service(temporary, client)

            with self.assertRaises(InputError):
                service.inspect(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123"))

    def test_unknown_completion_state_is_not_packable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            client = FakeClient()
            client.report["fights"][0]["inProgress"] = None
            service = self.make_service(temporary, client)
            result = service.inspect(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"))

        self.assertFalse(result["selected_fight"]["packable"])
        self.assertEqual(result["selected_fight"]["unpackable_reason"], "completion_unknown")

    def test_url_fight_cannot_be_expanded_by_another_selector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.make_service(temporary, FakeClient())
            ref = ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")

            with self.assertRaises(InputError):
                service.prepare(ref, all_boss_fights=True)
            with self.assertRaises(InputError):
                service.prepare(ref, encounter_id=5001)
            with self.assertRaises(InputError):
                service.prepare(ref, fight_ids=[1, 2])

    def test_bundle_checksum_is_validated_before_query_or_cache_hit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.make_service(temporary, FakeClient(event_pages()))
            ref = ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            result = service.prepare(ref)
            manifest_path = Path(result["bundles"][0]["manifest_path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            events_path = manifest_path.parent / manifest["events_file"]
            with events_path.open("ab") as handle:
                handle.write(b"changed")

            with self.assertRaises(DatasetError):
                query_bundle(manifest_path)
            with self.assertRaises(DatasetError):
                service.prepare(ref)

    def test_cache_hit_rejects_manifest_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.make_service(temporary, FakeClient(event_pages()))
            ref = ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            result = service.prepare(ref)
            manifest_path = Path(result["bundles"][0]["manifest_path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["identity"]["report_revision"] = 999
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaises(DatasetError):
                service.prepare(ref)

    def test_raw_checkpoint_checksum_is_validated_before_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = FakeClient(event_pages())
            first.fail_at = 2_000
            service = self.make_service(temporary, first)
            ref = ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            with self.assertRaises(ApiError):
                service.prepare(ref)
            checkpoint = json.loads(
                (Path(temporary) / "cache" / "raw" / "AbC123" / "3" / "1" / "checkpoint.json").read_text(
                    encoding="utf-8"
                )
            )
            with Path(checkpoint["pages"][0]["path"]).open("ab") as handle:
                handle.write(b"changed")

            with self.assertRaises(DatasetError):
                self.make_service(temporary, FakeClient(event_pages())).prepare(ref)

    def test_raw_checkpoint_converts_an_invalid_deflate_stream_to_a_dataset_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = FakeClient(event_pages())
            first.fail_at = 2_000
            service = self.make_service(temporary, first)
            ref = ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1")
            with self.assertRaises(ApiError):
                service.prepare(ref)
            checkpoint_path = (
                Path(temporary) / "cache" / "raw" / "AbC123" / "3" / "1" / "checkpoint.json"
            )
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            page_path = Path(checkpoint["pages"][0]["path"])
            compressed = bytearray(gzip.compress(b'{"data":[],"nextPageTimestamp":null}'))
            compressed[10] = 0xFF
            page_path.write_bytes(compressed)
            checkpoint["pages"][0]["sha256"] = hashlib.sha256(compressed).hexdigest()
            checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

            with self.assertRaisesRegex(DatasetError, "invalid gzip JSON"):
                self.make_service(temporary, FakeClient(event_pages())).prepare(ref)

    def test_cache_clear_refuses_unowned_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = DatasetStore(root / "data", root / "cache")
            raw_root = root / "cache" / "raw"
            raw_root.mkdir(parents=True)
            unrelated = raw_root / "unrelated.txt"
            unrelated.write_text("keep", encoding="utf-8")

            with self.assertRaises(DatasetError):
                store.clear_cache()

            self.assertTrue(unrelated.exists())

    def test_latest_revision_pointer_never_moves_backwards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = DatasetStore(root / "data", root / "cache")
            for revision in (4, 3):
                store.write_index(
                    {
                        "schema_version": 1,
                        "generated_at": f"revision-{revision}",
                        "report": {"code": "AbC123", "revision": revision},
                        "actors": [],
                        "abilities": [],
                        "fights": [],
                    }
                )
            latest = json.loads((root / "data" / "reports" / "AbC123" / "latest.json").read_text(encoding="utf-8"))

        self.assertEqual(latest["revision"], 4)

    def test_removing_latest_revision_repairs_pointer_to_highest_remaining(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = DatasetStore(root / "data", root / "cache")
            for revision in (3, 4):
                store.write_index(
                    {
                        "schema_version": 1,
                        "generated_at": f"revision-{revision}",
                        "report": {"code": "AbC123", "revision": revision},
                        "actors": [],
                        "abilities": [],
                        "fights": [],
                    }
                )
            store.remove_dataset("AbC123", revision=4)
            latest = json.loads((root / "data" / "reports" / "AbC123" / "latest.json").read_text(encoding="utf-8"))

        self.assertEqual(latest["revision"], 3)

    def test_prepare_rejects_trash_and_in_progress_fights(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = self.make_service(temporary, FakeClient())

            for fight_id in (2, 3):
                with self.subTest(fight_id=fight_id), self.assertRaises(InputError):
                    service.prepare(
                        ReportRef.parse(f"https://www.warcraftlogs.com/reports/AbC123#fight={fight_id}")
                    )

    def test_query_defaults_to_two_hundred_and_returns_cursor(self) -> None:
        pages = {
            1_000: {
                "data": [
                    {"timestamp": 1_000 + index, "type": "cast", "sourceID": 10, "abilityGameID": 7001}
                    for index in range(205)
                ],
                "nextPageTimestamp": None,
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            service = self.make_service(temporary, FakeClient(pages))
            result = service.prepare(ReportRef.parse("https://www.warcraftlogs.com/reports/AbC123#fight=1"))
            queried = query_bundle(Path(result["bundles"][0]["manifest_path"]))

        self.assertEqual(queried["matched"], 205)
        self.assertEqual(queried["returned"], 200)
        self.assertTrue(queried["truncated"])
        self.assertEqual(queried["next_cursor"], 199)

    def test_query_rejects_a_manifest_that_is_not_an_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            manifest_path.write_text("[]", encoding="utf-8")

            with self.assertRaisesRegex(DatasetError, "JSON object"):
                query_bundle(manifest_path)

    def test_query_rejects_an_unsupported_manifest_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            manifest_path.write_text(
                json.dumps({"schema_version": 999, "complete": True}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(DatasetError, "unsupported schema"):
                query_bundle(manifest_path)

    def test_query_rejects_a_boolean_manifest_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            manifest_path.write_text(
                json.dumps({"schema_version": True, "complete": True}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(DatasetError, "unsupported schema"):
                query_bundle(manifest_path)

    def test_query_converts_invalid_manifest_text_to_a_dataset_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            for content in (b"{", b"\xff"):
                with self.subTest(content=content):
                    manifest_path.write_bytes(content)
                    with self.assertRaisesRegex(DatasetError, "valid UTF-8 JSON"):
                        query_bundle(manifest_path)


if __name__ == "__main__":
    unittest.main()
