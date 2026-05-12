# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Script 2: ClawFlow Benchmark Runner.

Simple wrapper around clawflow_adapter.py: probe, run, parse, save JSON.
No GAIA integration, no framework comparison, no chart generation.

Usage:
    gaia email clawflow --workflow inbox-zero-helper --model A
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Optional


def _slug(text: str) -> str:
    """Filesystem-safe slug from a model name."""
    return re.sub(r"[^a-z0-9._-]", "_", text.lower()).strip("_")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gaia email clawflow",
        description="Run ClawFlow email triage benchmark. Outputs clawflow_results.json.",
    )
    parser.add_argument(
        "--workflow",
        type=str,
        default="inbox-zero-helper",
        help="ClawFlow workflow name.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model ID for ClawFlow.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="Timeout in seconds.",
    )
    parser.add_argument(
        "--cli-path",
        type=str,
        default=None,
        help="Explicit path to clawflow binary or script.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="benchmark_results",
        help="Directory to write output.",
    )
    parser.add_argument(
        "--mbox-path",
        type=str,
        default=None,
        help="MBOX path (recorded in output for report correlation).",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from gaia.agents.email.bench.clawflow_adapter import (
        parse_clawflow_output,
        probe_clawflow,
        run_clawflow,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Probe for ClawFlow availability.
    probe = probe_clawflow(args.cli_path)
    if not probe["available"]:
        print(f"ClawFlow not available: {probe.get('reason', 'unknown')}")
        print("Install with:")
        print(f"  cd C:\\Users\\antmi\\openclaw-eval\\scripts\\agentic-framework-test")
        print(f"  pip install -e .")
        return 1

    print(f"ClawFlow available: method={probe['method']}, path={probe['path']}")
    print(f"Running workflow: {args.workflow}")
    print(f"Model: {args.model or '(default)'}")
    print(f"Timeout: {args.timeout}s")

    try:
        clawflow_raw = run_clawflow(
            workflow=args.workflow,
            model=args.model,
            timeout=args.timeout,
            cli_path=args.cli_path,
        )

        clawflow_result = parse_clawflow_output(
            clawflow_raw,
            model_id=args.model or "unknown",
            mbox_path=args.mbox_path or "",
        )

        # Save ClawFlow results.
        model_slug = _slug(args.model or "unknown")
        cf_json = output_dir / f"clawflow_results_{model_slug}.json"
        with open(cf_json, "w", encoding="utf-8") as f:
            json.dump(clawflow_result, f, indent=2, ensure_ascii=False)
        print(f"ClawFlow results saved to: {cf_json}")

    except Exception as exc:
        print(f"ClawFlow execution failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
