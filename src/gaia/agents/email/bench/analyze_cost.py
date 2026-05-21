# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Cost analysis for GAIA Email Triage benchmark results.

Reads JSONL benchmark output (with token breakdown: input/reasoning/output)
and computes per-model cost estimates using published pricing tables.

Usage:
    gaia email bench --model foo ...   # produces results_foo.jsonl
    python -m gaia.agents.email.bench.analyze_cost --results results_foo.jsonl
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Pricing table (USD per 1M tokens) — sourced from vendor pricing as of
# May 2026. Update when pricing changes.
# ---------------------------------------------------------------------------
_PRICING_PER_1M: dict[str, tuple[float, float]] = {
    # Model ID prefix → (input, output) pricing per 1M tokens
    "qwen3.5-0.8b-gguf": (0.0, 0.0),
    "qwen3.5-4b-gguf": (0.0, 0.0),
    "qwen3.5-9b-gguf": (0.0, 0.0),
    "qwen3.5-35b-a3b-gguf": (0.0, 0.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-6": (15.0, 75.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
}


def _lookup_pricing(model_id: str) -> tuple[float, float]:
    """Return (input_price_per_1m, output_price_per_1m) for a model."""
    key = model_id.lower().strip()
    if key in _PRICING_PER_1M:
        return _PRICING_PER_1M[key]
    for prefix, prices in _PRICING_PER_1M.items():
        if key.startswith(prefix):
            return prices
    return (0.0, 0.0)


@dataclass
class RunCost:
    """Cost breakdown for a single benchmark run."""
    run_id: str = ""
    model: str = ""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_tokens: int = 0
    total_emails: int = 0
    total_duration_ms: int = 0
    heuristic_triaged: int = 0
    llm_triaged: int = 0
    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    cost_per_email_usd: float = 0.0
    cost_per_1k_emails_usd: float = 0.0
    cost_per_10k_emails_usd: float = 0.0
    heuristic_savings_pct: float = 0.0


def _compute_run_cost(record: dict[str, Any]) -> RunCost:
    """Compute cost for a single JSONL record."""
    result = RunCost(
        run_id=record.get("run_id", ""),
        model=record.get("model", ""),
        total_input_tokens=record.get("total_input_tokens", 0) or 0,
        total_output_tokens=record.get("total_output_tokens", 0) or 0,
        total_reasoning_tokens=record.get("total_reasoning_tokens", 0) or 0,
        total_tokens=record.get("total_tokens", 0) or 0,
        total_emails=record.get("total_emails", 0) or 0,
        total_duration_ms=record.get("total_duration_ms", 0) or 0,
    )

    if "heuristic_triaged" in record:
        val = record["heuristic_triaged"]
        result.heuristic_triaged = len(val) if isinstance(val, dict) else val
    if "llm_triaged" in record:
        val = record["llm_triaged"]
        result.llm_triaged = len(val) if isinstance(val, dict) else val

    input_p, output_p = _lookup_pricing(result.model)
    result.input_cost_usd = (result.total_input_tokens / 1_000_000) * input_p
    result.output_cost_usd = (result.total_output_tokens / 1_000_000) * output_p
    result.total_cost_usd = result.input_cost_usd + result.output_cost_usd

    if result.total_emails > 0:
        result.cost_per_email_usd = result.total_cost_usd / result.total_emails
        result.cost_per_1k_emails_usd = result.cost_per_email_usd * 1_000
        result.cost_per_10k_emails_usd = result.cost_per_email_usd * 10_000

    total_triaged = result.heuristic_triaged + result.llm_triaged
    if total_triaged > 0:
        result.heuristic_savings_pct = (
            result.heuristic_triaged / total_triaged
        ) * 100

    return result


def load_results(path: str) -> list[RunCost]:
    """Load JSONL results and compute cost for each record."""
    results_path = Path(path)
    if not results_path.exists():
        raise FileNotFoundError(f"Results file not found: {path}")

    costs: list[RunCost] = []
    with open(results_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                record = json.loads(line)
                costs.append(_compute_run_cost(record))
            except json.JSONDecodeError:
                continue
    return costs


def print_cost_report(costs: list[RunCost]) -> None:
    """Print a human-readable cost report."""
    if not costs:
        print("No benchmark results found.")
        return

    print(f"\n{'=' * 70}")
    print("  GAIA Email Benchmark - Cost Analysis Report")
    print(f"{'=' * 70}")
    print(f"  Runs analyzed: {len(costs)}")
    print(f"{'=' * 70}")

    for c in costs:
        print(f"\n  Run: {c.run_id}")
        print(f"  Model: {c.model}")
        print(f"  Emails: {c.total_emails}")
        print(f"  Duration: {c.total_duration_ms / 1000:.1f}s")
        print(
            f"  Tokens: {c.total_input_tokens:,} in / "
            f"{c.total_output_tokens:,} out / "
            f"{c.total_reasoning_tokens:,} reasoning / "
            f"{c.total_tokens:,} total"
        )
        print(
            f"  Heuristic triaged: {c.heuristic_triaged} | "
            f"LLM triaged: {c.llm_triaged}"
        )
        if c.total_cost_usd > 0:
            print(
                f"  Cost: ${c.total_cost_usd:.4f} total "
                f"(${c.input_cost_usd:.4f} input + "
                f"${c.output_cost_usd:.4f} output)"
            )
            print(
                f"  Per email: ${c.cost_per_email_usd:.6f} | "
                f"Per 1K emails: ${c.cost_per_1k_emails_usd:.2f} | "
                f"Per 10K emails: ${c.cost_per_10k_emails_usd:.2f}"
            )
        else:
            print(
                f"  Cost: $0.00 (local Lemonade model - no API charges)"
            )
        print(f"  Heuristic savings: {c.heuristic_savings_pct:.1f}%")

    print(f"\n{'=' * 70}")
    print("  Summary")
    print(f"{'=' * 70}")
    print(
        f"  {'Model':<25} {'Run':<12} {'Emails':>6} {'Cost':>10} "
        f"{'$/Email':>10} {'Heur%':>6}"
    )
    print(f"  {'-' * 25} {'-' * 12} {'-' * 6} {'-' * 10} "
          f"{'-' * 10} {'-' * 6}")
    for c in costs:
        cost_str = (
            f"${c.total_cost_usd:.4f}" if c.total_cost_usd > 0 else "$0.00"
        )
        per_email = (
            f"${c.cost_per_email_usd:.6f}"
            if c.total_cost_usd > 0
            else "$0.00"
        )
        print(
            f"  {c.model:<25} {c.run_id:<12} {c.total_emails:>6} "
            f"{cost_str:>10} {per_email:>10} {c.heuristic_savings_pct:>5.1f}%"
        )
    print(f"{'=' * 70}\n")


def export_csv(costs: list[RunCost], path: str) -> None:
    """Export cost data to CSV."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(
            "run_id,model,total_emails,total_input_tokens,"
            "total_output_tokens,total_reasoning_tokens,total_tokens,"
            "total_duration_ms,heuristic_triaged,llm_triaged,"
            "input_cost_usd,output_cost_usd,total_cost_usd,"
            "cost_per_email_usd,cost_per_1k_emails_usd,"
            "cost_per_10k_emails_usd,heuristic_savings_pct\n"
        )
        for c in costs:
            f.write(
                f"{c.run_id},{c.model},{c.total_emails},"
                f"{c.total_input_tokens},{c.total_output_tokens},"
                f"{c.total_reasoning_tokens},{c.total_tokens},"
                f"{c.total_duration_ms},{c.heuristic_triaged},"
                f"{c.llm_triaged},{c.input_cost_usd:.6f},"
                f"{c.output_cost_usd:.6f},{c.total_cost_usd:.6f},"
                f"{c.cost_per_email_usd:.6f},"
                f"{c.cost_per_1k_emails_usd:.6f},"
                f"{c.cost_per_10k_emails_usd:.6f},"
                f"{c.heuristic_savings_pct:.1f}\n"
            )
    print(f"  CSV exported to: {out_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gaia email bench analyze-cost",
        description=(
            "Compute cost estimates from email benchmark JSONL results."
        ),
    )
    parser.add_argument(
        "--results",
        type=str,
        required=True,
        help="Path to results JSONL file (or glob pattern).",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default=None,
        help="Export cost data to CSV at this path.",
    )
    parser.add_argument(
        "--pricing",
        type=str,
        default=None,
        help="Path to custom pricing JSON file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.pricing:
        pricing_path = Path(args.pricing)
        if pricing_path.exists():
            with open(pricing_path, "r", encoding="utf-8") as f:
                custom_pricing = json.load(f)
            for model_id, prices in custom_pricing.items():
                _PRICING_PER_1M[model_id.lower()] = tuple(prices)

    try:
        costs = load_results(args.results)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    print_cost_report(costs)

    if args.output_csv:
        export_csv(costs, args.output_csv)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
