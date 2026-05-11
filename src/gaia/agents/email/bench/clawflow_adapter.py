# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
ClawFlow CLI adapter for the GAIA Email Triage benchmark.

Probe, invoke, and parse ClawFlow CLI results, mapping them into GAIA
benchmark data shapes for cross-framework comparison.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Known ClawFlow CLI executable name.
CLAWFLOW_CLI_NAME = "clawflow"

# Default path to the ClawFlow PowerShell runner (fallback if CLI not on PATH).
DEFAULT_CLAWFLOW_PS1 = Path(
    r"C:\Users\antmi\openclaw-eval\scripts\agentic-framework-test\run-tasks.ps1"
)

# ---------------------------------------------------------------------------
# Category mapping (mirrors output.py OPENCLAW_TO_GAIA)
# ---------------------------------------------------------------------------

CLAWFLOW_TO_GAIA: dict[str, str] = {
    "URGENT": "urgent",
    "NEEDS_RESPONSE": "actionable",
    "FYI": "informational",
    "PROMOTIONAL": "low priority",
}


def normalize_categories(categories: dict[str, int]) -> dict[str, int]:
    """Map ClawFlow/openclaw category keys to GAIA taxonomy."""
    result: dict[str, int] = {}
    for key, count in categories.items():
        gaia_key = CLAWFLOW_TO_GAIA.get(key.upper(), key.lower())
        result[gaia_key] = result.get(gaia_key, 0) + count
    return result


# ---------------------------------------------------------------------------
# Probe: is ClawFlow available?
# ---------------------------------------------------------------------------


def probe_clawflow(cli_path: str | None = None) -> dict[str, Any]:
    """Check whether the ClawFlow CLI is available on this machine.

    Args:
        cli_path: Optional explicit path to the ``clawflow`` binary/script.

    Returns:
        Dict with ``available`` (bool), ``method`` ("cli" | "ps1" | "none"),
        and ``path`` (str) indicating how ClawFlow can be invoked.
    """
    # 1. Check for explicit path.
    if cli_path:
        p = Path(cli_path)
        if p.is_file():
            return {"available": True, "method": "cli", "path": str(p)}
        # Maybe a directory? Check for clawflow inside.
        if (p / CLAWFLOW_CLI_NAME).is_file():
            return {
                "available": True,
                "method": "cli",
                "path": str(p / CLAWFLOW_CLI_NAME),
            }
        return {
            "available": False,
            "method": "none",
            "path": cli_path,
            "reason": "path not found",
        }

    # 2. Check for clawflow on PATH.
    found = shutil.which(CLAWFLOW_CLI_NAME)
    if found:
        return {"available": True, "method": "cli", "path": found}

    # 3. Check for PowerShell runner fallback.
    if DEFAULT_CLAWFLOW_PS1.is_file():
        return {"available": True, "method": "ps1", "path": str(DEFAULT_CLAWFLOW_PS1)}

    return {
        "available": False,
        "method": "none",
        "path": None,
        "reason": "clawflow not found",
    }


# ---------------------------------------------------------------------------
# Invoke: run ClawFlow via PowerShell subprocess
# ---------------------------------------------------------------------------


def run_clawflow(
    workflow: str = "inbox-zero-helper",
    *,
    model: str | None = None,
    mbox_path: str | None = None,
    timeout: int = 3600,
    quiet: bool = True,
    cli_path: str | None = None,
) -> dict[str, Any]:
    """Execute the ClawFlow CLI and capture JSON output.

    Args:
        workflow: ClawFlow workflow name (e.g. "inbox-zero-helper").
        model: Optional model ID override.
        mbox_path: Optional MBOX file path override.
        timeout: Maximum seconds to wait for ClawFlow to complete.
        quiet: Suppress ClawFlow progress output (only capture JSON).
        cli_path: Optional explicit path to the clawflow binary.

    Returns:
        Parsed JSON dict from ClawFlow (BenchmarkRun shape).

    Raises:
        RuntimeError: If ClawFlow is not available or the command fails.
    """
    probe = probe_clawflow(cli_path)
    if not probe["available"]:
        raise RuntimeError(
            f"ClawFlow CLI not found: {probe.get('reason', 'unknown')}. "
            "Install with: pip install -e <openclaw-eval path>"
        )

    # Build the command.
    cmd_parts: list[str] = []

    if probe["method"] == "ps1":
        # Use PowerShell to run the .ps1 script.
        ps1_path = probe["path"]
        cmd_parts = [
            "pwsh",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f'& "{ps1_path}" -Workflow "{workflow}" -Json',
        ]
    else:
        # Direct CLI invocation.
        cli_exe = probe["path"]
        cmd_parts = [cli_exe, "--workflow", workflow, "--json"]
        if quiet:
            cmd_parts.append("--quiet")
        if model:
            cmd_parts.extend(["--model", model])
        if mbox_path:
            cmd_parts.extend(["--mbox", mbox_path])

    # Execute.
    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ClawFlow workflow '{workflow}' timed out after {timeout}s")
    except FileNotFoundError:
        raise RuntimeError(
            f"Executable not found: {cmd_parts[0]}. " "Is PowerShell (pwsh) installed?"
        )

    duration_ms = int((time.monotonic() - start) * 1000)

    # Parse JSON from stdout.
    stdout = result.stdout.strip()
    if not stdout:
        # Sometimes ClawFlow writes JSON to stderr in error cases.
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"ClawFlow returned empty stdout (exit code {result.returncode}). "
            f"stderr: {stderr[:500]}"
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        # Try to find JSON in the output (ClawFlow may prepend progress text).
        json_start = stdout.find("{")
        if json_start >= 0:
            try:
                data = json.loads(stdout[json_start:])
            except json.JSONDecodeError:
                raise RuntimeError(
                    f"Failed to parse ClawFlow JSON output: {exc}. "
                    f"Raw stdout (first 500 chars): {stdout[:500]}"
                )
        else:
            raise RuntimeError(
                f"No JSON found in ClawFlow output. "
                f"Raw stdout (first 500 chars): {stdout[:500]}"
            )

    # Attach GAIA-specific metadata.
    data["_clawflow_duration_ms"] = duration_ms
    data["_clawflow_returncode"] = result.returncode
    data["_clawflow_stderr_preview"] = (
        result.stderr.strip()[:500] if result.stderr else ""
    )

    return data


# ---------------------------------------------------------------------------
# Parse: transform ClawFlow BenchmarkRun to GAIA RunResult dict shape
# ---------------------------------------------------------------------------


def parse_clawflow_output(
    clawflow_data: dict[str, Any],
    *,
    model_id: str = "unknown",
    mbox_path: str = "",
) -> dict[str, Any]:
    """Transform ClawFlow BenchmarkRun JSON into a GAIA-compatible run dict.

    The ClawFlow schema (v2.0) has a different shape than GAIA's RunResult.
    This function maps fields so that variance analysis and chart generation
    can treat both frameworks uniformly.

    Args:
        clawflow_data: Raw JSON dict from ClawFlow CLI.
        model_id: Model identifier to use in the result.
        mbox_path: MBOX file path for reference.

    Returns:
        Dict matching GAIA RunResult JSON shape.
    """
    summary = clawflow_data.get("summary", {})
    tasks = clawflow_data.get("tasks", [])

    # Aggregate token counts from summary (top-level).
    total_input_tokens = summary.get("total_tokens_in", 0)
    total_output_tokens = summary.get("total_tokens_out", 0)
    total_tokens = summary.get("total_tokens", 0)
    total_duration_ms = clawflow_data.get("duration_ms", 0)

    # Build batch results from task per_batch_metrics.
    batch_results = []
    category_counts: dict[str, int] = {}
    email_results_list = []
    batch_num = 0

    for task in tasks:
        per_batch = task.get("execution", {}).get("per_batch_metrics", [])
        if per_batch:
            for bm in per_batch:
                batch_num += 1
                # Normalize categories from ClawFlow taxonomy.
                raw_cats = bm.get("categories", "")
                task_cats = {}
                if raw_cats:
                    for cat in raw_cats.split(","):
                        cat = cat.strip()
                        if cat:
                            gaia_cat = CLAWFLOW_TO_GAIA.get(cat.upper(), cat.lower())
                            task_cats[gaia_cat] = task_cats.get(gaia_cat, 0) + 1

                batch_email_results = []
                # Extract per-email breakdown if available.
                per_item = task.get("execution", {}).get("per_item_breakdown", [])
                for item in per_item:
                    email_id = item.get("email_id", "")
                    subject = item.get("subject", "")
                    raw_cat = item.get("category", "")
                    gaia_cat = CLAWFLOW_TO_GAIA.get(raw_cat.upper(), raw_cat.lower())
                    if gaia_cat:
                        category_counts[gaia_cat] = category_counts.get(gaia_cat, 0) + 1
                    batch_email_results.append(
                        {
                            "email_id": email_id,
                            "subject": subject,
                            "category": gaia_cat,
                            "duration_ms": item.get("load_time_ms", 0),
                        }
                    )
                    email_results_list.append(batch_email_results[-1])

                batch_results.append(
                    {
                        "batch_number": batch_num,
                        "batch_size": bm.get("email_count", len(batch_email_results)),
                        "total_batches": bm.get("total_batches", len(per_batch)),
                        "duration_ms": bm.get("duration_ms", 0),
                        "total_input_tokens": bm.get("input_tokens", 0),
                        "total_output_tokens": bm.get("output_tokens", 0),
                        "total_tokens": bm.get("total_tokens", 0),
                        "categories": list(task_cats.keys()),
                        "status": bm.get("status", "unknown"),
                        "email_results": batch_email_results,
                    }
                )

    # If no per-batch metrics, fall back to task-level aggregation.
    if not batch_results and tasks:
        batch_num = 0
        for task in tasks:
            batch_num += 1
            perf = task.get("performance", {})
            outputs = task.get("outputs", {})

            # Try to extract emails from outputs.
            batch_email_results = []
            per_item = task.get("execution", {}).get("per_item_breakdown", [])
            for item in per_item:
                raw_cat = item.get("category", "")
                gaia_cat = CLAWFLOW_TO_GAIA.get(raw_cat.upper(), raw_cat.lower())
                if gaia_cat:
                    category_counts[gaia_cat] = category_counts.get(gaia_cat, 0) + 1
                batch_email_results.append(
                    {
                        "email_id": item.get("email_id", ""),
                        "subject": item.get("subject", ""),
                        "category": gaia_cat,
                        "duration_ms": item.get("load_time_ms", 0),
                    }
                )
                email_results_list.append(batch_email_results[-1])

            batch_results.append(
                {
                    "batch_number": batch_num,
                    "batch_size": len(batch_email_results),
                    "total_batches": len(tasks),
                    "duration_ms": perf.get("latency_ms", 0),
                    "total_input_tokens": perf.get("tokens_in", 0),
                    "total_output_tokens": perf.get("tokens_out", 0),
                    "total_tokens": perf.get("tokens_total", 0),
                    "categories": list(category_counts.keys()),
                    "status": (
                        "success"
                        if task.get("validation", {}).get("passed")
                        else "failed"
                    ),
                    "email_results": batch_email_results,
                }
            )

    # Compute averages from task-level performance metrics.
    ttft_vals = []
    tps_vals = []
    for task in tasks:
        perf = task.get("performance", {})
        ttft = perf.get("ttft_ms")
        if ttft:
            ttft_vals.append(float(ttft))
        tps = perf.get("tokens_per_second", 0)
        if tps:
            tps_vals.append(float(tps))

    avg_ttft = sum(ttft_vals) / len(ttft_vals) if ttft_vals else 0.0
    avg_tps = sum(tps_vals) / len(tps_vals) if tps_vals else 0.0

    # Build the GAIA-compatible run dict.
    run_id = clawflow_data.get(
        "run_id", f"clawflow-{model_id.replace('/', '-')}-{int(time.time())}"
    )
    timestamp = clawflow_data.get("timestamp_start", "")

    return {
        "run_id": run_id,
        "timestamp": timestamp,
        "model": model_id,
        "provider": clawflow_data.get("provider", "clawflow"),
        "mbox_path": mbox_path or clawflow_data.get("mbox_path", ""),
        "mode": "full",
        "total_emails": clawflow_data.get("mbox_email_count", len(email_results_list)),
        "total_duration_ms": total_duration_ms,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_reasoning_tokens": 0,  # ClawFlow doesn't expose reasoning tokens
        "total_tokens": total_tokens,
        "avg_time_to_first_token_ms": round(avg_ttft, 1),
        "avg_tokens_per_second": round(avg_tps, 1),
        "category_counts": category_counts,
        "status": "completed" if summary.get("failed_tasks", 0) == 0 else "partial",
        "error": "",
        "source_framework": "clawflow",
        "is_cold_start": False,
        "batch_results": batch_results,
        "step_results": [],  # ClawFlow doesn't expose per-step data in the same shape
        # Pass-through of original ClawFlow data for advanced analysis.
        "_clawflow_summary": summary,
        "_clawflow_tasks": len(tasks),
    }
