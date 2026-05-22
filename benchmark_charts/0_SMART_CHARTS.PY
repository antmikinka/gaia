#!/usr/bin/env python3
"""
Professional Chart Generator for SMART Interactive Benchmark Analysis
Includes Token Source Breakdown (Chart 07)
"""

import json
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import numpy as np

# ====================== CONFIG ======================
INPUT_JSON = Path("smart_benchmark_analysis.json")
OUTPUT_DIR = Path("smart_charts")
OUTPUT_DIR.mkdir(exist_ok=True)

sns.set_theme(style="whitegrid", font_scale=1.1)
plt.rcParams["figure.dpi"] = 150
plt.rcParams["savefig.bbox"] = "tight"
# ====================================================


def load_data():
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    df = pd.DataFrame(data["results"])
    df = df[df["status"] == "completed"].copy()
    df["heuristic_pct"] = (df["heuristic_emails"] / df["limit"] * 100).round(1)
    df["llm_pct"] = (df["llm_emails"] / df["limit"] * 100).round(1)
    df["tokens_per_email"] = (df["total_tokens"] / df["limit"]).round(0)
    return df


def chart_1_heuristic_vs_llm(df):
    plt.figure(figsize=(10, 6))
    melted = df.melt(id_vars=["model", "limit"], 
                     value_vars=["heuristic_pct", "llm_pct"],
                     var_name="type", value_name="percentage")
    melted["type"] = melted["type"].map({"heuristic_pct": "Heuristic", "llm_pct": "LLM"})
    sns.barplot(data=melted, x="model", y="percentage", hue="type", palette=["#2ecc71", "#e74c3c"])
    plt.title("Heuristic vs LLM Coverage in SMART Mode\n(Stratified Dataset)", fontsize=14, pad=15)
    plt.ylabel("Percentage of Emails (%)")
    plt.xlabel("Model")
    plt.legend(title="Classification Path")
    plt.xticks(rotation=15)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "01_heuristic_vs_llm_split.png")
    plt.close()


def chart_2_token_scaling(df):
    plt.figure(figsize=(10, 6))
    sns.lineplot(data=df, x="limit", y="total_tokens", hue="model", 
                 marker="o", linewidth=2, markersize=8)
    plt.title("Total Token Consumption vs Email Limit (SMART Mode)", fontsize=14, pad=15)
    plt.xlabel("Email Limit")
    plt.ylabel("Total Tokens")
    plt.legend(title="Model", bbox_to_anchor=(1.05, 1), loc="upper left")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "02_token_scaling.png")
    plt.close()


def chart_3_duration_by_model(df):
    df100 = df[df["limit"] == 100]
    plt.figure(figsize=(9, 6))
    sns.barplot(data=df100, x="model", y="duration_s", palette="viridis")
    plt.title("Average Duration at 100 Emails (SMART Mode)", fontsize=14, pad=15)
    plt.ylabel("Duration (seconds)")
    plt.xlabel("Model")
    plt.xticks(rotation=15)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "03_duration_comparison.png")
    plt.close()


def chart_4_category_distribution(df):
    records = []
    for _, row in df.iterrows():
        for cat, vals in row["categories"].items():
            records.append({
                "model": row["model"],
                "limit": row["limit"],
                "category": cat,
                "count": vals["count"]
            })
    cat_df = pd.DataFrame(records)
    plt.figure(figsize=(10, 6))
    sns.barplot(data=cat_df, x="model", y="count", hue="category", 
                palette=["#3498db", "#95a5a6"])
    plt.title("Final Category Distribution in SMART Mode", fontsize=14, pad=15)
    plt.ylabel("Number of Emails")
    plt.xlabel("Model")
    plt.legend(title="Category")
    plt.xticks(rotation=15)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "04_category_distribution.png")
    plt.close()


def chart_5_tokens_per_email(df):
    plt.figure(figsize=(10, 6))
    sns.boxplot(data=df, x="model", y="tokens_per_email", palette="Set2")
    plt.title("Tokens per Email (Efficiency) in SMART Mode", fontsize=14, pad=15)
    plt.ylabel("Tokens per Email")
    plt.xlabel("Model")
    plt.xticks(rotation=15)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "05_tokens_per_email.png")
    plt.close()


def chart_6_success_rate():
    with open("smart_benchmark_analysis.json") as f:
        full = json.load(f)
    summary = full["summary_by_model"]
    models = list(summary.keys())
    completed = [summary[m]["completed"] for m in models]
    total = [summary[m]["total"] for m in models]
    success_rate = [c / t * 100 for c, t in zip(completed, total)]

    plt.figure(figsize=(9, 6))
    sns.barplot(x=models, y=success_rate, palette="coolwarm_r")
    plt.title("SMART Mode Success Rate by Model", fontsize=14, pad=15)
    plt.ylabel("Success Rate (%)")
    plt.xlabel("Model")
    plt.xticks(rotation=15)
    plt.ylim(0, 100)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "06_success_rate.png")
    plt.close()


def chart_7_token_sources_proxy(df):
    """
    Chart 07: Estimated Token Source Breakdown (Proxy Analysis)
    Uses available data + logical proxies from logs.
    """
    # Create proxy breakdown
    df = df.copy()
    df["get_message_proxy"] = df["llm_emails"] * 1800      # ~1800 tokens per get_message (body + overhead)
    df["planning_proxy"] = df["duration_s"] * 120          # Rough planning tokens per second of duration
    df["classification_proxy"] = df["total_tokens"] - (df["get_message_proxy"] + df["planning_proxy"])
    df["classification_proxy"] = df["classification_proxy"].clip(lower=0)

    plot_df = df.melt(
        id_vars=["model", "limit"],
        value_vars=["get_message_proxy", "planning_proxy", "classification_proxy"],
        var_name="token_source",
        value_name="estimated_tokens"
    )
    plot_df["token_source"] = plot_df["token_source"].map({
        "get_message_proxy": "get_message (Body Transmission)",
        "planning_proxy": "Planning + Multi-turn Reasoning",
        "classification_proxy": "LLM Classification Work"
    })

    plt.figure(figsize=(11, 7))
    sns.barplot(data=plot_df, x="model", y="estimated_tokens", hue="token_source",
                palette=["#e74c3c", "#f39c12", "#3498db"])
    plt.title("Estimated Token Source Breakdown in SMART Mode\n(Proxy Analysis from Logs)", fontsize=14, pad=15)
    plt.ylabel("Estimated Tokens")
    plt.xlabel("Model")
    plt.legend(title="Token Source", bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.xticks(rotation=15)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "07_token_sources_breakdown.png")
    plt.close()


def main():
    print("Loading SMART benchmark analysis data...")
    df = load_data()
    print(f"Loaded {len(df)} completed runs.")

    print("Generating professional charts...")
    chart_1_heuristic_vs_llm(df)
    chart_2_token_scaling(df)
    chart_3_duration_by_model(df)
    chart_4_category_distribution(df)
    chart_5_tokens_per_email(df)
    chart_6_success_rate()
    chart_7_token_sources_proxy(df)

    print(f"\n✅ All 7 charts saved to: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()