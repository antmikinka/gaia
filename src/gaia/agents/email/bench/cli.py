# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
CLI entry point for the GAIA Email Triage Agent benchmark.

Usage:
    gaia email bench --mbox-path <path> [--mode heuristic|full] [--experiments N]
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
        "--experiments",
        "--iterations",
        dest="experiments",
        type=int,
        default=1,
        help="Number of benchmark experiments to run per model (for variance analysis). Alias: --iterations (deprecated).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Number of emails per processing batch. Each batch is sent as one LLM prompt. "
        "Does NOT limit total emails — see --limit for that.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum total emails to read from the MBOX file. After this cap, no more emails "
        "are processed regardless of batch size. Default 100; use 0 for no limit.",
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
    # --- Multi-model support ---
    parser.add_argument(
        "--models",
        action="append",
        default=None,
        help="Model IDs to benchmark sequentially (can be specified multiple times).",
    )
    parser.add_argument(
        "--experiments-per-model",
        "--iterations-per-model",
        dest="experiments_per_model",
        type=int,
        default=1,
        help="Number of experiments per model in multi-model benchmark. Alias: --iterations-per-model (deprecated).",
    )
    parser.add_argument(
        "--model-batch-sizes",
        type=str,
        default=None,
        help="Comma-separated model:batch_size pairs, e.g. 'model1:10,model2:20'.",
    )
    parser.add_argument(
        "--skip-cold-start",
        action="store_true",
        help="Skip the first (cold-start) iteration for each model in reports.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Abort on first model iteration failure instead of continuing.",
    )
    # --- ClawFlow integration ---
    parser.add_argument(
        "--clawflow",
        action="store_true",
        help="Run ClawFlow CLI after GAIA benchmark completes for comparison.",
    )
    parser.add_argument(
        "--clawflow-timeout",
        type=int,
        default=3600,
        help="Timeout in seconds for ClawFlow execution (default 3600).",
    )
    parser.add_argument(
        "--clawflow-workflow",
        type=str,
        default="inbox-zero-helper",
        help="ClawFlow workflow name (default 'inbox-zero-helper').",
    )
    parser.add_argument(
        "--clawflow-path",
        type=str,
        default=None,
        help="Explicit path to the clawflow binary or script.",
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
    is_cold_start: bool = False,
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

        run = _run_full_agent(
            mbox_path,
            model_id=model,
            base_url=_base_url,
            limit=limit,
            _batch_size=batch_size,
        )
        # Tag cold-start and framework info.
        run.is_cold_start = is_cold_start
        run.source_framework = "gaia"
        return run


def _parse_model_batch_sizes(arg: str | None) -> dict[str, int]:
    """Parse --model-batch-sizes into a dict of model -> batch_size."""
    if not arg:
        return {}
    sizes = {}
    for pair in arg.split(","):
        pair = pair.strip()
        if ":" in pair:
            model, size = pair.split(":", 1)
            try:
                sizes[model.strip()] = int(size.strip())
            except ValueError:
                pass
    return sizes


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
        from gaia.agents.email.bench.compare import (
            print_mode_comparison,
            save_mode_comparison,
        )

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

        # Multi-model variance report (if multiple models present).
        from gaia.agents.email.bench.variance import compare_runs_by_model

        by_model = compare_runs_by_model(runs)
        if len(by_model) > 1:
            for model_id, model_report in by_model.items():
                print(f"\n  --- Model: {model_id} ---")
                print_comparison_report(model_report)
            by_model_path = output_dir / "variance_by_model.json"
            with open(by_model_path, "w", encoding="utf-8") as f:
                json.dump(
                    {m: to_dict(r) for m, r in by_model.items()},
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            print(f"Per-model variance saved to: {by_model_path}")

        if args.visualize:
            from gaia.agents.email.bench.visualize import generate_charts

            generate_charts(
                jsonl_path=jsonl_path,
                output_dir=Path(args.chart_dir),
                multi_model_runs=runs if len(by_model) > 1 else None,
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
                        "reasoning_tokens": s.reasoning_tokens,
                        "total_tokens": s.total_tokens,
                        "duration_ms": s.duration_ms,
                        "time_to_first_token_ms": round(s.time_to_first_token_ms, 1),
                        "tokens_per_second": round(s.tokens_per_second, 1),
                    }
                    for s in t.step_results
                ],
                "tools_called": t.tools_called,
                "emails_affected": t.emails_affected,
                "duration_ms": t.duration_ms,
                "input_tokens": t.input_tokens,
                "output_tokens": t.output_tokens,
                "reasoning_tokens": t.reasoning_tokens,
                "time_to_first_token_ms": round(t.time_to_first_token_ms, 1),
                "tokens_per_second": round(t.tokens_per_second, 1),
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
            "total_reasoning_tokens": summary["total_reasoning_tokens"],
            "total_tokens": summary["total_tokens"],
            "avg_tokens_per_turn": summary["avg_tokens_per_turn"],
            "avg_duration_per_turn_ms": summary["avg_duration_per_turn_ms"],
            "avg_time_to_first_token_ms": summary.get("avg_time_to_first_token_ms", 0),
            "avg_tokens_per_second": summary.get("avg_tokens_per_second", 0),
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

    # --- Multi-model benchmark loop ---

    # Determine which models to run.
    # Priority: --models > --model (backwards compatible).
    if args.models:
        model_list = args.models
    else:
        model_list = [args.model]

    # Parse per-model batch sizes.
    batch_size_map = _parse_model_batch_sizes(args.model_batch_sizes)

    # Determine experiments: --experiments-per-model is primary (backwards compat via alias).
    exps = args.experiments_per_model
    if not args.models and args.experiments != 1:
        exps = args.experiments

    # Track all runs across all models.
    all_runs: list = []
    last_run = None
    last_iter_suffix = ""

    for model_id in model_list:
        batch_size = batch_size_map.get(model_id, args.batch_size)
        model_exps = exps

        print(f"\n{'='*70}")
        print(f"  Model: {model_id}")
        print(f"  Experiments: {model_exps}  |  Batch size: {batch_size}")
        print(f"{'='*70}")

        for i in range(1, model_exps + 1):
            is_first = i == 1
            cold_start_label = " [COLD START]" if is_first else ""
            print(f"\n  --- Experiment {i}/{model_exps}{cold_start_label} ---")
            try:
                result = _run_single_iteration(
                    args.mbox_path,
                    mode=args.mode,
                    batch_size=batch_size,
                    limit=args.limit,
                    model=model_id,
                    _base_url=args.base_url,
                    is_cold_start=is_first,
                )
                all_runs.append(result)
                last_run = result

                # Print human-readable summary.
                print_summary(result)

                # Save outputs for this iteration.
                model_safe = model_id.replace("/", "-")
                run_suffix = (
                    f"-{model_safe}-iter{i}" if len(model_list) > 1 or exps > 1 else ""
                )
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
                last_iter_suffix = run_suffix

            except Exception as exc:
                print(f"  Iteration {i} failed: {exc}")
                if args.fail_fast:
                    print("  --fail-fast: aborting.")
                    return 1
                if not all_runs:
                    return 1

        # Skip cold-start reporting: filter out the first run of this model.
        if args.skip_cold_start and exps > 1:
            from gaia.agents.email.bench.output import load_jsonl

            jsonl_path = output_dir / "results.jsonl"
            all_jsonl = load_jsonl(jsonl_path)
            # Find cold-start runs for this model and mark them as filtered.
            model_runs = [r for r in all_jsonl if r.get("model") == model_id]
            if model_runs and model_runs[0].get("is_cold_start"):
                print(f"  Excluding 1 cold-start run for {model_id} from analysis.")

    # --- Cross-run variance analysis (across all models and iterations) ---
    if len(all_runs) >= 2:
        from gaia.agents.email.bench.output import to_json as run_to_json

        run_dicts = [json.loads(run_to_json(r)) for r in all_runs]

        # Filter cold-start runs if requested.
        cold_start_filtered = 0
        if args.skip_cold_start:
            filtered_dicts = []
            for rd in run_dicts:
                if rd.get("is_cold_start"):
                    cold_start_filtered += 1
                else:
                    filtered_dicts.append(rd)
            if cold_start_filtered:
                print(
                    f"\n  Filtered {cold_start_filtered} cold-start run(s) from analysis."
                )
            run_dicts = filtered_dicts

        if len(run_dicts) < 2:
            print(
                f"\n  Only {len(run_dicts)} warm run(s) remaining after cold-start filter."
            )
            print("  Skipping variance analysis (need >= 2 warm runs).")
        else:
            report = compare_runs(run_dicts)
            print_comparison_report(report)

        # Per-model variance.
        from gaia.agents.email.bench.variance import compare_runs_by_model

        by_model = compare_runs_by_model(run_dicts)
        if len(by_model) > 1:
            by_model_path = output_dir / "variance_by_model.json"
            with open(by_model_path, "w", encoding="utf-8") as f:
                json.dump(
                    {m: to_dict(r) for m, r in by_model.items()},
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            print(f"Per-model variance saved to: {by_model_path}")

            # Statistical tests between model pairs.
            from gaia.agents.email.bench.variance import (
                bootstrap_ci,
                cliffs_delta,
                mann_whitney_u,
            )

            model_ids = sorted(by_model.keys())
            stats_path = output_dir / "statistical_tests.json"
            stats_report: dict[str, Any] = {}
            for i in range(len(model_ids)):
                for j in range(i + 1, len(model_ids)):
                    m_a = model_ids[i]
                    m_b = model_ids[j]
                    vals_a = [
                        r.get("total_duration_ms", 0)
                        for r in run_dicts
                        if r.get("model") == m_a
                    ]
                    vals_b = [
                        r.get("total_duration_ms", 0)
                        for r in run_dicts
                        if r.get("model") == m_b
                    ]
                    if len(vals_a) >= 2 and len(vals_b) >= 2:
                        u_stat, p_val = mann_whitney_u(vals_a, vals_b)
                        delta = cliffs_delta(vals_a, vals_b)
                        ci = bootstrap_ci(vals_a, vals_b)
                        key = f"{m_a} vs {m_b}"
                        stats_report[key] = {
                            "metric": "total_duration_ms",
                            "mann_whitney_u": round(u_stat, 4),
                            "p_value": round(p_val, 4),
                            "cliffs_delta": round(delta, 4),
                            "bootstrap_ci_95": list(ci),
                        }
                        print(f"\n  {key}:")
                        print(f"    Mann-Whitney U = {u_stat:.4f}, p = {p_val:.4f}")
                        print(f"    Cliff's delta  = {delta:.4f}")
                        print(
                            f"    Bootstrap 95% CI for mean diff = [{ci[0]}, {ci[1]}]"
                        )
            if stats_report:
                with open(stats_path, "w", encoding="utf-8") as f:
                    json.dump(stats_report, f, indent=2, ensure_ascii=False)
                print(f"  Statistical tests saved to: {stats_path}")

        # Save overall variance report.
        variance_path = output_dir / "variance.json"
        with open(variance_path, "w", encoding="utf-8") as f:
            json.dump(to_dict(report), f, indent=2, ensure_ascii=False)
        print(f"Variance report saved to: {variance_path}")

    # --- ClawFlow integration ---
    clawflow_result = None
    if args.clawflow:
        from gaia.agents.email.bench.clawflow_adapter import (
            parse_clawflow_output,
            probe_clawflow,
            run_clawflow,
        )

        probe = probe_clawflow(args.clawflow_path)
        if not probe["available"]:
            print(f"\n  ClawFlow not available: {probe.get('reason', 'unknown')}")
            print("  Skipping ClawFlow comparison. Install with:")
            print(
                f"    cd C:\\Users\\antmi\\openclaw-eval\\scripts\\agentic-framework-test"
            )
            print(f"    pip install -e .")
        else:
            print(f"\n  Running ClawFlow workflow '{args.clawflow_workflow}' ...")
            print(f"  Method: {probe['method']} | Path: {probe['path']}")
            print(f"  Timeout: {args.clawflow_timeout}s")

            try:
                clawflow_raw = run_clawflow(
                    workflow=args.clawflow_workflow,
                    model=model_list[-1] if model_list else None,
                    timeout=args.clawflow_timeout,
                    cli_path=args.clawflow_path,
                )
                clawflow_result = parse_clawflow_output(
                    clawflow_raw,
                    model_id=model_list[-1] if model_list else "unknown",
                    mbox_path=args.mbox_path,
                )

                # Save ClawFlow results.
                cf_json = output_dir / "clawflow_results.json"
                with open(cf_json, "w", encoding="utf-8") as f:
                    json.dump(clawflow_result, f, indent=2, ensure_ascii=False)
                print(f"  ClawFlow results saved to: {cf_json}")

                # Append ClawFlow result to results.jsonl for unified analysis.
                jsonl_path = output_dir / "results.jsonl"
                with open(jsonl_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(clawflow_result, ensure_ascii=False) + "\n")

                # Framework comparison.
                if last_run:
                    from gaia.agents.email.bench.compare import (
                        print_framework_comparison,
                        save_framework_comparison,
                    )

                    last_run_dict = json.loads(
                        (
                            lambda r: __import__("json").dumps(
                                {
                                    "run_id": r.run_id,
                                    "timestamp": r.timestamp,
                                    "model": r.model,
                                    "provider": r.provider,
                                    "mbox_path": r.mbox_path,
                                    "mode": r.mode,
                                    "total_emails": r.total_emails,
                                    "total_duration_ms": r.total_duration_ms,
                                    "total_input_tokens": r.total_input_tokens,
                                    "total_output_tokens": r.total_output_tokens,
                                    "total_tokens": r.total_tokens,
                                    "avg_time_to_first_token_ms": r.avg_time_to_first_token_ms,
                                    "avg_tokens_per_second": r.avg_tokens_per_second,
                                    "category_counts": r.category_counts,
                                    "batch_results": [
                                        {
                                            "batch_number": b.batch_number,
                                            "email_results": [
                                                {
                                                    "email_id": e.email_id,
                                                    "category": e.category,
                                                }
                                                for e in b.email_results
                                            ],
                                        }
                                        for b in r.batch_results
                                    ],
                                }
                            )
                        )(last_run)
                    )
                    print_framework_comparison(last_run_dict, clawflow_result)
                    fw_comp_path = output_dir / "framework_comparison.json"
                    from gaia.agents.email.bench.compare import compare_frameworks

                    save_framework_comparison(
                        compare_frameworks(last_run_dict, clawflow_result),
                        fw_comp_path,
                    )

            except Exception as exc:
                print(f"  ClawFlow execution failed: {exc}")
                if args.fail_fast:
                    return 1

    # --- Visualization ---
    if args.visualize:
        from gaia.agents.email.bench.visualize import generate_charts

        last_json = (
            output_dir / f"results{last_iter_suffix}.json" if last_iter_suffix else None
        )
        jsonl_file = output_dir / "results.jsonl"

        # Load multi-model runs for cross-model charts.
        multi_model_data = None
        if jsonl_file.exists():
            from gaia.agents.email.bench.output import load_jsonl

            multi_model_data = load_jsonl(jsonl_file)
            # Filter to only keep runs with model info.
            multi_model_data = [r for r in multi_model_data if r.get("model")]

        gaia_for_comparison = None
        if last_json and last_json.exists():
            with open(last_json, "r", encoding="utf-8") as f:
                gaia_for_comparison = json.load(f)

        generate_charts(
            json_path=last_json if last_json and last_json.exists() else None,
            jsonl_path=jsonl_file if jsonl_file.exists() else None,
            output_dir=Path(args.chart_dir),
            multi_model_runs=multi_model_data,
            clawflow_result=clawflow_result,
            gaia_result_for_comparison=gaia_for_comparison,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
