import gzip
import hashlib
import json
import tempfile
import tracemalloc
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_analysis
from wcl_raid_coach.analysis import analyze_player
from wcl_raid_coach.dataset import query_bundle, validate_complete_bundle
from wcl_raid_coach.errors import DatasetError


class EventStreamTests(unittest.TestCase):
    def test_all_consumers_reject_trailing_corruption_after_accumulating_results(self):
        for corruption in (b'{bad json}\n', b'{"sequence":99}\n', b'{"sequence":4}\n', b'', None):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as temporary:
                manifest, index = test_analysis.AnalysisTests().make_bundle(Path(temporary))
                events = manifest.parent / "events.jsonl.gz"
                original = gzip.decompress(events.read_bytes())
                if corruption is None:
                    events.write_bytes(events.read_bytes()[:-4])
                else:
                    events.write_bytes(gzip.compress(original.rsplit(b'\n', 2)[0] + b'\n' + corruption))
                value = json.loads(manifest.read_text())
                value["events_file_sha256"] = hashlib.sha256(events.read_bytes()).hexdigest()
                manifest.write_text(json.dumps(value))
                for consume in (
                    lambda: query_bundle(manifest, limit=1, event_types={"cast"}),
                    lambda: analyze_player(manifest, index, 10),
                    lambda: validate_complete_bundle(manifest),
                ):
                    with self.assertRaises(DatasetError):
                        consume()

    def test_large_stream_keeps_query_and_analysis_memory_bounded_and_opens_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            events = [
                {"sequence": number, "fight_time_ms": 500, "type": "damage",
                 "source": {"actor_id": 10}, "target": {"actor_id": 20},
                 "ability_id": 3, "fields": {"amount": 1}}
                for number in range(5, 30005)
            ]
            manifest, index = test_analysis.AnalysisTests().make_bundle(Path(temporary), events)
            del events
            for consume in (lambda: query_bundle(manifest, limit=1), lambda: analyze_player(manifest, index, 10)):
                with patch("wcl_raid_coach.dataset.gzip.open", wraps=gzip.open) as opened:
                    tracemalloc.start()
                    try:
                        result = consume()
                        _, peak = tracemalloc.get_traced_memory()
                    finally:
                        tracemalloc.stop()
                self.assertEqual(opened.call_count, 1)
                self.assertLess(peak, 4 * 1024 * 1024)
                if "matched" in result:
                    self.assertEqual(result["matched"], 30005)
                    self.assertEqual(result["next_cursor"], 0)
                else:
                    self.assertEqual(result["metrics"]["damage_total"], 30150)
