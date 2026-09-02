from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import InputError
from .cohort import verify_benchmark
from .storage import artifact_lock, atomic_write_json, read_json, sha256_file


def create_guide_snapshot(
    benchmarks: list[dict[str, Any]], *, specialization_name: str, output_dir: Path, signing_key: str
) -> dict[str, Any]:
    if not benchmarks:
        raise InputError("A Raid Guide requires at least one Encounter Benchmark.")
    seen: set[tuple[Any, Any]] = set()
    shared_identity: dict[str, Any] | None = None
    chapters = []
    for benchmark in benchmarks:
        if not isinstance(benchmark, dict):
            raise InputError("Encounter Benchmark must be a JSON object.")
        verify_benchmark(benchmark, signing_key)
        identity = benchmark.get("identity")
        if not isinstance(identity, dict):
            raise InputError("Encounter Benchmark identity is missing.")
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
        chapters.append(
            {
                "identity": dict(identity),
                "sample_count": benchmark["sample_count"],
                "confidence": benchmark.get("confidence"),
                "metrics": benchmark.get("metrics", {}),
                "encounter_profile_id": benchmark.get("encounter_profile_id"),
                "specialization_profile_id": benchmark.get("specialization_profile_id"),
                "sources": benchmark.get("sources", {}),
                "reference_samples": benchmark.get("reference_samples", []),
            }
        )
    snapshot_body = {"specialization": specialization_name, "chapters": chapters}
    snapshot_id = hashlib.sha256(
        json.dumps(snapshot_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    markdown_path = output_dir / f"{snapshot_id}.md"
    index_path = output_dir / f"{snapshot_id}.json"
    with artifact_lock(index_path):
        if index_path.exists():
            snapshot = read_json(index_path)
            stored_body = {
                "specialization": snapshot.get("specialization"),
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
        markdown_path.write_text(_render_markdown(specialization_name, chapters), encoding="utf-8")
        snapshot = {
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **snapshot_body,
            "markdown_path": str(markdown_path),
            "markdown_sha256": sha256_file(markdown_path),
        }
        atomic_write_json(index_path, snapshot)
        return snapshot | {"index_path": str(index_path)}


def _render_markdown(specialization_name: str, chapters: list[dict[str, Any]]) -> str:
    lines = [f"# {specialization_name} 当前团队副本高分日志攻略", "", "## 使用范围", ""]
    lines.append("以下模式来自同一首领、难度、专精和排名分区的有效参考样本。不同首领的样本不会混合。")
    for chapter in chapters:
        identity = chapter["identity"]
        lines.extend(
            [
                "",
                f"## Encounter {identity.get('encounter_id')}",
                "",
                f"- 样本数：{chapter['sample_count']}",
                f"- 置信度：{chapter['confidence']}",
                f"- 分区：{identity.get('partition_id')}",
                "",
                "### 日志事实",
                "",
                f"- 有效伤害中位数：{chapter['metrics'].get('damage_total_median', '不可用')}",
                f"- 技能施放中位数：{json.dumps(chapter['metrics'].get('casts_median', {}), ensure_ascii=False, sort_keys=True)}",
                f"- 首次施放时间中位数（毫秒）：{json.dumps(chapter['metrics'].get('first_cast_ms_median', {}), ensure_ascii=False, sort_keys=True)}",
                f"- 目标伤害中位数：{json.dumps(chapter['metrics'].get('damage_by_target_median', {}), ensure_ascii=False, sort_keys=True)}",
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
