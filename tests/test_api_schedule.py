from __future__ import annotations

import tempfile
import unittest
import multiprocessing
import json
import time
from email.utils import formatdate
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from wcl_raid_coach.api_schedule import ApiSchedule
from wcl_raid_coach.errors import RateLimitError
from wcl_raid_coach.errors import ApiError


def schedule_worker(root, action, queue, active=None):
    schedule = ApiSchedule(Path(root))
    try:
        with schedule.attempt("RateLimit" if action in ("hold", "429") else "ReportRevision"):
            if action == "hold":
                queue.put("acquired")
                time.sleep(30)
            elif action == "429":
                raise HTTPError("https://example.invalid", 429, "limited", {}, None)
            elif action == "count":
                with active.get_lock():
                    active.value += 1
                    queue.put(active.value)
                time.sleep(0.05)
                with active.get_lock():
                    active.value -= 1
            else:
                queue.put("unexpected_request")
    except (HTTPError, RateLimitError):
        queue.put("limited")


class ApiScheduleTests(unittest.TestCase):
    def test_invalid_numbers_and_clock_changes_never_restore_budget(self):
        for field, value in (("estimated_points", float("nan")), ("cooldown_until", -1),
                             ("updated_at", 10 ** 400), ("in_flight", 1),
                             ("clock_baseline", 1)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.prime(root)
                state = json.loads((root / "state.json").read_text(encoding="utf-8"))
                state[field] = value
                (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
                with self.assertRaises(RateLimitError), ApiSchedule(root).attempt("OAuth"):
                    self.fail("Invalid state must fail closed")

    def test_lock_open_failure_is_an_api_domain_error(self):
        with tempfile.TemporaryDirectory() as directory, patch("wcl_raid_coach.dataset.os.open", side_effect=PermissionError()):
            with self.assertRaises(ApiError), ApiSchedule(Path(directory)).attempt("OAuth"):
                self.fail("A failed scheduling lock cannot start HTTP")

    def test_os_user_location_cannot_be_changed_by_home_environment(self):
        from wcl_raid_coach.api_schedule import coordination_root
        with patch.dict("os.environ", {"HOME": "/nonexistent/first", "USERPROFILE": "C:\\nonexistent\\first"}):
            first = coordination_root()
        with patch.dict("os.environ", {"HOME": "/nonexistent/second", "USERPROFILE": "C:\\nonexistent\\second"}):
            second = coordination_root()
        self.assertEqual(first, second)

    def prime(self, root):
        with ApiSchedule(root).attempt("RateLimit") as attempt:
            attempt.observe({"data": {"rateLimitData": {
                "limitPerHour": 3600, "pointsSpentThisHour": 0, "pointsResetIn": 3600,
            }}})

    def test_real_processes_never_overlap_attempts(self):
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as directory:
            self.prime(Path(directory))
            queue, active = context.Queue(), context.Value("i", 0)
            processes = [context.Process(target=schedule_worker, args=(directory, "count", queue, active)) for _ in range(4)]
            for process in processes:
                process.start()
                self.addCleanup(lambda p=process: p.is_alive() and p.terminate())
            observed = [queue.get(timeout=15) for _ in processes]
            for process in processes:
                process.join(15)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual(observed, [1, 1, 1, 1])
            queue.close()

    def test_real_process_429_blocks_another_process(self):
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as directory:
            queue = context.Queue()
            for action in ("429", "request"):
                process = context.Process(target=schedule_worker, args=(directory, action, queue))
                process.start()
                self.addCleanup(lambda p=process: p.is_alive() and p.terminate())
                self.assertEqual(queue.get(timeout=15), "limited")
                process.join(15)
                self.assertEqual(process.exitcode, 0)
            queue.close()

    def test_terminated_process_releases_lock_and_requires_one_refresh(self):
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as directory:
            queue = context.Queue()
            process = context.Process(target=schedule_worker, args=(directory, "hold", queue))
            process.start()
            self.addCleanup(lambda: process.is_alive() and process.terminate())
            self.assertEqual(queue.get(timeout=15), "acquired")
            started = time.monotonic()
            with self.assertRaises(RateLimitError), ApiSchedule(Path(directory)).attempt("OAuth"):
                self.fail("Lock waiting must time out")
            self.assertLess(time.monotonic() - started, 12)
            process.terminate()
            process.join(15)
            with self.assertRaises(RateLimitError), ApiSchedule(Path(directory)).attempt("ReportRevision"):
                self.fail("Interrupted request must refresh quota")
            self.prime(Path(directory))
            with ApiSchedule(Path(directory)).attempt("ReportRevision"):
                pass
            queue.close()

    def test_cooldown_expiry_allows_one_probe_then_reuses_observation(self):
        wall, monotonic = time.time(), time.monotonic()
        elapsed = [0.0]
        with tempfile.TemporaryDirectory() as directory, patch("time.time", side_effect=lambda: wall + elapsed[0]), patch(
            "time.monotonic", side_effect=lambda: monotonic + elapsed[0]
        ):
            root = Path(directory)
            with self.assertRaises(HTTPError), ApiSchedule(root).attempt("RateLimit"):
                raise HTTPError("https://example.invalid", 429, "limited", {"Retry-After": "2"}, None)
            elapsed[0] = 3
            with ApiSchedule(root).attempt("RateLimit") as first:
                self.assertIsNone(first.cached)
                first.observe({"data": {"rateLimitData": {"limitPerHour": 3600, "pointsSpentThisHour": 10, "pointsResetIn": 3600}}})
            with ApiSchedule(root).attempt("RateLimit") as second:
                self.assertIsNotNone(second.cached)

    def test_retry_after_and_reset_fallback(self):
        wall = time.time()
        for headers, has_quota, expected in (({"Retry-After": "5"}, False, 5),
                                            ({"Retry-After": formatdate(wall + 10, usegmt=True)}, False, 10),
                                            ({"Retry-After": "invalid"}, True, 3600),
                                            ({}, False, 60)):
            with self.subTest(headers=headers), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if has_quota:
                    self.prime(root)
                schedule = ApiSchedule(root)
                with self.assertRaises(HTTPError), schedule.attempt("OAuth"):
                    raise HTTPError("https://example.invalid", 429, "limited", headers, None)
                self.assertAlmostEqual(schedule.state["cooldown_until"] - wall, expected, delta=1)

    def test_default_coordination_is_independent_of_workspace_and_data_settings(self):
        from wcl_raid_coach.api_schedule import coordination_root
        with tempfile.TemporaryDirectory() as directory, patch("pathlib.Path.home", return_value=Path(directory)):
            roots = []
            for name in ("first", "second"):
                with patch.dict("os.environ", {"WCL_DATA_ROOT": name, "WCL_CACHE_ROOT": name, "PERSISTENT_WORKSPACE": name}):
                    roots.append(coordination_root())
            self.assertEqual(roots[0], roots[1])

    def test_cooldown_crosses_instances_and_cannot_be_bypassed_by_oauth(self):
        with tempfile.TemporaryDirectory() as directory:
            first = ApiSchedule(Path(directory))
            second = ApiSchedule(Path(directory))
            with self.assertRaises(HTTPError), first.attempt("RateLimit"):
                raise HTTPError("https://example.invalid", 429, "limited", {"Retry-After": "60"}, None)
            for operation in ("OAuth", "RateLimit", "ReportIndex"):
                with self.subTest(operation=operation), self.assertRaises(RateLimitError), second.attempt(operation):
                    self.fail("A new instance must not bypass cooldown")

    def test_observations_are_reused_and_failed_attempts_keep_reservations(self):
        with tempfile.TemporaryDirectory() as directory:
            schedule = ApiSchedule(Path(directory))
            with schedule.attempt("RateLimit") as attempt:
                attempt.observe({"data": {"rateLimitData": {
                    "limitPerHour": 1000, "pointsSpentThisHour": 300, "pointsResetIn": 3600,
                }}})
            with schedule.attempt("RateLimit") as attempt:
                self.assertEqual(attempt.cached["data"]["rateLimitData"]["pointsSpentThisHour"], 300)
            with self.assertRaises(TimeoutError), schedule.attempt("ReportIndex"):
                raise TimeoutError()
            with self.assertRaises(RateLimitError), schedule.attempt("ReportIndex"):
                self.fail("An unobserved failed request cannot restore spent budget")

    def test_corrupt_state_is_a_domain_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "state.json").write_text('{"schema_version":true}', encoding="utf-8")
            with self.assertRaises(RateLimitError), ApiSchedule(root).attempt("OAuth"):
                self.fail("Malformed state cannot restore budget")
