# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Variance analysis for the GAIA Email Triage Agent benchmark.

Computes statistical summaries (mean, stdev, min, max, CV%) and
+/- deltas between consecutive runs for duration, tokens, and
category distributions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class RunDelta:
    """+/- delta between two consecutive runs."""

    run_id_a: str  # earlier run
    run_id_b: str  # later run
    delta_duration_ms: int  # B - A
    delta_input_tokens: int
    delta_output_tokens: int
    delta_reasoning_tokens: int
    delta_total_tokens: int
    delta_total_emails: int
    delta_avg_ttft_ms: float = 0.0  # B - A, avg TTFT in milliseconds
    delta_avg_tps: float = 0.0      # B - A, avg tokens per second
    category_deltas: dict[str, int] = field(default_factory=dict)
    # Per-category: count in B - count in A


@dataclass
class BatchDelta:
    """+/- delta for a specific batch between two runs."""

    batch_number: int
    run_id_a: str
    run_id_b: str
    delta_duration_ms: int
    delta_input_tokens: int
    delta_output_tokens: int
    delta_reasoning_tokens: int
    delta_avg_ttft_ms: float = 0.0
    delta_avg_tps: float = 0.0
    delta_email_count: int


@dataclass
class VarianceSummary:
    """Statistical summary across multiple runs."""

    metric: str  # e.g., "total_duration_ms", "total_tokens"
    mean: float
    stdev: float
    min_val: float
    max_val: float
    cv_pct: float  # coefficient of variation (%)
    values: list[float] = field(default_factory=list)


@dataclass
class ComparisonReport:
    """Full comparison report across multiple benchmark runs."""

    runs_compared: int
    run_deltas: list[RunDelta] = field(default_factory=list)
    batch_deltas: list[BatchDelta] = field(default_factory=list)
    variance_summaries: list[VarianceSummary] = field(default_factory=list)
    category_stability: dict[str, dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _stdev(values: list[float], mean_val: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean_val) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _cv_pct(_values: list[float], mean_val: float, stdev_val: float) -> float:
    if mean_val == 0:
        return 0.0
    return abs(stdev_val / mean_val) * 100


def compute_variance(values: list[float], *, metric_name: str = "") -> VarianceSummary:
    """Compute mean/stdev/min/max/CV% for a list of values."""
    if not values:
        return VarianceSummary(
            metric=metric_name,
            mean=0.0,
            stdev=0.0,
            min_val=0.0,
            max_val=0.0,
            cv_pct=0.0,
        )
    m = _mean(values)
    s = _stdev(values, m)
    return VarianceSummary(
        metric=metric_name,
        mean=round(m, 2),
        stdev=round(s, 2),
        min_val=min(values),
        max_val=max(values),
        cv_pct=round(_cv_pct(values, m, s), 2),
        values=values,
    )


# ---------------------------------------------------------------------------
# Run-to-run deltas
# ---------------------------------------------------------------------------


def _compute_run_delta(run_a: dict, run_b: dict) -> RunDelta:
    """Compute +/- deltas between two run result dicts."""
    cat_a = run_a.get("category_counts", {})
    cat_b = run_b.get("category_counts", {})
    all_cats = set(cat_a.keys()) | set(cat_b.keys())

    category_deltas = {}
    for cat in sorted(all_cats):
        category_deltas[cat] = cat_b.get(cat, 0) - cat_a.get(cat, 0)

    return RunDelta(
        run_id_a=run_a.get("run_id", "unknown"),
        run_id_b=run_b.get("run_id", "unknown"),
        delta_duration_ms=run_b.get("total_duration_ms", 0)
        - run_a.get("total_duration_ms", 0),
        delta_input_tokens=run_b.get("total_input_tokens", 0)
        - run_a.get("total_input_tokens", 0),
        delta_output_tokens=run_b.get("total_output_tokens", 0)
        - run_a.get("total_output_tokens", 0),
        delta_reasoning_tokens=run_b.get("total_reasoning_tokens", 0)
        - run_a.get("total_reasoning_tokens", 0),
        delta_total_tokens=run_b.get("total_tokens", 0) - run_a.get("total_tokens", 0),
        delta_total_emails=run_b.get("total_emails", 0) - run_a.get("total_emails", 0),
        delta_avg_ttft_ms=run_b.get("avg_time_to_first_token_ms", 0)
        - run_a.get("avg_time_to_first_token_ms", 0),
        delta_avg_tps=run_b.get("avg_tokens_per_second", 0)
        - run_a.get("avg_tokens_per_second", 0),
        category_deltas=category_deltas,
    )


def _compute_batch_deltas(run_a: dict, run_b: dict) -> list[BatchDelta]:
    """Compute per-batch deltas between two runs."""
    deltas = []
    batches_a = {b["batch_number"]: b for b in run_a.get("batch_results", [])}
    batches_b = {b["batch_number"]: b for b in run_b.get("batch_results", [])}
    all_batch_nums = set(batches_a.keys()) | set(batches_b.keys())

    for batch_num in sorted(all_batch_nums):
        ba = batches_a.get(batch_num, {})
        bb = batches_b.get(batch_num, {})
        deltas.append(
            BatchDelta(
                batch_number=batch_num,
                run_id_a=run_a.get("run_id", "unknown"),
                run_id_b=run_b.get("run_id", "unknown"),
                delta_duration_ms=bb.get("duration_ms", 0) - ba.get("duration_ms", 0),
                delta_input_tokens=bb.get("total_input_tokens", 0)
                - ba.get("total_input_tokens", 0),
                delta_output_tokens=bb.get("total_output_tokens", 0)
                - ba.get("total_output_tokens", 0),
                delta_reasoning_tokens=bb.get("total_reasoning_tokens", 0)
                - ba.get("total_reasoning_tokens", 0),
                delta_avg_ttft_ms=bb.get("avg_time_to_first_token_ms", 0)
                - ba.get("avg_time_to_first_token_ms", 0),
                delta_avg_tps=bb.get("avg_tokens_per_second", 0)
                - ba.get("avg_tokens_per_second", 0),
                delta_email_count=len(bb.get("email_results", []))
                - len(ba.get("email_results", [])),
            )
        )
    return deltas


# ---------------------------------------------------------------------------
# Category stability analysis
# ---------------------------------------------------------------------------


def _compute_category_stability(runs: list[dict]) -> dict[str, dict[str, Any]]:
    """Track how category counts vary across runs."""
    all_cats: set[str] = set()
    for run in runs:
        all_cats.update(run.get("category_counts", {}).keys())

    stability = {}
    for cat in sorted(all_cats):
        counts = [run.get("category_counts", {}).get(cat, 0) for run in runs]
        m = _mean(counts)
        s = _stdev(counts, m)
        stability[cat] = {
            "mean": round(m, 2),
            "stdev": round(s, 2),
            "min": min(counts) if counts else 0,
            "max": max(counts) if counts else 0,
            "cv_pct": round(_cv_pct(counts, m, s), 2),
            "counts_per_run": counts,
        }
    return stability


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compare_runs(runs: list[dict]) -> ComparisonReport:
    """Compare multiple benchmark runs and compute variance + deltas.

    Args:
        runs: List of run result dicts (from JSON/JSONL output).

    Returns:
        ComparisonReport with run deltas, batch deltas, and variance summaries.
    """
    if len(runs) < 2:
        # Single run — compute variance summaries with single values.
        report = ComparisonReport(runs_compared=len(runs))
        if runs:
            run = runs[0]
            # Duration metrics: ms → mins.
            for metric_key in [
                "total_duration_ms",
                "avg_duration_per_email_ms",
            ]:
                val = run.get(metric_key, 0) / 60_000
                report.variance_summaries.append(
                    VarianceSummary(
                        metric=metric_key.replace("_ms", "_mins"),
                        mean=val,
                        stdev=0.0,
                        min_val=val,
                        max_val=val,
                        cv_pct=0.0,
                        values=[val],
                    )
                )
            for metric_key in [
                "total_input_tokens",
                "total_output_tokens",
                "total_reasoning_tokens",
                "total_tokens",
                "total_emails",
                "avg_input_tokens_per_email",
                "avg_output_tokens_per_email",
                "avg_total_tokens_per_email",
            ]:
                val = run.get(metric_key, 0)
                report.variance_summaries.append(
                    VarianceSummary(
                        metric=metric_key,
                        mean=val,
                        stdev=0.0,
                        min_val=val,
                        max_val=val,
                        cv_pct=0.0,
                        values=[val],
                    )
                )
            report.category_stability = _compute_category_stability(runs)
        return report

    # Compute run-to-run deltas.
    run_deltas = []
    batch_deltas = []
    for i in range(1, len(runs)):
        run_deltas.append(_compute_run_delta(runs[i - 1], runs[i]))
        batch_deltas.extend(_compute_batch_deltas(runs[i - 1], runs[i]))

    # Compute variance summaries across all runs.
    variance_summaries = []

    # Duration metrics: convert ms → mins before computing variance.
    duration_keys = ["total_duration_ms", "avg_duration_per_email_ms"]
    for key in duration_keys:
        values_ms = [run.get(key, 0) for run in runs]
        values_mins = [v / 60_000 for v in values_ms]
        display_key = key.replace("_ms", "_mins")
        variance_summaries.append(compute_variance(values_mins, metric_name=display_key))

    # Non-duration metrics: pass through as-is.
    for metric_key in [
        "total_input_tokens",
        "total_output_tokens",
        "total_reasoning_tokens",
        "total_tokens",
        "total_emails",
        "avg_input_tokens_per_email",
        "avg_output_tokens_per_email",
        "avg_total_tokens_per_email",
        "avg_time_to_first_token_ms",
        "avg_tokens_per_second",
    ]:
        values = [run.get(metric_key, 0) for run in runs]
        variance_summaries.append(compute_variance(values, metric_name=metric_key))

    # Category stability.
    category_stability = _compute_category_stability(runs)

    return ComparisonReport(
        runs_compared=len(runs),
        run_deltas=run_deltas,
        batch_deltas=batch_deltas,
        variance_summaries=variance_summaries,
        category_stability=category_stability,
    )


# ---------------------------------------------------------------------------
# Human-readable report
# ---------------------------------------------------------------------------


def print_comparison_report(report: ComparisonReport) -> None:
    """Print a human-readable comparison report to stdout."""
    print(f"\n{'='*70}")
    print("  GAIA Email Triage Benchmark — Variance Analysis")
    print(f"{'='*70}")
    print(f"  Runs compared: {report.runs_compared}")

    if report.run_deltas:
        print("\n  Run-to-Run Deltas (+/- values):")
        print(f"  {'─'*66}")
        for delta in report.run_deltas:
            sign_dur = "+" if delta.delta_duration_ms >= 0 else ""
            sign_tok = "+" if delta.delta_total_tokens >= 0 else ""
            print(f"  {delta.run_id_a[-14:]} → {delta.run_id_b[-14:]}")
            print(f"    Duration: {sign_dur}{delta.delta_duration_ms}ms")
            print(f"    Tokens:   {sign_tok}{delta.delta_total_tokens}")
            sign_ttft = "+" if delta.delta_avg_ttft_ms >= 0 else ""
            sign_tps = "+" if delta.delta_avg_tps >= 0 else ""
            print(f"    TTFT:     {sign_ttft}{delta.delta_avg_ttft_ms:.1f}ms")
            print(f"    TPS:      {sign_tps}{delta.delta_avg_tps:.1f}")
            if delta.category_deltas:
                for cat, d in sorted(delta.category_deltas.items()):
                    sign = "+" if d >= 0 else ""
                    print(f"    {cat}: {sign}{d}")
            print(f"  {'─'*66}")

    if report.variance_summaries:
        print("\n  Variance Summary (across all runs):")
        print(f"  {'─'*66}")
        for vs in report.variance_summaries:
            print(
                f"  {vs.metric:<30s}: μ={vs.mean:>10.2f}  "
                f"σ={vs.stdev:>10.2f}  "
                f"min={vs.min_val:>8.2f}  "
                f"max={vs.max_val:>8.2f}  "
                f"CV={vs.cv_pct:>5.1f}%"
            )

    if report.category_stability:
        print("\n  Category Stability:")
        print(f"  {'─'*66}")
        for cat, stats in sorted(report.category_stability.items()):
            print(
                f"  {cat:<16s}: μ={stats['mean']:.1f}  "
                f"σ={stats['stdev']:.1f}  "
                f"range=[{stats['min']}, {stats['max']}]  "
                f"CV={stats['cv_pct']:.1f}%"
            )

    print(f"{'='*70}\n")


def to_dict(report: ComparisonReport) -> dict[str, Any]:
    """Serialize a ComparisonReport to a JSON-serializable dict."""
    return {
        "runs_compared": report.runs_compared,
        "run_deltas": [
            {
                "run_id_a": d.run_id_a,
                "run_id_b": d.run_id_b,
                "delta_duration_ms": d.delta_duration_ms,
                "delta_input_tokens": d.delta_input_tokens,
                "delta_output_tokens": d.delta_output_tokens,
                "delta_reasoning_tokens": d.delta_reasoning_tokens,
                "delta_total_tokens": d.delta_total_tokens,
                "delta_total_emails": d.delta_total_emails,
                "delta_avg_ttft_ms": round(d.delta_avg_ttft_ms, 1),
                "delta_avg_tps": round(d.delta_avg_tps, 1),
                "category_deltas": d.category_deltas,
            }
            for d in report.run_deltas
        ],
        "batch_deltas": [
            {
                "batch_number": d.batch_number,
                "run_id_a": d.run_id_a,
                "run_id_b": d.run_id_b,
                "delta_duration_ms": d.delta_duration_ms,
                "delta_input_tokens": d.delta_input_tokens,
                "delta_output_tokens": d.delta_output_tokens,
                "delta_reasoning_tokens": d.delta_reasoning_tokens,
                "delta_avg_ttft_ms": round(d.delta_avg_ttft_ms, 1),
                "delta_avg_tps": round(d.delta_avg_tps, 1),
                "delta_email_count": d.delta_email_count,
            }
            for d in report.batch_deltas
        ],
        "variance_summaries": [
            {
                "metric": vs.metric,
                "mean": vs.mean,
                "stdev": vs.stdev,
                "min": vs.min_val,
                "max": vs.max_val,
                "cv_pct": vs.cv_pct,
            }
            for vs in report.variance_summaries
        ],
        "category_stability": report.category_stability,
    }
