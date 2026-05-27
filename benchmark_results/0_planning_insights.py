#!/usr/bin/env python3
"""
planning_insights.py — LLM invocation analysis for GAIA email benchmark.

Analyzes per-step LLM call patterns from benchmark results and produces
6 professional charts. Reads from both JSONL (full/batched/smart mode)
and JSON (interactive mode) files.

Usage:
    python 0_planning_insights.py                     # Auto-detect from cwd
    python 0_planning_insights.py --input-dir <dir>   # Specify data directory
    python 0_planning_insights.py --jsonl <path>      # Single JSONL file
    python 0_planning_insights.py --json <path>       # Single interactive JSON

Output:
    0_planning-{run_suffix}/   (or 0_planning/ if no run_id found)
    ├── 01_llm_stability.png
    ├── 02_llm_efficiency.png
    ├── 03_outlier_detection.png
    ├── 04_llm_reality.png
    ├── 05_llm_calls_heatmap.png
    └── 06_llm_tokens_heatmap.png

Charts are saved to a run-ID-tagged directory for lineage tracking.
"""

from __future__ import annotations

import argparse
import json
import glob
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

# Professional styling.
plt.rcParams.update({
    "figure.figsize": (13, 7.5),
    "axes.titlesize": 14,
    "axes.labelsize": 11,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "figure.dpi": 150,
})
sns.set_theme(style="whitegrid")


# ---------------------------------------------------------------------------
# Run ID suffix extraction (same logic as visualize.py)
# ---------------------------------------------------------------------------

def _extract_run_suffix(run_id: str) -> str:
    """Extract the last hyphen-delimited segment from a run_id."""
    suffix = run_id.rsplit("-", 1)[-1]
    if len(suffix) <= 1:
        suffix = run_id[-6:]
    return suffix


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _count_planning_calls(step_results: list[dict]) -> dict[str, int]:
    """Count LLM call categories from step_results.

    Returns dict with:
      - planning: LLM calls with no tool_name (pure reasoning/planning)
      - tool_execution: LLM calls with a named tool
      - total: all LLM invocations
    """
    planning = 0
    tool_execution = 0
    for s in step_results:
        action = str(s.get("action", ""))
        if "llm_call" not in action:
            continue
        tool = s.get("tool_name") or ""
        if tool.strip():
            tool_execution += 1
        else:
            planning += 1
    return {"planning": planning, "tool_execution": tool_execution, "total": planning + tool_execution}


def load_all_runs(
    jsonl_path: str | None = None,
    json_path: str | None = None,
    input_dir: str | None = None,
) -> tuple[pd.DataFrame, str]:
    """Load benchmark runs from JSONL/JSON files.

    Returns (DataFrame, run_id_suffix) where run_id_suffix is extracted
    from the last run's run_id for output directory naming.
    """
    runs: list[dict[str, Any]] = []
    run_id_suffix = ""

    if json_path:
        # Single interactive JSON file.
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        run_id = data.get("run_id", "")
        run_id_suffix = _extract_run_suffix(run_id) if run_id else ""
        turns = data.get("turns", [])
        total_steps = 0
        total_planning = 0
        total_tool_exec = 0
        for turn in turns:
            steps = turn.get("step_results", [])
            counts = _count_planning_calls(steps)
            total_steps += counts["total"]
            total_planning += counts["planning"]
            total_tool_exec += counts["tool_execution"]
        runs.append({
            "model": data.get("model", "unknown"),
            "emails": data.get("total_emails_affected", 0),
            "emails_in_initial_triage": data.get("emails_in_initial_triage", 0),
            "planning_calls": total_planning,
            "tool_exec_calls": total_tool_exec,
            "total_llm_calls": total_steps,
            "total_tokens": data.get("total_tokens", 0),
            "duration_s": data.get("total_duration_ms", 0) / 1000,
            "run_id": run_id,
            "mode": "interactive",
        })
    elif jsonl_path:
        # Single JSONL file.
        for line in open(jsonl_path, encoding="utf-8"):
            r = json.loads(line)
            counts = _count_planning_calls(r.get("step_results", []))
            run_id = r.get("run_id", "")
            if run_id:
                run_id_suffix = _extract_run_suffix(run_id)
            runs.append({
                "model": r.get("model", "unknown"),
                "emails": r.get("total_emails", 0),
                "planning_calls": counts["planning"],
                "tool_exec_calls": counts["tool_execution"],
                "total_llm_calls": counts["total"],
                "total_tokens": r.get("total_tokens", 0),
                "duration_s": r.get("total_duration_ms", 0) / 1000,
                "run_id": run_id,
                "mode": r.get("mode", "full"),
            })
    else:
        # Auto-detect from input_dir: read all results_*.jsonl and interactive_*.json.
        base = Path(input_dir) if input_dir else Path(".")

        # Read JSONL files.
        for f in sorted(base.glob("results_*.jsonl")):
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                counts = _count_planning_calls(r.get("step_results", []))
                run_id = r.get("run_id", "")
                if run_id:
                    run_id_suffix = _extract_run_suffix(run_id)
                runs.append({
                    "model": r.get("model", "unknown"),
                    "emails": r.get("total_emails", 0),
                    "planning_calls": counts["planning"],
                    "tool_exec_calls": counts["tool_execution"],
                    "total_llm_calls": counts["total"],
                    "total_tokens": r.get("total_tokens", 0),
                    "duration_s": r.get("total_duration_ms", 0) / 1000,
                    "run_id": run_id,
                    "mode": r.get("mode", "full"),
                })

        # Read interactive JSON files.
        for f in sorted(base.glob("interactive_*.json")):
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            run_id = data.get("run_id", "")
            if run_id:
                run_id_suffix = _extract_run_suffix(run_id)
            turns = data.get("turns", [])
            total_steps = 0
            total_planning = 0
            total_tool_exec = 0
            for turn in turns:
                steps = turn.get("step_results", [])
                c = _count_planning_calls(steps)
                total_steps += c["total"]
                total_planning += c["planning"]
                total_tool_exec += c["tool_execution"]
            runs.append({
                "model": data.get("model", "unknown"),
                "emails": data.get("total_emails_affected", 0),
                "emails_in_initial_triage": data.get("emails_in_initial_triage", 0),
                "planning_calls": total_planning,
                "tool_exec_calls": total_tool_exec,
                "total_llm_calls": total_steps,
                "total_tokens": data.get("total_tokens", 0),
                "duration_s": data.get("total_duration_ms", 0) / 1000,
                "run_id": run_id,
                "mode": "interactive",
            })

    # Also read per-run JSON files (run_*.json) for individual traceability.
    if not json_path and not jsonl_path:
        for f in sorted((Path(input_dir) if input_dir else Path(".")).glob("run_*.json")):
            # Skip if already loaded from JSONL (check run_id).
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            run_id = data.get("run_id", "")
            if run_id and any(r.get("run_id") == run_id for r in runs):
                continue  # Already loaded.
            counts = _count_planning_calls(data.get("step_results", []))
            if run_id:
                run_id_suffix = _extract_run_suffix(run_id)
            runs.append({
                "model": data.get("model", "unknown"),
                "emails": data.get("total_emails", 0),
                "emails_in_initial_triage": data.get("emails_in_initial_triage", 0),
                "planning_calls": counts["planning"],
                "tool_exec_calls": counts["tool_execution"],
                "total_llm_calls": counts["total"],
                "total_tokens": data.get("total_tokens", 0),
                "duration_s": data.get("total_duration_ms", 0) / 1000,
                "run_id": run_id,
                "mode": data.get("mode", "full"),
            })

    return pd.DataFrame(runs), run_id_suffix


# ---------------------------------------------------------------------------
# Chart functions
# ---------------------------------------------------------------------------

def create_heatmap(df, value, title, filename, cmap="RdYlBu_r"):
    """Professional heatmap matching Chart 24/29 style."""
    pivot = df.pivot_table(index="emails", columns="model", values=value, aggfunc="mean")
    plt.figure(figsize=(12, 6.5))
    ax = sns.heatmap(pivot, cmap=cmap, annot=True, fmt=".1f", linewidths=.6,
                     cbar_kws={"label": value.replace("_", " ").title()})
    plt.title(title, pad=18)
    plt.xlabel("Model")
    plt.ylabel("Email Limit")
    plt.tight_layout()
    plt.savefig(filename, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {filename}")


def plot_stability(df, output_dir: Path):
    """Box plot + strip of LLM call distribution per model."""
    plt.figure(figsize=(12, 6))
    ax = sns.boxplot(data=df, x="model", y="total_llm_calls", palette="Set2")
    sns.stripplot(data=df, x="model", y="total_llm_calls", color="black", alpha=0.55, jitter=0.25)
    means = df.groupby("model")["total_llm_calls"].mean()
    for i, m in enumerate(means.index):
        ax.text(i, means[m] + 0.25, f"μ={means[m]:.2f}", ha="center", color="darkred", fontsize=9)
    plt.title("LLM Call Stability by Model\n(Higher variance = less stable agent behavior)", pad=15)
    plt.ylabel("Total LLM Calls per Run")
    plt.xticks(rotation=10)
    plt.tight_layout()
    plt.savefig(output_dir / "01_llm_stability.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {output_dir / '01_llm_stability.png'}")


def plot_efficiency(df, output_dir: Path):
    """Tokens per LLM call — lower = better efficiency."""
    df = df.copy()
    df["tok_per_call"] = df["total_tokens"] / df["total_llm_calls"].replace(0, 1)
    plt.figure(figsize=(12, 6))
    sns.boxplot(data=df, x="model", y="tok_per_call", palette="coolwarm")
    plt.title("LLM Efficiency: Tokens per LLM Call\n(Lower = better efficiency)", pad=15)
    plt.ylabel("Tokens per LLM Call")
    plt.xticks(rotation=10)
    plt.tight_layout()
    plt.savefig(output_dir / "02_llm_efficiency.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {output_dir / '02_llm_efficiency.png'}")


def plot_tool_vs_planning(df, output_dir: Path):
    """Stacked bar: planning (no tool) vs tool execution LLM calls."""
    df = df.copy()
    df["model_emails"] = df["model"] + " (" + df["emails"].astype(str) + ")"
    plt.figure(figsize=(13, 6.5))
    x = range(len(df))
    plt.bar(x, df["planning_calls"], label="Planning (no tool)", color="#3182CE")
    plt.bar(x, df["tool_exec_calls"], bottom=df["planning_calls"], label="Tool execution", color="#DD6B20")
    for i, (_, r) in enumerate(df.iterrows()):
        total = r["planning_calls"] + r["tool_exec_calls"]
        if total > 0:
            plt.text(i, total + 0.15, str(int(total)), ha="center", fontsize=9, fontweight="bold")
    plt.xticks(x, df["model_emails"], rotation=25, ha="right")
    plt.ylabel("LLM Calls")
    plt.title("LLM Call Breakdown: Planning vs Tool Execution\n(Empty tool_name = planning/reasoning; named = tool call)", pad=15)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "03_planning_vs_tool.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {output_dir / '03_planning_vs_tool.png'}")


def plot_outlier(df, output_dir: Path):
    """Scatter of duration vs tokens with outlier annotation."""
    plt.figure(figsize=(11, 7))
    sns.scatterplot(data=df, x="duration_s", y="total_tokens", hue="model",
                    size="emails", sizes=(70, 450), alpha=0.75, edgecolor="white")
    outlier = df[df["duration_s"] > 1000]
    for _, r in outlier.iterrows():
        plt.annotate(f"OUTLIER: {r['model']}\n{r['duration_s']:.0f}s",
                     xy=(r["duration_s"], r["total_tokens"]),
                     xytext=(r["duration_s"] + 120, r["total_tokens"] + 6000),
                     arrowprops=dict(arrowstyle="->", color="red", lw=1.8),
                     fontsize=9, color="red", fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="red"))
    plt.title("Duration vs Total Tokens — Outlier Detection", pad=15)
    plt.xlabel("Duration (s)")
    plt.ylabel("Total Tokens")
    plt.legend(bbox_to_anchor=(1.02, 1))
    plt.tight_layout()
    plt.savefig(output_dir / "04_outlier_detection.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {output_dir / '04_outlier_detection.png'}")


def plot_reality(df, output_dir: Path):
    """Grouped bar: avg LLM calls by model and email limit."""
    plt.figure(figsize=(11, 5.5))
    sns.barplot(data=df, x="model", y="total_llm_calls", hue="emails", errorbar="sd", palette="viridis")
    plt.title("LLM Invocation Overhead by Model and Email Limit", pad=15)
    plt.ylabel("Avg LLM Calls per Run")
    plt.legend(title="Email Limit", bbox_to_anchor=(1.05, 1))
    plt.tight_layout()
    plt.savefig(output_dir / "05_llm_reality.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved: {output_dir / '05_llm_reality.png'}")


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM invocation analysis for GAIA email benchmark.")
    parser.add_argument("--input-dir", default=None, help="Directory containing benchmark results.")
    parser.add_argument("--jsonl", default=None, help="Single JSONL file to analyze.")
    parser.add_argument("--json", default=None, help="Single interactive JSON file to analyze.")
    parser.add_argument("--output-dir", default=None, help="Output directory for charts (default: 0_planning-{run_suffix}/).")
    args = parser.parse_args(argv)

    print("Loading benchmark data...")
    df, run_suffix = load_all_runs(jsonl_path=args.jsonl, json_path=args.json, input_dir=args.input_dir)

    if df.empty:
        print("No runs found.")
        return 1

    print(f"{len(df)} runs loaded across {df['model'].nunique()} models")
    if run_suffix:
        print(f"Run ID suffix: {run_suffix}")

    # Output directory with run ID for lineage tracking.
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        dir_name = f"0_planning-{run_suffix}" if run_suffix else "0_planning"
        input_base = Path(args.input_dir) if args.input_dir else Path(".")
        output_dir = input_base / dir_name
    output_dir.mkdir(parents=True, exist_ok=True)

    plot_stability(df, output_dir)
    plot_efficiency(df, output_dir)
    plot_tool_vs_planning(df, output_dir)
    plot_outlier(df, output_dir)
    plot_reality(df, output_dir)

    # Heatmap charts.
    if df["model"].nunique() >= 2 and df["emails"].nunique() >= 2:
        create_heatmap(df, "total_llm_calls",
                       "LLM Calls Heatmap (Model x Email Limit)",
                       str(output_dir / "06_llm_calls_heatmap.png"), cmap="RdYlBu_r")
        create_heatmap(df, "total_tokens",
                       "Total LLM Tokens Heatmap (Model x Email Limit)",
                       str(output_dir / "07_llm_tokens_heatmap.png"), cmap="viridis")
        print(f"\n7 high-sophistication charts created in {output_dir}/")
    else:
        print(f"\n5 charts created in {output_dir}/ (heatmaps need 2+ models and 2+ email limits)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
