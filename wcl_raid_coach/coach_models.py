from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .errors import InputError


DESIGNATOR = re.compile(r"^(PT|H|M)([1-9][0-9]*)$", re.IGNORECASE)


@dataclass(frozen=True)
class SpecializationIdentity:
    class_name: str
    spec_name: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class EncounterDesignator:
    difficulty_code: Literal["PT", "H", "M"]
    position: int

    @classmethod
    def parse(cls, value: str) -> "EncounterDesignator":
        match = DESIGNATOR.fullmatch(value.strip())
        if match is None:
            raise InputError("Encounter Designator must look like PT6, H6, or M6.")
        return cls(match.group(1).upper(), int(match.group(2)))  # type: ignore[arg-type]

    def as_dict(self) -> dict[str, Any]:
        return {"value": f"{self.difficulty_code}{self.position}", **asdict(self)}


@dataclass(frozen=True)
class CoachRequest:
    content_type: Literal["retail_raid"]
    mode: Literal["raid_guide", "personal_review", "report_data"]
    specialization: SpecializationIdentity | None = None
    encounter_designators: tuple[EncounterDesignator, ...] = ()
    report_code: str | None = None
    fight_id: int | None = None
    source_id: int | None = None
    cohort_mode: Literal["recent_ranked"] = "recent_ranked"
    sample_goal: int = 10

    def __post_init__(self) -> None:
        if self.content_type != "retail_raid":
            raise InputError("Only Retail raid Coach Requests are supported in this release.")
        if not 1 <= self.sample_goal <= 10:
            raise InputError("sample_goal must be between 1 and 10.")
        if self.mode == "raid_guide" and not self.encounter_designators:
            raise InputError("A raid guide requires at least one Encounter Designator.")
        if self.mode == "personal_review" and not self.report_code:
            raise InputError("A personal review requires a WCL report code.")
        if self.mode == "report_data" and not self.report_code:
            raise InputError("A report data request requires a WCL report code.")

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["specialization"] = self.specialization.as_dict() if self.specialization else None
        result["encounter_designators"] = [item.as_dict() for item in self.encounter_designators]
        return result

    def fingerprint(self, *, context: dict[str, Any] | None = None) -> str:
        payload = {"request": self.as_dict(), "context": context or {}}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def parse_specialization(value: str) -> SpecializationIdentity:
    normalized = re.sub(r"[\s_-]+", "", value.casefold())
    aliases = {
        "邪dk": ("DeathKnight", "Unholy"), "邪恶死亡骑士": ("DeathKnight", "Unholy"), "邪恶dk": ("DeathKnight", "Unholy"), "unholydk": ("DeathKnight", "Unholy"), "unholydeathknight": ("DeathKnight", "Unholy"),
        "冰dk": ("DeathKnight", "Frost"), "冰霜死亡骑士": ("DeathKnight", "Frost"), "frostdk": ("DeathKnight", "Frost"),
        "血dk": ("DeathKnight", "Blood"), "鲜血死亡骑士": ("DeathKnight", "Blood"), "blooddk": ("DeathKnight", "Blood"),
        "奥法": ("Mage", "Arcane"), "arcane": ("Mage", "Arcane"), "火法": ("Mage", "Fire"), "firemage": ("Mage", "Fire"), "冰法": ("Mage", "Frost"), "frostmage": ("Mage", "Frost"),
        "武器战": ("Warrior", "Arms"), "arms": ("Warrior", "Arms"), "狂暴战": ("Warrior", "Fury"), "fury": ("Warrior", "Fury"), "防战": ("Warrior", "Protection"), "protectionwarrior": ("Warrior", "Protection"),
        "惩戒骑": ("Paladin", "Retribution"), "retribution": ("Paladin", "Retribution"), "防骑": ("Paladin", "Protection"), "protectionpaladin": ("Paladin", "Protection"), "奶骑": ("Paladin", "Holy"), "holypaladin": ("Paladin", "Holy"),
        "兽王猎": ("Hunter", "BeastMastery"), "beastmastery": ("Hunter", "BeastMastery"), "射击猎": ("Hunter", "Marksmanship"), "marksmanship": ("Hunter", "Marksmanship"), "生存猎": ("Hunter", "Survival"), "survivalhunter": ("Hunter", "Survival"),
        "奇袭贼": ("Rogue", "Assassination"), "assassination": ("Rogue", "Assassination"), "狂徒贼": ("Rogue", "Outlaw"), "outlaw": ("Rogue", "Outlaw"), "敏锐贼": ("Rogue", "Subtlety"), "subtlety": ("Rogue", "Subtlety"),
        "戒律牧": ("Priest", "Discipline"), "discipline": ("Priest", "Discipline"), "神牧": ("Priest", "Holy"), "holypriest": ("Priest", "Holy"), "暗牧": ("Priest", "Shadow"), "shadowpriest": ("Priest", "Shadow"),
        "元素萨": ("Shaman", "Elemental"), "elemental": ("Shaman", "Elemental"), "增强萨": ("Shaman", "Enhancement"), "enhancement": ("Shaman", "Enhancement"), "奶萨": ("Shaman", "Restoration"), "restorationshaman": ("Shaman", "Restoration"),
        "痛苦术": ("Warlock", "Affliction"), "affliction": ("Warlock", "Affliction"), "恶魔术": ("Warlock", "Demonology"), "demonology": ("Warlock", "Demonology"), "毁灭术": ("Warlock", "Destruction"), "destruction": ("Warlock", "Destruction"),
        "酒仙": ("Monk", "Brewmaster"), "brewmaster": ("Monk", "Brewmaster"), "织雾": ("Monk", "Mistweaver"), "mistweaver": ("Monk", "Mistweaver"), "踏风": ("Monk", "Windwalker"), "windwalker": ("Monk", "Windwalker"),
        "平衡德": ("Druid", "Balance"), "balance": ("Druid", "Balance"), "猫德": ("Druid", "Feral"), "feral": ("Druid", "Feral"), "熊德": ("Druid", "Guardian"), "guardian": ("Druid", "Guardian"), "奶德": ("Druid", "Restoration"), "restorationdruid": ("Druid", "Restoration"),
        "浩劫dh": ("DemonHunter", "Havoc"), "havoc": ("DemonHunter", "Havoc"), "复仇dh": ("DemonHunter", "Vengeance"), "vengeance": ("DemonHunter", "Vengeance"), "吞噬dh": ("DemonHunter", "Devourer"), "devourer": ("DemonHunter", "Devourer"),
        "湮灭龙": ("Evoker", "Devastation"), "devastation": ("Evoker", "Devastation"), "恩护龙": ("Evoker", "Preservation"), "preservation": ("Evoker", "Preservation"), "增辉龙": ("Evoker", "Augmentation"), "augmentation": ("Evoker", "Augmentation"),
    }
    identity = aliases.get(normalized)
    if identity is None:
        raise InputError("Unsupported or ambiguous specialization; use a specific Retail specialization name.")
    return SpecializationIdentity(*identity)


def specialization_role(class_name: str, spec_name: str) -> Literal["dps", "tank", "healer"]:
    tanks = {
        ("DeathKnight", "Blood"), ("Warrior", "Protection"), ("Paladin", "Protection"),
        ("Monk", "Brewmaster"), ("Druid", "Guardian"), ("DemonHunter", "Vengeance"),
    }
    healers = {
        ("Paladin", "Holy"), ("Priest", "Discipline"), ("Priest", "Holy"),
        ("Shaman", "Restoration"), ("Monk", "Mistweaver"), ("Druid", "Restoration"),
        ("Evoker", "Preservation"),
    }
    identity = (class_name, spec_name)
    if identity in tanks:
        return "tank"
    if identity in healers:
        return "healer"
    return "dps"
