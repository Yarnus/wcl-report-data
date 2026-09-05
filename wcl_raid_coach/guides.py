from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .content_names import RAID_DIFFICULTY_IDS, RAID_MAP_ID
from .errors import InputError
from .cohort import verify_benchmark
from .storage import artifact_lock, atomic_write_json, read_json, sha256_file


def create_guide_snapshot(
    benchmarks: list[dict[str, Any]], *, specialization_name: str, output_dir: Path,
    ability_names: dict[str, str], encounter_names: dict[str, dict[str, Any]],
    content_names_build: str, content_names_sha256: str, ability_names_build: str = "unknown",
) -> dict[str, Any]:
    if not benchmarks:
        raise InputError("A Raid Guide requires at least one Encounter Benchmark.")
    seen: set[tuple[Any, Any]] = set()
    shared_identity: dict[str, Any] | None = None
    chapters = []
    for benchmark in benchmarks:
        if not isinstance(benchmark, dict):
            raise InputError("Encounter Benchmark must be a JSON object.")
        verify_benchmark(benchmark)
        identity = benchmark.get("identity")
        if not isinstance(identity, dict):
            raise InputError("Encounter Benchmark identity is missing.")
        if identity.get("difficulty_id") not in RAID_DIFFICULTY_IDS:
            raise InputError("Raid Guide difficulty is outside the zhCN content mapping scope.")
        key = (identity.get("encounter_id"), identity.get("difficulty_id"))
        if key in seen:
            raise InputError("A Guide Snapshot cannot contain duplicate Encounter Benchmarks.")
        seen.add(key)
        comparable = {
            field: identity.get(field)
            for field in ("game_version", "partition_id", "difficulty_id", "class_name", "spec_name")
        }
        if shared_identity is None:
            shared_identity = comparable
        elif comparable != shared_identity:
            raise InputError("Guide Snapshot Encounter Benchmarks have incompatible hard conditions.")
        if benchmark.get("sample_count", 0) < 3 or benchmark.get("stable_pattern_claims_allowed") is not True:
            raise InputError("Encounter Benchmark does not permit stable high-ranked pattern claims.")
        mechanic_anchors = _localize_mechanic_anchors(benchmark.get("mechanic_anchors", []), ability_names)
        encounter_id = identity.get("encounter_id")
        encounter_name = encounter_names.get(str(encounter_id))
        if (
            not isinstance(encounter_name, dict)
            or encounter_name.get("map_id") != RAID_MAP_ID
            or not isinstance(encounter_name.get("name_en"), str)
            or not encounter_name["name_en"].strip()
            or not isinstance(encounter_name.get("name_zh"), str)
            or not encounter_name["name_zh"].strip()
        ):
            raise InputError(f"Encounter ID {encounter_id} has no current-raid zhCN content-name mapping.")
        chapters.append(
            {
                "identity": dict(identity),
                "benchmark_id": benchmark["benchmark_id"],
                "encounter_name_en": encounter_name["name_en"],
                "encounter_name_zh": encounter_name["name_zh"],
                "sample_count": benchmark["sample_count"],
                "confidence": benchmark.get("confidence"),
                "metrics": benchmark.get("metrics", {}),
                "mechanic_anchors": mechanic_anchors,
                "encounter_profile_id": benchmark.get("encounter_profile_id"),
                "specialization_profile_id": benchmark.get("specialization_profile_id"),
                "sources": benchmark.get("sources", {}),
                "reference_samples": benchmark.get("reference_samples", []),
            }
        )
    snapshot_body = {
        "schema_version": 2,
        "specialization": specialization_name,
        "ability_names_build": ability_names_build,
        "ability_names_sha256": hashlib.sha256(
            json.dumps(ability_names, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "content_names_build": content_names_build,
        "content_names_sha256": content_names_sha256,
        "render_schema_version": 2,
        "chapters": chapters,
    }
    snapshot_id = hashlib.sha256(
        json.dumps(snapshot_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    markdown_path = output_dir / f"{snapshot_id}.md"
    index_path = output_dir / f"{snapshot_id}.json"
    with artifact_lock(index_path):
        if index_path.exists():
            snapshot = read_json(index_path)
            stored_body = {
                "schema_version": snapshot.get("schema_version"),
                "specialization": snapshot.get("specialization"),
                "ability_names_build": snapshot.get("ability_names_build"),
                "ability_names_sha256": snapshot.get("ability_names_sha256"),
                "content_names_build": snapshot.get("content_names_build"),
                "content_names_sha256": snapshot.get("content_names_sha256"),
                "render_schema_version": snapshot.get("render_schema_version"),
                "chapters": snapshot.get("chapters"),
            } if isinstance(snapshot, dict) else {}
            stored_id = hashlib.sha256(
                json.dumps(stored_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if (
                not isinstance(snapshot, dict)
                or snapshot.get("snapshot_id") != snapshot_id
                or stored_id != snapshot_id
                or not markdown_path.is_file()
                or sha256_file(markdown_path) != snapshot.get("markdown_sha256")
            ):
                raise InputError("Existing Guide Snapshot is incomplete or has an invalid identity.")
            return snapshot | {"index_path": str(index_path)}
        output_dir.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_render_markdown(specialization_name, chapters, ability_names), encoding="utf-8")
        snapshot = {
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **snapshot_body,
            "markdown_path": str(markdown_path),
            "markdown_sha256": sha256_file(markdown_path),
        }
        atomic_write_json(index_path, snapshot)
        return snapshot | {"index_path": str(index_path)}


def verify_guide_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError("Guide Snapshot must be a JSON object.")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 2:
        raise InputError("Guide Snapshot uses an unsupported schema version; build it again.")
    body_fields = (
        "schema_version", "specialization", "ability_names_build", "ability_names_sha256",
        "content_names_build", "content_names_sha256", "render_schema_version", "chapters",
    )
    body = {field: value.get(field) for field in body_fields}
    snapshot_id = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if value.get("snapshot_id") != snapshot_id:
        raise InputError("Guide Snapshot content ID is missing or invalid.")
    markdown_path = value.get("markdown_path")
    markdown_sha256 = value.get("markdown_sha256")
    if (
        not isinstance(markdown_path, str)
        or not isinstance(markdown_sha256, str)
        or not Path(markdown_path).is_file()
        or sha256_file(Path(markdown_path)) != markdown_sha256
    ):
        raise InputError("Guide Snapshot Markdown is missing or has an invalid hash.")
    chapters = value.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise InputError("Guide Snapshot chapters are malformed.")
    shared_identity = None
    seen = set()
    for chapter in chapters:
        if not isinstance(chapter, dict) or not isinstance(chapter.get("identity"), dict):
            raise InputError("Guide Snapshot chapter identity is malformed.")
        identity = chapter["identity"]
        key = (identity.get("encounter_id"), identity.get("difficulty_id"))
        if key in seen:
            raise InputError("Guide Snapshot contains duplicate encounter chapters.")
        seen.add(key)
        comparable = {
            field: identity.get(field)
            for field in ("game_version", "partition_id", "difficulty_id", "class_name", "spec_name")
        }
        if shared_identity is None:
            shared_identity = comparable
        elif comparable != shared_identity:
            raise InputError("Guide Snapshot chapters have incompatible hard conditions.")
        for field in ("benchmark_id", "encounter_profile_id", "specialization_profile_id"):
            if not isinstance(chapter.get(field), str) or re.fullmatch(r"[0-9a-f]{64}", chapter[field]) is None:
                raise InputError(f"Guide Snapshot chapter {field} is malformed.")
        if type(chapter.get("sample_count")) is not int or chapter["sample_count"] < 3:
            raise InputError("Guide Snapshot chapter sample count is malformed.")
    return value


def _render_markdown(
    specialization_name: str, chapters: list[dict[str, Any]], ability_names: dict[str, str]
) -> str:
    lines = [f"# {specialization_name} 当前团队副本高分日志攻略", "", "## 使用范围", ""]
    lines.append("以下模式来自同一首领、难度、专精和排名分区的有效参考样本。不同首领的样本不会混合。")
    for chapter in chapters:
        identity = chapter["identity"]
        encounter_heading = chapter["encounter_name_zh"]
        lines.extend(
            [
                "",
                f"## {encounter_heading}",
                "",
                f"- 样本数：{chapter['sample_count']}",
                f"- 置信度：{chapter['confidence']}",
                f"- 分区：{identity.get('partition_id')}",
                "",
                "### 日志事实",
                "",
                f"- 有效伤害中位数：{chapter['metrics'].get('damage_total_median', '不可用')}",
                f"- 技能施放中位数：{_localized_values(chapter['metrics'].get('casts_median', {}), ability_names)}",
                f"- 首次施放时间中位数（毫秒）：{_localized_values(chapter['metrics'].get('first_cast_ms_median', {}), ability_names)}",
                f"- 目标伤害中位数：{json.dumps(chapter['metrics'].get('damage_by_target_median', {}), ensure_ascii=False, sort_keys=True)}",
                "",
                "### 机制时间线",
                "",
                *_render_mechanic_anchors(chapter.get("mechanic_anchors", [])),
                "",
                "### 资料结论",
                "",
                f"- 本章节由 Encounter Profile `{chapter.get('encounter_profile_id')}` 约束；具体机制说明应引用该 Profile 的来源摘要。",
                f"- 专精规则由 Specialization Profile `{chapter.get('specialization_profile_id')}` 约束。",
                f"- 来源摘要：{_source_summaries(chapter.get('sources'))}",
                "",
                "### 推断",
                "",
                "- 仅可依据上述日志事实与已校验 Profile 补充实战建议；不得把总排名差距写成可实现提升。",
            ]
        )
    lines.extend(["", "## 下一把动作", "", "- 按各 Boss 章节核对爆发、目标选择和个人减伤锚点。", ""])
    return "\n".join(lines)


def _localize_mechanic_anchors(value: Any, ability_names: dict[str, str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise InputError("Encounter Benchmark mechanic anchors are malformed.")
    result = []
    for anchor in value:
        if (
            not isinstance(anchor, dict)
            or not isinstance(anchor.get("ability_id"), int)
            or isinstance(anchor["ability_id"], bool)
        ):
            raise InputError("Encounter Benchmark mechanic anchor ID is malformed.")
        ability_id = str(anchor["ability_id"])
        name = ability_names.get(ability_id)
        if not isinstance(name, str) or not name.strip():
            raise InputError(f"Spell ID {ability_id} has no zhCN SpellName mapping.")
        result.append(dict(anchor) | {"name_zh": name})
    return result


def _localized_values(value: Any, ability_names: dict[str, str]) -> str:
    if not isinstance(value, dict) or not value:
        return "不可用"
    return "；".join(
        f"{ability_names.get(str(ability), f'未本地化技能（ID {ability}）')}：{amount}"
        for ability, amount in sorted(value.items(), key=lambda item: str(item[0]))
    )


def _render_mechanic_anchors(value: Any) -> list[str]:
    if not value:
        return ["暂无已验证的机制 Spell 时间锚点。"]
    lines = ["| 观察时间 | 机制 Spell |", "| --- | --- | "]
    for anchor in value:
        timestamp = anchor.get("observed_anchor_ms")
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            time_text = f"约 {timestamp / 1000:g} 秒"
        else:
            time_text = "时间未确定"
        lines.append(f"| {time_text} | {anchor['name_zh']} |")
    return lines


def _source_summaries(value: Any) -> str:
    if not isinstance(value, dict):
        return "不可用"
    summaries = []
    for kind in ("encounter", "specialization"):
        sources = value.get(kind)
        if isinstance(sources, list):
            summaries.extend(
                f"[{source.get('title')}]({source.get('url')})：{source.get('quote_summary')}"
                for source in sources
                if isinstance(source, dict)
            )
    return "；".join(summaries) if summaries else "不可用"
