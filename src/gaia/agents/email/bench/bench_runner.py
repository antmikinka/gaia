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

from gaia.agents.email.bench.visualize import _extract_run_suffix


def _slug(text: str) -> str:
    """Filesystem-safe slug from a model name."""
    return re.sub(r"[^a-z0-9._-]", "_", text.lower()).strip("_")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gaia email bench",
        description="Run GAIA email triage benchmarks. Outputs results.jsonl.",
    )
    parser.add_argument("--mbox-path", type=str, default=None)
    parser.add_argument("--jsonl-path", type=str, default=None)
    parser.add_argument(
        "--mode",
        choices=["full", "interactive"],
        default="full",
    )
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--models", action="append", default=None)
    parser.add_argument("--experiments-per-model", type=int, default=1)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default="benchmark_results")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--skip-cold-start", action="store_true")
    parser.add_argument("--steps", action="store_true")
    parser.add_argument("--force-llm", action="store_true")
    parser.add_argument("--batched", action="store_true")
    parser.add_argument("--smart", action="store_true")
    parser.add_argument("--batch-size", type=int, default=5)
    return parser


def _write_generation_manifest(output_dir: Path, entry: dict) -> None:
    """Append a generation-tracking entry to _manifest.json.

    Each entry links run_id -> output files -> timestamp -> mode -> model,
    enabling cross-generation report lineage tracking.
    """
    manifest_path = output_dir / "_manifest.json"
    entries = []
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except (json.JSONDecodeError, IOError):
            entries = []
    entries.append(entry)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def _run_single_iteration(
    mbox_path: str = "",
    jsonl_path: str = "",
    *,
    limit: int,
    model: str,
    _base_url: str,
    is_cold_start: bool = False,
    force_llm: bool = False,
):
    """Run a single benchmark iteration."""
    from gaia.agents.email.bench.runner import _run_full_agent

    run = _run_full_agent(
        mbox_path=mbox_path,
        jsonl_path=jsonl_path,
        model_id=model,
        base_url=_base_url,
        limit=limit,
        force_llm=force_llm,
    )
    run.is_cold_start = is_cold_start
    run.source_framework = "gaia"
    return run


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Batched mode: full bodies, no truncation, batches of N.
    if args.batched:
        from gaia.agents.email.bench.runner import _run_batched_agent

        model = args.model or (args.models[0] if args.models else None)
        if not model:
            print("Error: --model or --models is required for batched mode.")
            return 1

        print(f"\n{'='*70}")
        print(f"  Batched Email Triage — {model}")
        print(f"{'='*70}")
        print(f"  Data:     {args.mbox_path or args.jsonl_path}")
        print(f"  Limit:    {args.limit} emails")
        print(
            f"  Batch:    {args.limit // args.batch_size + 1} batches of ~{args.batch_size} emails"
        )
        print(f"{'='*70}")

        try:
            result = _run_batched_agent(
                args.mbox_path or "",
                args.jsonl_path or "",
                model_id=model,
                base_url=args.base_url,
                max_steps=12,
                limit=args.limit,
                batch_size=args.batch_size,
            )

            if result.status == "error":
                print(f"\n  Error: {result.error}")
                return 1

            from gaia.agents.email.bench.output import save_jsonl

            run_suffix = _extract_run_suffix(result.run_id) if result.run_id else _slug(model)
            jsonl_path = output_dir / f"results_{run_suffix}_batched.jsonl"
            save_jsonl(result, jsonl_path)

            _write_generation_manifest(output_dir, {
                "run_id": result.run_id,
                "timestamp": result.timestamp,
                "model": model,
                "mode": "batched",
                "output_files": [str(jsonl_path.relative_to(output_dir))],
                "total_emails": result.total_emails,
                "total_tokens": result.total_tokens,
                "status": result.status,
            })

            print(f"\n  Results saved to: {jsonl_path}")
            return 0
        except Exception as exc:
            print(f"\n  Error: {exc}")
            return 1

    # Smart mode: heuristic fast-path + selective LLM batching.
    # When --mode interactive is also set, fall through to the interactive
    # handler below (which already wires enable_smart_mode=True).
    if args.smart and getattr(args, "mode", None) != "interactive":
        from gaia.agents.email.bench.runner import _run_smart_agent

        model = args.model or (args.models[0] if args.models else None)
        if not model:
            print("Error: --model or --models is required for smart mode.")
            return 1

        try:
            print(f"\n{'='*70}")
            print(f"  Smart Email Triage -- {model}")
            print(f"{'='*70}")
            print(f"  Data:     {args.mbox_path or args.jsonl_path}")
            print(f"  Limit:    {args.limit} emails")
            print(f"  Batch:    up to {args.batch_size} emails per LLM batch")
            print(f"{'='*70}")

            result = _run_smart_agent(
                args.mbox_path or "",
                args.jsonl_path or "",
                model_id=model,
                base_url=args.base_url,
                max_steps=12,
                limit=args.limit,
                batch_size=args.batch_size,
                force_llm=args.force_llm,
            )

            if result.status == "error":
                print(f"\n  Error: {result.error}")
                return 1

            from gaia.agents.email.bench.output import print_summary, save_jsonl

            run_suffix = _extract_run_suffix(result.run_id) if result.run_id else _slug(model)
            jsonl_path = output_dir / f"results_{run_suffix}_smart.jsonl"
            save_jsonl(result, jsonl_path)
            print_summary(result)

            _write_generation_manifest(output_dir, {
                "run_id": result.run_id,
                "timestamp": result.timestamp,
                "model": model,
                "mode": "smart",
                "output_files": [str(jsonl_path.relative_to(output_dir))],
                "total_emails": result.total_emails,
                "total_tokens": result.total_tokens,
                "heuristic_only": getattr(result, "heuristic_only_count", 0),
                "llm_escalated": getattr(result, "llm_processed_count", 0),
                "status": result.status,
            })

            print(f"\n  Results saved to: {jsonl_path}")
            return 0
        except Exception as exc:
            print(f"\n  Error: {exc}")
            return 1

    # Interactive mode: single multi-turn session (special case, one-shot).
    if args.mode == "interactive":
        from gaia.agents.email.bench.runner import run_interactive_session

        model = args.model or (args.models[0] if args.models else None)
        if not model:
            print("Error: --model or --models is required for interactive mode.")
            return 1

        summary = run_interactive_session(
            args.mbox_path or "",
            args.jsonl_path or "",
            model_id=model,
            base_url=args.base_url,
            limit=args.limit,
            force_llm=getattr(args, "force_llm", False),
            enable_smart_mode=getattr(args, "smart", False),
            batch_size=getattr(args, "batch_size", 5),
        )

        model_slug = _slug(model or "unknown")
        run_id_suffix = (
            _extract_run_suffix(summary["run_id"]) if summary.get("run_id") else None
        )
        filename = (
            f"interactive_{model_slug}_{run_id_suffix}.json"
            if run_id_suffix
            else f"interactive_{model_slug}.json"
        )
        interactive_path = output_dir / filename
        interactive_path.parent.mkdir(parents=True, exist_ok=True)

        def _turn_to_dict(t):
            d = {
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
            # Include per-turn smart-mode fields when present.
            if getattr(t, "heuristic_email_count", 0) or getattr(t, "llm_email_count", 0):
                d["heuristic_email_count"] = t.heuristic_email_count
                d["llm_email_count"] = t.llm_email_count
            if getattr(t, "context_compacted", False):
                d["context_compacted"] = True
            if getattr(t, "gate_decisions"):
                d["gate_decisions"] = t.gate_decisions
            return d

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
            "heuristic_triaged": summary.get("heuristic_triaged", {}),
            "llm_triaged": summary.get("llm_triaged", {}),
            "heuristic_only_count": summary.get("heuristic_only_count", 0),
            "llm_escalated_count": summary.get("llm_escalated_count", 0),
            "per_email_classification": [
                {
                    "email_id": eid,
                    "category": cat,
                    "confident": True,
                    "source": "heuristic",
                }
                for eid, cat in summary.get("heuristic_triaged", {}).items()
            ]
            + [
                {"email_id": eid, "category": cat, "confident": False, "source": "llm"}
                for eid, cat in summary.get("llm_triaged", {}).items()
            ],
            "turns": [_turn_to_dict(t) for t in summary["turns"]],
            "session_state": summary.get("session_state", {}),
            "heuristic_savings": summary.get("heuristic_savings", {}),
        }
        with open(interactive_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        _write_generation_manifest(output_dir, {
            "run_id": summary["run_id"],
            "timestamp": summary["timestamp"],
            "model": model,
            "mode": "interactive" + ("-smart" if getattr(args, "smart", False) else ""),
            "output_files": [str(interactive_path.relative_to(output_dir))],
            "total_turns": summary["total_turns"],
            "total_emails_affected": summary["total_emails_affected"],
            "total_tokens": summary["total_tokens"],
            "heuristic_triaged": len(summary.get("heuristic_triaged", {})),
            "llm_triaged": len(summary.get("llm_triaged", {})),
        })

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

    exps = args.experiments_per_model

    last_successful_model: str | None = None

    for model_id in model_list:
        model_exps = exps
        jsonl_path = output_dir / f"results_{_slug(model_id)}.jsonl"

        print(f"\n{'='*70}")
        print(f"  Model: {model_id}")
        print(f"  Experiments: {model_exps}  |  Emails: {args.limit}")
        print(f"{'='*70}")

        model_had_success = False
        for i in range(1, model_exps + 1):
            is_first = i == 1
            cold_start_label = " [COLD START]" if is_first else ""
            print(f"\n  --- Experiment {i}/{model_exps}{cold_start_label} ---")
            try:
                result = _run_single_iteration(
                    args.mbox_path or "",
                    args.jsonl_path or "",
                    limit=args.limit,
                    model=model_id,
                    _base_url=args.base_url,
                    is_cold_start=is_first,
                    force_llm=args.force_llm,
                )

                # Detect structured error results (model not found, etc.).
                if getattr(result, "status", None) == "error":
                    error_msg = getattr(result, "error", "unknown error")
                    print(f"  Experiment {i} failed: {error_msg}")
                    if args.fail_fast:
                        print("  --fail-fast: aborting.")
                        return 1
                    continue

                from gaia.agents.email.bench.output import print_summary, save_jsonl

                save_jsonl(result, jsonl_path)
                print_summary(result)

                # Per-run JSON file keyed by run_id for traceability.
                run_suffix = _extract_run_suffix(result.run_id) if result.run_id else f"exp{i}"
                per_run_path = output_dir / f"run_{run_suffix}.json"
                from gaia.agents.email.bench.output import _run_result_to_dict
                with open(per_run_path, "w", encoding="utf-8") as f:
                    json.dump(_run_result_to_dict(result), f, indent=2, ensure_ascii=False)

                _write_generation_manifest(output_dir, {
                    "run_id": result.run_id,
                    "timestamp": result.timestamp,
                    "model": model_id,
                    "experiment": i,
                    "mode": "full",
                    "output_files": [
                        str(jsonl_path.relative_to(output_dir)),
                        str(per_run_path.relative_to(output_dir)),
                    ],
                    "total_emails": result.total_emails,
                    "total_tokens": result.total_tokens,
                    "status": result.status,
                })

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
                error_run_id = f"error-{model_id}-{i}"
                error_record = {
                    "run_id": error_run_id,
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

                _write_generation_manifest(output_dir, {
                    "run_id": error_run_id,
                    "timestamp": "",
                    "model": model_id,
                    "experiment": i,
                    "mode": "full",
                    "output_files": [str(jsonl_path.relative_to(output_dir))],
                    "status": "error",
                    "error": str(exc),
                })
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
