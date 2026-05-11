# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Benchmark harness for the GAIA Email Triage Agent.

Produces CSV/JSON/JSONL output compatible with openclaw-eval's
inbox_zero benchmarks, with +/- variance analysis across runs.
"""

from gaia.agents.email.bench.compare import (
    ModeComparison,
    compare_modes,
    print_mode_comparison,
    save_mode_comparison,
)
from gaia.agents.email.bench.output import (
    load_jsonl,
    print_summary,
    save_csv,
    save_json,
    save_jsonl,
    save_summary_csv,
    to_csv,
    to_json,
)
from gaia.agents.email.bench.runner import (
    BatchResult,
    EmailResult,
    RunResult,
    StepResult,
    TurnResult,
    run_heuristic_benchmark,
    run_interactive_benchmark,
)
from gaia.agents.email.bench.variance import (
    ComparisonReport,
    VarianceSummary,
    compare_runs,
    to_dict,
)
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
    # Runner
    "BatchResult",
    "EmailResult",
    "RunResult",
    "StepResult",
    "TurnResult",
    "run_heuristic_benchmark",
    "run_interactive_benchmark",
    # Output
    "load_jsonl",
    "print_summary",
    "save_csv",
    "save_json",
    "save_jsonl",
    "save_summary_csv",
    "to_csv",
    "to_json",
    # Variance
    "ComparisonReport",
    "VarianceSummary",
    "compare_runs",
    "to_dict",
    # Compare
    "ModeComparison",
    "compare_modes",
    "print_mode_comparison",
    "save_mode_comparison",
    # Visualize
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
