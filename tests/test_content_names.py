from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wcl_raid_coach.content_names import (
    ensure_content_names,
    load_content_names,
    localize_encounter,
    localize_npc,
)
from wcl_raid_coach.errors import DatasetError


class ContentNamesTests(unittest.TestCase):
    def test_builds_scoped_wago_content_mapping(self) -> None:
        encounters = [
            (3421, 3004, "The Twin Fangs", "双子毒牙"),
            (4001, 2773, "Dungeon Boss 1", "地下城首领一"),
            (4002, 725, "Dungeon Boss 2", "地下城首领二"),
            (4003, 2830, "Dungeon Boss 3", "地下城首领三"),
            (4004, 658, "Dungeon Boss 4", "地下城首领四"),
            (4005, 2805, "Dungeon Boss 5", "地下城首领五"),
            (4006, 2811, "Dungeon Boss 6", "地下城首领六"),
            (4007, 2915, "Dungeon Boss 7", "地下城首领七"),
            (4008, 2874, "Dungeon Boss 8", "地下城首领八"),
        ]
        tables = {
            "map_zhCN": "ID,MapName_lang\n"
            + "\n".join(
                f"{map_id},Map {map_id}" for map_id in [3004, 2773, 725, 2830, 658, 2805, 2811, 2915, 2874]
            )
            + "\n",
            "encounter_enUS": "ID,MapID,Name_lang\n"
            + "\n".join(f"{encounter_id},{map_id},{name_en}" for encounter_id, map_id, name_en, _ in encounters)
            + "\n",
            "encounter_zhCN": "ID,MapID,Name_lang\n"
            + "\n".join(f"{encounter_id},{map_id},{name_zh}" for encounter_id, map_id, _, name_zh in encounters)
            + "\n",
            "journal_zhCN": "ID,DungeonEncounterID\n"
            + "\n".join(f"{5000 + index},{encounter_id}" for index, (encounter_id, _, _, _) in enumerate(encounters))
            + "\n",
            "creature_enUS": "ID,JournalEncounterID,Name_lang\n"
            + "\n".join(f"{6000 + index},{5000 + index},NPC {index}" for index in range(len(encounters)))
            + "\n6151,5000,Vexhul\n6150,5000,Ithraz\n",
            "creature_zhCN": "ID,JournalEncounterID,Name_lang\n"
            + "\n".join(f"{6000 + index},{5000 + index},NPC 中文 {index}" for index in range(len(encounters)))
            + "\n6151,5000,维克苏尔\n6150,5000,伊斯拉兹\n",
        }

        def fake_download(directory: Path, key: str, url: str) -> tuple[Path, str]:
            path = directory / f"{key}.csv"
            path.write_text(tables[key], encoding="utf-8")
            return path, "12.1.0.69587"

        expected_counts = {map_id: 1 for _, map_id, _, _ in encounters}
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("wcl_raid_coach.content_names._download", side_effect=fake_download),
                patch("wcl_raid_coach.content_names.EXPECTED_ENCOUNTER_COUNTS", expected_counts),
                patch("wcl_raid_coach.content_names.MIN_NPC_COUNT", 9),
            ):
                result = ensure_content_names(Path(temporary))
                mapping = load_content_names(Path(result["mapping_path"]))
                malformed = mapping | {"npcs": dict(mapping["npcs"])}
                malformed["npcs"]["²"] = malformed["npcs"].pop("6000")
                Path(result["mapping_path"]).write_text(json.dumps(malformed), encoding="utf-8")
                with self.assertRaises(DatasetError):
                    load_content_names(Path(result["mapping_path"]))
                conflicting = mapping | {
                    "npcs": dict(mapping["npcs"]),
                    "npc_names_by_encounter": {
                        encounter_id: dict(names)
                        for encounter_id, names in mapping["npc_names_by_encounter"].items()
                    },
                }
                conflicting["npcs"]["9999"] = conflicting["npcs"]["6000"] | {"name_zh": "冲突名称"}
                conflicting["npc_names_by_encounter"]["3421"]["NPC 0"] = "冲突名称"
                Path(result["mapping_path"]).write_text(json.dumps(conflicting), encoding="utf-8")
                with self.assertRaises(DatasetError):
                    load_content_names(Path(result["mapping_path"]))
        self.assertEqual((result["map_count"], result["encounter_count"], result["npc_count"]), (9, 9, 11))
        self.assertEqual(
            mapping["encounters"]["3421"],
            {"map_id": 3004, "name_en": "The Twin Fangs", "name_zh": "双子毒牙"},
        )
        self.assertEqual(
            mapping["npc_names_by_encounter"]["3421"],
            {"NPC 0": "NPC 中文 0", "Vexhul": "维克苏尔", "Ithraz": "伊斯拉兹"},
        )
        self.assertEqual(localize_encounter(mapping, 3421, "The Twin Fangs"), "双子毒牙")
        self.assertEqual(localize_npc(mapping, 3421, "Vexhul"), "维克苏尔")
        self.assertEqual(localize_npc(mapping, 3421, "Unknown NPC"), "Unknown NPC")
