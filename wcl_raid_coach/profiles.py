from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .errors import InputError
from .storage import atomic_write_json, read_json


ProfileKind = Literal["specialization", "encounter"]


def validate_profile(value: Any, expected_kind: ProfileKind | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError("Profile must be a JSON object.")
    kind = value.get("kind")
    if kind not in {"specialization", "encounter"}:
        raise InputError("Profile kind must be specialization or encounter.")
    if expected_kind is not None and kind != expected_kind:
        raise InputError(f"Expected a {expected_kind} Profile.")
    identity = value.get("identity")
    if not isinstance(identity, dict):
        raise InputError("Profile identity must be an object.")
    for field in ("game_version", "partition_id"):
        if identity.get(field) in (None, ""):
            raise InputError(f"Profile identity requires {field}.")
    if kind == "specialization":
        for field in ("class_name", "spec_name"):
            if not isinstance(identity.get(field), str) or not identity[field].strip():
                raise InputError(f"Specialization Profile identity requires {field}.")
        if not isinstance(value.get("abilities"), list):
            raise InputError("Specialization Profile abilities must be a list.")
        for ability in value["abilities"]:
            if not isinstance(ability, dict) or not _positive_int(ability.get("id")):
                raise InputError("Every specialization ability requires a positive numeric id.")
        for field in ("resources", "cooldown_relationships", "role_guardrails"):
            if not isinstance(value.get(field), list) or not value[field]:
                raise InputError(f"Specialization Profile requires non-empty {field}.")
    else:
        for field in ("encounter_id", "difficulty_id"):
            if not _positive_int(identity.get(field)):
                raise InputError(f"Encounter Profile identity requires a positive {field}.")
        eligibility = value.get("eligibility")
        if not isinstance(eligibility, dict):
            raise InputError("Encounter Profile requires eligibility rules.")
        if not isinstance(eligibility.get("priority_target_ids"), list):
            raise InputError("Encounter Profile eligibility requires priority_target_ids.")
        if not isinstance(eligibility.get("excluded_target_ids"), list):
            raise InputError("Encounter Profile eligibility requires excluded_target_ids.")
        for field in ("phases", "mechanic_anchors"):
            if not isinstance(value.get(field), list) or not value[field]:
                raise InputError(f"Encounter Profile requires non-empty {field}.")
    sources = value.get("sources")
    if not isinstance(sources, list) or not sources:
        raise InputError("Profile requires at least one sourced assertion.")
    for source in sources:
        if not isinstance(source, dict):
            raise InputError("Profile source must be an object.")
        for field in ("url", "title", "accessed_at", "quote_summary", "content_hash"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                raise InputError(f"Profile source requires {field}.")
        if re.fullmatch(r"[0-9a-fA-F]{64}", source["content_hash"]) is None:
            raise InputError("Profile source content_hash must be a SHA-256 hex digest.")
        try:
            datetime.fromisoformat(source["accessed_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise InputError("Profile source accessed_at must be ISO 8601.") from exc
    canonical = dict(value)
    canonical.pop("profile_id", None)
    profile_id = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return canonical | {"profile_id": profile_id}


class ProfileStore:
    def __init__(self, root: Path) -> None:
        self.root = root / "profiles"

    def store(self, value: Any) -> Path:
        profile = validate_profile(value)
        path = self.root / profile["kind"] / f"{profile['profile_id']}.json"
        return atomic_write_json(path, profile)

    def load(self, path: Path, expected_kind: ProfileKind | None = None) -> dict[str, Any]:
        return validate_profile(read_json(path), expected_kind)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
