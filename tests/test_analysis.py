from __future__ import annotations

import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from wcl_raid_coach.analysis import analyze_player
from wcl_raid_coach.dataset import query_bundle, sign_bundle_manifest
from wcl_raid_coach.errors import DatasetError, InputError


class AnalysisTests(unittest.TestCase):
    def make_bundle(self, root: Path) -> tuple[Path, Path]:
        events = [
            {"sequence": 0, "fight_time_ms": 100, "type": "cast", "source": {"actor_id": 10}, "target": {"actor_id": 20}, "ability_id": 1, "fields": {}},
            {"sequence": 1, "fight_time_ms": 200, "type": "damage", "source": {"actor_id": 10}, "target": {"actor_id": 20}, "ability_id": 1, "fields": {"amount": 100, "absorbed": 20}},
            {"sequence": 2, "fight_time_ms": 300, "type": "interrupt", "source": {"actor_id": 10}, "target": {"actor_id": 20}, "ability_id": 2, "fields": {}},
            {"sequence": 3, "fight_time_ms": 400, "type": "damage", "source": {"actor_id": 11}, "target": {"actor_id": 20}, "ability_id": 3, "fields": {"amount": 50}},
            {"sequence": 4, "fight_time_ms": 500, "type": "death", "source": None, "target": {"actor_id": 10}, "ability_id": None, "fields": {}},
        ]
        events_path = root / "events.jsonl.gz"
        with gzip.open(events_path, "wt", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")
        digest = hashlib.sha256(events_path.read_bytes()).hexdigest()
        raw_path = root / "page-000001.json.gz"
        with gzip.open(raw_path, "wt", encoding="utf-8") as handle:
            json.dump({"data": events, "nextPageTimestamp": None}, handle)
        raw_digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        index_value = {
            "report": {
                "code": "ABC",
                "revision": 1,
                "game_version": 1,
                "zone": {"partitions": [{"id": 2, "compactName": "12.1", "default": True}]},
            },
            "actors": [{"id": 10, "name": "Player"}, {"id": 11, "name": "Pet", "petOwner": 10}],
            "fights": [{"fight_id": 7, "encounter_id": 1007, "difficulty": 4, "duration_ms": 1000, "participants": [{"actor_id": 10, "name": "Player", "class": "DeathKnight", "spec": "Unholy"}]}],
        }
        index_hash = hashlib.sha256(json.dumps(index_value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        manifest_path = root / "manifest.json"
        manifest_value = {
            "product": "wcl-raid-coach",
            "schema_version": 1,
            "complete": True,
            "identity": {"report_code": "ABC", "report_revision": 1, "fight_id": 7},
            "events_file": "events.jsonl.gz",
            "events_sha256": digest,
            "event_count": len(events),
            "raw_pages": [{"number": 1, "path": str(raw_path), "query_start_time": 0, "query_end_time": 1000, "next_page_timestamp": None, "events": len(events), "sha256": raw_digest}],
            "collection": {"protocol_version": 2, "start_time": 0, "end_time": 1000, "page_count": 1},
            "report_index_sha256": index_hash,
        }
        manifest_path.write_text(json.dumps(sign_bundle_manifest(manifest_value, "secret")), encoding="utf-8")
        index_path = root / "report.json"
        index_path.write_text(json.dumps(index_value), encoding="utf-8")
        return manifest_path, index_path

    def test_analyzes_one_participant_from_complete_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, index = self.make_bundle(Path(directory))
            result = analyze_player(manifest, index, 10, partition_id=2, signing_key="secret")
        self.assertEqual(result["player"]["name"], "Player")
        self.assertEqual(result["metrics"]["casts"]["1"], 1)
        self.assertEqual(result["metrics"]["first_cast_ms"]["1"], 100)
        self.assertEqual(result["metrics"]["damage_total"], 150)
        self.assertEqual(result["metrics"]["interrupts"], 1)
        self.assertEqual(result["metrics"]["deaths"], 1)
        self.assertEqual(result["comparison_identity"]["encounter_id"], 1007)
        self.assertEqual(result["comparison_identity"]["game_version"], "12.1")

    def test_rejects_unknown_participant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, index = self.make_bundle(Path(directory))
            with self.assertRaises(InputError):
                analyze_player(manifest, index, 99, signing_key="secret")

    def test_rejects_unknown_comparison_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, index = self.make_bundle(Path(directory))
            with self.assertRaisesRegex(DatasetError, "ranking partition"):
                analyze_player(manifest, index, 10, partition_id=99, signing_key="secret")

    def test_rejects_incomplete_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, index = self.make_bundle(Path(directory))
            value = json.loads(manifest.read_text(encoding="utf-8"))
            value["complete"] = False
            manifest.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(DatasetError):
                analyze_player(manifest, index, 10, signing_key="secret")

    def test_query_rejects_a_bundle_from_the_old_product(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _ = self.make_bundle(Path(directory))
            value = json.loads(manifest.read_text(encoding="utf-8"))
            value.pop("product")
            manifest.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(DatasetError):
                query_bundle(manifest)


if __name__ == "__main__":
    unittest.main()
