# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Benchmark harness for the GAIA Email Triage Agent.

Produces CSV/JSON/JSONL output compatible with openclaw-eval's
inbox_zero benchmarks, with +/- variance analysis across runs.

Extended for multi-model support and cross-framework (GAIA vs ClawFlow) comparison.
"""

from gaia.agents.email.bench.clawflow_adapter import (
    normalize_categories,
    parse_clawflow_output,
    probe_clawflow,
    run_clawflow,
)
from gaia.agents.email.bench.compare import (
    FrameworkComparison,
    compare_frameworks,
    print_framework_comparison,
    save_framework_comparison,
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
    run_interactive_benchmark,
)
from gaia.agents.email.bench.variance import (
    ComparisonReport,
    VarianceSummary,
    bootstrap_ci,
    cliffs_delta,
    compare_runs,
    compare_runs_by_model,
    mann_whitney_u,
    to_dict,
)
from gaia.agents.email.bench.visualize import (
    generate_charts,
    plot_architecture_radar,
    plot_category_distribution,
    plot_category_stability,
    plot_cold_start_impact,
    plot_duration_vs_tokens,
    plot_email_duration_histogram,
    plot_framework_category_comparison,
    plot_interactive_heatmap,
    plot_interactive_turns,
    plot_model_duration_comparison,
    plot_model_token_cost,
    plot_per_model_variance_trend,
    plot_step_performance,
    plot_token_composition,
    plot_token_duration_scatter,
    plot_tps_comparison,
    plot_ttft_comparison,
    plot_variance_trend,
)

__all__ = [
    # Runner
    "BatchResult",
    "EmailResult",
    "RunResult",
    "StepResult",
    "TurnResult",
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
    "bootstrap_ci",
    "cliffs_delta",
    "compare_runs",
    "compare_runs_by_model",
    "mann_whitney_u",
    "to_dict",
    # Compare (GAIA vs ClawFlow only)
    "FrameworkComparison",
    "compare_frameworks",
    "print_framework_comparison",
    "save_framework_comparison",
    # Visualize
    "generate_charts",
    "plot_architecture_radar",
    "plot_category_distribution",
    "plot_category_stability",
    "plot_cold_start_impact",
    "plot_duration_vs_tokens",
    "plot_email_duration_histogram",
    "plot_framework_category_comparison",
    "plot_interactive_heatmap",
    "plot_interactive_turns",
    "plot_model_duration_comparison",
    "plot_model_token_cost",
    "plot_per_model_variance_trend",
    "plot_step_performance",
    "plot_token_composition",
    "plot_token_duration_scatter",
    "plot_ttft_comparison",
    "plot_tps_comparison",
    "plot_variance_trend",
    # ClawFlow adapter
    "normalize_categories",
    "parse_clawflow_output",
    "probe_clawflow",
    "run_clawflow",
]
