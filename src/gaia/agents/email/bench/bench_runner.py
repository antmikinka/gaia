# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Script 1: GAIA Email Benchmark Runner.

Runs benchmarks across models and experiments, appending results to
a single results.jsonl file. No variance analysis, no charts, no ClawFlow.

Usage:
    gaia email bench --mbox-path <path> --models A --models B --experiments-per-model 3
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Optional


def _slug(text: str) -> str:
    """Filesystem-safe slug from a model name."""
    return re.sub(r"[^a-z0-9._-]", "_", text.lower()).strip("_")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gaia email bench",
        description="Run GAIA email triage benchmarks. Outputs results.jsonl.",
    )
    parser.add_argument("--mbox-path", required=True)
    parser.add_argument(
        "--mode",
        choices=["full", "interactive"],
        default="full",
    )
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--models", action="append", default=None)
    parser.add_argument("--experiments-per-model", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--model-batch-sizes", type=str, default=None)
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default="benchmark_results")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--skip-cold-start", action="store_true")
    parser.add_argument("--steps", action="store_true")
    return parser


def _parse_model_batch_sizes(arg: str | None) -> dict[str, int]:
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


def _run_single_iteration(
    mbox_path: str,
    *,
    batch_size: int,
    limit: int,
    model: str,
    _base_url: str,
    is_cold_start: bool = False,
):
    """Run a single benchmark iteration."""
    from gaia.agents.email.bench.runner import _run_full_agent

    run = _run_full_agent(
        mbox_path,
        model_id=model,
        base_url=_base_url,
        limit=limit,
        _batch_size=batch_size,
    )
    run.is_cold_start = is_cold_start
    run.source_framework = "gaia"
    return run


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Interactive mode: single multi-turn session (special case, one-shot).
    if args.mode == "interactive":
        from gaia.agents.email.bench.runner import run_interactive_benchmark

        summary = run_interactive_benchmark(
            args.mbox_path,
            model_id=args.model,
            base_url=args.base_url,
            limit=args.limit,
        )

        model_slug = _slug(args.model or "unknown")
        interactive_path = output_dir / f"interactive_{model_slug}.json"
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
        return 0

    # --- Multi-model benchmark loop ---

    if args.models:
        model_list = args.models
    elif args.model:
        model_list = [args.model]
    else:
        print("Error: --model or --models is required.")
        return 1

    batch_size_map = _parse_model_batch_sizes(args.model_batch_sizes)
    exps = args.experiments_per_model

    last_successful_model: str | None = None

    for model_id in model_list:
        batch_size = batch_size_map.get(model_id, args.batch_size)
        model_exps = exps
        jsonl_path = output_dir / f"results_{_slug(model_id)}.jsonl"

        print(f"\n{'='*70}")
        print(f"  Model: {model_id}")
        print(f"  Experiments: {model_exps}  |  Batch size: {batch_size}")
        print(f"{'='*70}")

        model_had_success = False
        for i in range(1, model_exps + 1):
            is_first = i == 1
            cold_start_label = " [COLD START]" if is_first else ""
            print(f"\n  --- Experiment {i}/{model_exps}{cold_start_label} ---")
            try:
                result = _run_single_iteration(
                    args.mbox_path,
                    batch_size=batch_size,
                    limit=args.limit,
                    model=model_id,
                    _base_url=args.base_url,
                    is_cold_start=is_first,
                )

                # Detect structured error results (model not found, etc.).
                if getattr(result, "status", None) == "error":
                    error_msg = getattr(result, "error", "unknown error")
                    print(f"  Experiment {i} failed: {error_msg}")
                    if args.fail_fast:
                        print("  --fail-fast: aborting.")
                        return 1
                    continue

                from gaia.agents.email.bench.output import save_jsonl, print_summary

                save_jsonl(result, jsonl_path)
                print_summary(result)

                if args.steps:
                    for s in result.step_results:
                        time_str = (
                            f"{s.duration_ms}ms"
                            if s.duration_ms < 1000
                            else f"{s.duration_ms/1000:.1f}s"
                        )
                        print(
                            f"    Step {s.step_number}: {s.input_tokens} in / "
                            f"{s.output_tokens} out / {s.reasoning_tokens} reasoning / "
                            f"{s.total_tokens} total / {time_str}"
                        )

                model_had_success = True
                last_successful_model = model_id

            except Exception as exc:
                print(f"  Iteration {i} failed: {exc}")
                error_record = {
                    "run_id": f"error-{model_id}-{i}",
                    "model": model_id,
                    "experiment": i,
                    "status": "error",
                    "total_emails": 0,
                    "total_duration_ms": 0,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_tokens": 0,
                    "error": str(exc),
                    "source_framework": "gaia",
                    "is_cold_start": is_first,
                }
                with open(jsonl_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(error_record, ensure_ascii=False) + "\n")
                if args.fail_fast:
                    print("  --fail-fast: aborting.")
                    return 1

        if not model_had_success and model_exps > 0:
            print(f"\n  WARNING: All {model_exps} experiment(s) for {model_id} failed.")
            if args.fail_fast:
                print("  --fail-fast: aborting.")
                return 1

    print(f"\n  All results appended to: {jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
