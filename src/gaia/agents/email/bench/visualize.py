# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Chart generation for the GAIA Email Triage Agent benchmark.

Produces static PNG visualizations from benchmark JSON/JSONL output,
organized by the 4-category visualization taxonomy:
  1. Comparison  (bar/column/line)
  2. Composition (donut/stacked bar)
  3. Distribution (histogram)
  4. Relationship (heatmap/scatter)
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

try:
    import matplotlib

    matplotlib.use("Agg")  # Non-interactive backend
    import matplotlib.pyplot as plt
except ImportError:  # pragma: no cover - handled at runtime
    plt = None  # type: ignore[assignment]

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

from gaia.agents.email.bench.output import load_jsonl

# ---------------------------------------------------------------------------
# Color palette — GAIA AMD-inspired
# ---------------------------------------------------------------------------
COLORS = {
    "urgent": "#E53E3E",
    "actionable": "#DD6B20",
    "informational": "#3182CE",
    "low priority": "#718096",
    "input": "#3182CE",
    "output": "#DD6B20",
    "reasoning": "#9B59B6",
    "heuristic": "#718096",
    "full": "#3182CE",
    "duration": "#DD6B20",
    "tokens": "#3182CE",
    # Framework colors.
    "gaia": "#ED6C02",  # AMD orange
    "clawflow": "#3182CE",  # Blue
}


def _require_matplotlib():
    if plt is None:
        raise RuntimeError(
            "matplotlib is required for chart generation. "
            "Install with `pip install matplotlib` or `pip install -e .[dev]`."
        )
    return plt


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _detect_mode(run: dict[str, Any]) -> str:
    return run.get("mode", "heuristic")


def _save_chart(fig, output_dir: Path, name: str, dpi: int = 150) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{name}.png"
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return path


def _compute_stats(values: list[float]) -> dict[str, float]:
    """Compute mean, stdev, min, max, CV% for a list of values."""
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "stdev": 0.0, "min": 0.0, "max": 0.0, "cv_pct": 0.0}
    mean = sum(values) / n
    if n < 2:
        stdev = 0.0
    else:
        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        stdev = variance**0.5
    min_v = min(values)
    max_v = max(values)
    cv_pct = (stdev / mean * 100) if mean != 0 else 0.0
    return {"mean": mean, "stdev": stdev, "min": min_v, "max": max_v, "cv_pct": cv_pct}


def _add_consistency_box(
    ax,
    stats: dict[str, float],
    unit: str = "",
    label: str = "LLM Non-Determinism",
    n_runs: int = 1,
    y_pos: float = 0.97,
) -> None:
    """Add a consistency report text box to the upper-right of an axis.

    Args:
        ax: Matplotlib axis to annotate.
        stats: Dict with mean, stdev, min, max, cv_pct keys.
        unit: Unit label (e.g., 'min', 'tokens').
        label: Short heading for the box.
        n_runs: Number of runs for the 'n =' line.
        y_pos: Vertical position in axes coordinates (0-1).
    """
    text = (
        f"{label}\n"
        f"n = {n_runs} runs\n"
        f"μ = {stats['mean']:.1f} {unit}\n"
        f"σ = {stats['stdev']:.1f}\n"
        f"CV = {stats['cv_pct']:.1f}%"
    )
    props = dict(
        boxstyle="round,pad=0.4", facecolor="#F7FAFC", edgecolor="#CBD5E0", alpha=0.9
    )
    ax.text(
        0.98,
        y_pos,
        text,
        transform=ax.transAxes,
        fontsize=8,
        verticalalignment="top",
        horizontalalignment="right",
        fontfamily="monospace",
        bbox=props,
    )


def _add_subtitle(fig, text: str, y_offset: float = 0.02) -> None:
    """Add a subtitle below the main title."""
    pass  # fig.text() is always available once figure exists
    fig.text(
        0.5,
        y_offset,
        text,
        ha="center",
        va="bottom",
        fontsize=8,
        color="#718096",
        style="italic",
    )


# ---------------------------------------------------------------------------
# Chart 1: Category Distribution (Comparison — Horizontal Bar)
# ---------------------------------------------------------------------------


def plot_category_distribution(run: dict[str, Any], output_dir: Path) -> Path | None:
    """Horizontal bar chart of category counts."""
    plt_mod = _require_matplotlib()
    cats = run.get("category_counts", {})
    if not cats:
        return None

    labels = sorted(cats.keys())
    values = [cats[l] for l in labels]
    colors = [COLORS.get(l.lower(), "#4c78a8") for l in labels]

    fig, ax = plt_mod.subplots(figsize=(8, 4))
    bars = ax.barh(labels, values, color=colors, edgecolor="white", height=0.5)
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_width() + 0.1,
            bar.get_y() + bar.get_height() / 2,
            str(val),
            va="center",
            fontweight="bold",
            fontsize=10,
        )
    ax.set_xlabel("Email count")
    ax.set_title("Category Distribution", fontweight="bold", fontsize=12)
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "01_category_distribution")


# ---------------------------------------------------------------------------
# Chart 2: Token Composition (Composition — Donut)
# ---------------------------------------------------------------------------


def plot_token_composition(run: dict[str, Any], output_dir: Path) -> Path | None:
    """Donut chart showing input / reasoning / output token split."""
    plt_mod = _require_matplotlib()
    in_tok = run.get("total_input_tokens", 0)
    out_tok = run.get("total_output_tokens", 0)
    reasoning_tok = run.get("total_reasoning_tokens", 0)
    if in_tok == 0 and out_tok == 0:
        return None

    fig, ax = plt_mod.subplots(figsize=(5, 5))

    if reasoning_tok > 0:
        sizes = [in_tok, reasoning_tok, out_tok]
        labels = [
            f"Input ({in_tok:,})",
            f"Reasoning ({reasoning_tok:,})",
            f"Output ({out_tok:,})",
        ]
        colors = [COLORS["input"], COLORS["reasoning"], COLORS["output"]]
    else:
        sizes = [in_tok, out_tok]
        labels = [f"Input ({in_tok:,})", f"Output ({out_tok:,})"]
        colors = [COLORS["input"], COLORS["output"]]

    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=labels,
        colors=colors,
        autopct="%1.1f%%",
        startangle=90,
        wedgeprops={"width": 0.5, "edgecolor": "white"},
    )
    for t in autotexts:
        t.set_fontsize(10)
        t.set_fontweight("bold")
    total = sum(sizes)
    ax.text(
        0,
        0,
        f"Total\n{total:,}",
        ha="center",
        va="center",
        fontsize=11,
        fontweight="bold",
    )
    ax.set_title("Token Composition", fontweight="bold", fontsize=12)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "02_token_composition")


# ---------------------------------------------------------------------------
# Chart 3: Duration vs Tokens (Comparison — Grouped Column)
# ---------------------------------------------------------------------------


def plot_duration_vs_tokens(run: dict[str, Any], output_dir: Path) -> Path | None:
    """Side-by-side columns: total duration (seconds) vs total tokens."""
    plt_mod = _require_matplotlib()
    dur = run.get("total_duration_ms", 0)
    tok = run.get("total_tokens", 0)
    if dur == 0 and tok == 0:
        return None

    dur_s = dur / 1_000
    fig, ax1 = plt_mod.subplots(figsize=(6, 4))

    x = [0]
    width = 0.35
    bar1 = ax1.bar(
        x[0] - width / 2,
        dur_s,
        width,
        label=f"Duration: {dur_s:.1f}s",
        color=COLORS["duration"],
    )
    ax1.set_ylabel("Duration (seconds)", color=COLORS["duration"])
    ax1.tick_params(axis="y", labelcolor=COLORS["duration"])

    ax2 = ax1.twinx()
    bar2 = ax2.bar(
        x[0] + width / 2, tok, width, label=f"Tokens: {tok:,}", color=COLORS["tokens"]
    )
    ax2.set_ylabel("Total tokens", color=COLORS["tokens"])
    ax2.tick_params(axis="y", labelcolor=COLORS["tokens"])

    ax1.set_xticks(x)
    ax1.set_xticklabels(["Benchmark Run"])
    ax1.set_title("Duration vs Token Cost", fontweight="bold", fontsize=12)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
    ax1.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "03_duration_vs_tokens")


# ---------------------------------------------------------------------------
# Chart 4: Per-Email Duration Histogram (Distribution)
# ---------------------------------------------------------------------------


def plot_email_duration_histogram(run: dict[str, Any], output_dir: Path) -> Path | None:
    """Histogram of per-email processing durations."""
    plt_mod = _require_matplotlib()
    durations = []
    for batch in run.get("batch_results", []):
        for email in batch.get("email_results", []):
            d = email.get("duration_ms", 0)
            if d > 0:
                durations.append(d / 1_000)  # ms → seconds

    if not durations:
        return None

    fig, ax = plt_mod.subplots(figsize=(8, 4))
    ax.hist(
        durations,
        bins=min(15, len(durations)),
        color=COLORS["duration"],
        edgecolor="white",
        alpha=0.85,
    )
    mean_dur = sum(durations) / len(durations)
    ax.axvline(
        mean_dur,
        color="black",
        linestyle="--",
        linewidth=1,
        label=f"Mean: {mean_dur:.1f}s",
    )
    ax.set_xlabel("Duration per email (seconds)")
    ax.set_ylabel("Frequency")
    ax.set_title("Per-Email Duration Distribution", fontweight="bold", fontsize=12)
    ax.legend(fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "04_email_duration_histogram")


# ---------------------------------------------------------------------------
# Chart 5: Variance Trend (Comparison — Line Graph)
# ---------------------------------------------------------------------------


def plot_variance_trend(runs: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    """Line graphs showing LLM non-determinism across iterations.

    Same emails + same prompt → different outputs due to temperature-based sampling.
    Each chart includes a consistency report (μ, σ, CV%) quantifying the variance.
    Low CV% = predictable cost. High CV% = volatile token/duration behavior.
    """
    plt_mod = _require_matplotlib()
    paths = []
    if len(runs) < 2:
        return paths

    n = len(runs)
    x = list(range(1, n + 1))

    # 5a: Duration trend (seconds) — LLM latency consistency
    dur_vals = [r.get("total_duration_ms", 0) / 1_000 for r in runs]
    dur_stats = _compute_stats(dur_vals)
    fig, ax = plt_mod.subplots(figsize=(8, 4))
    ax.plot(
        x,
        dur_vals,
        marker="o",
        linestyle="-",
        linewidth=2,
        color=COLORS["duration"],
        label="Duration",
    )
    # Mean reference line
    ax.axhline(
        dur_stats["mean"],
        color=COLORS["duration"],
        linestyle="--",
        alpha=0.4,
        linewidth=1,
    )
    for i, v in enumerate(dur_vals):
        ax.annotate(
            f"{v:.1f}",
            (x[i], v),
            textcoords="offset points",
            xytext=(0, 10),
            ha="center",
            fontsize=8,
        )
    ax.set_xlabel("Run iteration")
    ax.set_ylabel("Duration (seconds)")
    ax.set_title("LLM Latency Consistency Across Runs", fontweight="bold", fontsize=12)
    ax.set_xticks(x)
    ax.grid(True, linestyle="--", alpha=0.3)
    _add_consistency_box(ax, dur_stats, unit="s", label="Latency Variance", n_runs=n)
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    _add_subtitle(
        fig,
        "Same emails, different timing — measures inference latency non-determinism",
    )
    paths.append(_save_chart(fig, output_dir, "05a_duration_trend"))

    # 5b: Token trend — LLM output non-determinism
    tok_vals = [r.get("total_tokens", 0) for r in runs]
    if any(v > 0 for v in tok_vals):
        tok_stats = _compute_stats([float(v) for v in tok_vals])
        fig, ax = plt_mod.subplots(figsize=(8, 4))
        ax.plot(
            x,
            tok_vals,
            marker="s",
            linestyle="-",
            linewidth=2,
            color=COLORS["tokens"],
            label="Total tokens",
        )
        # Mean reference line
        ax.axhline(
            tok_stats["mean"],
            color=COLORS["tokens"],
            linestyle="--",
            alpha=0.4,
            linewidth=1,
        )
        # Reasoning token overlay if present
        reasoning_vals = [r.get("total_reasoning_tokens", 0) for r in runs]
        if any(v > 0 for v in reasoning_vals):
            ax.plot(
                x,
                reasoning_vals,
                marker="^",
                linestyle="-",
                linewidth=1.5,
                color=COLORS["reasoning"],
                label="Reasoning tokens",
            )
            reason_stats = _compute_stats([float(v) for v in reasoning_vals])
            ax.axhline(
                reason_stats["mean"],
                color=COLORS["reasoning"],
                linestyle="--",
                alpha=0.3,
                linewidth=1,
            )
        for i, v in enumerate(tok_vals):
            ax.annotate(
                f"{v:,}",
                (x[i], v),
                textcoords="offset points",
                xytext=(0, 10),
                ha="center",
                fontsize=8,
            )
        ax.set_xlabel("Run iteration")
        ax.set_ylabel("Total tokens")
        ax.set_title(
            "LLM Token Consumption Variance Across Runs", fontweight="bold", fontsize=12
        )
        ax.set_xticks(x)
        ax.legend(fontsize=9)
        ax.grid(True, linestyle="--", alpha=0.3)
        _add_consistency_box(
            ax, tok_stats, unit="tokens", label="Token Variance", n_runs=n
        )
        fig.tight_layout(rect=[0, 0.06, 1, 1])
        _add_subtitle(
            fig,
            "Same prompt, different responses — temperature-based sampling variance",
        )
        paths.append(_save_chart(fig, output_dir, "05b_token_trend"))

    # 5c: Per-email averages trend — granular cost variance
    avg_dur = [r.get("avg_duration_per_email_ms", 0) for r in runs]
    avg_tok = [r.get("avg_total_tokens_per_email", 0) for r in runs]
    if any(v > 0 for v in avg_tok) or any(v > 0 for v in avg_dur):
        avg_dur_s = [v / 1_000 for v in avg_dur]
        avg_dur_stats = _compute_stats(avg_dur_s)
        avg_tok_stats = _compute_stats([float(v) for v in avg_tok])
        fig, ax1 = plt_mod.subplots(figsize=(8, 4))
        ax1.plot(
            x,
            avg_dur_s,
            marker="o",
            linestyle="-",
            linewidth=2,
            color=COLORS["duration"],
            label="Avg duration/email (s)",
        )
        ax1.axhline(
            avg_dur_stats["mean"],
            color=COLORS["duration"],
            linestyle="--",
            alpha=0.4,
            linewidth=1,
        )
        ax1.set_xlabel("Run iteration")
        ax1.set_ylabel("Avg duration/email (s)", color=COLORS["duration"])
        ax1.tick_params(axis="y", labelcolor=COLORS["duration"])

        ax2 = ax1.twinx()
        ax2.plot(
            x,
            avg_tok,
            marker="s",
            linestyle="-",
            linewidth=2,
            color=COLORS["tokens"],
            label="Avg tokens/email",
        )
        ax2.axhline(
            avg_tok_stats["mean"],
            color=COLORS["tokens"],
            linestyle="--",
            alpha=0.4,
            linewidth=1,
        )
        ax2.set_ylabel("Avg tokens/email", color=COLORS["tokens"])
        ax2.tick_params(axis="y", labelcolor=COLORS["tokens"])

        ax1.set_title(
            "Per-Email Cost Variance (LLM Non-Determinism)",
            fontweight="bold",
            fontsize=12,
        )
        ax1.set_xticks(x)
        ax1.grid(True, linestyle="--", alpha=0.3)
        # Dual consistency boxes
        _add_consistency_box(
            ax1, avg_dur_stats, unit="s", label="Duration/Email", n_runs=n
        )
        _add_consistency_box(
            ax1,
            avg_tok_stats,
            unit="tokens",
            label="Tokens/Email",
            n_runs=n,
            y_pos=0.78,
        )
        fig.tight_layout(rect=[0, 0.06, 1, 1])
        _add_subtitle(
            fig,
            "Per-email granularity of LLM cost variance — range shows min to max across runs",
        )
        paths.append(_save_chart(fig, output_dir, "05c_per_email_trend"))

    # 5d: TTFT trend — model load/prefill latency consistency
    ttft_vals = [r.get("avg_time_to_first_token_ms", 0) / 1_000 for r in runs]
    if any(v > 0 for v in ttft_vals):
        ttft_stats = _compute_stats([float(v) for v in ttft_vals])
        fig, ax = plt_mod.subplots(figsize=(8, 4))
        ax.plot(
            x,
            ttft_vals,
            marker="D",
            linestyle="-",
            linewidth=2,
            color="#E53E3E",
            label="Avg TTFT (s)",
        )
        ax.axhline(
            ttft_stats["mean"], color="#E53E3E", linestyle="--", alpha=0.4, linewidth=1
        )
        for i, v in enumerate(ttft_vals):
            ax.annotate(
                f"{v:.2f}",
                (x[i], v),
                textcoords="offset points",
                xytext=(0, 10),
                ha="center",
                fontsize=8,
            )
        ax.set_xlabel("Run iteration")
        ax.set_ylabel("Avg TTFT (seconds)")
        ax.set_title("TTFT Consistency Across Runs", fontweight="bold", fontsize=12)
        ax.set_xticks(x)
        ax.grid(True, linestyle="--", alpha=0.3)
        _add_consistency_box(ax, ttft_stats, unit="s", label="TTFT Variance", n_runs=n)
        fig.tight_layout(rect=[0, 0.06, 1, 1])
        _add_subtitle(
            fig,
            "Model load + prefill latency — high variance indicates cold-start instability",
        )
        paths.append(_save_chart(fig, output_dir, "05d_ttft_trend"))

    # 5e: TPS trend — throughput consistency
    tps_vals = [r.get("avg_tokens_per_second", 0) for r in runs]
    if any(v > 0 for v in tps_vals):
        tps_stats = _compute_stats([float(v) for v in tps_vals])
        fig, ax = plt_mod.subplots(figsize=(8, 4))
        ax.plot(
            x,
            tps_vals,
            marker="^",
            linestyle="-",
            linewidth=2,
            color="#38A169",
            label="Avg TPS (tokens/s)",
        )
        ax.axhline(
            tps_stats["mean"], color="#38A169", linestyle="--", alpha=0.4, linewidth=1
        )
        for i, v in enumerate(tps_vals):
            ax.annotate(
                f"{v:.1f}",
                (x[i], v),
                textcoords="offset points",
                xytext=(0, 10),
                ha="center",
                fontsize=8,
            )
        ax.set_xlabel("Run iteration")
        ax.set_ylabel("Avg Tokens Per Second")
        ax.set_title(
            "Throughput Consistency Across Runs", fontweight="bold", fontsize=12
        )
        ax.set_xticks(x)
        ax.grid(True, linestyle="--", alpha=0.3)
        _add_consistency_box(
            ax, tps_stats, unit="tok/s", label="TPS Variance", n_runs=n
        )
        fig.tight_layout(rect=[0, 0.06, 1, 1])
        _add_subtitle(
            fig, "Inference throughput — lower variance = predictable throughput"
        )
        paths.append(_save_chart(fig, output_dir, "05e_tps_trend"))

    return paths


# ---------------------------------------------------------------------------
# Chart 6: Interactive Turn Breakdown (Comparison — Grouped Column)
# ---------------------------------------------------------------------------


def plot_interactive_turns(
    interactive: dict[str, Any], output_dir: Path
) -> Path | None:
    """Grouped column chart: per-turn tokens and duration."""
    plt_mod = _require_matplotlib()
    turns = interactive.get("turns", [])
    if not turns:
        return None

    turn_labels = [f"T{i['turn_number']}" for i in turns]
    dur_vals = [t.get("duration_ms", 0) / 1000 for t in turns]
    tok_vals = [t.get("total_tokens", 0) for t in turns]
    reasoning_vals = [t.get("total_reasoning_tokens", 0) for t in turns]
    has_reasoning = any(v > 0 for v in reasoning_vals)

    fig, ax1 = plt_mod.subplots(figsize=(8, 4))
    x = list(range(len(turns)))

    if has_reasoning:
        width = 0.25
        bars1 = ax1.bar(
            [i - width for i in x],
            dur_vals,
            width,
            label="Duration (s)",
            color=COLORS["duration"],
            alpha=0.85,
        )
        ax1.bar(
            [i for i in x],
            reasoning_vals,
            width,
            label="Reasoning tokens",
            color=COLORS["reasoning"],
            alpha=0.85,
        )
        ax2 = ax1.twinx()
        ax2.bar(
            [i + width for i in x],
            tok_vals,
            width,
            label="Total tokens",
            color=COLORS["tokens"],
            alpha=0.85,
        )
        ax2.set_ylabel("Tokens", color=COLORS["tokens"])
        ax2.tick_params(axis="y", labelcolor=COLORS["tokens"])
    else:
        width = 0.35
        bars1 = ax1.bar(
            [i - width / 2 for i in x],
            dur_vals,
            width,
            label="Duration (s)",
            color=COLORS["duration"],
            alpha=0.85,
        )
        ax2 = ax1.twinx()
        ax2.bar(
            [i + width / 2 for i in x],
            tok_vals,
            width,
            label="Tokens",
            color=COLORS["tokens"],
            alpha=0.85,
        )
        ax2.set_ylabel("Tokens", color=COLORS["tokens"])
        ax2.tick_params(axis="y", labelcolor=COLORS["tokens"])

    ax1.set_ylabel("Duration (seconds)", color=COLORS["duration"])
    ax1.tick_params(axis="y", labelcolor=COLORS["duration"])

    ax1.set_xticks(x)
    ax1.set_xticklabels(turn_labels)
    ax1.set_title(
        "Interactive Session — Per-Turn Breakdown", fontweight="bold", fontsize=12
    )

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
    ax1.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "06_interactive_turns")


# ---------------------------------------------------------------------------
# Chart 7: Interactive Token Heatmap (Relationship — Heatmap)
# ---------------------------------------------------------------------------


def plot_interactive_heatmap(
    interactive: dict[str, Any], output_dir: Path
) -> Path | None:
    """Heatmap: Turn x Step matrix of token consumption."""
    plt_mod = _require_matplotlib()
    turns = interactive.get("turns", [])
    if not turns:
        return None

    # Build matrix: turns x steps of total_tokens
    max_steps = max(len(t.get("step_results", [])) for t in turns)
    if max_steps == 0:
        return None

    matrix = []
    for t in turns:
        row = [s.get("total_tokens", 0) for s in t.get("step_results", [])]
        while len(row) < max_steps:
            row.append(0)
        matrix.append(row)

    fig, ax = plt_mod.subplots(
        figsize=(max(6, max_steps * 2), max(3, len(turns) * 1.2))
    )
    im = ax.imshow(matrix, aspect="auto", cmap="YlOrRd")

    ax.set_xticks(range(max_steps))
    ax.set_xticklabels([f"S{i + 1}" for i in range(max_steps)])
    ax.set_yticks(range(len(turns)))
    ax.set_yticklabels([f"T{i['turn_number']}" for i in turns])
    ax.set_xlabel("Step")
    ax.set_ylabel("Turn")
    ax.set_title(
        "Token Consumption Heatmap (Turn x Step)", fontweight="bold", fontsize=12
    )

    # Add value labels
    for i in range(len(turns)):
        for j in range(max_steps):
            val = matrix[i][j]
            if val > 0:
                ax.text(
                    j,
                    i,
                    f"{val:,}",
                    ha="center",
                    va="center",
                    fontsize=8,
                    fontweight="bold",
                    color=(
                        "white"
                        if val > max(v for row in matrix for v in row) * 0.6
                        else "black"
                    ),
                )

    fig.colorbar(im, ax=ax, label="Total tokens")
    fig.tight_layout()
    return _save_chart(fig, output_dir, "07_interactive_heatmap")


# ---------------------------------------------------------------------------
# Chart 8: Category Stability (Composition — Stacked Bar)
# ---------------------------------------------------------------------------


def plot_category_stability(
    runs: list[dict[str, Any]], output_dir: Path
) -> Path | None:
    """Stacked bar chart showing category composition per run.

    Heuristic category assignment is deterministic — bars should be identical
    across runs. This contrasts with LLM-based modes where classification
    can vary due to temperature-based sampling.
    """
    plt_mod = _require_matplotlib()
    if len(runs) < 2:
        return None

    all_cats = set()
    for r in runs:
        all_cats.update(r.get("category_counts", {}).keys())
    if not all_cats:
        return None

    cats = sorted(all_cats)
    x = list(range(1, len(runs) + 1))
    bottom = [0] * len(runs)
    cat_colors = [COLORS.get(c.lower(), "#4c78a8") for c in cats]

    fig, ax = plt_mod.subplots(figsize=(max(6, len(runs) * 1.5), 4))
    for i, cat in enumerate(cats):
        vals = [r.get("category_counts", {}).get(cat, 0) for r in runs]
        ax.bar(
            x, vals, bottom=bottom, label=cat, color=cat_colors[i], edgecolor="white"
        )
        bottom = [b + v for b, v in zip(bottom, vals)]

    ax.set_xlabel("Run iteration")
    ax.set_ylabel("Email count")
    ax.set_title("Category Stability Across Runs", fontweight="bold", fontsize=12)
    ax.set_xticks(x)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    # Annotation: heuristic categories are deterministic
    props = dict(
        boxstyle="round,pad=0.4", facecolor="#F0FFF4", edgecolor="#9AE6B4", alpha=0.9
    )
    ax.text(
        0.02,
        0.97,
        "Heuristic categories are deterministic\n"
        "— bars should be identical across runs —",
        transform=ax.transAxes,
        fontsize=7,
        verticalalignment="top",
        fontfamily="monospace",
        bbox=props,
    )
    fig.tight_layout()
    return _save_chart(fig, output_dir, "08_category_stability")


# ---------------------------------------------------------------------------
# Chart 9: Token vs Duration Scatter (Relationship — Scatter)
# ---------------------------------------------------------------------------


def plot_token_duration_scatter(run: dict[str, Any], output_dir: Path) -> Path | None:
    """Scatter plot: per-email tokens vs duration with size=email_id hash."""
    plt_mod = _require_matplotlib()
    points = []
    for batch in run.get("batch_results", []):
        for email in batch.get("email_results", []):
            d = email.get("duration_ms", 0) / 1_000  # ms → seconds
            t = email.get("total_tokens", 0)
            if d > 0 or t > 0:
                points.append((d, t))

    if len(points) < 2:
        return None

    durations, tokens = zip(*points)
    fig, ax = plt_mod.subplots(figsize=(8, 4))
    ax.scatter(
        durations, tokens, c=COLORS["tokens"], alpha=0.7, s=60, edgecolors="white"
    )

    # Add trend line if numpy is available.
    if np is not None:
        z = np.polyfit(durations, tokens, 1)
        p = np.poly1d(z)
        xs = np.linspace(min(durations), max(durations), 50)
        ax.plot(
            xs,
            p(xs),
            "--",
            color=COLORS["duration"],
            alpha=0.6,
            label=f"Trend (slope={z[0]:.2f})",
        )
        ax.legend(fontsize=9)

    ax.set_xlabel("Duration per email (seconds)")
    ax.set_ylabel("Tokens per email")
    ax.set_title("Token vs Duration Relationship", fontweight="bold", fontsize=12)
    ax.grid(True, linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "09_token_duration_scatter")


# ---------------------------------------------------------------------------
# Chart 10: Per-Step TTFT & TPS (Comparison — Dual-Axis Line)
# ---------------------------------------------------------------------------


def plot_step_performance(run: dict[str, Any], output_dir: Path) -> Path | None:
    """Dual-axis line chart: per-step TTFT and TPS."""
    plt_mod = _require_matplotlib()
    steps = run.get("step_results", [])
    if not steps:
        return None

    ttft_vals = [s.get("time_to_first_token_ms", 0) / 1_000 for s in steps]
    tps_vals = [s.get("tokens_per_second", 0) for s in steps]
    if not any(v > 0 for v in ttft_vals) and not any(v > 0 for v in tps_vals):
        return None

    fig, ax1 = plt_mod.subplots(figsize=(8, 4))
    x = list(range(1, len(steps) + 1))

    ax1.plot(
        x,
        ttft_vals,
        marker="o",
        linestyle="-",
        linewidth=2,
        color="#E53E3E",
        label="TTFT (s)",
    )
    ax1.set_ylabel("Time to First Token (seconds)", color="#E53E3E")
    ax1.tick_params(axis="y", labelcolor="#E53E3E")

    ax2 = ax1.twinx()
    ax2.plot(
        x,
        tps_vals,
        marker="s",
        linestyle="-",
        linewidth=2,
        color="#38A169",
        label="TPS (tokens/s)",
    )
    ax2.set_ylabel("Tokens Per Second", color="#38A169")
    ax2.tick_params(axis="y", labelcolor="#38A169")

    ax1.set_xlabel("Step")
    ax1.set_xticks(x)
    ax1.set_title("Per-Step TTFT & Throughput", fontweight="bold", fontsize=12)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="best")
    ax1.grid(True, linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "10_step_ttft_tps")


# ---------------------------------------------------------------------------
# Chart 11: Model Duration Comparison (Grouped Column)
# ---------------------------------------------------------------------------


def plot_model_duration_comparison(
    runs: list[dict[str, Any]], output_dir: Path
) -> Path | None:
    """Grouped column chart: total duration per model."""
    plt_mod = _require_matplotlib()
    if not runs:
        return None

    # Group by model.
    model_durations: dict[str, list[float]] = {}
    for r in runs:
        model = r.get("model", "unknown")
        dur = r.get("total_duration_ms", 0) / 1_000  # ms → seconds
        model_durations.setdefault(model, []).append(dur)

    if len(model_durations) < 2:
        return None

    models = sorted(model_durations.keys())
    x = list(range(len(models)))
    width = 0.35

    fig, ax = plt_mod.subplots(figsize=(max(6, len(models) * 1.5), 4))
    means = [sum(v) / len(v) for v in model_durations.values()]
    mins = [min(v) for v in model_durations.values()]
    bars = ax.bar(
        [i - width / 2 for i in x],
        means,
        width,
        label="Mean duration",
        color=COLORS["duration"],
        alpha=0.85,
    )
    ax.bar(
        [i + width / 2 for i in x],
        mins,
        width,
        label="Min duration",
        color=COLORS["heuristic"],
        alpha=0.85,
    )

    ax.set_xticks(x)
    ax.set_xticklabels([m[:20] for m in models], rotation=30, ha="right")
    ax.set_ylabel("Duration (seconds)")
    ax.set_title("Model Duration Comparison", fontweight="bold", fontsize=12)
    ax.legend(fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "11_model_duration_comparison")


# ---------------------------------------------------------------------------
# Chart 12: Model Token Cost (Stacked Column)
# ---------------------------------------------------------------------------


def plot_model_token_cost(runs: list[dict[str, Any]], output_dir: Path) -> Path | None:
    """Stacked column chart: input / output token cost per model."""
    plt_mod = _require_matplotlib()
    if not runs:
        return None

    model_tokens: dict[str, dict[str, float]] = {}
    for r in runs:
        model = r.get("model", "unknown")
        if model not in model_tokens:
            model_tokens[model] = {"input": 0, "output": 0, "reasoning": 0, "n": 0}
        model_tokens[model]["input"] += r.get("total_input_tokens", 0)
        model_tokens[model]["output"] += r.get("total_output_tokens", 0)
        model_tokens[model]["reasoning"] += r.get("total_reasoning_tokens", 0)
        model_tokens[model]["n"] += 1

    # Average per run.
    models = sorted(model_tokens.keys())
    x = list(range(len(models)))
    in_avg = [model_tokens[m]["input"] / model_tokens[m]["n"] for m in models]
    out_avg = [model_tokens[m]["output"] / model_tokens[m]["n"] for m in models]
    reason_avg = [model_tokens[m]["reasoning"] / model_tokens[m]["n"] for m in models]

    if all(v == 0 for v in in_avg):
        return None

    fig, ax = plt_mod.subplots(figsize=(max(6, len(models) * 1.5), 4))
    ax.bar(x, in_avg, label="Input tokens", color=COLORS["input"])
    ax.bar(x, out_avg, bottom=in_avg, label="Output tokens", color=COLORS["output"])
    if any(v > 0 for v in reason_avg):
        inout = [i + o for i, o in zip(in_avg, out_avg)]
        ax.bar(
            x,
            reason_avg,
            bottom=inout,
            label="Reasoning tokens",
            color=COLORS["reasoning"],
        )

    ax.set_xticks(x)
    ax.set_xticklabels([m[:20] for m in models], rotation=30, ha="right")
    ax.set_ylabel("Avg tokens per run")
    ax.set_title("Model Token Cost", fontweight="bold", fontsize=12)
    ax.legend(fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "12_model_token_cost")


# ---------------------------------------------------------------------------
# Chart 13: TTFT Comparison (Horizontal Bar)
# ---------------------------------------------------------------------------


def plot_ttft_comparison(runs: list[dict[str, Any]], output_dir: Path) -> Path | None:
    """Horizontal bar chart: avg TTFT per model."""
    plt_mod = _require_matplotlib()
    if not runs:
        return None

    model_ttft: dict[str, list[float]] = {}
    for r in runs:
        model = r.get("model", "unknown")
        ttft = r.get("avg_time_to_first_token_ms", 0) / 1_000  # ms → seconds
        if ttft > 0:
            model_ttft.setdefault(model, []).append(ttft)

    if not model_ttft:
        return None

    models = sorted(model_ttft.keys())
    means = [sum(v) / len(v) for v in model_ttft.values()]

    fig, ax = plt_mod.subplots(figsize=(8, max(3, len(models) * 0.7)))
    colors = [COLORS.get(m.lower().split("/")[0], "#4c78a8") for m in models]
    bars = ax.barh(models, means, color=colors, edgecolor="white", height=0.5)
    for bar, val in zip(bars, means):
        ax.text(
            bar.get_width() + 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"{val:.2f}s",
            va="center",
            fontsize=9,
        )
    ax.set_xlabel("Avg TTFT (seconds)")
    ax.set_title("TTFT Comparison Across Models", fontweight="bold", fontsize=12)
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "13_ttft_comparison")


# ---------------------------------------------------------------------------
# Chart 14: TPS Comparison (Horizontal Bar)
# ---------------------------------------------------------------------------


def plot_tps_comparison(runs: list[dict[str, Any]], output_dir: Path) -> Path | None:
    """Horizontal bar chart: avg TPS per model."""
    plt_mod = _require_matplotlib()
    if not runs:
        return None

    model_tps: dict[str, list[float]] = {}
    for r in runs:
        model = r.get("model", "unknown")
        tps = r.get("avg_tokens_per_second", 0)
        if tps > 0:
            model_tps.setdefault(model, []).append(tps)

    if not model_tps:
        return None

    models = sorted(model_tps.keys())
    means = [sum(v) / len(v) for v in model_tps.values()]

    fig, ax = plt_mod.subplots(figsize=(8, max(3, len(models) * 0.7)))
    colors = [COLORS.get(m.lower().split("/")[0], "#38A169") for m in models]
    bars = ax.barh(models, means, color=colors, edgecolor="white", height=0.5)
    for bar, val in zip(bars, means):
        ax.text(
            bar.get_width() + 0.5,
            bar.get_y() + bar.get_height() / 2,
            f"{val:.1f} t/s",
            va="center",
            fontsize=9,
        )
    ax.set_xlabel("Avg Tokens Per Second")
    ax.set_title("TPS Comparison Across Models", fontweight="bold", fontsize=12)
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "14_tps_comparison")


# ---------------------------------------------------------------------------
# Chart 15: Framework Category Comparison (Side-by-Side Stacked Bars)
# ---------------------------------------------------------------------------


def plot_framework_category_comparison(
    gaia_runs: list[dict[str, Any]],
    clawflow_runs: list[dict[str, Any]],
    output_dir: Path,
) -> Path | None:
    """Side-by-side stacked bars: GAIA vs ClawFlow category distribution."""
    plt_mod = _require_matplotlib()
    if not gaia_runs and not clawflow_runs:
        return None

    all_cats = set()
    for r in gaia_runs + clawflow_runs:
        all_cats.update(r.get("category_counts", {}).keys())
    if not all_cats:
        return None

    cats = sorted(all_cats)
    cat_colors = [COLORS.get(c.lower(), "#4c78a8") for c in cats]

    def _avg_counts(runs):
        if not runs:
            return {c: 0 for c in cats}
        totals = {c: 0 for c in cats}
        for r in runs:
            for c in cats:
                totals[c] += r.get("category_counts", {}).get(c, 0)
        return {c: totals[c] / len(runs) for c in cats}

    gaia_avgs = _avg_counts(gaia_runs)
    cf_avgs = _avg_counts(clawflow_runs)

    fig, ax = plt_mod.subplots(figsize=(7, 4))
    x = [0, 1]
    width = 0.35
    bottom_g = [0, 0]
    bottom_cf = [0, 0]

    for i, cat in enumerate(cats):
        vals_g = [gaia_avgs[cat], 0] if gaia_runs else [0, 0]
        vals_cf = [0, cf_avgs[cat]] if clawflow_runs else [0, 0]
        if gaia_runs:
            ax.bar(
                [x[0]],
                vals_g,
                bottom=bottom_g[0:1],
                label=cat if i == 0 else "",
                color=cat_colors[i],
                alpha=0.85,
            )
            bottom_g = [b + v for b, v in zip(bottom_g, vals_g)]
        if clawflow_runs:
            ax.bar(
                [x[1]],
                vals_cf,
                bottom=bottom_cf[1:2],
                label=cat if i == 0 else "",
                color=cat_colors[i],
                alpha=0.65,
            )
            bottom_cf = [b + v for b, v in zip(bottom_cf, vals_cf)]

    ax.set_xticks(x)
    ax.set_xticklabels(["GAIA", "ClawFlow"])
    ax.set_ylabel("Avg emails per category")
    ax.set_title("Framework Category Comparison", fontweight="bold", fontsize=12)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "15_framework_category_comparison")


# ---------------------------------------------------------------------------
# Chart 16: Architecture Radar (Radar/Spider Chart)
# ---------------------------------------------------------------------------


def plot_architecture_radar(
    gaia_result: dict[str, Any],
    clawflow_result: dict[str, Any],
    output_dir: Path,
) -> Path | None:
    """Radar/spider chart comparing GAIA vs ClawFlow on multiple dimensions."""
    plt_mod = _require_matplotlib()
    if not gaia_result or not clawflow_result:
        return None

    # Normalized dimensions (0-1 scale).
    def _normalize(val, max_val):
        return min(val / max(max_val, 1), 1.0)

    g_dur = gaia_result.get("total_duration_ms", 0)
    c_dur = clawflow_result.get("total_duration_ms", 0)
    max_dur = max(g_dur, c_dur, 1)

    g_tok = gaia_result.get("total_tokens", 0)
    c_tok = clawflow_result.get("total_tokens", 0)
    max_tok = max(g_tok, c_tok, 1)

    g_ttft = gaia_result.get("avg_time_to_first_token_ms", 0)
    c_ttft = clawflow_result.get("avg_time_to_first_token_ms", 0)
    max_ttft = max(g_ttft, c_ttft, 1)

    g_emails = gaia_result.get("total_emails", 0)
    c_emails = clawflow_result.get("total_emails", 0)
    max_emails = max(g_emails, c_emails, 1)

    categories = ["Duration", "Tokens", "TTFT", "Emails Processed"]
    gaia_vals = [
        1.0 - _normalize(g_dur, max_dur),  # Lower is better (invert)
        1.0 - _normalize(g_tok, max_tok),
        1.0 - _normalize(g_ttft, max_ttft),
        _normalize(g_emails, max_emails),  # Higher is better
    ]
    cf_vals = [
        1.0 - _normalize(c_dur, max_dur),
        1.0 - _normalize(c_tok, max_tok),
        1.0 - _normalize(c_ttft, max_ttft),
        _normalize(c_emails, max_emails),
    ]

    N = len(categories)
    angles = [n / N * 2 * math.pi for n in range(N)]
    angles += angles[:1]  # Close the radar.

    fig, ax = plt_mod.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))
    gaia_vals += gaia_vals[:1]
    cf_vals += cf_vals[:1]

    ax.plot(angles, gaia_vals, "o-", linewidth=2, label="GAIA", color=COLORS["gaia"])
    ax.fill(angles, gaia_vals, alpha=0.15, color=COLORS["gaia"])
    ax.plot(
        angles, cf_vals, "s-", linewidth=2, label="ClawFlow", color=COLORS["clawflow"]
    )
    ax.fill(angles, cf_vals, alpha=0.15, color=COLORS["clawflow"])

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontsize=9)
    ax.set_ylim(0, 1)
    ax.set_title(
        "Architecture Comparison Radar\n(higher = better)",
        fontweight="bold",
        fontsize=12,
        pad=20,
    )
    ax.legend(loc="upper right", fontsize=10)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "16_architecture_radar")


# ---------------------------------------------------------------------------
# Chart 17: Per-Model Variance Trend (Multi-Line)
# ---------------------------------------------------------------------------


def plot_per_model_variance_trend(
    runs: list[dict[str, Any]], output_dir: Path
) -> Path | None:
    """Multi-line chart showing token variance per model across iterations."""
    plt_mod = _require_matplotlib()
    if not runs:
        return None

    # Group by model, preserve iteration order.
    model_tokens: dict[str, list[int]] = {}
    for r in runs:
        model = r.get("model", "unknown")
        model_tokens.setdefault(model, []).append(r.get("total_tokens", 0))

    # Only show models with >= 2 runs.
    models_with_runs = {m: v for m, v in model_tokens.items() if len(v) >= 2}
    if not models_with_runs:
        return None

    max_iters = max(len(v) for v in models_with_runs.values())
    fig, ax = plt_mod.subplots(figsize=(max(6, max_iters * 1.5), 4))

    model_colors = [
        COLORS.get(m.lower().split("/")[0], f"C{i}")
        for i, m in enumerate(models_with_runs)
    ]
    for i, (model, vals) in enumerate(models_with_runs.items()):
        x = list(range(1, len(vals) + 1))
        ax.plot(
            x,
            vals,
            marker="o",
            linestyle="-",
            linewidth=2,
            color=model_colors[i],
            label=model[:25],
        )

    ax.set_xlabel("Run iteration")
    ax.set_ylabel("Total tokens")
    ax.set_title(
        "Per-Model Token Variance Across Iterations", fontweight="bold", fontsize=12
    )
    ax.legend(fontsize=8)
    ax.grid(True, linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "17_per_model_variance_trend")


# ---------------------------------------------------------------------------
# Chart 18: Cold-Start Impact (Scatter with Annotation)
# ---------------------------------------------------------------------------


def plot_cold_start_impact(runs: list[dict[str, Any]], output_dir: Path) -> Path | None:
    """Scatter plot: duration vs tokens, annotated with cold-start markers."""
    plt_mod = _require_matplotlib()
    if not runs:
        return None

    cold_points = []
    warm_points = []
    for r in runs:
        dur = r.get("total_duration_ms", 0) / 1000
        tok = r.get("total_tokens", 0)
        is_cold = r.get("is_cold_start", False)
        if is_cold:
            cold_points.append((dur, tok, r.get("model", "unknown")))
        else:
            warm_points.append((dur, tok, r.get("model", "unknown")))

    if not cold_points:
        return None

    fig, ax = plt_mod.subplots(figsize=(8, 4))

    if warm_points:
        wx, wy = zip(*[(p[0], p[1]) for p in warm_points])
        ax.scatter(
            wx,
            wy,
            c=COLORS["clawflow"],
            alpha=0.7,
            s=80,
            edgecolors="white",
            label="Warm start",
        )

    if cold_points:
        cx, cy = zip(*[(p[0], p[1]) for p in cold_points])
        ax.scatter(
            cx,
            cy,
            c=COLORS["urgent"],
            alpha=0.9,
            s=120,
            edgecolors="black",
            marker="D",
            label="Cold start",
        )
        # Annotate cold-start points.
        for dur, tok, model in cold_points:
            ax.annotate(
                model[:20],
                (dur, tok),
                textcoords="offset points",
                xytext=(8, 5),
                fontsize=7,
            )

    # Add cold-start impact annotation.
    if warm_points and cold_points:
        warm_avg_dur = sum(p[0] for p in warm_points) / len(warm_points)
        cold_avg_dur = sum(p[0] for p in cold_points) / len(cold_points)
        overhead_pct = (
            ((cold_avg_dur - warm_avg_dur) / warm_avg_dur * 100)
            if warm_avg_dur > 0
            else 0
        )
        props = dict(
            boxstyle="round,pad=0.4",
            facecolor="#FFF5F5",
            edgecolor="#E53E3E",
            alpha=0.9,
        )
        text = (
            f"Cold-start overhead: +{overhead_pct:.0f}%\n"
            f"Warm avg: {warm_avg_dur:.1f}s  |  Cold avg: {cold_avg_dur:.1f}s"
        )
        ax.text(
            0.02,
            0.95,
            text,
            transform=ax.transAxes,
            fontsize=8,
            verticalalignment="top",
            fontfamily="monospace",
            bbox=props,
        )

    ax.set_xlabel("Duration (seconds)")
    ax.set_ylabel("Total tokens")
    ax.set_title("Cold-Start Impact on Duration", fontweight="bold", fontsize=12)
    ax.legend(fontsize=9)
    ax.grid(True, linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "18_cold_start_impact")


# ---------------------------------------------------------------------------
# Chart 19: Model x Architecture Duration (Grouped Column)
# ---------------------------------------------------------------------------


def plot_model_architecture_duration(
    gaia_runs: list[dict[str, Any]],
    clawflow_runs: list[dict[str, Any]],
    output_dir: Path,
) -> Path | None:
    """Grouped column chart: duration per model, colored by architecture.

    For each model on the x-axis, shows two bars: GAIA (orange) and
    ClawFlow (blue). Duration is in seconds.
    """
    plt_mod = _require_matplotlib()
    if not gaia_runs and not clawflow_runs:
        return None

    # Aggregate per (model, framework).
    data: dict[str, dict[str, list[float]]] = {}
    for r in gaia_runs:
        model = r.get("model", "unknown")
        dur = r.get("total_duration_ms", 0) / 1_000
        data.setdefault(model, {}).setdefault("gaia", []).append(dur)
    for r in clawflow_runs:
        model = r.get("model", "unknown")
        dur = r.get("total_duration_ms", 0) / 1_000
        data.setdefault(model, {}).setdefault("clawflow", []).append(dur)

    if not data:
        return None

    models = sorted(data.keys())
    x = list(range(len(models)))
    width = 0.35

    gaia_means = []
    cf_means = []
    has_gaia = False
    has_cf = False
    for m in models:
        g = data[m].get("gaia", [])
        c = data[m].get("clawflow", [])
        gaia_means.append(sum(g) / len(g) if g else 0)
        cf_means.append(sum(c) / len(c) if c else 0)
        if g:
            has_gaia = True
        if c:
            has_cf = True

    fig, ax = plt_mod.subplots(figsize=(max(6, len(models) * 2), 4))

    bars_g = []
    bars_c = []
    if has_gaia:
        bars_g = ax.bar(
            [i - width / 2 for i in x],
            gaia_means,
            width,
            label="GAIA",
            color=COLORS["gaia"],
            alpha=0.85,
        )
    if has_cf:
        bars_c = ax.bar(
            [i + width / 2 for i in x],
            cf_means,
            width,
            label="ClawFlow",
            color=COLORS["clawflow"],
            alpha=0.85,
        )

    # Value labels on bars.
    for bars, vals in [(bars_g, gaia_means), (bars_c, cf_means)]:
        for bar, val in zip(bars, vals):
            if val > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.1,
                    f"{val:.1f}s",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                )

    ax.set_xticks(x)
    ax.set_xticklabels([m[:25] for m in models], rotation=30, ha="right")
    ax.set_ylabel("Duration (seconds)")
    ax.set_title(
        "Duration by Model & Architecture", fontweight="bold", fontsize=12
    )
    ax.legend(fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "19_model_architecture_duration")


# ---------------------------------------------------------------------------
# Chart 20: Model x Architecture Token Efficiency (Stacked Grouped Column)
# ---------------------------------------------------------------------------


def plot_model_architecture_tokens(
    gaia_runs: list[dict[str, Any]],
    clawflow_runs: list[dict[str, Any]],
    output_dir: Path,
) -> Path | None:
    """Grouped column chart: token cost per model, colored by architecture.

    Each column is stacked: Input tokens (solid) + Output tokens (lighter
    shade). Grouped by framework within each model.
    """
    plt_mod = _require_matplotlib()
    if not gaia_runs and not clawflow_runs:
        return None

    data: dict[str, dict[str, dict[str, list[float]]]] = {}
    for r in gaia_runs:
        model = r.get("model", "unknown")
        in_tok = r.get("total_input_tokens", 0)
        out_tok = r.get("total_output_tokens", 0)
        data.setdefault(model, {}).setdefault("gaia", {"in": [], "out": []})
        data[model]["gaia"]["in"].append(in_tok)
        data[model]["gaia"]["out"].append(out_tok)
    for r in clawflow_runs:
        model = r.get("model", "unknown")
        in_tok = r.get("total_input_tokens", 0)
        out_tok = r.get("total_output_tokens", 0)
        data.setdefault(model, {}).setdefault("clawflow", {"in": [], "out": []})
        data[model]["clawflow"]["in"].append(in_tok)
        data[model]["clawflow"]["out"].append(out_tok)

    if not data:
        return None

    models = sorted(data.keys())
    x = list(range(len(models)))
    width = 0.35

    gaia_in = []
    gaia_out = []
    cf_in = []
    cf_out = []
    has_gaia = False
    has_cf = False

    for m in models:
        g = data[m].get("gaia", {"in": [], "out": []})
        c = data[m].get("clawflow", {"in": [], "out": []})
        gi = sum(g["in"]) / len(g["in"]) if g["in"] else 0
        go = sum(g["out"]) / len(g["out"]) if g["out"] else 0
        ci = sum(c["in"]) / len(c["in"]) if c["in"] else 0
        co = sum(c["out"]) / len(c["out"]) if c["out"] else 0
        gaia_in.append(gi)
        gaia_out.append(go)
        cf_in.append(ci)
        cf_out.append(co)
        if g["in"] or g["out"]:
            has_gaia = True
        if c["in"] or c["out"]:
            has_cf = True

    fig, ax = plt_mod.subplots(figsize=(max(6, len(models) * 2), 4))

    if has_gaia:
        ax.bar(
            [i - width / 2 for i in x],
            gaia_in,
            width,
            label="GAIA Input",
            color=COLORS["gaia"],
            alpha=0.85,
        )
        ax.bar(
            [i - width / 2 for i in x],
            gaia_out,
            width,
            bottom=gaia_in,
            label="GAIA Output",
            color=COLORS["gaia"],
            alpha=0.45,
        )
    if has_cf:
        ax.bar(
            [i + width / 2 for i in x],
            cf_in,
            width,
            label="ClawFlow Input",
            color=COLORS["clawflow"],
            alpha=0.85,
        )
        ax.bar(
            [i + width / 2 for i in x],
            cf_out,
            width,
            bottom=cf_in,
            label="ClawFlow Output",
            color=COLORS["clawflow"],
            alpha=0.45,
        )

    ax.set_xticks(x)
    ax.set_xticklabels([m[:25] for m in models], rotation=30, ha="right")
    ax.set_ylabel("Avg tokens per run")
    ax.set_title(
        "Token Cost by Model & Architecture", fontweight="bold", fontsize=12
    )
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "20_model_architecture_tokens")


# ---------------------------------------------------------------------------
# Chart 21: Architecture Performance Dashboard (4-Panel Faceted)
# ---------------------------------------------------------------------------


def plot_architecture_dashboard(
    gaia_runs: list[dict[str, Any]],
    clawflow_runs: list[dict[str, Any]],
    output_dir: Path,
) -> Path | None:
    """4-panel dashboard: TTFT, TPS, Duration, and Tokens by model & architecture.

    Each panel is a grouped bar chart with consistent x-axis (models).
    Architecture colors: GAIA=#ED6C02 (AMD orange), ClawFlow=#3182CE (blue).
    """
    plt_mod = _require_matplotlib()
    if not gaia_runs and not clawflow_runs:
        return None

    # Collect all unique models.
    all_models = set()
    for r in gaia_runs + clawflow_runs:
        all_models.add(r.get("model", "unknown"))
    if len(all_models) < 1:
        return None

    models = sorted(all_models)
    n = len(models)

    # Build aggregated data per (model, framework).
    def _agg(runs, framework):
        result = {}
        for r in runs:
            m = r.get("model", "unknown")
            result.setdefault(m, {"dur": [], "ttft": [], "tps": [], "in": [], "out": []})
            result[m]["dur"].append(r.get("total_duration_ms", 0) / 1_000)
            result[m]["ttft"].append(r.get("avg_time_to_first_token_ms", 0) / 1_000)
            result[m]["tps"].append(r.get("avg_tokens_per_second", 0))
            result[m]["in"].append(r.get("total_input_tokens", 0))
            result[m]["out"].append(r.get("total_output_tokens", 0))
        return result

    gaia_data = _agg(gaia_runs, "gaia")
    cf_data = _agg(clawflow_runs, "clawflow")

    def _mean(d, m, key):
        vals = d.get(m, {}).get(key, [])
        return sum(vals) / len(vals) if vals else 0

    fig, axes = plt_mod.subplots(2, 2, figsize=(max(10, n * 3), 7))

    x = list(range(n))
    width = 0.35

    has_gaia = bool(gaia_runs)
    has_cf = bool(clawflow_runs)

    # Panel 1: TTFT (seconds)
    ax = axes[0, 0]
    if has_gaia:
        ax.bar(
            [i - width / 2 for i in x],
            [_mean(gaia_data, m, "ttft") for m in models],
            width,
            label="GAIA",
            color=COLORS["gaia"],
            alpha=0.85,
        )
    if has_cf:
        ax.bar(
            [i + width / 2 for i in x],
            [_mean(cf_data, m, "ttft") for m in models],
            width,
            label="ClawFlow",
            color=COLORS["clawflow"],
            alpha=0.85,
        )
    ax.set_xticks(x)
    ax.set_xticklabels([m[:20] for m in models], rotation=30, ha="right")
    ax.set_ylabel("Time to First Token (seconds)")
    ax.set_title("TTFT", fontweight="bold")
    ax.legend(fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3)

    # Panel 2: TPS (tokens/s)
    ax = axes[0, 1]
    if has_gaia:
        ax.bar(
            [i - width / 2 for i in x],
            [_mean(gaia_data, m, "tps") for m in models],
            width,
            label="GAIA",
            color=COLORS["gaia"],
            alpha=0.85,
        )
    if has_cf:
        ax.bar(
            [i + width / 2 for i in x],
            [_mean(cf_data, m, "tps") for m in models],
            width,
            label="ClawFlow",
            color=COLORS["clawflow"],
            alpha=0.85,
        )
    ax.set_xticks(x)
    ax.set_xticklabels([m[:20] for m in models], rotation=30, ha="right")
    ax.set_ylabel("Tokens Per Second")
    ax.set_title("Throughput", fontweight="bold")
    ax.legend(fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3)

    # Panel 3: Duration (seconds)
    ax = axes[1, 0]
    if has_gaia:
        ax.bar(
            [i - width / 2 for i in x],
            [_mean(gaia_data, m, "dur") for m in models],
            width,
            label="GAIA",
            color=COLORS["gaia"],
            alpha=0.85,
        )
    if has_cf:
        ax.bar(
            [i + width / 2 for i in x],
            [_mean(cf_data, m, "dur") for m in models],
            width,
            label="ClawFlow",
            color=COLORS["clawflow"],
            alpha=0.85,
        )
    ax.set_xticks(x)
    ax.set_xticklabels([m[:20] for m in models], rotation=30, ha="right")
    ax.set_ylabel("Duration (seconds)")
    ax.set_title("Total Duration", fontweight="bold")
    ax.legend(fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3)

    # Panel 4: Tokens (stacked: input + output)
    ax = axes[1, 1]
    if has_gaia:
        in_vals = [_mean(gaia_data, m, "in") for m in models]
        out_vals = [_mean(gaia_data, m, "out") for m in models]
        ax.bar(
            [i - width / 2 for i in x],
            in_vals,
            width,
            label="GAIA Input",
            color=COLORS["gaia"],
            alpha=0.85,
        )
        ax.bar(
            [i - width / 2 for i in x],
            out_vals,
            width,
            bottom=in_vals,
            label="GAIA Output",
            color=COLORS["gaia"],
            alpha=0.45,
        )
    if has_cf:
        in_vals = [_mean(cf_data, m, "in") for m in models]
        out_vals = [_mean(cf_data, m, "out") for m in models]
        ax.bar(
            [i + width / 2 for i in x],
            in_vals,
            width,
            label="CF Input",
            color=COLORS["clawflow"],
            alpha=0.85,
        )
        ax.bar(
            [i + width / 2 for i in x],
            out_vals,
            width,
            bottom=in_vals,
            label="CF Output",
            color=COLORS["clawflow"],
            alpha=0.45,
        )
    ax.set_xticks(x)
    ax.set_xticklabels([m[:20] for m in models], rotation=30, ha="right")
    ax.set_ylabel("Tokens")
    ax.set_title("Token Cost", fontweight="bold")
    ax.legend(fontsize=7, loc="upper right")
    ax.grid(axis="y", linestyle="--", alpha=0.3)

    fig.suptitle(
        "Architecture Performance Dashboard",
        fontweight="bold",
        fontsize=14,
        y=0.98,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    return _save_chart(fig, output_dir, "21_architecture_dashboard")


def generate_charts(
    json_path: Path | None = None,
    jsonl_path: Path | None = None,
    interactive_path: Path | None = None,
    output_dir: Path | None = None,
    *,
    multi_model_runs: list[dict[str, Any]] | None = None,
    clawflow_result: dict[str, Any] | None = None,
    gaia_result_for_comparison: dict[str, Any] | None = None,
) -> list[Path]:
    """Generate all applicable charts from benchmark output files.

    Auto-detects which charts are relevant based on available data and mode.
    Returns list of generated PNG paths.
    """
    plt_mod = _require_matplotlib()
    paths: list[Path] = []

    if output_dir is None:
        output_dir = Path("benchmark_charts")
    output_dir.mkdir(parents=True, exist_ok=True)

    charts_index = []

    # --- Single run charts ---
    if json_path and json_path.exists():
        run = _load_json(json_path)
        mode = _detect_mode(run)

        # Chart 1: Category distribution (always)
        p = plot_category_distribution(run, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "Category Distribution — Horizontal bar chart of email categories",
                )
            )

        # Chart 2: Token composition (full/interactive only)
        if mode in ("full", "interactive"):
            p = plot_token_composition(run, output_dir)
            if p:
                paths.append(p)
                charts_index.append(
                    (
                        p.name,
                        "Token Composition — Donut chart of input, reasoning, and output tokens",
                    )
                )

            # Chart 3: Duration vs tokens (full/interactive only)
            p = plot_duration_vs_tokens(run, output_dir)
            if p:
                paths.append(p)
                charts_index.append(
                    (
                        p.name,
                        "Duration vs Token Cost — Grouped column of total time and tokens",
                    )
                )

        # Chart 4: Per-email duration histogram (always)
        p = plot_email_duration_histogram(run, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "Per-Email Duration Distribution — Histogram of processing times",
                )
            )

        # Chart 9: Token vs duration scatter
        p = plot_token_duration_scatter(run, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "Token vs Duration Relationship — Scatter plot with trend line",
                )
            )

        # Chart 10: Per-step TTFT & TPS (full mode only)
        if mode in ("full", "interactive"):
            p = plot_step_performance(run, output_dir)
            if p:
                paths.append(p)
                charts_index.append(
                    (
                        p.name,
                        "Per-Step TTFT & TPS — Dual-axis line chart of latency and throughput per LLM call",
                    )
                )

    # --- Variance trend charts (multi-iteration) ---
    if jsonl_path and jsonl_path.exists():
        runs = load_jsonl(jsonl_path)
        if len(runs) >= 2:
            # Chart 5: Variance trend lines
            trend_paths = plot_variance_trend(runs, output_dir)
            paths.extend(trend_paths)
            for tp in trend_paths:
                charts_index.append(
                    (
                        tp.name,
                        "LLM Non-Determinism Trend — Line graph with μ, σ, CV% showing token/duration variance across identical runs",
                    )
                )

            # Chart 8: Category stability stacked bar
            p = plot_category_stability(runs, output_dir)
            if p:
                paths.append(p)
                charts_index.append(
                    (
                        p.name,
                        "Category Stability — Stacked bar; identical bars confirm deterministic heuristic classification",
                    )
                )

    # --- Interactive mode charts ---
    if interactive_path and interactive_path.exists():
        interactive = _load_json(interactive_path)

        # Chart 6: Interactive turn breakdown
        p = plot_interactive_turns(interactive, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (p.name, "Interactive Turn Breakdown — Per-turn duration and tokens")
            )

        # Chart 7: Interactive token heatmap
        p = plot_interactive_heatmap(interactive, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "Interactive Token Heatmap — Turn x Step matrix of token consumption",
                )
            )

    # --- Multi-model charts ---
    if multi_model_runs and len(multi_model_runs) >= 2:
        # Chart 11: Model duration comparison
        p = plot_model_duration_comparison(multi_model_runs, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "Model Duration Comparison — Grouped column of mean and min duration per model",
                )
            )

        # Chart 12: Model token cost
        p = plot_model_token_cost(multi_model_runs, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "Model Token Cost — Stacked column of input/output/reasoning tokens per model",
                )
            )

        # Chart 13: TTFT comparison
        p = plot_ttft_comparison(multi_model_runs, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "TTFT Comparison — Horizontal bar of avg time-to-first-token per model",
                )
            )

        # Chart 14: TPS comparison
        p = plot_tps_comparison(multi_model_runs, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "TPS Comparison — Horizontal bar of avg tokens-per-second per model",
                )
            )

        # Chart 17: Per-model variance trend
        p = plot_per_model_variance_trend(multi_model_runs, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "Per-Model Variance Trend — Multi-line chart of token variance across iterations",
                )
            )

        # Chart 18: Cold-start impact
        p = plot_cold_start_impact(multi_model_runs, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "Cold-Start Impact — Scatter plot with annotation showing cold vs warm start overhead",
                )
            )

    # --- Framework comparison charts ---
    if clawflow_result and gaia_result_for_comparison:
        gaia_list = [gaia_result_for_comparison]
        cf_list = [clawflow_result]

        # Chart 15: Framework category comparison
        p = plot_framework_category_comparison(gaia_list, cf_list, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "Framework Category Comparison — Side-by-side stacked bars of GAIA vs ClawFlow categories",
                )
            )

        # Chart 16: Architecture radar
        p = plot_architecture_radar(
            gaia_result_for_comparison, clawflow_result, output_dir
        )
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "Architecture Radar — Spider chart comparing GAIA vs ClawFlow on multiple normalized dimensions",
                )
            )

        # Build combined run lists: GAIA multi-model + ClawFlow single run.
        gaia_comp_runs = list(multi_model_runs) if multi_model_runs else []
        if not gaia_comp_runs and gaia_result_for_comparison:
            gaia_comp_runs = [gaia_result_for_comparison]

        # Chart 19: Model x Architecture Duration
        p = plot_model_architecture_duration(gaia_comp_runs, cf_list, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "Model x Architecture Duration — Grouped column: duration per model, GAIA (orange) vs ClawFlow (blue)",
                )
            )

        # Chart 20: Model x Architecture Token Cost
        p = plot_model_architecture_tokens(gaia_comp_runs, cf_list, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "Model x Architecture Token Cost — Grouped stacked column: input/output tokens per model by architecture",
                )
            )

        # Chart 21: Architecture Performance Dashboard (4-panel)
        p = plot_architecture_dashboard(gaia_comp_runs, cf_list, output_dir)
        if p:
            paths.append(p)
            charts_index.append(
                (
                    p.name,
                    "Architecture Performance Dashboard — 4-panel: TTFT, Throughput, Duration, Token Cost by model & architecture",
                )
            )

    # --- Write charts index ---
    if charts_index:
        index_path = output_dir / "CHARTS.md"
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# Benchmark Charts\n\n")
            f.write("Auto-generated charts from benchmark output.\n\n")
            for i, (fname, desc) in enumerate(charts_index, 1):
                f.write(f"## {i}. {desc}\n\n")
                f.write(f"![{desc}]({fname})\n\n")
        print(f"\nCharts index: {index_path}")

    if paths:
        print(f"Generated {len(paths)} chart(s) in {output_dir}/")
        for p in paths:
            print(f"  - {p.name}")

    return paths


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="gaia email bench --visualize",
        description="Generate charts from benchmark JSON/JSONL output.",
    )
    parser.add_argument("--json-path", type=str, help="Path to results.json")
    parser.add_argument("--jsonl-path", type=str, help="Path to results.jsonl")
    parser.add_argument("--interactive-path", type=str, help="Path to interactive.json")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="benchmark_charts",
        help="Directory to write chart PNGs",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not any([args.json_path, args.jsonl_path, args.interactive_path]):
        # Auto-detect: look in current directory and output_dir
        for candidate in [Path("results.json"), Path("benchmark_results/results.json")]:
            if candidate.exists():
                args.json_path = str(candidate)
                break
        for candidate in [
            Path("results.jsonl"),
            Path("benchmark_results/results.jsonl"),
        ]:
            if candidate.exists():
                args.jsonl_path = str(candidate)
                break
        for candidate in [
            Path("interactive.json"),
            Path("benchmark_results/interactive.json"),
        ]:
            if candidate.exists():
                args.interactive_path = str(candidate)
                break

        if not any([args.json_path, args.jsonl_path, args.interactive_path]):
            print(
                "Error: No benchmark output files found. "
                "Run a benchmark first or specify --json-path/--jsonl-path/--interactive-path"
            )
            return 1

    generate_charts(
        json_path=Path(args.json_path) if args.json_path else None,
        jsonl_path=Path(args.jsonl_path) if args.jsonl_path else None,
        interactive_path=Path(args.interactive_path) if args.interactive_path else None,
        output_dir=Path(args.output_dir),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
