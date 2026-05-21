# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Cross-framework comparison for the GAIA Email Triage Agent benchmark.

Compares GAIA vs ClawFlow results on the same MBOX + model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class FrameworkComparison:
    """Comparison between GAIA and ClawFlow on the same MBOX + model."""

    gaia_run_id: str
    clawflow_run_id: str
    model: str  # Shared model being compared
    mbox_path: str

    # Aggregate deltas (clawflow - gaia)
    delta_duration_ms: int
    delta_input_tokens: int
    delta_output_tokens: int
    delta_total_tokens: int
    delta_total_emails: int

    # Per-framework totals
    gaia_duration_ms: int = 0
    clawflow_duration_ms: int = 0
    gaia_input_tokens: int = 0
    gaia_output_tokens: int = 0
    gaia_total_tokens: int = 0
    clawflow_input_tokens: int = 0
    clawflow_output_tokens: int = 0
    clawflow_total_tokens: int = 0

    # TTFT/TPS comparison
    gaia_avg_ttft_ms: float = 0.0
    clawflow_avg_ttft_ms: float = 0.0
    gaia_avg_tps: float = 0.0
    clawflow_avg_tps: float = 0.0

    # Category distribution
    gaia_categories: dict[str, int] = field(default_factory=dict)
    clawflow_categories: dict[str, int] = field(default_factory=dict)

    # Per-email classification agreement
    category_agreement: int = 0
    category_disagreement: int = 0
    category_mismatches: list[dict[str, str]] = field(default_factory=list)

    # Per-email counts
    gaia_emails: int = 0
    clawflow_emails: int = 0


def _email_categories_from_run(run: dict) -> dict[str, str]:
    """Extract email_id -> category from a run dict (GAIA or ClawFlow shape)."""
    cats = {}
    for batch in run.get("batch_results", []):
        for email in batch.get("email_results", []):
            if email.get("email_id"):
                cats[email["email_id"]] = email.get("category", "")
    return cats


def compare_frameworks(gaia_result: dict, clawflow_result: dict) -> FrameworkComparison:
    """Compare GAIA and ClawFlow results on the same MBOX."""
    from gaia.agents.email.bench.clawflow_adapter import normalize_categories

    g_cats = _email_categories_from_run(gaia_result)
    c_cats = _email_categories_from_run(clawflow_result)
    common_ids = set(g_cats.keys()) & set(c_cats.keys())

    agreement = 0
    disagreement = 0
    mismatches = []
    for eid in sorted(common_ids):
        g_cat = g_cats[eid]
        c_cat = c_cats[eid]
        if g_cat == c_cat:
            agreement += 1
        else:
            disagreement += 1
            mismatches.append(
                {
                    "email_id": eid,
                    "gaia_category": g_cat,
                    "clawflow_category": c_cat,
                }
            )

    g_dur = gaia_result.get("total_duration_ms", 0)
    c_dur = clawflow_result.get("total_duration_ms", 0)
    g_in = gaia_result.get("total_input_tokens", 0)
    g_out = gaia_result.get("total_output_tokens", 0)
    g_tok = gaia_result.get("total_tokens", 0)
    c_in = clawflow_result.get("total_input_tokens", 0)
    c_out = clawflow_result.get("total_output_tokens", 0)
    c_tok = clawflow_result.get("total_tokens", 0)

    # Normalize ClawFlow categories to GAIA taxonomy.
    raw_c_cats = clawflow_result.get("category_counts", {})
    normalized_c_cats = normalize_categories(raw_c_cats)

    return FrameworkComparison(
        gaia_run_id=gaia_result.get("run_id", "unknown"),
        clawflow_run_id=clawflow_result.get("run_id", "unknown"),
        model=gaia_result.get("model", clawflow_result.get("model", "unknown")),
        mbox_path=gaia_result.get("mbox_path", clawflow_result.get("mbox_path", "")),
        delta_duration_ms=c_dur - g_dur,
        delta_input_tokens=c_in - g_in,
        delta_output_tokens=c_out - g_out,
        delta_total_tokens=c_tok - g_tok,
        delta_total_emails=clawflow_result.get("total_emails", 0)
        - gaia_result.get("total_emails", 0),
        gaia_duration_ms=g_dur,
        clawflow_duration_ms=c_dur,
        gaia_input_tokens=g_in,
        gaia_output_tokens=g_out,
        gaia_total_tokens=g_tok,
        clawflow_input_tokens=c_in,
        clawflow_output_tokens=c_out,
        clawflow_total_tokens=c_tok,
        gaia_avg_ttft_ms=gaia_result.get("avg_time_to_first_token_ms", 0) or 0.0,
        clawflow_avg_ttft_ms=clawflow_result.get("avg_time_to_first_token_ms", 0)
        or 0.0,
        gaia_avg_tps=gaia_result.get("avg_tokens_per_second", 0) or 0.0,
        clawflow_avg_tps=clawflow_result.get("avg_tokens_per_second", 0) or 0.0,
        gaia_categories=gaia_result.get("category_counts", {}),
        clawflow_categories=normalized_c_cats,
        category_agreement=agreement,
        category_disagreement=disagreement,
        category_mismatches=mismatches,
        gaia_emails=gaia_result.get("total_emails", 0),
        clawflow_emails=clawflow_result.get("total_emails", 0),
    )


def print_framework_comparison(
    gaia_result: dict, clawflow_result: dict
) -> FrameworkComparison:
    """Print a comprehensive GAIA vs ClawFlow comparison to stdout."""
    c = compare_frameworks(gaia_result, clawflow_result)

    print(f"\n{'='*70}")
    print("  GAIA vs ClawFlow — Framework Comparison")
    print(f"{'='*70}")
    print(f"  Model:   {c.model}")
    print(f"  MBOX:    {c.mbox_path}")
    print(f"  Emails:  {c.gaia_emails} (GAIA) vs {c.clawflow_emails} (ClawFlow)")
    print()

    # Summary table
    print(f"  {'─'*66}")
    print(f"  {'':<28}  {'GAIA':>12}  {'ClawFlow':>12}  {'delta':>10}")
    print(f"  {'─'*66}")

    rows = [
        ("Duration (ms)", c.gaia_duration_ms, c.clawflow_duration_ms),
        (
            "Duration (s)",
            round(c.gaia_duration_ms / 1000, 1),
            round(c.clawflow_duration_ms / 1000, 1),
        ),
        ("Input tokens", c.gaia_input_tokens, c.clawflow_input_tokens),
        ("Output tokens", c.gaia_output_tokens, c.clawflow_output_tokens),
        ("Total tokens", c.gaia_total_tokens, c.clawflow_total_tokens),
    ]
    for label, g_val, cf_val in rows:
        d = cf_val - g_val
        sign = "+" if d >= 0 else ""
        g_str = f"{g_val:,}" if isinstance(g_val, int) else f"{g_val}"
        cf_str = f"{cf_val:,}" if isinstance(cf_val, int) else f"{cf_val}"
        d_str = f"{sign}{d:,}" if isinstance(d, int) else f"{sign}{d}"
        print(f"    {label:<26}  {g_str:>12}  {cf_str:>12}  {d_str:>10}")

    print()

    # TTFT/TPS comparison
    print(f"  {'─'*66}")
    print(f"  Performance:")
    print(f"  {'─'*66}")
    if c.gaia_avg_ttft_ms > 0 or c.clawflow_avg_ttft_ms > 0:
        print(
            f"    Avg TTFT:     {c.gaia_avg_ttft_ms:.0f}ms (GAIA)  vs  {c.clawflow_avg_ttft_ms:.0f}ms (ClawFlow)"
        )
    if c.gaia_avg_tps > 0 or c.clawflow_avg_tps > 0:
        print(
            f"    Avg TPS:      {c.gaia_avg_tps:.1f} t/s (GAIA)  vs  {c.clawflow_avg_tps:.1f} t/s (ClawFlow)"
        )
    print()

    # Category distribution
    print(f"  {'─'*66}")
    print(f"  Category Distribution:")
    print(f"  {'':<20}  {'GAIA':>10}  {'ClawFlow':>10}  {'delta':>6}")
    print(f"  {'─'*66}")
    all_cats = sorted(set(c.gaia_categories.keys()) | set(c.clawflow_categories.keys()))
    for cat in all_cats:
        g = c.gaia_categories.get(cat, 0)
        cf = c.clawflow_categories.get(cat, 0)
        d = cf - g
        sign = "+" if d >= 0 else ""
        print(f"    {cat:<18}  {g:>10}  {cf:>10}  {sign}{d:>5}")
    print()

    # Per-email agreement
    total = max(c.category_agreement + c.category_disagreement, 1)
    agree_pct = c.category_agreement / total * 100
    print(f"  {'─'*66}")
    print(f"  Per-Email Classification Agreement:")
    print(f"    Same category:      {c.category_agreement}/{total} ({agree_pct:.0f}%)")
    print(
        f"    Different category: {c.category_disagreement}/{total} ({100 - agree_pct:.0f}%)"
    )
    print(f"{'='*70}\n")

    return c


def save_framework_comparison(report: FrameworkComparison, path: Path) -> Path:
    """Save framework comparison report to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "gaia_run_id": report.gaia_run_id,
        "clawflow_run_id": report.clawflow_run_id,
        "model": report.model,
        "mbox_path": report.mbox_path,
        "emails_compared": report.gaia_emails,
        "totals": {
            "gaia": {
                "duration_ms": report.gaia_duration_ms,
                "input_tokens": report.gaia_input_tokens,
                "output_tokens": report.gaia_output_tokens,
                "total_tokens": report.gaia_total_tokens,
            },
            "clawflow": {
                "duration_ms": report.clawflow_duration_ms,
                "input_tokens": report.clawflow_input_tokens,
                "output_tokens": report.clawflow_output_tokens,
                "total_tokens": report.clawflow_total_tokens,
            },
            "deltas": {
                "duration_ms": report.delta_duration_ms,
                "input_tokens": report.delta_input_tokens,
                "output_tokens": report.delta_output_tokens,
                "total_tokens": report.delta_total_tokens,
            },
        },
        "performance": {
            "gaia_avg_ttft_ms": report.gaia_avg_ttft_ms,
            "clawflow_avg_ttft_ms": report.clawflow_avg_ttft_ms,
            "gaia_avg_tps": report.gaia_avg_tps,
            "clawflow_avg_tps": report.clawflow_avg_tps,
        },
        "category_distribution": {
            "gaia": report.gaia_categories,
            "clawflow": report.clawflow_categories,
        },
        "per_email_agreement": {
            "same_category": report.category_agreement,
            "different_category": report.category_disagreement,
            "agreement_pct": round(
                report.category_agreement
                / max(report.category_agreement + report.category_disagreement, 1)
                * 100,
                1,
            ),
        },
        "mismatches": report.category_mismatches,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path
