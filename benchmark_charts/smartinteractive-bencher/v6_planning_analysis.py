#!/usr/bin/env python3
"""
planning_insights_final_v6.py — Professional GAIA Email Benchmark Analysis
FINAL VERSION with TOP 3 NEW INSIGHTS + All Previous Charts
"""

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

# Professional styling
plt.rcParams.update({
    "figure.figsize": (13, 7.5),
    "axes.titlesize": 15,
    "axes.labelsize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "figure.dpi": 160,
    "axes.grid": True,
    "grid.alpha": 0.3,
})
sns.set_theme(style="whitegrid")


def _extract_run_suffix(run_id: str) -> str:
    suffix = run_id.rsplit("-", 1)[-1]
    return suffix if len(suffix) > 1 else run_id[-6:]


def load_all_runs(input_dir: str | None = None) -> tuple[pd.DataFrame, str]:
    runs: list[dict[str, Any]] = []
    run_id_suffix = ""

    if input_dir is None:
        input_dir = r"C:\Users\antmi\gaia-visualizations\benchmark_charts\smartinteractive-bencher\benchmark_results\interactive-smart"

    base = Path(input_dir)
    print(f"Loading from: {base}")

    for f in sorted(base.glob("interactive_*.json")):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        run_id = data.get("run_id", "")
        if run_id:
            run_id_suffix = _extract_run_suffix(run_id)

        total_duration = data.get("total_duration_ms", 0) / 1000
        total_tokens = data.get("total_tokens", 0)
        heuristic_only = data.get("heuristic_only_count", 0)
        llm_escalated = data.get("llm_escalated_count", 0)
        input_tokens = data.get("total_input_tokens", 0)
        output_tokens = data.get("total_output_tokens", 0)
        emails = data.get("total_emails_affected", 0)

        # Per-turn breakdown
        turns = data.get("turns", [])
        for turn in turns:
            turn_number = turn.get("turn_number", 0)
            turn_tokens = 0
            planning_tokens = 0
            tool_tokens = 0
            for step in turn.get("step_results", []):
                if step.get("action") == "llm_call":
                    t = step.get("total_tokens", 0)
                    turn_tokens += t
                    if not step.get("tool_name"):
                        planning_tokens += t
                    else:
                        tool_tokens += t
            if turn_tokens > 0 or turn_number > 0:
                runs.append({
                    "model": data.get("model", "unknown"),
                    "emails": emails,
                    "duration_s": total_duration,
                    "heuristic_only": heuristic_only,
                    "llm_escalated": llm_escalated,
                    "total_tokens": total_tokens,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "turn_number": turn_number,
                    "turn_tokens": turn_tokens,
                    "planning_tokens": planning_tokens,
                    "tool_tokens": tool_tokens,
                    "run_id": run_id,
                    "mode": "interactive",
                })

        # Aggregate per-run row
        runs.append({
            "model": data.get("model", "unknown"),
            "emails": emails,
            "duration_s": total_duration,
            "heuristic_only": heuristic_only,
            "llm_escalated": llm_escalated,
            "total_tokens": total_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "turn_number": 0,
            "turn_tokens": 0,
            "planning_tokens": 0,
            "tool_tokens": 0,
            "run_id": run_id,
            "mode": "interactive",
        })

    df = pd.DataFrame(runs)
    df["time_per_email"] = df["duration_s"] / df["emails"].replace(0, 1)

    print(f"Loaded {len(df)} runs across {df['model'].nunique()} models")
    return df, run_id_suffix


# ==================== CHARTS ====================

def plot_small_model_struggle(df: pd.DataFrame, output_dir: Path):
    plt.figure(figsize=(12, 6))
    sns.boxplot(data=df, x="model", y="duration_s", hue="model", palette="Reds", legend=False)
    sns.stripplot(data=df, x="model", y="duration_s", color="black", alpha=0.55, jitter=0.3)
    plt.title("Why Small Models Struggled", pad=18)
    plt.ylabel("Duration (seconds)")
    plt.xticks(rotation=12)
    plt.tight_layout()
    plt.savefig(output_dir / "01b_small_model_struggle.png", dpi=160, bbox_inches="tight")
    plt.close()
    print("Saved: 01b_small_model_struggle.png")


def plot_input_tokens(df: pd.DataFrame, output_dir: Path):
    plt.figure(figsize=(12, 6))
    sns.boxplot(data=df, x="model", y="input_tokens", hue="model", palette="Blues", legend=False)
    plt.title("Input Tokens by Model", pad=18)
    plt.ylabel("Total Input Tokens")
    plt.xticks(rotation=12)
    plt.tight_layout()
    plt.savefig(output_dir / "02a_input_tokens.png", dpi=160, bbox_inches="tight")
    plt.close()
    print("Saved: 02a_input_tokens.png")


def plot_output_tokens(df: pd.DataFrame, output_dir: Path):
    plt.figure(figsize=(12, 6))
    sns.boxplot(data=df, x="model", y="output_tokens", hue="model", palette="Oranges", legend=False)
    plt.title("Output Tokens by Model", pad=18)
    plt.ylabel("Total Output Tokens")
    plt.xticks(rotation=12)
    plt.tight_layout()
    plt.savefig(output_dir / "02b_output_tokens.png", dpi=160, bbox_inches="tight")
    plt.close()
    print("Saved: 02b_output_tokens.png")


def plot_heuristic_vs_llm(df: pd.DataFrame, output_dir: Path):
    df = df.copy()
    df["model_short"] = df["model"].str.replace("-GGUF", "")
    plt.figure(figsize=(14, 6.5))
    x = range(len(df))
    plt.bar(x, df["heuristic_only"], label="Heuristic Only", color="#27ae60", width=0.7)
    plt.bar(x, df["llm_escalated"], bottom=df["heuristic_only"], label="LLM Escalated", color="#e74c3c", width=0.7)
    plt.xticks(x, df["model_short"], rotation=45, ha="right", fontsize=9)
    plt.title("Heuristic vs LLM Escalation", pad=18)
    plt.legend(loc="upper right")
    plt.tight_layout()
    plt.savefig(output_dir / "03_heuristic_vs_llm.png", dpi=160, bbox_inches="tight")
    plt.close()
    print("Saved: 03_heuristic_vs_llm.png")


def plot_duration_heatmap(df: pd.DataFrame, output_dir: Path):
    if df["emails"].nunique() < 2 or df["model"].nunique() < 2:
        return
    pivot = df.pivot_table(index="emails", columns="model", values="duration_s", aggfunc="mean")
    plt.figure(figsize=(12, 6.5))
    sns.heatmap(pivot, cmap="YlOrRd", annot=True, fmt=".0f", linewidths=0.6,
                cbar_kws={"label": "Duration (seconds)"})
    plt.title("End-to-End Duration (seconds)\nModel × Email Limit", pad=18)
    plt.xlabel("Model")
    plt.ylabel("Email Limit")
    plt.tight_layout()
    plt.savefig(output_dir / "08_duration_heatmap.png", dpi=160, bbox_inches="tight")
    plt.close()
    print("Saved: 08_duration_heatmap.png")


def plot_time_per_email(df: pd.DataFrame, output_dir: Path):
    plt.figure(figsize=(12, 6))
    sns.barplot(data=df, x="model", y="time_per_email", hue="emails", errorbar="sd", palette="coolwarm")
    plt.title("Average Time per Email (seconds) — Lower is Better", pad=18)
    plt.ylabel("Seconds per Email")
    plt.legend(title="Email Limit", bbox_to_anchor=(1.05, 1))
    plt.tight_layout()
    plt.savefig(output_dir / "09_time_per_email.png", dpi=160, bbox_inches="tight")
    plt.close()
    print("Saved: 09_time_per_email.png")


def plot_planning_vs_tool_tokens(df: pd.DataFrame, output_dir: Path):
    plt.figure(figsize=(13, 6.5))
    x = range(len(df))
    plt.bar(x, df["planning_tokens"], label="Planning Tokens", color="#3498db", width=0.7)
    plt.bar(x, df["tool_tokens"], bottom=df["planning_tokens"], label="Tool + Context Tokens", color="#e67e22", width=0.7)
    plt.xticks(x, df["model"].str.replace("-GGUF", ""), rotation=45, ha="right")
    plt.title("Planning vs Tool Execution Tokens", pad=18)
    plt.ylabel("Total Tokens")
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "10_planning_vs_tool_tokens.png", dpi=160, bbox_inches="tight")
    plt.close()
    print("Saved: 10_planning_vs_tool_tokens.png")


def plot_tokens_per_turn(df: pd.DataFrame, output_dir: Path):
    turn_df = df[df["turn_number"] > 0].copy()
    if turn_df.empty:
        return
    plt.figure(figsize=(12, 6))
    sns.barplot(data=turn_df, x="turn_number", y="turn_tokens", hue="model", errorbar="sd")
    plt.title("Tokens per Turn / Stage", pad=18)
    plt.xlabel("Turn Number")
    plt.ylabel("Tokens per Turn")
    plt.legend(title="Model", bbox_to_anchor=(1.05, 1))
    plt.tight_layout()
    plt.savefig(output_dir / "11_tokens_per_turn.png", dpi=160, bbox_inches="tight")
    plt.close()
    print("Saved: 11_tokens_per_turn.png")


# ==================== NEW TOP 3 INSIGHTS ====================

def plot_context_explosion(df: pd.DataFrame, output_dir: Path):
    """NEW Chart 12: Context Explosion Rate"""
    turn_df = df[df["turn_number"] > 0].copy()
    if turn_df.empty:
        return
    plt.figure(figsize=(12, 6))
    sns.lineplot(data=turn_df, x="turn_number", y="turn_tokens", hue="model", marker="o")
    plt.title("Context Explosion Rate\n(Input Tokens Growth per Turn)", pad=18)
    plt.xlabel("Turn Number")
    plt.ylabel("Input Tokens per Turn")
    plt.legend(title="Model")
    plt.tight_layout()
    plt.savefig(output_dir / "12_context_explosion.png", dpi=160, bbox_inches="tight")
    plt.close()
    print("Saved: 12_context_explosion.png")


def plot_heuristic_savings(df: pd.DataFrame, output_dir: Path):
    """NEW Chart 13: Heuristic Savings %"""
    df = df.copy()
    df["heuristic_pct"] = (df["heuristic_only"] / (df["heuristic_only"] + df["llm_escalated"])) * 100
    plt.figure(figsize=(12, 6))
    sns.barplot(data=df, x="model", y="heuristic_pct", hue="model", palette="Greens", legend=False)
    plt.title("Heuristic Savings % per Model", pad=18)
    plt.ylabel("Heuristic Emails Handled (%)")
    plt.xticks(rotation=12)
    plt.tight_layout()
    plt.savefig(output_dir / "13_heuristic_savings.png", dpi=160, bbox_inches="tight")
    plt.close()
    print("Saved: 13_heuristic_savings.png")


def plot_tool_usage(df: pd.DataFrame, output_dir: Path):
    """NEW Chart 14: Tool Usage Breakdown"""
    # Placeholder - real tool breakdown would require parsing tools_used list
    plt.figure(figsize=(12, 6))
    sns.barplot(data=df, x="model", y="tool_tokens", hue="model", palette="Oranges", legend=False)
    plt.title("Tool Usage Token Cost per Model", pad=18)
    plt.ylabel("Tool + Context Tokens")
    plt.xticks(rotation=12)
    plt.tight_layout()
    plt.savefig(output_dir / "14_tool_usage.png", dpi=160, bbox_inches="tight")
    plt.close()
    print("Saved: 14_tool_usage.png")


# ==================== MAIN ====================

def main():
    parser = argparse.ArgumentParser(description="Professional GAIA Email Benchmark Analysis - Final v6")
    parser.add_argument("--input-dir", default=None)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    print("=== GAIA Planning Insights (Final Professional Version v6) ===")
    df, run_suffix = load_all_runs(input_dir=args.input_dir)

    if df.empty:
        print("No data found.")
        return 1

    output_dir = Path(args.output_dir) if args.output_dir else Path(f"0_planning-{run_suffix}" if run_suffix else "0_planning")
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_dir}")

    # All previous charts
    plot_small_model_struggle(df, output_dir)
    plot_input_tokens(df, output_dir)
    plot_output_tokens(df, output_dir)
    plot_heuristic_vs_llm(df, output_dir)
    plot_duration_heatmap(df, output_dir)
    plot_time_per_email(df, output_dir)
    plot_planning_vs_tool_tokens(df, output_dir)
    plot_tokens_per_turn(df, output_dir)

    # NEW TOP 3 INSIGHTS
    plot_context_explosion(df, output_dir)
    plot_heuristic_savings(df, output_dir)
    plot_tool_usage(df, output_dir)

    # Full insights summary
    summary = df.groupby("model").agg({
        "duration_s": "mean",
        "time_per_email": "mean",
        "heuristic_only": "mean",
        "llm_escalated": "mean",
        "total_tokens": "mean",
        "input_tokens": "mean",
        "output_tokens": "mean",
        "planning_tokens": "mean",
        "tool_tokens": "mean"
    }).round(2)

    print("\n=== ALL BENEFICIAL INSIGHTS SUMMARY ===")
    print(summary)

    heuristic_pct = (summary["heuristic_only"] / (summary["heuristic_only"] + summary["llm_escalated"])) * 100
    print("\nHeuristic % by Model:")
    print(heuristic_pct.round(1))

    print("\n=== REMAINING INSIGHTS TO ADD LATER ===")
    print("4. Classification Consistency")
    print("5. Error Frequency (context overflow, batch failures)")
    print("6. Scaling Curve (tokens vs email limit)")
    print("7. Per-Model Planning Overhead")
    print("8. Interactive Turn Efficiency")

    print(f"\n✅ All charts saved to: {output_dir.absolute()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())