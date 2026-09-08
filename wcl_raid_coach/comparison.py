from __future__ import annotations

from pathlib import Path
from typing import Any

from .analysis import ANALYSIS_SCHEMA_VERSION, analyze_player, is_finite_number, per_minute
from .cohort import verify_benchmark
from .errors import InputError


def compare_player(
    target: dict[str, Any], benchmark: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(target, dict) or not isinstance(benchmark, dict):
        raise InputError("Personal Review and Encounter Benchmark must be JSON objects.")
    verify_benchmark(benchmark)
    verify_analysis_evidence(target)
    target_identity = target.get("comparison_identity")
    benchmark_identity = benchmark.get("identity")
    if not isinstance(target_identity, dict) or not isinstance(benchmark_identity, dict):
        raise InputError("Personal Review comparison identities are missing.")
    if target_identity != benchmark_identity:
        raise InputError("Personal Review and Encounter Benchmark hard conditions do not match.")
    metrics = target.get("metrics")
    benchmark_metrics = benchmark.get("metrics")
    if not isinstance(metrics, dict) or not isinstance(benchmark_metrics, dict):
        raise InputError("Personal Review metrics are malformed.")
    target_casts = metrics.get("player_casts") if isinstance(metrics.get("player_casts"), dict) else {}
    median_casts = benchmark_metrics.get("key_action_casts_median")
    median_casts = median_casts if isinstance(median_casts, dict) else {}
    median_rates = benchmark_metrics.get("key_action_casts_per_minute_median", {})
    rate_sample_counts = benchmark_metrics.get("key_action_rate_sample_count", {})
    if not isinstance(median_rates, dict) or not isinstance(rate_sample_counts, dict):
        raise InputError("Personal Review rate metrics are malformed.")
    all_abilities = sorted(median_casts)
    cast_deltas = {
        ability: _delta(target_casts.get(ability, 0), median_casts.get(ability, 0))
        for ability in all_abilities
    }
    damage_median = benchmark_metrics.get("damage_total_median")
    damage_delta = None
    if is_finite_number(damage_median) and is_finite_number(metrics.get("damage_total")):
        damage_delta = metrics["damage_total"] - damage_median
    return {
        "schema_version": 3,
        "identity": dict(target_identity),
        "target": target.get("player"),
        "benchmark_sample_count": benchmark.get("sample_count"),
        "confidence": benchmark.get("confidence"),
        "guardrails": {
            "player_death": bool(metrics.get("deaths")),
            "unmatched_context": ["survival", "downtime", "phases", "talents", "gear", "assignments"],
        },
        "metrics": {
            "damage_total_delta": damage_delta,
            "reference_damage_total_median": damage_median,
            "cast_count_deltas": cast_deltas,
            "player_duration_ms": metrics.get("duration_ms"),
            "reference_duration_ms_median": benchmark_metrics.get("duration_ms_median"),
            "reference_duration_ms_min": benchmark_metrics.get("duration_ms_min"),
            "reference_duration_ms_max": benchmark_metrics.get("duration_ms_max"),
            "reference_rate_sample_count": benchmark_metrics.get("rate_sample_count", 0),
            "player_damage_per_minute": metrics.get("damage_per_minute"),
            "reference_damage_per_minute_median": benchmark_metrics.get("damage_per_minute_median"),
            "damage_per_minute_delta": _delta(metrics.get("damage_per_minute"), benchmark_metrics.get("damage_per_minute_median")),
            "player_healing_per_minute": metrics.get("healing_per_minute"),
            "reference_healing_per_minute_median": benchmark_metrics.get("healing_per_minute_median"),
            "reference_healing_rate_sample_count": benchmark_metrics.get("healing_rate_sample_count", 0),
            "healing_per_minute_delta": _delta(metrics.get("healing_per_minute"), benchmark_metrics.get("healing_per_minute_median")),
            "key_action_casts_per_minute_deltas": {
                ability: _delta(
                    per_minute(target_casts.get(ability, 0), metrics.get("duration_ms")),
                    median_rates.get(ability),
                ) for ability in all_abilities
            },
            "key_action_player_casts_per_minute": {
                ability: per_minute(target_casts.get(ability, 0), metrics.get("duration_ms"))
                for ability in all_abilities
            },
            "key_action_reference_casts_per_minute_median": {
                ability: median_rates.get(ability) for ability in all_abilities
            },
            "key_action_rate_sample_counts": {
                ability: rate_sample_counts.get(ability, 0) for ability in all_abilities
            },
        },
        "claim_limits": {
            "stable_patterns_allowed": benchmark.get("stable_pattern_claims_allowed") is True,
            "damage_delta_is_achievable_improvement": False,
            "sample_medians_are_prescribed_casts": False,
            "normalization_corrects_unmatched_context": False,
            "key_actions_require_profile_player_cast_declaration": True,
        },
    }


def _delta(value: Any, reference: Any) -> float | None:
    if value is None or reference is None:
        return None
    if not is_finite_number(value) or not is_finite_number(reference):
        raise InputError("Personal Review numeric metrics are malformed.")
    return value - reference


def verify_analysis_evidence(analysis: dict[str, Any]) -> None:
    if type(analysis.get("schema_version")) is not int or analysis["schema_version"] != ANALYSIS_SCHEMA_VERSION:
        raise InputError("Personal Analysis uses an unsupported schema version; run coach review again.")
    evidence = analysis.get("evidence")
    player = analysis.get("player")
    identity = analysis.get("comparison_identity")
    if not isinstance(evidence, dict) or not isinstance(player, dict) or not isinstance(identity, dict):
        raise InputError("Personal Review evidence provenance is missing.")
    actor_id = player.get("actor_id")
    if not isinstance(actor_id, int) or isinstance(actor_id, bool):
        raise InputError("Personal Review actor identity is malformed.")
    try:
        manifest_path = Path(str(evidence["manifest_path"]))
        index_path = Path(str(evidence["index_path"]))
    except KeyError as exc:
        raise InputError("Personal Review evidence provenance is incomplete.") from exc
    try:
        recomputed = analyze_player(
            manifest_path,
            index_path,
            actor_id,
            partition_id=identity.get("partition_id"),
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise InputError("Personal Review evidence could not be verified.") from exc
    if recomputed != analysis:
        raise InputError("Personal Review does not match its Complete Bundle evidence.")
