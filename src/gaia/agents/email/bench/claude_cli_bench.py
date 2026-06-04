# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Claude CLI benchmark orchestrator for the GAIA Email Triage benchmark.

Runs email classification through the Claude CLI (``claude --bare``),
supports checkpointing, resume, and incremental JSONL output.

Usage (via gaia CLI):
    gaia email claude-cli --jsonl-path emails.jsonl --model sonnet
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from gaia.agents.email.bench.claude_prompt import build_classification_prompt
from gaia.agents.email.bench.claude_result_adapter import parse_claude_response
from gaia.agents.email.bench.data_shapes import (
    BatchResult,
    EmailResult,
    RunResult,
)
from gaia.agents.email.bench.output import print_summary, save_jsonl, load_jsonl

# Default Claude CLI command prefix.
_CLAUDE_CMD = ["claude", "--bare"]


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the ``gaia email claude-cli`` subcommand."""
    parser = argparse.ArgumentParser(
        prog="gaia email claude-cli",
        description="Run email classification benchmark via Claude CLI.",
    )
    parser.add_argument(
        "--jsonl-path",
        type=str,
        required=True,
        help="Path to the JSONL file containing emails to classify.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="sonnet",
        help="Claude model to use (default: sonnet).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of emails to process (default: all).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="benchmark_results",
        help="Directory to write results (default: benchmark_results).",
    )
    parser.add_argument(
        "--checkpoint-interval",
        type=int,
        default=25,
        help="Save checkpoint every N emails (default: 25).",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not resume from existing checkpoint.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Abort on first error.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds per email (default: 120).",
    )
    return parser


def _load_emails(jsonl_path: str, *, limit: int | None = None) -> list[dict]:
    """Load emails from a JSONL file.

    Each line is expected to be a JSON object with at least an ``id`` key.
    Maps the JSONL shape to the prompt builder shape.
    """
    path = Path(jsonl_path)
    if not path.exists():
        raise FileNotFoundError(f"Email JSONL not found: {jsonl_path}")

    emails = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue

            email = {
                "id": raw.get("id", raw.get("email_id", str(len(emails)))),
                "subject": raw.get("subject", ""),
                "sender": raw.get("sender", raw.get("from", "")),
                "date": raw.get("date", ""),
                "to": raw.get("to", ""),
                "cc": raw.get("cc", ""),
                "body": raw.get("body", raw.get("snippet", "")),
                "label_ids": raw.get("label_ids", []),
            }
            emails.append(email)
            if limit and len(emails) >= limit:
                break

    return emails


def _checkpoint_path(output_dir: Path, run_id: str) -> Path:
    """Return the checkpoint file path for a given run."""
    return output_dir / f".checkpoint_{run_id}.json"


def _save_checkpoint(
    checkpoint: dict[str, Any], path: Path, *, processed_count: int
) -> None:
    """Persist a checkpoint to disk."""
    checkpoint["processed_count"] = processed_count
    with open(path, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, indent=2, ensure_ascii=False)


def _load_checkpoint(path: Path) -> dict[str, Any] | None:
    """Load a checkpoint from disk. Returns None if not found or corrupt."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, IOError):
        return None


def _run_claude(
    prompt: str,
    model: str,
    *,
    timeout: int = 120,
) -> tuple[str, dict[str, Any], float, int]:
    """Invoke the Claude CLI and return (stdout_text, usage_dict, cost, elapsed_ms).

    The Claude CLI with ``--output-format json`` returns a JSON object
    with ``content`` and ``usage`` fields.
    """
    cmd = [
        "claude",
        "--bare",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--model",
        model,
        "--max-budget-usd",
        "5",
    ]

    start = time.monotonic()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    if result.returncode != 0:
        stderr_text = result.stderr.strip()[:500]
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, stderr_text
        )

    # Parse the JSON output from Claude CLI.
    output_text = result.stdout.strip()
    try:
        envelope = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Claude CLI output is not valid JSON: {exc}") from exc

    # Extract content text.
    # Claude CLI with --output-format json uses "result" for the text field,
    # but some CLI versions may use "content". Check both.
    content = ""
    for field_name in ["result", "content"]:
        content_block = envelope.get(field_name)
        if not content_block:
            continue
        if isinstance(content_block, list):
            for block in content_block:
                if block.get("type") == "text":
                    content += block.get("text", "")
        elif isinstance(content_block, str):
            content = content_block
            break  # Found raw text, use it directly.

    # Extract usage dict.
    usage = envelope.get("usage", {})

    # Compute cost from usage (if available).
    cost = 0.0
    if usage:
        input_tok = (
            usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
            + usage.get("input_tokens", 0)
        )
        output_tok = usage.get("output_tokens", 0)
        # Sonnet pricing: $3.00 / 1M input, $15.00 / 1M output.
        cost = (input_tok * 3.0 + output_tok * 15.0) / 1_000_000

    return content, usage, cost, elapsed_ms


def run_benchmark(args) -> int:
    """Execute the Claude CLI email classification benchmark.

    Returns:
        Exit code (0 = success, non-zero = failure).
    """
    # Load emails.
    try:
        emails = _load_emails(args.jsonl_path, limit=args.limit)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not emails:
        print("Error: No emails found to process.", file=sys.stderr)
        return 1

    print(f"Loaded {len(emails)} emails from {args.jsonl_path}")

    # Setup output directory and run metadata.
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = f"claude-cli-{args.model}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"

    # Checkpoint management.
    ckpt_path = _checkpoint_path(output_dir, run_id)
    checkpoint = {"run_id": run_id, "email_results": []}
    start_index = 0

    if not args.no_resume:
        existing = _load_checkpoint(ckpt_path)
        if existing:
            start_index = existing.get("processed_count", 0)
            checkpoint["email_results"] = existing.get("email_results", [])
            print(f"Resuming from checkpoint: {start_index}/{len(emails)} done")

    # Run classification loop.
    email_results: list[EmailResult] = checkpoint["email_results"]
    errors: list[str] = []
    total_cost = 0.0
    total_duration_ms = 0
    last_elapsed_ms = 0

    for idx in range(start_index, len(emails)):
        email = emails[idx]
        progress = f"[{idx + 1}/{len(emails)}]"
        print(f"{progress} Classifying: {email.get('subject', '(no subject)')[:60]}...", end=" ", flush=True)

        prompt = build_classification_prompt(email)

        try:
            content, usage, cost, last_elapsed_ms = _run_claude(prompt, args.model, timeout=args.timeout)
            duration_ms = last_elapsed_ms

            result = parse_claude_response(
                result_text=content,
                usage=usage,
                cost=cost,
                duration_ms=duration_ms,
                email_id=email["id"],
                subject=email["subject"],
                sender=email["sender"],
            )
            email_results.append(result)
            total_cost += cost
            total_duration_ms += duration_ms
            print(f"done ({result.category}, {duration_ms}ms, ${cost:.4f})")

        except subprocess.TimeoutExpired:
            err_msg = f"Timeout after {args.timeout}s"
            errors.append(f"{email['id']}: {err_msg}")
            email_results.append(
                EmailResult(
                    email_id=email["id"],
                    subject=email["subject"],
                    sender=email["sender"],
                    duration_ms=args.timeout * 1000,
                    status="timeout",
                    error=err_msg,
                )
            )
            print(f"TIMEOUT ({args.timeout}s)")
            if args.fail_fast:
                print("Aborting due to --fail-fast.", file=sys.stderr)
                break

        except subprocess.CalledProcessError as exc:
            err_msg = f"CLI exit {exc.returncode}: {exc.stderr or ''}"[:200]
            errors.append(f"{email['id']}: {err_msg}")
            email_results.append(
                EmailResult(
                    email_id=email["id"],
                    subject=email["subject"],
                    sender=email["sender"],
                    duration_ms=last_elapsed_ms,
                    status="error",
                    error=err_msg,
                )
            )
            print(f"ERROR: {err_msg}")
            if args.fail_fast:
                print("Aborting due to --fail-fast.", file=sys.stderr)
                break

        except Exception as exc:
            err_msg = str(exc)[:200]
            errors.append(f"{email['id']}: {err_msg}")
            email_results.append(
                EmailResult(
                    email_id=email["id"],
                    subject=email["subject"],
                    sender=email["sender"],
                    duration_ms=last_elapsed_ms,
                    status="error",
                    error=err_msg,
                )
            )
            print(f"ERROR: {err_msg}")
            if args.fail_fast:
                print("Aborting due to --fail-fast.", file=sys.stderr)
                break

        # Checkpoint periodically -- sync email_results into checkpoint.
        if (idx + 1 - start_index) % args.checkpoint_interval == 0:
            checkpoint["email_results"] = [
                {"email_id": r.email_id, "category": r.category, "status": r.status,
                 "duration_ms": r.duration_ms, "error": r.error}
                for r in email_results
            ]
            _save_checkpoint(checkpoint, ckpt_path, processed_count=idx + 1)

    # Build category counts.
    category_counts: dict[str, int] = {}
    for er in email_results:
        if er.category:
            category_counts[er.category] = category_counts.get(er.category, 0) + 1

    total_input = sum(er.input_tokens for er in email_results)
    total_output = sum(er.output_tokens for er in email_results)
    total_tokens = total_input + total_output
    n = max(len(email_results), 1)
    avg_ttft = (
        sum(er.time_to_first_token_ms for er in email_results if er.time_to_first_token_ms > 0) / n
    )
    avg_tps = (
        sum(er.tokens_per_second for er in email_results if er.tokens_per_second > 0) / n
    )

    # Build BatchResult.
    batch = BatchResult(
        batch_number=1,
        batch_size=len(email_results),
        total_batches=1,
        email_results=email_results,
        duration_ms=total_duration_ms,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_tokens=total_tokens,
        avg_time_to_first_token_ms=round(avg_ttft, 1),
        avg_tokens_per_second=round(avg_tps, 1),
        categories=sorted(category_counts.keys()),
        status="ok" if not errors else "partial",
        error="; ".join(errors[:5]) if errors else "",
    )

    # Build RunResult.
    run_result = RunResult(
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        model=args.model,
        provider="claude",
        jsonl_path=args.jsonl_path,
        data_source="jsonl",
        mode="batched",
        batch_results=[batch],
        total_emails=len(email_results),
        total_duration_ms=total_duration_ms,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_tokens=total_tokens,
        avg_time_to_first_token_ms=round(avg_ttft, 1),
        avg_tokens_per_second=round(avg_tps, 1),
        category_counts=category_counts,
        status="ok" if not errors else "partial",
        error="; ".join(errors) if errors else "",
        source_framework="claude_cli",
    )

    # Write outputs.
    jsonl_path = output_dir / f"results_claude_cli_{args.model}.jsonl"
    save_jsonl(run_result, jsonl_path)

    # Clean up checkpoint on successful completion.
    if ckpt_path.exists():
        ckpt_path.unlink()

    # Print summary.
    print_summary(run_result)
    print(f"Results saved to: {jsonl_path}")
    if errors:
        print(f"\n{len(errors)} error(s) occurred during processing.")

    return 0 if not errors else 1


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for ``gaia email claude-cli``."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_benchmark(args)


if __name__ == "__main__":
    raise SystemExit(main())
