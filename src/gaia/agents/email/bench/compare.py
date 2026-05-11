# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Cross-mode comparison for the GAIA Email Triage Agent benchmark.

Compares heuristic vs full mode results to show what the LLM adds:
duration cost, token cost, category differences, and per-email mismatches.
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
class ModeComparison:
    """Comparison between heuristic and full mode on the same MBOX."""

    heuristic_run_id: str
    full_run_id: str
    mbox_path: str
    limit: int

    # Aggregate deltas
    delta_duration_ms: int  # full - heuristic
    delta_input_tokens: int
    delta_output_tokens: int
    delta_reasoning_tokens: int
    delta_total_tokens: int

    # Category overlap
    heuristic_categories: dict[str, int] = field(default_factory=dict)
    full_categories: dict[str, int] = field(default_factory=dict)
    category_agreement: int = 0
    category_disagreement: int = 0
    category_mismatches: list[dict[str, str]] = field(default_factory=list)

    # Per-mode email counts
    heuristic_emails: int = 0
    full_emails: int = 0

    # Per-mode totals
    heuristic_duration_ms: int = 0
    full_duration_ms: int = 0
    heuristic_input_tokens: int = 0
    heuristic_output_tokens: int = 0
    heuristic_reasoning_tokens: int = 0
    heuristic_total_tokens: int = 0
    full_input_tokens: int = 0
    full_output_tokens: int = 0
    full_reasoning_tokens: int = 0
    full_total_tokens: int = 0

    # Derived metrics
    heuristic_avg_ms_per_email: float = 0.0
    full_avg_ms_per_email: float = 0.0
    full_avg_tokens_per_email: float = 0.0
    full_avg_input_per_email: float = 0.0
    full_avg_output_per_email: float = 0.0
    full_avg_reasoning_per_email: float = 0.0
    full_ms_per_token: float = 0.0
    full_tokens_per_second: float = 0.0
    # TTFT/TPS from server stats
    full_avg_ttft_ms: float = 0.0
    full_avg_tps: float = 0.0

    # Quality (if ground truth available)
    heuristic_quality: float = 0.0
    full_quality: float = 0.0


# ---------------------------------------------------------------------------
# Cross-framework comparison (GAIA vs ClawFlow)
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

    # Category comparison
    gaia_categories: dict[str, int] = field(default_factory=dict)
    clawflow_categories: dict[str, int] = field(default_factory=dict)

    # Per-email classification agreement
    category_agreement: int = 0
    category_disagreement: int = 0
    category_mismatches: list[dict[str, str]] = field(default_factory=list)

    # Per-email counts
    gaia_emails: int = 0
    clawflow_emails: int = 0

    # Quality scores (if ground truth available)
    gaia_quality: float = 0.0
    clawflow_quality: float = 0.0


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


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------


def _compute_quality(run: dict) -> float:
    """Heuristic quality proxy: fraction of emails with a category assigned."""
    total = run.get("total_emails", 0)
    if total == 0:
        return 0.0
    cats = run.get("category_counts", {})
    categorized = sum(cats.values())
    return round(categorized / total, 4)


def compare_modes(heuristic: dict, full: dict) -> ModeComparison:
    """Compare heuristic and full mode results."""

    def _email_categories(run: dict) -> dict[str, str]:
        """email_id -> category."""
        cats = {}
        for batch in run.get("batch_results", []):
            for email in batch.get("email_results", []):
                if email.get("email_id"):
                    cats[email["email_id"]] = email.get("category", "")
        return cats

    h_cats = _email_categories(heuristic)
    f_cats = _email_categories(full)
    common_ids = set(h_cats.keys()) & set(f_cats.keys())

    agreement = 0
    disagreement = 0
    mismatches = []
    for eid in sorted(common_ids):
        h_cat = h_cats[eid]
        f_cat = f_cats[eid]
        if h_cat == f_cat:
            agreement += 1
        else:
            disagreement += 1
            mismatches.append(
                {
                    "email_id": eid,
                    "subject": "",
                    "heuristic_category": h_cat,
                    "full_category": f_cat,
                }
            )

    f_subjects = {}
    for batch in full.get("batch_results", []):
        for email in batch.get("email_results", []):
            if email.get("email_id"):
                f_subjects[email["email_id"]] = email.get("subject", "")
    for m in mismatches:
        m["subject"] = f_subjects.get(m["email_id"], "")

    h_emails = heuristic.get("total_emails", 0)
    f_emails = full.get("total_emails", 0)
    h_dur = heuristic.get("total_duration_ms", 0)
    f_dur = full.get("total_duration_ms", 0)
    h_tok = heuristic.get("total_tokens", 0)
    f_tok = full.get("total_tokens", 0)
    h_in = heuristic.get("total_input_tokens", 0)
    h_out = heuristic.get("total_output_tokens", 0)
    h_reason = heuristic.get("total_reasoning_tokens", 0)
    f_in = full.get("total_input_tokens", 0)
    f_out = full.get("total_output_tokens", 0)
    f_reason = full.get("total_reasoning_tokens", 0)

    h_avg = round(h_dur / max(h_emails, 1), 1)
    f_avg = round(f_dur / max(f_emails, 1), 1)
    f_avg_tok = round(f_tok / max(f_emails, 1), 1)
    f_avg_in = round(f_in / max(f_emails, 1), 1)
    f_avg_out = round(f_out / max(f_emails, 1), 1)
    f_avg_reason = round(f_reason / max(f_emails, 1), 1)
    f_ms_per_tok = round(f_dur / max(f_tok, 1), 1) if f_tok > 0 else 0.0
    f_tok_per_sec = round(f_tok / max(f_dur / 1000, 0.001), 1) if f_dur > 0 else 0.0
    # TTFT/TPS from server stats (full mode only)
    f_ttft = full.get("avg_time_to_first_token_ms", 0) or 0.0
    f_tps = full.get("avg_tokens_per_second", 0) or 0.0

    return ModeComparison(
        heuristic_run_id=heuristic.get("run_id", "unknown"),
        full_run_id=full.get("run_id", "unknown"),
        mbox_path=full.get("mbox_path", heuristic.get("mbox_path", "")),
        limit=len(common_ids),
        delta_duration_ms=f_dur - h_dur,
        delta_input_tokens=f_in - h_in,
        delta_output_tokens=f_out - h_out,
        delta_reasoning_tokens=f_reason - h_reason,
        delta_total_tokens=f_tok - h_tok,
        heuristic_categories=heuristic.get("category_counts", {}),
        full_categories=full.get("category_counts", {}),
        category_agreement=agreement,
        category_disagreement=disagreement,
        category_mismatches=mismatches,
        heuristic_emails=h_emails,
        full_emails=f_emails,
        heuristic_duration_ms=h_dur,
        full_duration_ms=f_dur,
        heuristic_input_tokens=h_in,
        heuristic_output_tokens=h_out,
        heuristic_reasoning_tokens=h_reason,
        heuristic_total_tokens=h_tok,
        full_input_tokens=f_in,
        full_output_tokens=f_out,
        full_reasoning_tokens=f_reason,
        full_total_tokens=f_tok,
        heuristic_avg_ms_per_email=h_avg,
        full_avg_ms_per_email=f_avg,
        full_avg_tokens_per_email=f_avg_tok,
        full_avg_input_per_email=f_avg_in,
        full_avg_output_per_email=f_avg_out,
        full_avg_reasoning_per_email=f_avg_reason,
        full_ms_per_token=f_ms_per_tok,
        full_tokens_per_second=f_tok_per_sec,
        full_avg_ttft_ms=f_ttft,
        full_avg_tps=f_tps,
        heuristic_quality=_compute_quality(heuristic),
        full_quality=_compute_quality(full),
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_mode_comparison(heuristic: dict, full: dict) -> ModeComparison:
    """Print a comprehensive heuristic vs full comparison to stdout."""
    c = compare_modes(heuristic, full)

    print(f"\n{'='*70}")
    print("  GAIA Email Triage Benchmark — Mode Comparison")
    print(f"{'='*70}")
    print(f"  MBOX:    {c.mbox_path}")
    print(f"  Emails:  {c.heuristic_emails} (heuristic) vs {c.full_emails} (full)")
    print()

    # Summary table — side-by-side totals
    print(f"  {'─'*66}")
    print(f"  Totals:")
    print(f"  {'':<28}  {'heuristic':>12}  {'full':>12}  {'delta':>10}")
    print(f"  {'─'*66}")

    rows = [
        ("Duration (ms)", c.heuristic_duration_ms, c.full_duration_ms),
        (
            "Duration (s)",
            round(c.heuristic_duration_ms / 1000, 1),
            round(c.full_duration_ms / 1000, 1),
        ),
        ("Input tokens", c.heuristic_input_tokens, c.full_input_tokens),
        ("Reasoning tokens", c.heuristic_reasoning_tokens, c.full_reasoning_tokens),
        ("Output tokens", c.heuristic_output_tokens, c.full_output_tokens),
        ("Total tokens", c.heuristic_total_tokens, c.full_total_tokens),
    ]
    for label, h_val, f_val in rows:
        d = f_val - h_val
        sign = "+" if d >= 0 else ""
        h_str = f"{h_val:,}" if isinstance(h_val, int) else f"{h_val}"
        f_str = f"{f_val:,}" if isinstance(f_val, int) else f"{f_val}"
        d_str = f"{sign}{d:,}" if isinstance(d, int) else f"{sign}{d}"
        print(f"    {label:<26}  {h_str:>12}  {f_str:>12}  {d_str:>10}")

    print()

    # Per-email averages
    print(f"  {'─'*66}")
    print(f"  Per-Email Averages:")
    print(f"  {'':<28}  {'heuristic':>12}  {'full':>12}")
    print(f"  {'─'*66}")

    per_email_rows = [
        ("Time per email (ms)", c.heuristic_avg_ms_per_email, c.full_avg_ms_per_email),
        (
            "Time per email (s)",
            round(c.heuristic_avg_ms_per_email / 1000, 3),
            round(c.full_avg_ms_per_email / 1000, 3),
        ),
        (
            "Input tokens/email",
            c.heuristic_input_tokens / max(c.heuristic_emails, 1),
            c.full_avg_input_per_email,
        ),
        (
            "Reasoning tokens/email",
            c.heuristic_reasoning_tokens / max(c.heuristic_emails, 1),
            c.full_avg_reasoning_per_email,
        ),
        (
            "Output tokens/email",
            c.heuristic_output_tokens / max(c.heuristic_emails, 1),
            c.full_avg_output_per_email,
        ),
        (
            "Total tokens/email",
            c.heuristic_total_tokens / max(c.heuristic_emails, 1),
            c.full_avg_tokens_per_email,
        ),
    ]
    for label, h_val, f_val in per_email_rows:
        h_str = f"{h_val:,.1f}" if isinstance(h_val, float) else f"{h_val}"
        f_str = f"{f_val:,.1f}" if isinstance(f_val, float) else f"{f_val}"
        print(f"    {label:<26}  {h_str:>12}  {f_str:>12}")

    print()

    # Efficiency metrics (full mode only)
    if c.full_total_tokens > 0:
        print(f"  {'─'*66}")
        print(f"  Full Mode Efficiency:")
        print(f"  {'─'*66}")
        print(f"    ms per token:        {c.full_ms_per_token:.1f}")
        print(f"    tokens per second:   {c.full_tokens_per_second:,.1f}")
        if c.full_avg_ttft_ms > 0:
            print(f"    avg TTFT (server):   {c.full_avg_ttft_ms:.0f}ms")
        if c.full_avg_tps > 0:
            print(f"    avg TPS (server):    {c.full_avg_tps:,.1f} tokens/s")
            if c.full_tokens_per_second > 0:
                overhead = c.full_avg_tps / c.full_tokens_per_second
                print(
                    f"    Agent overhead:    {overhead:.1f}x server TPS vs end-to-end"
                )
        print(
            f"    Time overhead vs heuristic:  {c.delta_duration_ms / max(c.heuristic_duration_ms, 1) * 100:.0f}% slower"
        )
        print()

    # Category distribution
    print(f"  {'─'*66}")
    print(f"  Category Distribution:")
    print(f"  {'':<20}  {'heuristic':>10}  {'full':>10}  {'delta':>6}")
    print(f"  {'─'*66}")
    all_cats = sorted(
        set(c.heuristic_categories.keys()) | set(c.full_categories.keys())
    )
    for cat in all_cats:
        h = c.heuristic_categories.get(cat, 0)
        f = c.full_categories.get(cat, 0)
        d = f - h
        sign = "+" if d >= 0 else ""
        print(f"    {cat:<18}  {h:>10}  {f:>10}  {sign}{d:>5}")
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

    if c.category_mismatches:
        print()
        print(f"  Mismatches ({len(c.category_mismatches)} emails):")
        for m in c.category_mismatches:
            subj = m["subject"][:60] if m["subject"] else m["email_id"][:60]
            print(
                f"    {subj:<60}  "
                f"heuristic={m['heuristic_category']:<15}  "
                f"full={m['full_category']:<15}"
            )
    print(f"{'='*70}\n")

    return c


def save_mode_comparison(report: ModeComparison, path: Path) -> Path:
    """Save comparison report to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "heuristic_run_id": report.heuristic_run_id,
        "full_run_id": report.full_run_id,
        "mbox_path": report.mbox_path,
        "emails_compared": report.limit,
        "totals": {
            "heuristic": {
                "duration_ms": report.heuristic_duration_ms,
                "input_tokens": report.heuristic_input_tokens,
                "output_tokens": report.heuristic_output_tokens,
                "reasoning_tokens": report.heuristic_reasoning_tokens,
                "total_tokens": report.heuristic_total_tokens,
            },
            "full": {
                "duration_ms": report.full_duration_ms,
                "input_tokens": report.full_input_tokens,
                "output_tokens": report.full_output_tokens,
                "reasoning_tokens": report.full_reasoning_tokens,
                "total_tokens": report.full_total_tokens,
            },
            "deltas": {
                "duration_ms": report.delta_duration_ms,
                "input_tokens": report.delta_input_tokens,
                "output_tokens": report.delta_output_tokens,
                "reasoning_tokens": report.delta_reasoning_tokens,
                "total_tokens": report.delta_total_tokens,
            },
        },
        "per_email_averages": {
            "heuristic": {
                "avg_ms_per_email": report.heuristic_avg_ms_per_email,
                "avg_tokens_per_email": report.heuristic_total_tokens
                / max(report.heuristic_emails, 1),
            },
            "full": {
                "avg_ms_per_email": report.full_avg_ms_per_email,
                "avg_input_per_email": report.full_avg_input_per_email,
                "avg_output_per_email": report.full_avg_output_per_email,
                "avg_reasoning_per_email": report.full_avg_reasoning_per_email,
                "avg_tokens_per_email": report.full_avg_tokens_per_email,
            },
        },
        "efficiency": {
            "full_ms_per_token": report.full_ms_per_token,
            "full_tokens_per_second": report.full_tokens_per_second,
            "full_avg_ttft_ms": report.full_avg_ttft_ms,
            "full_avg_tps": report.full_avg_tps,
        },
        "category_distribution": {
            "heuristic": report.heuristic_categories,
            "full": report.full_categories,
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
