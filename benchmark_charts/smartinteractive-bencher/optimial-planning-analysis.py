#!/usr/bin/env python3
"""
v4-planning-analysis.py — OPTIMAL GAIA SMART Benchmark Visualization Suite
All charts fixed + professional output
"""

import argparse
import json
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

plt.rcParams.update({"figure.figsize": (14, 8), "axes.titlesize": 16, "axes.labelsize": 13,
                     "xtick.labelsize": 11, "ytick.labelsize": 11, "figure.dpi": 200})
sns.set_theme(style="whitegrid")


def load_data(input_dir=None):
    if input_dir is None:
        input_dir = r"C:\Users\antmi\gaia-visualizations\benchmark_charts\smartinteractive-bencher\benchmark_results\interactive-smart"
    base = Path(input_dir)
    print(f"Loading from: {base}")
    runs = []
    for f in sorted(base.glob("interactive_*.json")):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        model = data.get("model", "unknown")
        emails = data.get("total_emails_affected", 0)
        duration_s = data.get("total_duration_ms", 0) / 1000
        heuristic_only = data.get("heuristic_only_count", 0)
        llm_escalated = data.get("llm_escalated_count", 0)
        input_tokens = data.get("total_input_tokens", 0)
        output_tokens = data.get("total_output_tokens", 0)

        # Per-turn rows for stream graph & context explosion
        turns = data.get("turns", [])
        for turn in turns:
            turn_number = turn.get("turn_number", 0)
            turn_tokens = sum(step.get("total_tokens", 0) for step in turn.get("step_results", []))
            if turn_tokens > 0 or turn_number > 0:
                runs.append({
                    "model": model,
                    "emails": emails,
                    "duration_s": duration_s,
                    "heuristic_only": heuristic_only,
                    "llm_escalated": llm_escalated,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "turn_number": turn_number,
                    "turn_tokens": turn_tokens,
                })

        # Aggregate row for other charts
        runs.append({
            "model": model,
            "emails": emails,
            "duration_s": duration_s,
            "heuristic_only": heuristic_only,
            "llm_escalated": llm_escalated,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "turn_number": 0,
            "turn_tokens": 0,
        })

    df = pd.DataFrame(runs)
    df["heuristic_pct"] = (df["heuristic_only"] / (df["heuristic_only"] + df["llm_escalated"])) * 100
    df["time_per_email"] = df["duration_s"] / df["emails"].replace(0, 1)
    print(f"Loaded {len(df)} rows across {df['model'].nunique()} models")
    return df


def save_chart(fig, name, output_dir):
    fig.savefig(output_dir / name, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {name}")


def main():
    output_dir = Path("v4_optimal_charts")
    output_dir.mkdir(parents=True, exist_ok=True)
    df = load_data()

    print("=== V4 OPTIMAL CHART SUITE — GAIA SMART BENCHMARK ===")

    # 1. Ridgeline — Duration Distribution
    fig, ax = plt.subplots()
    sns.kdeplot(data=df, x="duration_s", hue="model", fill=True, alpha=0.4, ax=ax)
    ax.set_title("1. Ridgeline — Duration Distribution by Model")
    save_chart(fig, "01_ridgeline_duration.png", output_dir)

    # 2. Diverging Bar — Heuristic vs LLM
    fig, ax = plt.subplots()
    df_plot = df.groupby("model").mean().reset_index()
    df_plot["heuristic_diff"] = df_plot["heuristic_pct"] - 50
    sns.barplot(data=df_plot, x="model", y="heuristic_diff", hue="model", palette="RdYlBu", legend=False, ax=ax)
    ax.set_title("2. Diverging Bar — Heuristic vs LLM %")
    save_chart(fig, "02_diverging_heuristic.png", output_dir)

    # 3. Slope Chart — Time per Email
    fig, ax = plt.subplots()
    sns.lineplot(data=df, x="emails", y="time_per_email", hue="model", marker="o", ax=ax)
    ax.set_title("3. Slope Chart — Time per Email Across Limits")
    save_chart(fig, "03_slope_time_per_email.png", output_dir)

    # 4. Stream Graph — Tokens per Turn
    fig, ax = plt.subplots()
    turn_df = df[df["turn_number"] > 0].copy()
    sns.lineplot(data=turn_df, x="turn_number", y="turn_tokens", hue="model", marker="o", ax=ax)
    ax.set_title("4. Stream Graph — Tokens per Turn")
    save_chart(fig, "04_stream_tokens_per_turn.png", output_dir)

    # 5. Heatmap + Correlation
    fig, ax = plt.subplots()
    corr = df[["input_tokens", "output_tokens", "duration_s", "heuristic_pct", "time_per_email"]].corr()
    sns.heatmap(corr, annot=True, cmap="RdYlBu", ax=ax)
    ax.set_title("5. Heatmap — Token Correlation")
    save_chart(fig, "05_heatmap_correlation.png", output_dir)

    # 6. Stacked Bar (Sunburst proxy) — Token Cost by Limit
    fig, ax = plt.subplots()
    sns.barplot(data=df, x="model", y="input_tokens", hue="emails", palette="viridis", ax=ax)
    ax.set_title("6. Stacked Bar — Token Cost by Limit")
    save_chart(fig, "06_stacked_token_cost.png", output_dir)

    # 7. PCA Quadrant Chart
    from sklearn.decomposition import PCA
    features = df[["duration_s", "input_tokens", "output_tokens", "heuristic_pct", "time_per_email"]]
    pca = PCA(n_components=2)
    components = pca.fit_transform(features)
    df["pca1"] = components[:, 0]
    df["pca2"] = components[:, 1]
    fig, ax = plt.subplots()
    sns.scatterplot(data=df, x="pca1", y="pca2", hue="model", s=200, ax=ax)
    ax.set_title("7. PCA Quadrant — Model Positioning")
    save_chart(fig, "07_pca_quadrant.png", output_dir)

    print(f"\n✅ ALL 7 OPTIMAL CHARTS SAVED TO: {output_dir.absolute()}")
    return 0


if __name__ == "__main__":
    main()