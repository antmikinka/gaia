# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Output formatters for the GAIA Email Triage Agent benchmark.

Produces CSV (matching openclaw-eval column layout), JSON (per-run
detail), and JSONL (append-only for iterative runs).
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from gaia.agents.email.bench.runner import (
    BatchResult,
    EmailResult,
    RunResult,
)

# ---------------------------------------------------------------------------
# Category mapping between GAIA and openclaw-eval taxonomies
# ---------------------------------------------------------------------------

GAIA_TO_OPENCLAW: dict[str, str] = {
    "urgent": "URGENT",
    "actionable": "NEEDS_RESPONSE",
    "informational": "FYI",
    "low priority": "PROMOTIONAL",
}

OPENCLAW_TO_GAIA: dict[str, str] = {v: k for k, v in GAIA_TO_OPENCLAW.items()}


def map_category(category: str, target: str = "openclaw") -> str:
    """Translate a category string between GAIA and openclaw taxonomies."""
    if target == "openclaw":
        return GAIA_TO_OPENCLAW.get(category, category.upper())
    return OPENCLAW_TO_GAIA.get(category, category.lower())


# ---------------------------------------------------------------------------
# CSV output — matches openclaw-eval column layout
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "run_id",
    "timestamp",
    "model",
    "source_framework",
    "provider",
    "mbox_path",
    "turn_number",
    "turn_type",
    "role",
    "input_text",
    "output_text",
    "tool_name",
    "tool_input",
    "tool_output",
    "turn_input_tokens",
    "turn_output_tokens",
    "turn_reasoning_tokens",
    "cumulative_input_tokens",
    "cumulative_output_tokens",
    "cumulative_reasoning_tokens",
    "total_input_tokens",
    "total_output_tokens",
    "total_reasoning_tokens",
    "total_tokens",
    "total_steps",
    "total_duration_ms",
    "emails_fetched",
    "categories_assigned",
    "final_response",
    "run_status",
    "batch_number",
    "batch_size",
    "batch_total_batches",
    # Extra GAIA-specific columns
    "email_id",
    "subject",
    "sender",
    "gaia_category",
    "openclaw_category",
    "is_spam",
    "is_phishing",
    "confident",
    "reason",
    "error",
    "duration_per_email_ms",
]


def _run_to_csv_rows(run: RunResult) -> list[dict[str, Any]]:
    """Convert a RunResult to a list of CSV row dicts.

    Produces one row per email, plus a summary row at the end.
    """
    rows = []
    cumulative_input = 0
    cumulative_output = 0

    for batch in run.batch_results:
        for email in batch.email_results:
            cumulative_input += email.input_tokens
            cumulative_output += email.output_tokens

            row = {
                "run_id": run.run_id,
                "timestamp": run.timestamp,
                "model": run.model,
                "source_framework": getattr(run, "source_framework", "gaia"),
                "provider": run.provider,
                "mbox_path": run.mbox_path,
                "turn_number": batch.batch_number,
                "turn_type": "batch_processing",
                "role": "assistant",
                "input_text": f"Batch {batch.batch_number}/{batch.total_batches}: {len(batch.email_results)} emails",
                "output_text": _build_output_summary(batch),
                "tool_name": "triage_inbox",
                "tool_input": f"max_messages={batch.batch_size}",
                "tool_output": f"{len(batch.email_results)} emails fetched, categories: {', '.join(batch.categories)}",
                "turn_input_tokens": email.input_tokens,
                "turn_output_tokens": email.output_tokens,
                "turn_reasoning_tokens": email.reasoning_tokens,
                "cumulative_input_tokens": cumulative_input,
                "cumulative_output_tokens": cumulative_output,
                "cumulative_reasoning_tokens": cumulative_input,  # reasoning is part of output
                "total_input_tokens": run.total_input_tokens,
                "total_output_tokens": run.total_output_tokens,
                "total_reasoning_tokens": run.total_reasoning_tokens,
                "total_tokens": run.total_tokens,
                "total_steps": 0,
                "total_duration_ms": run.total_duration_ms,
                "emails_fetched": run.total_emails,
                "categories_assigned": ", ".join(batch.categories),
                "final_response": _build_output_summary(batch),
                "run_status": run.status,
                "batch_number": batch.batch_number,
                "batch_size": batch.batch_size,
                "batch_total_batches": batch.total_batches,
                "email_id": email.email_id,
                "subject": _truncate(email.subject, 120),
                "sender": _truncate(email.sender, 80),
                "gaia_category": email.category,
                "openclaw_category": map_category(email.category, "openclaw"),
                "is_spam": email.is_spam,
                "is_phishing": email.is_phishing,
                "confident": email.confident,
                "reason": _truncate(email.reason, 200),
                "error": _truncate(email.error, 200),
                "duration_per_email_ms": email.duration_ms,
            }
            rows.append(row)

    # Summary row.
    rows.append(
        {
            "run_id": run.run_id,
            "timestamp": run.timestamp,
            "model": run.model,
            "source_framework": getattr(run, "source_framework", "gaia"),
            "provider": run.provider,
            "mbox_path": run.mbox_path,
            "turn_number": "SUMMARY",
            "turn_type": "run_summary",
            "role": "",
            "input_text": "",
            "output_text": "",
            "tool_name": "",
            "tool_input": "",
            "tool_output": "",
            "turn_input_tokens": run.total_input_tokens,
            "turn_output_tokens": run.total_output_tokens,
            "turn_reasoning_tokens": run.total_reasoning_tokens,
            "cumulative_input_tokens": run.total_input_tokens,
            "cumulative_output_tokens": run.total_output_tokens,
            "cumulative_reasoning_tokens": run.total_reasoning_tokens,
            "total_input_tokens": run.total_input_tokens,
            "total_output_tokens": run.total_output_tokens,
            "total_reasoning_tokens": run.total_reasoning_tokens,
            "total_tokens": run.total_tokens,
            "total_steps": 0,
            "total_duration_ms": run.total_duration_ms,
            "emails_fetched": run.total_emails,
            "categories_assigned": ", ".join(run.category_counts.keys()),
            "final_response": "",
            "run_status": run.status,
            "batch_number": "",
            "batch_size": run.total_emails,
            "batch_total_batches": len(run.batch_results),
            "email_id": "",
            "subject": "",
            "sender": "",
            "gaia_category": "",
            "openclaw_category": "",
            "is_spam": "",
            "is_phishing": "",
            "confident": "",
            "reason": "",
            "error": "",
            "duration_per_email_ms": run.total_duration_ms // max(run.total_emails, 1),
        }
    )

    return rows


def _build_output_summary(batch: BatchResult) -> str:
    """Build a concise category summary for a batch."""
    counts: dict[str, int] = {}
    for er in batch.email_results:
        if er.category:
            counts[er.category] = counts.get(er.category, 0) + 1
    parts = []
    for cat in sorted(counts.keys()):
        oc = map_category(cat, "openclaw")
        parts.append(f"{oc}: {counts[cat]}")
    return ", ".join(parts) if parts else "no categories assigned"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def to_csv(run: RunResult) -> str:
    """Serialize a RunResult to CSV text."""
    rows = _run_to_csv_rows(run)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def save_csv(run: RunResult, path: Path) -> Path:
    """Write a RunResult to a CSV file. Returns the written path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(to_csv(run))
    return path


# ---------------------------------------------------------------------------
# JSON output — per-run detail
# ---------------------------------------------------------------------------


def _email_result_to_dict(er: EmailResult) -> dict[str, Any]:
    return {
        "email_id": er.email_id,
        "subject": er.subject,
        "sender": er.sender,
        "label_ids": er.label_ids,
        "category": er.category,
        "openclaw_category": map_category(er.category, "openclaw"),
        "is_spam": er.is_spam,
        "is_phishing": er.is_phishing,
        "confident": er.confident,
        "reason": er.reason,
        "duration_ms": er.duration_ms,
        "input_tokens": er.input_tokens,
        "output_tokens": er.output_tokens,
        "reasoning_tokens": er.reasoning_tokens,
        "total_tokens": er.total_tokens,
        "time_to_first_token_ms": round(er.time_to_first_token_ms, 1),
        "tokens_per_second": round(er.tokens_per_second, 1),
        "status": er.status,
        "error": er.error,
    }


def _batch_result_to_dict(br: BatchResult) -> dict[str, Any]:
    return {
        "batch_number": br.batch_number,
        "batch_size": br.batch_size,
        "total_batches": br.total_batches,
        "duration_ms": br.duration_ms,
        "total_input_tokens": br.total_input_tokens,
        "total_output_tokens": br.total_output_tokens,
        "total_reasoning_tokens": br.total_reasoning_tokens,
        "total_tokens": br.total_tokens,
        "avg_time_to_first_token_ms": round(br.avg_time_to_first_token_ms, 1),
        "avg_tokens_per_second": round(br.avg_tokens_per_second, 1),
        "categories": br.categories,
        "openclaw_categories": [map_category(c, "openclaw") for c in br.categories],
        "status": br.status,
        "error": br.error,
        "email_results": [_email_result_to_dict(e) for e in br.email_results],
    }


def _run_result_to_dict(run: RunResult) -> dict[str, Any]:
    n = max(run.total_emails, 1)
    return {
        "run_id": run.run_id,
        "timestamp": run.timestamp,
        "model": run.model,
        "source_framework": getattr(run, "source_framework", "gaia"),
        "provider": run.provider,
        "mbox_path": run.mbox_path,
        "mode": run.mode,
        "total_emails": run.total_emails,
        "total_duration_ms": run.total_duration_ms,
        "avg_duration_per_email_ms": round(run.total_duration_ms / n, 1),
        "total_input_tokens": run.total_input_tokens,
        "total_output_tokens": run.total_output_tokens,
        "total_reasoning_tokens": run.total_reasoning_tokens,
        "total_tokens": run.total_tokens,
        "avg_input_tokens_per_email": round(run.total_input_tokens / n, 1),
        "avg_output_tokens_per_email": round(run.total_output_tokens / n, 1),
        "avg_reasoning_tokens_per_email": round(run.total_reasoning_tokens / n, 1),
        "avg_total_tokens_per_email": round(run.total_tokens / n, 1),
        "avg_time_to_first_token_ms": round(run.avg_time_to_first_token_ms, 1),
        "avg_tokens_per_second": round(run.avg_tokens_per_second, 1),
        "is_cold_start": getattr(run, "is_cold_start", False),
        "category_counts": run.category_counts,
        "openclaw_category_counts": {
            map_category(k, "openclaw"): v for k, v in run.category_counts.items()
        },
        "status": run.status,
        "error": run.error,
        "batch_results": [_batch_result_to_dict(b) for b in run.batch_results],
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
            for s in run.step_results
        ],
    }


def to_json(run: RunResult, *, indent: int = 2) -> str:
    """Serialize a RunResult to JSON."""
    return json.dumps(_run_result_to_dict(run), indent=indent, ensure_ascii=False)


def save_json(run: RunResult, path: Path) -> Path:
    """Write a RunResult to a JSON file. Returns the written path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_json(run))
    return path


# ---------------------------------------------------------------------------
# JSONL output — append-only for iterative runs
# ---------------------------------------------------------------------------


def save_jsonl(run: RunResult, path: Path) -> Path:
    """Append a RunResult to a JSONL file. Returns the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(_run_result_to_dict(run), ensure_ascii=False) + "\n")
    return path


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load all results from a JSONL file."""
    if not path.exists():
        return []
    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return results


# ---------------------------------------------------------------------------
# Human-readable summary
# ---------------------------------------------------------------------------


def print_summary(run: RunResult) -> None:
    """Print a human-readable summary to stdout."""
    w = max(len(k) for k in run.category_counts) if run.category_counts else 10
    print(f"\n{'='*70}")
    print(f"  GAIA Email Triage Benchmark — {run.mode.upper()} mode")
    print(f"{'='*70}")
    print(f"  Run ID:       {run.run_id}")
    print(f"  Model:        {run.model}")
    print(f"  Provider:     {run.provider}")
    print(f"  MBOX:         {run.mbox_path}")
    print(f"  Emails:       {run.total_emails}")
    print(f"  Duration:     {run.total_duration_ms/1000:.1f}s")
    if run.total_emails > 0:
        print(f"  Avg/email:    {run.total_duration_ms // max(run.total_emails, 1)}ms")
    if run.mode == "heuristic":
        print("  Tokens:     N/A (heuristic)")
    elif run.mode == "smart":
        heuristic = getattr(run, "heuristic_only_count", 0)
        llm = getattr(run, "llm_processed_count", 0)
        print(f"  Heuristic:  {heuristic} emails (zero LLM cost)")
        print(f"  LLM:        {llm} emails")
        if run.total_tokens > 0:
            print(f"  Total tokens: {run.total_tokens:,}")
            print(f"    Input:      {run.total_input_tokens:,}")
            print(f"    Output:     {run.total_output_tokens:,}")
            print(f"    Reasoning:  {run.total_reasoning_tokens:,}")
        else:
            print("  Tokens:     0 (all heuristic)")
    else:
        print(f"  Total tokens: {run.total_tokens:,}")
        print(f"    Input:      {run.total_input_tokens:,}")
        print(f"    Output:     {run.total_output_tokens:,}")
        print(f"    Reasoning:  {run.total_reasoning_tokens:,}")
        # Per-step breakdown for full mode.
        if run.step_results:
            print(f"\n  Per-Step Token Breakdown:")
            print(f"  {'─'*78}")
            print(
                f"  {'Step':<6}  {'Action':<12}  {'Input':>8}  {'Output':>8}  {'Reason':>8}  {'Total':>8}  {'Time':>8}"
            )
            print(f"  {'─'*78}")
            for s in run.step_results:
                time_str = (
                    f"{s.duration_ms}ms"
                    if s.duration_ms < 1000
                    else f"{s.duration_ms/1000:.1f}s"
                )
                print(
                    f"    {s.step_number:<4}  {s.action:<12}  {s.input_tokens:>8}  "
                    f"{s.output_tokens:>8}  {s.reasoning_tokens:>8}  {s.total_tokens:>8}  {time_str:>8}"
                )
            print(f"  {'─'*78}")
        # Performance metrics.
        if run.avg_time_to_first_token_ms > 0 or run.avg_tokens_per_second > 0:
            print(f"\n  Performance:")
            if run.avg_time_to_first_token_ms > 0:
                print(f"    Avg TTFT:    {run.avg_time_to_first_token_ms:.0f}ms")
            if run.avg_tokens_per_second > 0:
                print(f"    Avg TPS:     {run.avg_tokens_per_second:.1f} tokens/s")
    print(f"  Status:       {run.status}")

    if run.category_counts:
        print("\n  Category Distribution:")
        for cat, count in sorted(run.category_counts.items()):
            oc = map_category(cat, "openclaw")
            pct = count / max(run.total_emails, 1) * 100
            print(f"    {cat:<{w}} ({oc:<15s}): {count:>4} ({pct:.1f}%)")

    print(f"{'='*70}\n")


# ---------------------------------------------------------------------------
# Summary spreadsheet CSV — matches "Email Triage Bench.csv" layout
# ---------------------------------------------------------------------------

SUMMARY_CSV_COLUMNS = [
    "",  # empty A column
    "",  # empty B column
    "GAIA",
    "GAIA",
]

SUMMARY_ROW_DEFS = [
    ("Email Triage", "", "Agent", "Agent"),
    ("Model Type", "", "{provider}", "{provider}"),
    ("Model", "", "{model}", "{model}"),
    ("Agent/Workflow", "", "Email Triage Agent", "Email Triage Agent"),
    ("", "", "", ""),
    ("Emails Per Turn", "", "{batch_size}", "{batch_size}"),
    ("Cost Per Turn", "", "{cost_per_turn}", "{cost_per_turn}"),
    ("Avg Input Tokens Per Turn", "", "{avg_input_tokens}", "{avg_input_tokens}"),
    ("Avg Output Tokens Per Turn", "", "{avg_output_tokens}", "{avg_output_tokens}"),
    (
        "Avg Reasoning Tokens Per Turn",
        "",
        "{avg_reasoning_tokens}",
        "{avg_reasoning_tokens}",
    ),
    (
        "Avg Time Per Batch (mins)",
        "",
        "{avg_time_per_batch_mins}",
        "{avg_time_per_batch_mins}",
    ),
    ("Quality Per Turn", "", "{quality_per_turn}", "{quality_per_turn}"),
    ("", "", "", ""),
    ("Total Email Amount", "", "{total_emails}", "{total_emails}"),
    ("Total Cost", "", "{total_cost}", "{total_cost}"),
    ("Total Input Tokens", "", "{total_input_tokens}", "{total_input_tokens}"),
    ("Total Output Tokens", "", "{total_output_tokens}", "{total_output_tokens}"),
    (
        "Total Reasoning Tokens",
        "",
        "{total_reasoning_tokens}",
        "{total_reasoning_tokens}",
    ),
    ("Total Time (mins)", "", "{total_time_mins}", "{total_time_mins}"),
    ("Total Quality", "", "{total_quality}", "{total_quality}"),
]


def _compute_quality(run: RunResult, ground_truth: dict[str, Any]) -> float:
    """Compute classification accuracy against ground truth.

    Returns a score 0.0–1.0 based on category agreement.
    """
    if not ground_truth or not run.total_emails:
        return 0.0

    gt_categories = {}
    for email_id, gt_entry in ground_truth.items():
        if isinstance(gt_entry, dict) and "category" in gt_entry:
            gt_categories[email_id] = gt_entry["category"]

    if not gt_categories:
        return 0.0

    correct = 0
    total = 0
    for batch in run.batch_results:
        for email in batch.email_results:
            if email.email_id in gt_categories:
                total += 1
                if email.category == gt_categories[email.email_id]:
                    correct += 1

    return round(correct / max(total, 1), 4)


# Default cost per 1M tokens for Lemonade local models (essentially $0).
# Override via --cost-per-1m-tokens if using a paid API.
DEFAULT_COST_PER_1M_INPUT = 0.0
DEFAULT_COST_PER_1M_OUTPUT = 0.0


def _compute_cost(
    run: RunResult,
    *,
    cost_per_1m_input: float = DEFAULT_COST_PER_1M_INPUT,
    cost_per_1m_output: float = DEFAULT_COST_PER_1M_OUTPUT,
) -> float:
    """Compute estimated cost for the run."""
    input_cost = run.total_input_tokens * cost_per_1m_input / 1_000_000
    output_cost = run.total_output_tokens * cost_per_1m_output / 1_000_000
    return round(input_cost + output_cost, 6)


def to_summary_csv(
    run: RunResult,
    *,
    ground_truth: dict[str, Any] | None = None,
    cost_per_1m_input: float = DEFAULT_COST_PER_1M_INPUT,
    cost_per_1m_output: float = DEFAULT_COST_PER_1M_OUTPUT,
) -> str:
    """Produce a summary-style spreadsheet CSV matching "Email Triage Bench.csv".

    Two-column layout: Metric name | GAIA value (repeated for side-by-side).
    """
    quality = _compute_quality(run, ground_truth or {})
    cost = _compute_cost(
        run, cost_per_1m_input=cost_per_1m_input, cost_per_1m_output=cost_per_1m_output
    )

    batch_size = run.batch_results[0].batch_size if run.batch_results else 0
    num_batches = len(run.batch_results)
    total_time_mins = (
        round(run.total_duration_ms / 60_000, 2) if run.total_duration_ms else 0
    )
    avg_time_per_batch_mins = round(total_time_mins / max(num_batches, 1), 2)
    avg_input_tokens = (
        round(run.total_input_tokens / max(num_batches, 1), 0)
        if run.total_input_tokens
        else 0
    )
    avg_output_tokens = (
        round(run.total_output_tokens / max(num_batches, 1), 0)
        if run.total_output_tokens
        else 0
    )
    avg_reasoning_tokens = (
        round(run.total_reasoning_tokens / max(num_batches, 1), 0)
        if run.total_reasoning_tokens
        else 0
    )

    fmt = {
        "provider": run.provider,
        "model": run.model,
        "batch_size": batch_size,
        "cost_per_turn": f"${cost:.4f}" if cost > 0 else "$0.00",
        "avg_input_tokens": int(avg_input_tokens),
        "avg_output_tokens": int(avg_output_tokens),
        "avg_reasoning_tokens": int(avg_reasoning_tokens),
        "avg_time_per_batch_mins": avg_time_per_batch_mins,
        "quality_per_turn": f"{quality:.2%}" if quality > 0 else "N/A",
        "total_emails": run.total_emails,
        "total_cost": f"${cost:.4f}" if cost > 0 else "$0.00",
        "total_input_tokens": run.total_input_tokens,
        "total_output_tokens": run.total_output_tokens,
        "total_reasoning_tokens": run.total_reasoning_tokens,
        "total_time_mins": total_time_mins,
        "total_quality": f"{quality:.2%}" if quality > 0 else "N/A",
    }

    rows = [SUMMARY_CSV_COLUMNS[:]]  # header
    for row_def in SUMMARY_ROW_DEFS:
        label, _, col_c, col_d = row_def
        row = [
            label,
            "",
            col_c.format(**fmt) if "{" in col_c else col_c,
            col_d.format(**fmt) if "{" in col_d else col_d,
        ]
        rows.append(row)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    return buf.getvalue()


def save_summary_csv(
    run: RunResult,
    path: Path,
    *,
    ground_truth: dict[str, Any] | None = None,
    cost_per_1m_input: float = DEFAULT_COST_PER_1M_INPUT,
    cost_per_1m_output: float = DEFAULT_COST_PER_1M_OUTPUT,
) -> Path:
    """Write a summary spreadsheet CSV. Returns the written path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    csv_text = to_summary_csv(
        run,
        ground_truth=ground_truth,
        cost_per_1m_input=cost_per_1m_input,
        cost_per_1m_output=cost_per_1m_output,
    )
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(csv_text)
    return path
