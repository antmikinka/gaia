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
    "heuristic": "#718096",
    "full": "#3182CE",
    "duration": "#DD6B20",
    "tokens": "#3182CE",
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
        ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
                str(val), va="center", fontweight="bold", fontsize=10)
    ax.set_xlabel("Email count")
    ax.set_title("Category Distribution", fontweight="bold", fontsize=12)
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "01_category_distribution")


# ---------------------------------------------------------------------------
# Chart 2: Token Composition (Composition — Donut)
# ---------------------------------------------------------------------------

def plot_token_composition(run: dict[str, Any], output_dir: Path) -> Path | None:
    """Donut chart showing input vs output token split."""
    plt_mod = _require_matplotlib()
    in_tok = run.get("total_input_tokens", 0)
    out_tok = run.get("total_output_tokens", 0)
    if in_tok == 0 and out_tok == 0:
        return None

    fig, ax = plt_mod.subplots(figsize=(5, 5))
    sizes = [in_tok, out_tok]
    labels = [f"Input ({in_tok:,})", f"Output ({out_tok:,})"]
    colors = [COLORS["input"], COLORS["output"]]

    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=colors, autopct="%1.1f%%",
        startangle=90, wedgeprops={"width": 0.5, "edgecolor": "white"},
    )
    for t in autotexts:
        t.set_fontsize(10)
        t.set_fontweight("bold")
    total = in_tok + out_tok
    ax.text(0, 0, f"Total\n{total:,}", ha="center", va="center",
            fontsize=11, fontweight="bold")
    ax.set_title("Token Composition", fontweight="bold", fontsize=12)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "02_token_composition")


# ---------------------------------------------------------------------------
# Chart 3: Duration vs Tokens (Comparison — Grouped Column)
# ---------------------------------------------------------------------------

def plot_duration_vs_tokens(run: dict[str, Any], output_dir: Path) -> Path | None:
    """Side-by-side columns: total duration (mins) vs total tokens."""
    plt_mod = _require_matplotlib()
    dur = run.get("total_duration_ms", 0)
    tok = run.get("total_tokens", 0)
    if dur == 0 and tok == 0:
        return None

    dur_mins = dur / 60_000
    fig, ax1 = plt_mod.subplots(figsize=(6, 4))

    x = [0]
    width = 0.35
    bar1 = ax1.bar(x[0] - width / 2, dur_mins, width,
                   label=f"Duration: {dur_mins:.1f} min", color=COLORS["duration"])
    ax1.set_ylabel("Duration (minutes)", color=COLORS["duration"])
    ax1.tick_params(axis="y", labelcolor=COLORS["duration"])

    ax2 = ax1.twinx()
    bar2 = ax2.bar(x[0] + width / 2, tok, width,
                   label=f"Tokens: {tok:,}", color=COLORS["tokens"])
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
                durations.append(d)

    if not durations:
        return None

    fig, ax = plt_mod.subplots(figsize=(8, 4))
    ax.hist(durations, bins=min(15, len(durations)), color=COLORS["duration"],
            edgecolor="white", alpha=0.85)
    mean_dur = sum(durations) / len(durations)
    ax.axvline(mean_dur, color="black", linestyle="--", linewidth=1,
               label=f"Mean: {mean_dur:.0f}ms")
    ax.set_xlabel("Duration per email (ms)")
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
    """Line graphs showing duration and tokens across iterations."""
    plt_mod = _require_matplotlib()
    paths = []
    if len(runs) < 2:
        return paths

    n = len(runs)
    x = list(range(1, n + 1))

    # 5a: Duration trend (mins)
    dur_vals = [r.get("total_duration_ms", 0) / 60_000 for r in runs]
    fig, ax = plt_mod.subplots(figsize=(8, 4))
    ax.plot(x, dur_vals, marker="o", linestyle="-", linewidth=2,
            color=COLORS["duration"], label="Duration")
    for i, v in enumerate(dur_vals):
        ax.annotate(f"{v:.1f}", (x[i], v), textcoords="offset points",
                    xytext=(0, 10), ha="center", fontsize=8)
    ax.set_xlabel("Run iteration")
    ax.set_ylabel("Duration (minutes)")
    ax.set_title("Duration Trend Across Iterations", fontweight="bold", fontsize=12)
    ax.set_xticks(x)
    ax.grid(True, linestyle="--", alpha=0.3)
    fig.tight_layout()
    paths.append(_save_chart(fig, output_dir, "05a_duration_trend"))

    # 5b: Token trend
    tok_vals = [r.get("total_tokens", 0) for r in runs]
    if any(v > 0 for v in tok_vals):
        fig, ax = plt_mod.subplots(figsize=(8, 4))
        ax.plot(x, tok_vals, marker="s", linestyle="-", linewidth=2,
                color=COLORS["tokens"], label="Total tokens")
        for i, v in enumerate(tok_vals):
            ax.annotate(f"{v:,}", (x[i], v), textcoords="offset points",
                        xytext=(0, 10), ha="center", fontsize=8)
        ax.set_xlabel("Run iteration")
        ax.set_ylabel("Total tokens")
        ax.set_title("Token Consumption Trend Across Iterations", fontweight="bold", fontsize=12)
        ax.set_xticks(x)
        ax.grid(True, linestyle="--", alpha=0.3)
        fig.tight_layout()
        paths.append(_save_chart(fig, output_dir, "05b_token_trend"))

    # 5c: Per-email averages trend
    avg_dur = [r.get("avg_duration_per_email_ms", 0) for r in runs]
    avg_tok = [r.get("avg_total_tokens_per_email", 0) for r in runs]
    if any(v > 0 for v in avg_tok) or any(v > 0 for v in avg_dur):
        fig, ax1 = plt_mod.subplots(figsize=(8, 4))
        ax1.plot(x, avg_dur, marker="o", linestyle="-", linewidth=2,
                 color=COLORS["duration"], label="Avg duration/email (ms)")
        ax1.set_xlabel("Run iteration")
        ax1.set_ylabel("Avg duration/email (ms)", color=COLORS["duration"])
        ax1.tick_params(axis="y", labelcolor=COLORS["duration"])

        ax2 = ax1.twinx()
        ax2.plot(x, avg_tok, marker="s", linestyle="-", linewidth=2,
                 color=COLORS["tokens"], label="Avg tokens/email")
        ax2.set_ylabel("Avg tokens/email", color=COLORS["tokens"])
        ax2.tick_params(axis="y", labelcolor=COLORS["tokens"])

        ax1.set_title("Per-Email Averages Trend", fontweight="bold", fontsize=12)
        ax1.set_xticks(x)
        ax1.grid(True, linestyle="--", alpha=0.3)
        fig.tight_layout()
        paths.append(_save_chart(fig, output_dir, "05c_per_email_trend"))

    return paths


# ---------------------------------------------------------------------------
# Chart 6: Interactive Turn Breakdown (Comparison — Grouped Column)
# ---------------------------------------------------------------------------

def plot_interactive_turns(interactive: dict[str, Any], output_dir: Path) -> Path | None:
    """Grouped column chart: per-turn tokens and duration."""
    plt_mod = _require_matplotlib()
    turns = interactive.get("turns", [])
    if not turns:
        return None

    turn_labels = [f"T{i['turn_number']}" for i in turns]
    dur_vals = [t.get("duration_ms", 0) / 1000 for t in turns]
    tok_vals = [t.get("total_tokens", 0) for t in turns]

    fig, ax1 = plt_mod.subplots(figsize=(8, 4))
    x = list(range(len(turns)))
    width = 0.35

    bars1 = ax1.bar([i - width / 2 for i in x], dur_vals, width,
                    label="Duration (s)", color=COLORS["duration"], alpha=0.85)
    ax1.set_ylabel("Duration (seconds)", color=COLORS["duration"])
    ax1.tick_params(axis="y", labelcolor=COLORS["duration"])

    ax2 = ax1.twinx()
    bars2 = ax2.bar([i + width / 2 for i in x], tok_vals, width,
                    label="Tokens", color=COLORS["tokens"], alpha=0.85)
    ax2.set_ylabel("Tokens", color=COLORS["tokens"])
    ax2.tick_params(axis="y", labelcolor=COLORS["tokens"])

    ax1.set_xticks(x)
    ax1.set_xticklabels(turn_labels)
    ax1.set_title("Interactive Session — Per-Turn Breakdown", fontweight="bold", fontsize=12)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
    ax1.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "06_interactive_turns")


# ---------------------------------------------------------------------------
# Chart 7: Interactive Token Heatmap (Relationship — Heatmap)
# ---------------------------------------------------------------------------

def plot_interactive_heatmap(interactive: dict[str, Any], output_dir: Path) -> Path | None:
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

    fig, ax = plt_mod.subplots(figsize=(max(6, max_steps * 2), max(3, len(turns) * 1.2)))
    im = ax.imshow(matrix, aspect="auto", cmap="YlOrRd")

    ax.set_xticks(range(max_steps))
    ax.set_xticklabels([f"S{i + 1}" for i in range(max_steps)])
    ax.set_yticks(range(len(turns)))
    ax.set_yticklabels([f"T{i['turn_number']}" for i in turns])
    ax.set_xlabel("Step")
    ax.set_ylabel("Turn")
    ax.set_title("Token Consumption Heatmap (Turn x Step)", fontweight="bold", fontsize=12)

    # Add value labels
    for i in range(len(turns)):
        for j in range(max_steps):
            val = matrix[i][j]
            if val > 0:
                ax.text(j, i, f"{val:,}", ha="center", va="center",
                        fontsize=8, fontweight="bold",
                        color="white" if val > max(v for row in matrix for v in row) * 0.6 else "black")

    fig.colorbar(im, ax=ax, label="Total tokens")
    fig.tight_layout()
    return _save_chart(fig, output_dir, "07_interactive_heatmap")


# ---------------------------------------------------------------------------
# Chart 8: Category Stability (Composition — Stacked Bar)
# ---------------------------------------------------------------------------

def plot_category_stability(runs: list[dict[str, Any]], output_dir: Path) -> Path | None:
    """Stacked bar chart showing category composition per run."""
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
    colors = [COLORS.get(c.lower(), "#4c78a8") for c in cats]

    fig, ax = plt_mod.subplots(figsize=(max(6, len(runs) * 1.5), 4))
    for i, cat in enumerate(cats):
        vals = [r.get("category_counts", {}).get(cat, 0) for r in runs]
        ax.bar(x, vals, bottom=bottom, label=cat, color=colors[i], edgecolor="white")
        bottom = [b + v for b, v in zip(bottom, vals)]

    ax.set_xlabel("Run iteration")
    ax.set_ylabel("Email count")
    ax.set_title("Category Stability Across Runs", fontweight="bold", fontsize=12)
    ax.set_xticks(x)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
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
            d = email.get("duration_ms", 0)
            t = email.get("total_tokens", 0)
            if d > 0 or t > 0:
                points.append((d, t))

    if len(points) < 2:
        return None

    durations, tokens = zip(*points)
    fig, ax = plt_mod.subplots(figsize=(8, 4))
    ax.scatter(durations, tokens, c=COLORS["tokens"], alpha=0.7, s=60, edgecolors="white")

    # Add trend line if numpy is available.
    if np is not None:
        z = np.polyfit(durations, tokens, 1)
        p = np.poly1d(z)
        xs = np.linspace(min(durations), max(durations), 50)
        ax.plot(xs, p(xs), "--", color=COLORS["duration"], alpha=0.6,
                label=f"Trend (slope={z[0]:.2f})")
        ax.legend(fontsize=9)

    ax.set_xlabel("Duration per email (ms)")
    ax.set_ylabel("Tokens per email")
    ax.set_title("Token vs Duration Relationship", fontweight="bold", fontsize=12)
    ax.grid(True, linestyle="--", alpha=0.3)
    fig.tight_layout()
    return _save_chart(fig, output_dir, "09_token_duration_scatter")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_charts(
    json_path: Path | None = None,
    jsonl_path: Path | None = None,
    interactive_path: Path | None = None,
    output_dir: Path | None = None,
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
            charts_index.append((p.name, "Category Distribution — Horizontal bar chart of email categories"))

        # Chart 2: Token composition (full/interactive only)
        if mode in ("full", "interactive"):
            p = plot_token_composition(run, output_dir)
            if p:
                paths.append(p)
                charts_index.append((p.name, "Token Composition — Donut chart of input vs output tokens"))

            # Chart 3: Duration vs tokens (full/interactive only)
            p = plot_duration_vs_tokens(run, output_dir)
            if p:
                paths.append(p)
                charts_index.append((p.name, "Duration vs Token Cost — Grouped column of total time and tokens"))

        # Chart 4: Per-email duration histogram (always)
        p = plot_email_duration_histogram(run, output_dir)
        if p:
            paths.append(p)
            charts_index.append((p.name, "Per-Email Duration Distribution — Histogram of processing times"))

        # Chart 9: Token vs duration scatter
        p = plot_token_duration_scatter(run, output_dir)
        if p:
            paths.append(p)
            charts_index.append((p.name, "Token vs Duration Relationship — Scatter plot with trend line"))

    # --- Variance trend charts (multi-iteration) ---
    if jsonl_path and jsonl_path.exists():
        runs = load_jsonl(jsonl_path)
        if len(runs) >= 2:
            # Chart 5: Variance trend lines
            trend_paths = plot_variance_trend(runs, output_dir)
            paths.extend(trend_paths)
            for tp in trend_paths:
                charts_index.append((tp.name, "Variance Trend — Line graph of metrics across iterations"))

            # Chart 8: Category stability stacked bar
            p = plot_category_stability(runs, output_dir)
            if p:
                paths.append(p)
                charts_index.append((p.name, "Category Stability — Stacked bar of category composition per run"))

    # --- Interactive mode charts ---
    if interactive_path and interactive_path.exists():
        interactive = _load_json(interactive_path)

        # Chart 6: Interactive turn breakdown
        p = plot_interactive_turns(interactive, output_dir)
        if p:
            paths.append(p)
            charts_index.append((p.name, "Interactive Turn Breakdown — Per-turn duration and tokens"))

        # Chart 7: Interactive token heatmap
        p = plot_interactive_heatmap(interactive, output_dir)
        if p:
            paths.append(p)
            charts_index.append((p.name, "Interactive Token Heatmap — Turn x Step matrix of token consumption"))

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
    parser.add_argument("--output-dir", type=str, default="benchmark_charts",
                        help="Directory to write chart PNGs")
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
        for candidate in [Path("results.jsonl"), Path("benchmark_results/results.jsonl")]:
            if candidate.exists():
                args.jsonl_path = str(candidate)
                break
        for candidate in [Path("interactive.json"), Path("benchmark_results/interactive.json")]:
            if candidate.exists():
                args.interactive_path = str(candidate)
                break

        if not any([args.json_path, args.jsonl_path, args.interactive_path]):
            print("Error: No benchmark output files found. "
                  "Run a benchmark first or specify --json-path/--jsonl-path/--interactive-path")
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
