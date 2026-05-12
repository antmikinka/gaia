# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Script 3: Unified Report Generator.

Reads results.jsonl (and optional clawflow_results.json) from a directory,
produces:
    report.csv            -- unified table
    variance.json         -- statistical variance analysis
    statistical_tests.json -- Mann-Whitney U, Cliff's delta, bootstrap CI
    framework_comparison.json -- GAIA vs ClawFlow (only if ClawFlow data present)
    charts/               -- PNGs (via visualize.py)

Can be re-run without re-running benchmarks.
ClawFlow is optional: if no clawflow_results.json, skip GAIA-vs-ClawFlow sections.

Usage:
    gaia email report --input-dir benchmark_results --charts
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Optional


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gaia email report",
        description="Generate reports from existing benchmark data.",
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        default="benchmark_results",
        help="Directory containing results.jsonl and optional clawflow_results.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to write reports. Defaults to --input-dir.",
    )
    parser.add_argument(
        "--charts",
        action="store_true",
        help="Generate chart PNGs.",
    )
    parser.add_argument(
        "--chart-dir",
        type=str,
        default=None,
        help="Directory for charts. Defaults to <input-dir>/charts.",
    )
    parser.add_argument(
        "--skip-cold-start",
        action="store_true",
        help="Exclude cold-start runs from variance analysis.",
    )
    parser.add_argument(
        "--ground-truth",
        type=str,
        default=None,
        help="Path to ground truth JSON for quality scoring.",
    )
    parser.add_argument(
        "--cost-per-1m-input",
        type=float,
        default=0.0,
        help="Cost per 1M input tokens.",
    )
    parser.add_argument(
        "--cost-per-1m-output",
        type=float,
        default=0.0,
        help="Cost per 1M output tokens.",
    )
    return parser


# ---------------------------------------------------------------------------
# Report generation helpers
# ---------------------------------------------------------------------------

UNIFIED_CSV_COLUMNS = [
    "model",
    "framework",
    "experiment",
    "duration_s",
    "emails",
    "tokens_in",
    "tokens_out",
    "categories",
    "status",
    "cost_usd",
    "quality_score",
]


def _compute_run_cost(run: dict[str, Any], cost_per_1m_input: float, cost_per_1m_output: float) -> float:
    """Compute estimated cost for a single run dict."""
    if cost_per_1m_input == 0.0 and cost_per_1m_output == 0.0:
        return 0.0
    input_cost = run.get("total_input_tokens", 0) * cost_per_1m_input / 1_000_000
    output_cost = run.get("total_output_tokens", 0) * cost_per_1m_output / 1_000_000
    return round(input_cost + output_cost, 6)


def _compute_run_quality(run: dict[str, Any], ground_truth: dict[str, Any]) -> float:
    """Compute classification accuracy for a run dict against ground truth."""
    if not ground_truth:
        return 0.0
    # Per-email categories live in batch_results[].email_results[].
    batch_results = run.get("batch_results", [])
    if not batch_results:
        return 0.0
    correct = 0
    total = 0
    for batch in batch_results:
        for email in batch.get("email_results", []):
            email_id = email.get("email_id", "")
            if email_id in ground_truth:
                total += 1
                gt_category = ground_truth[email_id].get("category", "")
                actual_category = email.get("category", "")
                if actual_category.lower() == gt_category.lower():
                    correct += 1
    return round(correct / max(total, 1), 4) if total > 0 else 0.0


def _generate_report_csv(
    runs: list[dict[str, Any]],
    clawflow_run: dict[str, Any] | None,
    output_path: Path,
    *,
    cost_per_1m_input: float = 0.0,
    cost_per_1m_output: float = 0.0,
    ground_truth: dict[str, Any] | None = None,
) -> None:
    """Generate unified report.csv with GAIA + optional ClawFlow data."""
    rows = []

    # GAIA runs from JSONL.
    for i, run in enumerate(runs):
        cost = _compute_run_cost(run, cost_per_1m_input, cost_per_1m_output)
        quality = _compute_run_quality(run, ground_truth or {})
        rows.append({
            "model": run.get("model", "unknown"),
            "framework": run.get("source_framework", "gaia"),
            "experiment": i + 1,
            "duration_s": round(run.get("total_duration_ms", 0) / 1000, 1),
            "emails": run.get("total_emails", 0),
            "tokens_in": run.get("total_input_tokens", 0),
            "tokens_out": run.get("total_output_tokens", 0),
            "categories": ", ".join(run.get("category_counts", {}).keys()),
            "status": run.get("status", "unknown"),
            "cost_usd": cost if cost > 0 else "",
            "quality_score": quality if quality > 0 else "",
        })

    # ClawFlow run (single).
    if clawflow_run:
        cost = _compute_run_cost(clawflow_run, cost_per_1m_input, cost_per_1m_output)
        quality = _compute_run_quality(clawflow_run, ground_truth or {})
        rows.append({
            "model": clawflow_run.get("model", "unknown"),
            "framework": "clawflow",
            "experiment": 1,
            "duration_s": round(clawflow_run.get("total_duration_ms", 0) / 1000, 1),
            "emails": clawflow_run.get("total_emails", 0),
            "tokens_in": clawflow_run.get("total_input_tokens", 0),
            "tokens_out": clawflow_run.get("total_output_tokens", 0),
            "categories": ", ".join(clawflow_run.get("category_counts", {}).keys()),
            "status": clawflow_run.get("status", "unknown"),
            "cost_usd": cost if cost > 0 else "",
            "quality_score": quality if quality > 0 else "",
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=UNIFIED_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Report CSV saved to: {output_path}")


def _generate_variance_json(
    runs: list[dict[str, Any]],
    output_path: Path,
    skip_cold_start: bool = False,
) -> None:
    """Generate variance.json with statistical analysis."""
    from gaia.agents.email.bench.variance import (
        compare_runs,
        compare_runs_by_model,
        to_dict,
        print_comparison_report,
    )

    # Filter cold-start runs if requested.
    if skip_cold_start:
        filtered = [r for r in runs if not r.get("is_cold_start", False)]
        if filtered and len(filtered) < len(runs):
            print(f"  Filtered {len(runs) - len(filtered)} cold-start run(s).")
        runs = filtered if len(filtered) >= 2 else runs

    if len(runs) < 2:
        print(f"  Need >= 2 runs for variance analysis, found {len(runs)}. Skipping.")
        return

    report = compare_runs(runs)
    print_comparison_report(report)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(to_dict(report), f, indent=2, ensure_ascii=False)
    print(f"Variance report saved to: {output_path}")

    # Per-model variance (if multiple models).
    by_model = compare_runs_by_model(runs)
    if len(by_model) > 1:
        by_model_path = output_path.parent / "variance_by_model.json"
        with open(by_model_path, "w", encoding="utf-8") as f:
            json.dump(
                {m: to_dict(r) for m, r in by_model.items()},
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"Per-model variance saved to: {by_model_path}")


def _generate_quality_report(
    runs: list[dict[str, Any]],
    ground_truth: dict[str, Any],
    output_path: Path,
) -> None:
    """Generate quality.json with per-run classification accuracy."""
    quality_report: dict[str, Any] = {}
    for run in runs:
        model = run.get("model", "unknown")
        quality_score = _compute_run_quality(run, ground_truth)
        # Build per-email match details from batch_results.
        gt_matches: dict[str, Any] = {}
        for batch in run.get("batch_results", []):
            for email in batch.get("email_results", []):
                email_id = email.get("email_id", "")
                if email_id in ground_truth:
                    gt_cat = ground_truth[email_id].get("category", "unknown")
                    actual = email.get("category", "")
                    gt_matches[email_id] = {
                        "actual": actual,
                        "ground_truth": gt_cat,
                        "correct": actual.lower() == gt_cat.lower(),
                    }
        quality_report[f"{model}-{run.get('run_id', 'n/a')}"] = {
            "model": model,
            "quality_score": quality_score,
            "total_compared": len(gt_matches),
            "correct": sum(1 for v in gt_matches.values() if v["correct"]),
            "incorrect": sum(1 for v in gt_matches.values() if not v["correct"]),
            "matches": gt_matches,
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(quality_report, f, indent=2, ensure_ascii=False)
    print(f"Quality report saved to: {output_path}")


def _generate_statistical_tests(
    runs: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Generate statistical_tests.json with Mann-Whitney U, Cliff's delta, bootstrap CI."""
    from gaia.agents.email.bench.variance import (
        compare_runs_by_model,
        mann_whitney_u,
        cliffs_delta,
        bootstrap_ci,
    )

    by_model = compare_runs_by_model(runs)
    if len(by_model) < 2:
        print("  Need >= 2 models for statistical tests. Skipping.")
        return

    model_ids = sorted(by_model.keys())
    stats_report: dict[str, Any] = {}

    for i in range(len(model_ids)):
        for j in range(i + 1, len(model_ids)):
            m_a = model_ids[i]
            m_b = model_ids[j]
            vals_a = [
                r.get("total_duration_ms", 0) for r in runs if r.get("model") == m_a
            ]
            vals_b = [
                r.get("total_duration_ms", 0) for r in runs if r.get("model") == m_b
            ]
            if len(vals_a) >= 2 and len(vals_b) >= 2:
                u_stat, p_val = mann_whitney_u(vals_a, vals_b)
                delta = cliffs_delta(vals_a, vals_b)
                ci = bootstrap_ci(vals_a, vals_b)
                key = f"{m_a} vs {m_b}"
                stats_report[key] = {
                    "metric": "total_duration_ms",
                    "mann_whitney_u": round(u_stat, 4),
                    "p_value": round(p_val, 4),
                    "cliffs_delta": round(delta, 4),
                    "bootstrap_ci_95": list(ci),
                }
                print(f"  {key}:")
                print(f"    Mann-Whitney U = {u_stat:.4f}, p = {p_val:.4f}")
                print(f"    Cliff's delta  = {delta:.4f}")
                print(f"    Bootstrap 95% CI for mean diff = [{ci[0]}, {ci[1]}]")

    if stats_report:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(stats_report, f, indent=2, ensure_ascii=False)
        print(f"Statistical tests saved to: {output_path}")


def _generate_framework_comparison(
    gaia_runs: list[dict[str, Any]],
    clawflow_run: dict[str, Any],
    output_path: Path,
) -> None:
    """Generate framework_comparison.json (GAIA vs ClawFlow)."""
    from gaia.agents.email.bench.compare import (
        compare_frameworks,
        print_framework_comparison,
        save_framework_comparison,
    )

    # Use the last GAIA run for comparison.
    if not gaia_runs:
        print("  No GAIA runs for framework comparison. Skipping.")
        return

    last_gaia = gaia_runs[-1]
    print_framework_comparison(last_gaia, clawflow_run)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    comparison = compare_frameworks(last_gaia, clawflow_run)
    save_framework_comparison(comparison, output_path)
    print(f"Framework comparison saved to: {output_path}")


def _generate_charts(
    runs: list[dict[str, Any]],
    clawflow_run: dict[str, Any] | None,
    chart_dir: Path,
    jsonl_path: Path | None = None,
    last_gaia_json: dict[str, Any] | None = None,
) -> None:
    """Generate chart PNGs."""
    from gaia.agents.email.bench.visualize import generate_charts

    gaia_list = [last_gaia_json] if last_gaia_json else []
    if not gaia_list and runs:
        gaia_list = [runs[-1]]

    generate_charts(
        jsonl_path=jsonl_path,
        output_dir=chart_dir,
        multi_model_runs=runs if len(runs) >= 2 else None,
        clawflow_result=clawflow_run,
        gaia_result_for_comparison=gaia_list[0] if gaia_list else None,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_reports(
    input_dir: Path,
    output_dir: Path | None = None,
    generate_charts: bool = False,
    chart_dir: Path | None = None,
    skip_cold_start: bool = False,
    ground_truth: str | None = None,
    cost_per_1m_input: float = 0.0,
    cost_per_1m_output: float = 0.0,
) -> None:
    """Generate all reports from benchmark data in input_dir."""
    if output_dir is None:
        output_dir = input_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load GAIA results.
    jsonl_path = input_dir / "results.jsonl"
    if not jsonl_path.exists():
        print(f"Error: No results.jsonl found in {input_dir}")
        return

    from gaia.agents.email.bench.output import load_jsonl

    runs = load_jsonl(jsonl_path)
    if not runs:
        print(f"Error: results.jsonl is empty in {input_dir}")
        return

    print(f"Loaded {len(runs)} GAIA run(s) from {jsonl_path}")

    # Load optional ground truth for quality scoring.
    gt_data: dict[str, Any] | None = None
    if ground_truth:
        gt_path = Path(ground_truth)
        if gt_path.exists():
            with open(gt_path, "r", encoding="utf-8") as f:
                gt_data = json.load(f)
            print(f"Loaded ground truth from {gt_path} ({len(gt_data)} entries)")
        else:
            print(f"Warning: ground truth file not found: {gt_path}")

    # Load optional ClawFlow results.
    cf_json_path = input_dir / "clawflow_results.json"
    clawflow_run = None
    if cf_json_path.exists():
        with open(cf_json_path, "r", encoding="utf-8") as f:
            clawflow_run = json.load(f)
        print(f"Loaded ClawFlow run from {cf_json_path}")

    # 1. report.csv (with cost/quality columns if provided)
    _generate_report_csv(
        runs, clawflow_run, output_dir / "report.csv",
        cost_per_1m_input=cost_per_1m_input,
        cost_per_1m_output=cost_per_1m_output,
        ground_truth=gt_data,
    )

    # 2. quality.json (ground truth comparison, if provided)
    if gt_data:
        _generate_quality_report(runs, gt_data, output_dir / "quality.json")

    # 3. variance.json
    _generate_variance_json(runs, output_dir / "variance.json", skip_cold_start)

    # 4. statistical_tests.json
    if len(set(r.get("model", "unknown") for r in runs)) >= 2:
        _generate_statistical_tests(runs, output_dir / "statistical_tests.json")

    # 5. framework_comparison.json (only if ClawFlow present)
    if clawflow_run:
        _generate_framework_comparison(
            runs, clawflow_run, output_dir / "framework_comparison.json"
        )

    # 6. charts
    if generate_charts:
        if chart_dir is None:
            chart_dir = output_dir / "charts"
        _generate_charts(
            runs,
            clawflow_run,
            chart_dir,
            jsonl_path=jsonl_path,
            last_gaia_json=runs[-1] if runs else None,
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir) if args.output_dir else input_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate all reports.
    generate_reports(
        input_dir=input_dir,
        output_dir=output_dir,
        generate_charts=args.charts,
        chart_dir=Path(args.chart_dir) if args.chart_dir else None,
        skip_cold_start=args.skip_cold_start,
        ground_truth=args.ground_truth,
        cost_per_1m_input=args.cost_per_1m_input,
        cost_per_1m_output=args.cost_per_1m_output,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
