#!/usr/bin/env python3
"""
planning_insights.py — High-sophistication planning overhead analysis
Matches visual/analytical quality of Charts 24-29 in visualize.py
Focus: Honest view of CURRENT data (planning overhead + 100% heuristic)
"""

import json
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# Professional styling
plt.rcParams.update({
    "figure.figsize": (13, 7.5),
    "axes.titlesize": 14,
    "axes.labelsize": 11,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "figure.dpi": 150,
})
sns.set_theme(style="whitegrid")

def load_all_runs(pattern="results_*.jsonl"):
    runs = []
    for f in glob.glob(pattern):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            step_results = r.get("step_results", [])
            planning_calls = sum(
                1 for s in step_results 
                if "llm_call" in str(s.get("action", "")) or 
                   s.get("tool_name") in ("triage_inbox", None)
            )
            runs.append({
                "model": r.get("model", "unknown"),
                "emails": r.get("total_emails", 0),
                "planning_calls": planning_calls,
                "total_tokens": r.get("total_tokens", 0),
                "duration_s": r.get("total_duration_ms", 0) / 1000,
            })
    return pd.DataFrame(runs)

def create_heatmap(df, value, title, filename, cmap="RdYlBu_r"):
    """Professional heatmap like Chart 24/29"""
    pivot = df.pivot_table(index="emails", columns="model", values=value, aggfunc="mean")
    plt.figure(figsize=(12, 6.5))
    ax = sns.heatmap(pivot, cmap=cmap, annot=True, fmt=".1f", linewidths=.6,
                     cbar_kws={"label": value.replace("_", " ").title()})
    plt.title(title, pad=18)
    plt.xlabel("Model")
    plt.ylabel("Email Limit")
    plt.tight_layout()
    plt.savefig(filename, dpi=150, bbox_inches="tight")
    print(f"Saved: {filename}")

def plot_stability(df):
    plt.figure(figsize=(12, 6))
    ax = sns.boxplot(data=df, x="model", y="planning_calls", palette="Set2")
    sns.stripplot(data=df, x="model", y="planning_calls", color="black", alpha=0.55, jitter=0.25)
    means = df.groupby("model")["planning_calls"].mean()
    for i, m in enumerate(means.index):
        ax.text(i, means[m] + 0.25, f"μ={means[m]:.2f}", ha="center", color="darkred", fontsize=9)
    plt.title("Planning LLM Calls Stability by Model\n(Higher variance = less stable agent behavior)", pad=15)
    plt.ylabel("Planning LLM Calls per Run")
    plt.xticks(rotation=10)
    plt.tight_layout()
    plt.savefig("01_planning_stability.png", dpi=150, bbox_inches="tight")
    print("Saved: 01_planning_stability.png")

def plot_efficiency(df):
    df = df.copy()
    df["tok_per_call"] = df["total_tokens"] / df["planning_calls"].replace(0, 1)
    plt.figure(figsize=(12, 6))
    sns.boxplot(data=df, x="model", y="tok_per_call", palette="coolwarm")
    plt.title("Planning Efficiency: Tokens per LLM Planning Call\n(Lower = better planning efficiency)", pad=15)
    plt.ylabel("Tokens per Planning Call")
    plt.xticks(rotation=10)
    plt.tight_layout()
    plt.savefig("02_planning_efficiency.png", dpi=150, bbox_inches="tight")
    print("Saved: 02_planning_efficiency.png")

def plot_outlier(df):
    plt.figure(figsize=(11, 7))
    sns.scatterplot(data=df, x="duration_s", y="total_tokens", hue="model", 
                    size="emails", sizes=(70, 450), alpha=0.75, edgecolor="white")
    outlier = df[df["duration_s"] > 1000]
    for _, r in outlier.iterrows():
        plt.annotate(f"⚠️ MAJOR OUTLIER\n{r['model']}\n{r['duration_s']:.0f}s",
                     xy=(r["duration_s"], r["total_tokens"]),
                     xytext=(r["duration_s"]+120, r["total_tokens"]+6000),
                     arrowprops=dict(arrowstyle="->", color="red", lw=1.8),
                     fontsize=9, color="red", fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="red"))
    plt.title("Duration vs Total Tokens — Outlier Detection\n(Planning overhead only)", pad=15)
    plt.xlabel("Duration (s)")
    plt.ylabel("Total Tokens")
    plt.legend(bbox_to_anchor=(1.02, 1))
    plt.tight_layout()
    plt.savefig("03_outlier_detection.png", dpi=150, bbox_inches="tight")
    print("Saved: 03_outlier_detection.png")

def plot_reality(df):
    plt.figure(figsize=(11, 5.5))
    sns.barplot(data=df, x="model", y="planning_calls", hue="emails", errorbar="sd", palette="viridis")
    plt.title("Current Data Reality: Planning Overhead Only\n(100% Heuristic Classification — No per-email LLM work)", pad=15)
    plt.ylabel("Avg Planning LLM Calls")
    plt.legend(title="Email Limit", bbox_to_anchor=(1.05, 1))
    plt.tight_layout()
    plt.savefig("04_heuristic_reality.png", dpi=150, bbox_inches="tight")
    print("Saved: 04_heuristic_reality.png")

if __name__ == "__main__":
    print("Loading benchmark data...")
    df = load_all_runs()
    print(f"{len(df)} runs loaded across {df['model'].nunique()} models")

    plot_stability(df)
    plot_efficiency(df)
    plot_outlier(df)
    plot_reality(df)

    # Heatmap level charts
    create_heatmap(df, "planning_calls", 
                   "Planning LLM Calls Heatmap (Model × Email Limit)", 
                   "05_planning_calls_heatmap.png", cmap="RdYlBu_r")
    create_heatmap(df, "total_tokens", 
                   "Total Planning Tokens Heatmap (Model × Email Limit)", 
                   "06_planning_tokens_heatmap.png", cmap="viridis")

    print("\n✅ 6 high-sophistication charts created (heatmap + professional level).")