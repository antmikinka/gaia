# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
CLI entry point for the GAIA Email Triage Agent benchmark.

Usage:
    gaia email bench --mbox-path <path> [--mode heuristic|full] [--iterations N]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from gaia.agents.email.bench.output import (
    print_summary,
    save_csv,
    save_json,
    save_jsonl,
)
from gaia.agents.email.bench.runner import run_heuristic_benchmark
from gaia.agents.email.bench.variance import (
    compare_runs,
    print_comparison_report,
    to_dict,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gaia email bench",
        description="Benchmark the GAIA Email Triage Agent against an MBOX file.",
    )
    parser.add_argument(
        "--mbox-path",
        required=True,
        help="Path to the MBOX file to benchmark against.",
    )
    parser.add_argument(
        "--mode",
        choices=["heuristic", "full", "interactive"],
        default="heuristic",
        help="Benchmark mode: 'heuristic' (fast, no LLM), 'full' (single LLM turn), or 'interactive' (multi-turn session).",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of benchmark iterations to run (for variance analysis).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Number of emails to process per batch.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of emails to process.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="heuristic-only",
        help="Model ID for full agent mode (e.g., 'Qwen3-5-Coder-4B-GGUF').",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="Base URL for the LLM server (full mode only). Defaults to LEMONADE_BASE_URL env or http://localhost:13305/api/v1.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="benchmark_results",
        help="Directory to write output files (CSV, JSON, JSONL).",
    )
    parser.add_argument(
        "--variance-only",
        action="store_true",
        help="Only run variance analysis on existing JSONL results, skip benchmark.",
    )
    parser.add_argument(
        "--jsonl-path",
        type=str,
        default=None,
        help="Path to JSONL file for variance-only mode (default: output-dir/results.jsonl).",
    )
    parser.add_argument(
        "--ground-truth",
        type=str,
        default=None,
        help="Path to ground truth JSON file for quality scoring.",
    )
    parser.add_argument(
        "--cost-per-1m-input",
        type=float,
        default=0.0,
        help="Cost per 1M input tokens (default 0 for local LLM).",
    )
    parser.add_argument(
        "--cost-per-1m-output",
        type=float,
        default=0.0,
        help="Cost per 1M output tokens (default 0 for local LLM).",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("HEURISTIC_JSON", "FULL_JSON"),
        help="Compare heuristic and full mode results. Pass paths to two JSON output files.",
    )
    parser.add_argument(
        "--steps",
        action="store_true",
        help="Print per-step token breakdown for full mode (LLM call-by-call).",
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Generate chart PNGs from benchmark output after the run completes.",
    )
    parser.add_argument(
        "--chart-dir",
        type=str,
        default="benchmark_charts",
        help="Directory to write chart PNGs (used with --visualize).",
    )
    return parser


def _run_single_iteration(
    mbox_path: str,
    *,
    mode: str,
    batch_size: int,
    limit: int,
    model: str,
    _base_url: str,
):
    """Run a single benchmark iteration."""
    if mode == "heuristic":
        return run_heuristic_benchmark(
            mbox_path,
            limit=limit,
            batch_size=batch_size,
            model=model,
        )
    else:
        from gaia.agents.email.bench.runner import _run_full_agent

        return _run_full_agent(
            mbox_path,
            model_id=model,
            base_url=_base_url,
            limit=limit,
            _batch_size=batch_size,
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load ground truth if provided.
    ground_truth: dict[str, Any] = {}
    if args.ground_truth:
        gt_path = Path(args.ground_truth)
        if gt_path.exists():
            with open(gt_path, "r", encoding="utf-8") as f:
                ground_truth = json.load(f)

    # Compare mode: diff heuristic vs full JSON results.
    if args.compare:
        from gaia.agents.email.bench.compare import print_mode_comparison, save_mode_comparison

        h_path = Path(args.compare[0])
        f_path = Path(args.compare[1])
        if not h_path.exists():
            print(f"Error: heuristic JSON not found: {h_path}")
            return 1
        if not f_path.exists():
            print(f"Error: full JSON not found: {f_path}")
            return 1

        with open(h_path, "r", encoding="utf-8") as fh:
            heuristic = json.load(fh)
        with open(f_path, "r", encoding="utf-8") as ff:
            full = json.load(ff)

        report = print_mode_comparison(heuristic, full)
        save_mode_comparison(report, output_dir / "comparison.json")
        return 0

    # Variance-only mode: load existing JSONL and compare.
    if args.variance_only:
        jsonl_path = (
            Path(args.jsonl_path) if args.jsonl_path else output_dir / "results.jsonl"
        )
        if not jsonl_path.exists():
            print(f"Error: JSONL file not found: {jsonl_path}")
            return 1

        from gaia.agents.email.bench.output import load_jsonl

        runs = load_jsonl(jsonl_path)
        if len(runs) < 2:
            print(f"Need at least 2 runs for variance analysis, found {len(runs)}.")
            return 1

        report = compare_runs(runs)
        print_comparison_report(report)

        # Save variance report.
        variance_path = output_dir / "variance.json"
        with open(variance_path, "w", encoding="utf-8") as f:
            json.dump(to_dict(report), f, indent=2, ensure_ascii=False)
        print(f"Variance report saved to: {variance_path}")

        if args.visualize:
            from gaia.agents.email.bench.visualize import generate_charts
            generate_charts(
                jsonl_path=jsonl_path,
                output_dir=Path(args.chart_dir),
            )

        return 0

    # Run benchmark iterations.
    from gaia.agents.email.bench.output import save_summary_csv

    # Interactive mode: single multi-turn session.
    if args.mode == "interactive":
        from gaia.agents.email.bench.runner import run_interactive_benchmark

        summary = run_interactive_benchmark(
            args.mbox_path,
            model_id=args.model,
            base_url=args.base_url,
            limit=args.limit,
        )

        # Save interactive results.
        interactive_path = output_dir / "interactive.json"
        interactive_path.parent.mkdir(parents=True, exist_ok=True)

        def _turn_to_dict(t):
            return {
                "turn_number": t.turn_number,
                "prompt": t.prompt,
                "step_results": [
                    {
                        "step_number": s.step_number,
                        "action": s.action,
                        "tool_name": s.tool_name,
                        "input_tokens": s.input_tokens,
                        "output_tokens": s.output_tokens,
                        "total_tokens": s.total_tokens,
                        "duration_ms": s.duration_ms,
                    }
                    for s in t.step_results
                ],
                "tools_called": t.tools_called,
                "emails_affected": t.emails_affected,
                "duration_ms": t.duration_ms,
                "input_tokens": t.input_tokens,
                "output_tokens": t.output_tokens,
                "total_tokens": t.total_tokens,
                "final_answer": t.final_answer,
                "status": t.status,
                "error": t.error,
            }

        output_data = {
            "run_id": summary["run_id"],
            "timestamp": summary["timestamp"],
            "model": summary["model"],
            "mbox_path": summary["mbox_path"],
            "total_turns": summary["total_turns"],
            "total_emails_affected": summary["total_emails_affected"],
            "total_tools_used": summary["total_tools_used"],
            "tools_used": summary["tools_used"],
            "total_duration_ms": summary["total_duration_ms"],
            "total_input_tokens": summary["total_input_tokens"],
            "total_output_tokens": summary["total_output_tokens"],
            "total_tokens": summary["total_tokens"],
            "avg_tokens_per_turn": summary["avg_tokens_per_turn"],
            "avg_duration_per_turn_ms": summary["avg_duration_per_turn_ms"],
            "turns": [_turn_to_dict(t) for t in summary["turns"]],
        }
        with open(interactive_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to: {interactive_path}")

        if args.visualize:
            from gaia.agents.email.bench.visualize import generate_charts
            generate_charts(
                interactive_path=interactive_path,
                output_dir=Path(args.chart_dir),
            )

        return 0

    all_runs = []
    for i in range(1, args.iterations + 1):
        print(f"\n--- Iteration {i}/{args.iterations} ---")
        try:
            result = _run_single_iteration(
                args.mbox_path,
                mode=args.mode,
                batch_size=args.batch_size,
                limit=args.limit,
                model=args.model,
                _base_url=args.base_url,
            )
            all_runs.append(result)

            # Print human-readable summary.
            print_summary(result)

            # Save outputs for this iteration.
            run_suffix = f"-iter{i}" if args.iterations > 1 else ""
            save_csv(result, output_dir / f"results{run_suffix}.csv")
            save_json(result, output_dir / f"results{run_suffix}.json")
            save_jsonl(result, output_dir / "results.jsonl")
            save_summary_csv(
                result,
                output_dir / f"summary{run_suffix}.csv",
                ground_truth=ground_truth,
                cost_per_1m_input=args.cost_per_1m_input,
                cost_per_1m_output=args.cost_per_1m_output,
            )

        except Exception as exc:
            print(f"Iteration {i} failed: {exc}")
            if not all_runs:
                return 1

    # Cross-run variance analysis (if multiple iterations).
    if len(all_runs) >= 2:
        from gaia.agents.email.bench.output import to_json as run_to_json

        run_dicts = [json.loads(run_to_json(r)) for r in all_runs]
        report = compare_runs(run_dicts)
        print_comparison_report(report)

        # Save variance report.
        variance_path = output_dir / "variance.json"
        with open(variance_path, "w", encoding="utf-8") as f:
            json.dump(to_dict(report), f, indent=2, ensure_ascii=False)
        print(f"Variance report saved to: {variance_path}")

    if args.visualize:
        from gaia.agents.email.bench.visualize import generate_charts

        jsonl_file = output_dir / "results.jsonl"
        last_iter_suffix = f"-iter{args.iterations}" if args.iterations > 1 else ""
        last_json = output_dir / f"results{last_iter_suffix}.json"
        generate_charts(
            json_path=last_json if last_json.exists() else None,
            jsonl_path=jsonl_file if jsonl_file.exists() else None,
            output_dir=Path(args.chart_dir),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
