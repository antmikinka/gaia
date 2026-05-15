# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Trace extractor — converts ``process_query()`` result dicts (and their
JSON trace files) into structured ``RunResult`` / ``StepResult`` /
``EmailResult`` objects.

This module enables two workflows:
1. **Benchmark path:** ``_run_full_agent()`` calls ``extract_from_agent_result()``
   on the dict returned by ``agent.process_query()``.
2. **CLI trace path:** ``extract_from_trace_json()`` reads a ``--trace`` JSON
   file and produces the same ``RunResult`` — enabling post-hoc analysis
   of any agent run.

Both paths produce identical output formats for downstream consumers
(report generation, variance analysis, charting).
"""

from __future__ import annotations

import json
import re
from typing import Any

from gaia.agents.email.bench.data_shapes import (
    BatchResult,
    EmailResult,
    RunResult,
    StepResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_reasoning_tokens(text: str) -> int:
    """Estimate reasoning tokens from ``<thinking>`` blocks in assistant text.

    The Lemonade /stats endpoint does not report reasoning tokens separately.
    We approximate by counting characters inside ``<thinking>...</thinking>``
    blocks and using a 1 token ≈ 4 character ratio (standard BPE estimate).
    Returns 0 if no thinking blocks are found.
    """
    thinking_blocks = re.findall(r"<thinking>(.*?)</thinking>", text, re.DOTALL)
    if not thinking_blocks:
        return 0
    total_chars = sum(len(b.strip()) for b in thinking_blocks)
    return max(1, total_chars // 4)


def _last_assistant_text(conversation: list, stats_msg: dict) -> str:
    """Find the last assistant message before a system stats message."""
    try:
        idx = conversation.index(stats_msg)
    except ValueError:
        return ""
    for i in range(idx - 1, -1, -1):
        msg = conversation[i]
        if msg.get("role") == "assistant":
            text = msg.get("content", "")
            if isinstance(text, str):
                return text
            if isinstance(text, list):
                return "".join(b.get("text", "") for b in text if isinstance(b, dict))
    return ""


def _find_triage_results(conversation: list) -> tuple[list[dict], str]:
    """Walk conversation to find triage_inbox tool results.

    Returns (triage_results, tool_error).
    """
    for msg in conversation:
        if msg.get("role") != "tool" or not msg.get("content"):
            continue

        content = msg["content"]
        # Content can be a string, list of content blocks, or a dict
        # (when _handle_large_tool_result re-parses after truncation).
        if isinstance(content, dict):
            text = json.dumps(content)
        elif isinstance(content, list):
            text = "".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        elif isinstance(content, str):
            text = content
        else:
            continue

        try:
            envelope = json.loads(text)
            if envelope.get("ok") and "data" in envelope:
                data = envelope["data"]
                if "results" in data:
                    return data["results"], ""
            elif not envelope.get("ok") and "error" in envelope:
                return [], envelope["error"]
        except (json.JSONDecodeError, TypeError):
            continue

    return [], ""


def _extract_step_stats(
    conversation: list,
) -> tuple[list[StepResult], int]:
    """Extract per-step StepResult objects and total reasoning tokens.

    Returns (step_results, total_reasoning_tokens).
    """
    step_results: list[StepResult] = []
    step_num = 0
    total_reasoning_tokens = 0
    last_tool_name = ""

    for msg in conversation:
        role = msg.get("role", "")

        # Track tool names from role=="tool" messages.
        if role == "tool" and msg.get("name"):
            last_tool_name = msg["name"]

        # Reset tool name when we see an assistant message (new LLM call, no tool yet).
        if role == "assistant":
            last_tool_name = ""

        # Extract reasoning tokens from assistant response text.
        if role == "assistant":
            assistant_text = msg.get("content", "")
            if isinstance(assistant_text, str) and assistant_text:
                reasoning = _extract_reasoning_tokens(assistant_text)
                if reasoning > 0:
                    total_reasoning_tokens += reasoning

        # Extract per-step stats from system entries.
        if role == "system" and isinstance(msg.get("content"), dict):
            content = msg["content"]
            if content.get("type") == "stats" and "performance_stats" in content:
                stats = content["performance_stats"]
                step_num += 1
                raw_ttft = stats.get("time_to_first_token")
                ttft_ms = float(raw_ttft) * 1000 if raw_ttft else 0.0
                step_results.append(
                    StepResult(
                        step_number=step_num,
                        action="llm_call",
                        tool_name=last_tool_name,
                        input_tokens=stats.get("input_tokens", 0) or 0,
                        output_tokens=stats.get("output_tokens", 0) or 0,
                        reasoning_tokens=_extract_reasoning_tokens(
                            _last_assistant_text(conversation, msg)
                        ),
                        total_tokens=(
                            stats.get("total_tokens", 0)
                            or (stats.get("input_tokens", 0) or 0)
                            + (stats.get("output_tokens", 0) or 0)
                        ),
                        duration_ms=int(stats.get("duration", 0) * 1000),
                        time_to_first_token_ms=ttft_ms,
                        tokens_per_second=float(stats.get("tokens_per_second", 0) or 0),
                    )
                )

    return step_results, total_reasoning_tokens


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------


def extract_from_agent_result(
    agent_result: dict[str, Any],
    *,
    run_id: str,
    timestamp: str,
    model_id: str,
    mbox_path: str = "",
    jsonl_path: str = "",
    mode: str,
    total_duration_ms: int = 0,
    force_llm: bool = False,
) -> RunResult:
    """Extract structured ``RunResult`` from a ``process_query()`` result dict.

    This is the core function that converts the raw agent output (which
    ``--trace`` writes to JSON) into the structured benchmark format.

    Args:
        agent_result: The dict returned by ``agent.process_query()``.
        run_id: Unique run identifier.
        timestamp: ISO-8601 timestamp.
        model_id: Model identifier (e.g. ``Qwen3.5-4B-GGUF``).
        mbox_path: Path to the MBOX file used (empty if using JSONL).
        jsonl_path: Path to the JSONL file used (empty if using MBOX).
        mode: Benchmark mode (``"full"`` or ``"interactive"``).
        total_duration_ms: Wall-clock duration if available externally.
        force_llm: Whether heuristic fast-path was bypassed.

    Returns:
        A ``RunResult`` dataclass with all metrics extracted.
    """
    # Extract aggregated token counts from the agent result.
    input_tokens = agent_result.get("input_tokens", 0) or 0
    output_tokens = agent_result.get("output_tokens", 0) or 0
    total_tokens = agent_result.get("total_tokens", 0) or 0

    # Extract per-step stats and reasoning tokens.
    conversation = agent_result.get("conversation", [])
    step_results, total_reasoning_tokens = _extract_step_stats(conversation)

    # Extract triage results from the conversation.
    triage_results, tool_error = _find_triage_results(conversation)

    # If no triage results found and we have a tool error, use it.
    if not triage_results and tool_error:
        return RunResult(
            run_id=run_id,
            timestamp=timestamp,
            model=model_id,
            provider="lemonade",
            mbox_path=mbox_path,
            jsonl_path=jsonl_path,
            data_source="jsonl" if jsonl_path else "mbox",
            mode=mode,
            batch_results=[],
            step_results=step_results,
            total_emails=0,
            total_duration_ms=total_duration_ms,
            total_input_tokens=input_tokens,
            total_output_tokens=output_tokens,
            total_reasoning_tokens=total_reasoning_tokens,
            total_tokens=total_tokens,
            category_counts={},
            status="error",
            error=tool_error,
        )

    # Build per-email EmailResult objects from the triage output.
    email_results: list[EmailResult] = []
    category_counts: dict[str, int] = {}
    for item in triage_results:
        category = item.get("category", "")
        if category:
            category_counts[category] = category_counts.get(category, 0) + 1
        email_results.append(
            EmailResult(
                email_id=item.get("id", ""),
                subject=item.get("subject", ""),
                sender=item.get("from", ""),
                category=category,
                is_spam=item.get("is_spam", False),
                is_phishing=item.get("is_phishing", False),
                confident=item.get("confident", False),
                reason=item.get("rationale", ""),
                status="ok",
            )
        )

    # Compute TTFT and TPS averages across all steps.
    ttft_vals = [
        s.time_to_first_token_ms for s in step_results if s.time_to_first_token_ms > 0
    ]
    tps_vals = [s.tokens_per_second for s in step_results if s.tokens_per_second > 0]
    avg_ttft = sum(ttft_vals) / len(ttft_vals) if ttft_vals else 0.0
    avg_tps = sum(tps_vals) / len(tps_vals) if tps_vals else 0.0

    batch = BatchResult(
        batch_number=1,
        batch_size=len(email_results),
        total_batches=1,
        email_results=email_results,
        duration_ms=total_duration_ms,
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        total_reasoning_tokens=total_reasoning_tokens,
        total_tokens=total_tokens,
        avg_time_to_first_token_ms=round(avg_ttft, 1),
        avg_tokens_per_second=round(avg_tps, 1),
        categories=sorted(category_counts.keys()),
        status="completed" if email_results else "error",
        error=(
            "No triage results found in agent conversation" if not email_results else ""
        ),
    )

    return RunResult(
        run_id=run_id,
        timestamp=timestamp,
        model=model_id,
        provider="lemonade",
        mbox_path=mbox_path,
        jsonl_path=jsonl_path,
        data_source="jsonl" if jsonl_path else "mbox",
        mode=mode,
        batch_results=[batch],
        step_results=step_results,
        total_emails=len(email_results),
        total_duration_ms=total_duration_ms,
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        total_reasoning_tokens=total_reasoning_tokens,
        total_tokens=total_tokens,
        avg_time_to_first_token_ms=round(avg_ttft, 1),
        avg_tokens_per_second=round(avg_tps, 1),
        category_counts=category_counts,
        status="completed" if email_results else "error",
        error=(
            "No triage results found in agent conversation" if not email_results else ""
        ),
    )


def extract_from_trace_json(
    trace_path: str,
    *,
    run_id: str,
    timestamp: str,
    model_id: str,
    mbox_path: str = "",
    jsonl_path: str = "",
    mode: str,
    total_duration_ms: int = 0,
    force_llm: bool = False,
) -> RunResult:
    """Read a ``--trace`` JSON file and extract structured ``RunResult``.

    Convenience wrapper that loads the JSON file, then calls
    ``extract_from_agent_result()``.

    Args:
        trace_path: Path to the trace JSON file written by ``--trace``.
        **kwargs: Forwarded to ``extract_from_agent_result()``.

    Returns:
        A ``RunResult`` dataclass with all metrics extracted.
    """
    with open(trace_path, "r", encoding="utf-8") as f:
        agent_result = json.load(f)
    return extract_from_agent_result(
        agent_result,
        run_id=run_id,
        timestamp=timestamp,
        model_id=model_id,
        mbox_path=mbox_path,
        jsonl_path=jsonl_path,
        mode=mode,
        total_duration_ms=total_duration_ms,
        force_llm=force_llm,
    )
