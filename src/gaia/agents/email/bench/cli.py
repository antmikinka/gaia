# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
CLI entry point for the GAIA Email Triage Agent benchmark.

Three independent subcommands:
    gaia email bench       -- Run GAIA benchmarks, produce results.jsonl
    gaia email clawflow    -- Run ClawFlow benchmarks, produce clawflow_results.json
    gaia email report      -- Generate reports from existing benchmark data

Usage:
    gaia email bench --mbox-path <path> --models A --models B --experiments-per-model 3
    gaia email clawflow --workflow inbox-zero-helper --model A
    gaia email report --input-dir benchmark_results --charts
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gaia email",
        description="GAIA Email Triage Agent benchmark tools.",
    )
    subparsers = parser.add_subparsers(dest="bench_action", required=True)

    # ------------------------------------------------------------------
    # Subcommand: bench (GAIA benchmark runner)
    # ------------------------------------------------------------------
    bench_parser = subparsers.add_parser(
        "bench",
        help="Run GAIA email triage benchmarks. Outputs results.jsonl.",
    )
    bench_parser.add_argument(
        "--mbox-path",
        type=str,
        default=None,
        help="Path to the MBOX file to benchmark against.",
    )
    bench_parser.add_argument(
        "--jsonl-path",
        type=str,
        default=None,
        help="Path to the JSONL file to benchmark against (mutually exclusive with --mbox-path).",
    )
    bench_parser.add_argument(
        "--mode",
        choices=["full", "interactive"],
        default="full",
        help="Benchmark mode: 'full' (single LLM turn), or 'interactive' (multi-turn session).",
    )
    bench_parser.add_argument(
        "--model",
        type=str,
        default="heuristic-only",
        help="Model ID for full agent mode (e.g., 'Qwen3-5-Coder-4B-GGUF').",
    )
    bench_parser.add_argument(
        "--models",
        action="append",
        default=None,
        help="Model IDs to benchmark sequentially (can be specified multiple times).",
    )
    bench_parser.add_argument(
        "--experiments-per-model",
        type=int,
        default=1,
        help="Number of experiments per model. Default 1.",
    )
    bench_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum total emails to read from MBOX. Default 100; 0 for no limit.",
    )
    bench_parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="Base URL for the LLM server (full mode only).",
    )
    bench_parser.add_argument(
        "--output-dir",
        type=str,
        default="benchmark_results",
        help="Directory to write results.jsonl. Default 'benchmark_results'.",
    )
    bench_parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Abort on first model experiment failure.",
    )
    bench_parser.add_argument(
        "--skip-cold-start",
        action="store_true",
        help="Mark first iteration as cold-start (tagged in JSONL for later filtering).",
    )
    bench_parser.add_argument(
        "--steps",
        action="store_true",
        help="Print per-step token breakdown for full mode.",
    )
    # Legacy flags (deprecated, print warning, delegate to report_generator).
    bench_parser.add_argument(
        "--variance-only",
        action="store_true",
        help="DEPRECATED: use 'gaia email report --input-dir <dir>' instead.",
    )
    bench_parser.add_argument(
        "--visualize",
        action="store_true",
        help="DEPRECATED: use 'gaia email report --charts --input-dir <dir>' instead.",
    )
    bench_parser.add_argument(
        "--ground-truth",
        type=str,
        default=None,
        help="Path to ground truth JSON for quality scoring (passed to report).",
    )
    bench_parser.add_argument(
        "--cost-per-1m-input",
        type=float,
        default=0.0,
        help="Cost per 1M input tokens.",
    )
    bench_parser.add_argument(
        "--cost-per-1m-output",
        type=float,
        default=0.0,
        help="Cost per 1M output tokens.",
    )
    bench_parser.add_argument(
        "--force-llm",
        action="store_true",
        help="Bypass heuristic fast-path; force LLM classification of every email.",
    )
    bench_parser.add_argument(
        "--batched",
        action="store_true",
        help="Run batched triage mode (full bodies, no truncation, batches of 5).",
    )
    bench_parser.add_argument(
        "--smart",
        action="store_true",
        help="Run smart triage mode: heuristic fast-path + selective LLM on uncertain emails.",
    )
    bench_parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Number of emails per batch (default 5). Used by --batched and --smart.",
    )

    # ------------------------------------------------------------------
    # Subcommand: clawflow (ClawFlow runner)
    # ------------------------------------------------------------------
    cf_parser = subparsers.add_parser(
        "clawflow",
        help="Run ClawFlow email triage benchmark. Outputs clawflow_results.json.",
    )
    cf_parser.add_argument(
        "--workflow",
        type=str,
        default="inbox-zero-helper",
        help="ClawFlow workflow name. Default 'inbox-zero-helper'.",
    )
    cf_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model ID to use for ClawFlow.",
    )
    cf_parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="Timeout in seconds for ClawFlow execution. Default 3600.",
    )
    cf_parser.add_argument(
        "--cli-path",
        type=str,
        default=None,
        help="Explicit path to the clawflow binary or script.",
    )
    cf_parser.add_argument(
        "--output-dir",
        type=str,
        default="benchmark_results",
        help="Directory to write clawflow_results.json. Default 'benchmark_results'.",
    )
    cf_parser.add_argument(
        "--mbox-path",
        type=str,
        default=None,
        help="MBOX path (recorded in output for report correlation).",
    )

    # ------------------------------------------------------------------
    # Subcommand: report (unified report generator)
    # ------------------------------------------------------------------
    rpt_parser = subparsers.add_parser(
        "report",
        help="Generate reports from existing benchmark data.",
    )
    rpt_parser.add_argument(
        "--input-dir",
        type=str,
        default="benchmark_results",
        help="Directory containing results.jsonl and optional clawflow_results.json.",
    )
    rpt_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to write report files. Defaults to --input-dir.",
    )
    rpt_parser.add_argument(
        "--charts",
        action="store_true",
        help="Generate chart PNGs in charts/ subdirectory.",
    )
    rpt_parser.add_argument(
        "--chart-dir",
        type=str,
        default=None,
        help="Directory for chart PNGs. Defaults to <input-dir>/charts.",
    )
    rpt_parser.add_argument(
        "--skip-cold-start",
        action="store_true",
        help="Exclude cold-start runs from variance analysis.",
    )
    rpt_parser.add_argument(
        "--ground-truth",
        type=str,
        default=None,
        help="Path to ground truth JSON for quality scoring.",
    )
    rpt_parser.add_argument(
        "--cost-per-1m-input",
        type=float,
        default=0.0,
        help="Cost per 1M input tokens.",
    )
    rpt_parser.add_argument(
        "--cost-per-1m-output",
        type=float,
        default=0.0,
        help="Cost per 1M output tokens.",
    )

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.bench_action == "bench":
        # Validate mutually exclusive data source args.
        if args.mbox_path and args.jsonl_path:
            print(
                "Error: --mbox-path and --jsonl-path are mutually exclusive.",
                file=sys.stderr,
            )
            return 1
        if not args.mbox_path and not args.jsonl_path:
            print(
                "Error: one of --mbox-path or --jsonl-path is required.",
                file=sys.stderr,
            )
            return 1

        # Check for legacy flags that should delegate to report_generator.
        if args.variance_only or args.visualize:
            _handle_legacy_delegations(args)

        # Warn about silently-ignored cost/quality flags on bench subcommand.
        if args.ground_truth or args.cost_per_1m_input or args.cost_per_1m_output:
            print(
                "WARNING: --ground-truth, --cost-per-1m-input, and --cost-per-1m-output "
                "are ignored by 'gaia email bench'. "
                "Pass them to 'gaia email report' instead.",
                file=sys.stderr,
            )

        from gaia.agents.email.bench.bench_runner import main as bench_main

        return bench_main(_build_bench_args(args))

    elif args.bench_action == "clawflow":
        from gaia.agents.email.bench.clawflow_runner import main as cf_main

        return cf_main(_build_clawflow_args(args))

    elif args.bench_action == "report":
        from gaia.agents.email.bench.report_generator import main as rpt_main

        return rpt_main(_build_report_args(args))

    return 0


def _handle_legacy_delegations(args) -> None:
    """Handle deprecated flags by delegating to report_generator."""
    import sys
    from pathlib import Path

    output_dir = Path(args.output_dir)

    if args.variance_only:
        print(
            "WARNING: --variance-only is deprecated. Use 'gaia email report --input-dir <dir>' instead.",
            file=sys.stderr,
        )
        jsonl_path = output_dir / "results.jsonl"
        if not jsonl_path.exists():
            print(f"Error: No results.jsonl found in {output_dir}", file=sys.stderr)
            sys.exit(1)

        from gaia.agents.email.bench.report_generator import generate_reports

        generate_reports(
            input_dir=output_dir,
            output_dir=output_dir,
            generate_charts=args.visualize,
        )
        sys.exit(0)

    if args.visualize and not args.variance_only:
        print(
            "WARNING: --visualize is deprecated. Use 'gaia email report --charts --input-dir <dir>' instead.",
            file=sys.stderr,
        )
        from gaia.agents.email.bench.report_generator import generate_reports

        generate_reports(
            input_dir=output_dir,
            output_dir=output_dir,
            generate_charts=True,
        )
        sys.exit(0)


def _build_bench_args(args) -> list[str]:
    """Convert argparse Namespace to argv list for bench_runner.main()."""
    bench_args = []
    if args.mbox_path:
        bench_args.extend(["--mbox-path", args.mbox_path])
    if args.jsonl_path:
        bench_args.extend(["--jsonl-path", args.jsonl_path])

    if args.mode != "heuristic":
        bench_args.extend(["--mode", args.mode])
    if args.model != "heuristic-only":
        bench_args.extend(["--model", args.model])
    if args.models:
        for m in args.models:
            bench_args.extend(["--models", m])
    if args.experiments_per_model != 1:
        bench_args.extend(["--experiments-per-model", str(args.experiments_per_model)])
    if args.limit != 100:
        bench_args.extend(["--limit", str(args.limit)])
    if args.base_url:
        bench_args.extend(["--base-url", args.base_url])
    if args.output_dir != "benchmark_results":
        bench_args.extend(["--output-dir", args.output_dir])
    if args.fail_fast:
        bench_args.append("--fail-fast")
    if args.skip_cold_start:
        bench_args.append("--skip-cold-start")
    if args.steps:
        bench_args.append("--steps")
    if args.force_llm:
        bench_args.append("--force-llm")
    if args.batched:
        bench_args.append("--batched")
    if args.smart:
        bench_args.append("--smart")
    if getattr(args, "batch_size", None) and args.batch_size != 5:
        bench_args.extend(["--batch-size", str(args.batch_size)])

    return bench_args


def _build_clawflow_args(args) -> list[str]:
    """Convert argparse Namespace to argv list for clawflow_runner.main()."""
    cf_args = []
    if args.workflow != "inbox-zero-helper":
        cf_args.extend(["--workflow", args.workflow])
    if args.model:
        cf_args.extend(["--model", args.model])
    if args.timeout != 3600:
        cf_args.extend(["--timeout", str(args.timeout)])
    if args.cli_path:
        cf_args.extend(["--cli-path", args.cli_path])
    if args.output_dir != "benchmark_results":
        cf_args.extend(["--output-dir", args.output_dir])
    if args.mbox_path:
        cf_args.extend(["--mbox-path", args.mbox_path])

    return cf_args


def _build_report_args(args) -> list[str]:
    """Convert argparse Namespace to argv list for report_generator.main()."""
    rpt_args = ["--input-dir", args.input_dir]

    if args.output_dir:
        rpt_args.extend(["--output-dir", args.output_dir])
    if args.charts:
        rpt_args.append("--charts")
    if args.chart_dir:
        rpt_args.extend(["--chart-dir", args.chart_dir])
    if args.skip_cold_start:
        rpt_args.append("--skip-cold-start")
    if args.ground_truth:
        rpt_args.extend(["--ground-truth", args.ground_truth])
    if args.cost_per_1m_input:
        rpt_args.extend(["--cost-per-1m-input", str(args.cost_per_1m_input)])
    if args.cost_per_1m_output:
        rpt_args.extend(["--cost-per-1m-output", str(args.cost_per_1m_output)])

    return rpt_args


if __name__ == "__main__":
    raise SystemExit(main())
