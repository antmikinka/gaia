# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Benchmark harness for the GAIA Email Triage Agent.

Produces CSV/JSON/JSONL output compatible with openclaw-eval's
inbox_zero benchmarks, with +/- variance analysis across runs.
"""

from gaia.agents.email.bench.visualize import (
    generate_charts,
    plot_category_distribution,
    plot_category_stability,
    plot_duration_vs_tokens,
    plot_email_duration_histogram,
    plot_interactive_heatmap,
    plot_interactive_turns,
    plot_token_composition,
    plot_token_duration_scatter,
    plot_variance_trend,
)

__all__ = [
    "generate_charts",
    "plot_category_distribution",
    "plot_category_stability",
    "plot_duration_vs_tokens",
    "plot_email_duration_histogram",
    "plot_interactive_heatmap",
    "plot_interactive_turns",
    "plot_token_composition",
    "plot_token_duration_scatter",
    "plot_variance_trend",
]
