# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Core benchmark runner for the GAIA Email Triage Agent.

Supports two modes:
- ``heuristic`` — Fast path, no LLM. Classifies each email via the
  pre-processing heuristic pipeline.
- ``full`` — End-to-end. Instantiates ``EmailTriageAgent`` with
  ``FakeGmailBackend`` injected, calls ``triage_inbox``, and captures
  token/duration metrics from the LLM round-trips.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from gaia.agents.email.tools.triage_heuristics import (
    classify_category_heuristic,
)

# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    """Single step in the agent loop with its token/duration cost."""

    step_number: int
    action: str  # "llm_call", "planning", "final_answer"
    tool_name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0  # tokens in <thinking> blocks (estimated)
    total_tokens: int = 0
    duration_ms: int = 0
    time_to_first_token_ms: float = 0.0  # TTFT: time from prompt send to first token
    tokens_per_second: float = 0.0  # TPS: inference throughput
    status: str = "ok"


@dataclass
class TurnResult:
    """Single turn in an interactive benchmark session."""

    turn_number: int
    prompt: str
    step_results: list[StepResult] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    emails_affected: list[str] = field(default_factory=list)
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    time_to_first_token_ms: float = 0.0
    tokens_per_second: float = 0.0
    final_answer: str = ""
    status: str = "ok"
    error: str = ""


@dataclass
class EmailResult:
    """Result of classifying a single email."""

    email_id: str
    subject: str
    sender: str
    label_ids: list[str] = field(default_factory=list)
    category: str = ""
    is_spam: bool = False
    is_phishing: bool = False
    confident: bool = False
    reason: str = ""
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    time_to_first_token_ms: float = 0.0
    tokens_per_second: float = 0.0
    status: str = "ok"
    error: str = ""


@dataclass
class BatchResult:
    """Result of processing one batch of emails."""

    batch_number: int
    batch_size: int
    total_batches: int
    email_results: list[EmailResult] = field(default_factory=list)
    duration_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_tokens: int = 0
    avg_time_to_first_token_ms: float = 0.0
    avg_tokens_per_second: float = 0.0
    categories: list[str] = field(default_factory=list)
    status: str = "ok"
    error: str = ""


@dataclass
class RunResult:
    """Result of a complete benchmark run."""

    run_id: str
    timestamp: str
    model: str
    provider: str
    mbox_path: str
    mode: str  # "heuristic" | "full"
    batch_results: list[BatchResult] = field(default_factory=list)
    step_results: list[StepResult] = field(default_factory=list)
    total_emails: int = 0
    total_duration_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_tokens: int = 0
    avg_time_to_first_token_ms: float = 0.0
    avg_tokens_per_second: float = 0.0
    category_counts: dict[str, int] = field(default_factory=dict)
    status: str = "ok"
    error: str = ""
    # Multi-model / cross-framework extensions.
    is_cold_start: bool = False
    source_framework: str = "gaia"


# ---------------------------------------------------------------------------
# MBOX loader — uses FakeGmailBackend's Gmail-API-shape output
# ---------------------------------------------------------------------------


def _extract_headers(payload: dict) -> dict[str, str]:
    """Pull headers out of a Gmail-API-shape payload dict."""
    out = {}
    for h in payload.get("headers", []):
        name = (h.get("name") or "").lower()
        out[name] = h.get("value", "")
    return out


def _last_assistant_text(conversation: list, stats_msg: dict) -> str:
    """Find the last assistant message before a system stats message."""
    for i in range(conversation.index(stats_msg) - 1, -1, -1):
        msg = conversation[i]
        if msg.get("role") == "assistant":
            text = msg.get("content", "")
            if isinstance(text, str):
                return text
            if isinstance(text, list):
                return "".join(b.get("text", "") for b in text if isinstance(b, dict))
    return ""


def _extract_reasoning_tokens(text: str) -> int:
    """Estimate reasoning tokens from <thinking> blocks in assistant text.

    The Lemonade /stats endpoint does not report reasoning tokens separately.
    We approximate by counting characters inside <thinking>...</thinking>
    blocks and using a 1 token ≈ 4 character ratio (standard BPE estimate).
    Returns 0 if no thinking blocks are found.
    """
    import re

    thinking_blocks = re.findall(r"<thinking>(.*?)</thinking>", text, re.DOTALL)
    if not thinking_blocks:
        return 0
    total_chars = sum(len(b.strip()) for b in thinking_blocks)
    return max(1, total_chars // 4)


def load_emails_from_mbox(
    mbox_path: str,
    *,
    limit: int = 100,
) -> list[dict]:
    """Load emails from an MBOX file via FakeGmailBackend.

    Returns a list of dicts with: id, subject, from, label_ids, payload.
    The payload is in Gmail API v1 shape for direct use by the agent.
    """
    # Build FakeGmailBackend from the MBOX path.
    from gaia.agents.email.fake_gmail import FakeGmailBackend
    from gaia.agents.email.tools.triage_heuristics import LABEL_INBOX

    backend = FakeGmailBackend(mbox_path=Path(mbox_path))
    listing = backend.list_messages(label_ids=[LABEL_INBOX], max_results=limit)

    emails = []
    for stub in listing.get("messages", [])[:limit]:
        msg = backend.get_message(stub["id"])
        headers = _extract_headers(msg.get("payload", {}))
        emails.append(
            {
                "id": msg["id"],
                "thread_id": msg.get("threadId", msg["id"]),
                "subject": headers.get("subject", ""),
                "sender": headers.get("from", ""),
                "date": headers.get("date", ""),
                "label_ids": list(msg.get("labelIds", [])),
                "snippet": msg.get("snippet", ""),
                "payload": msg.get("payload", {}),
            }
        )

    return emails


# ---------------------------------------------------------------------------
# Heuristic mode
# ---------------------------------------------------------------------------


def _run_heuristic_batch(
    emails: list[dict],
    batch_num: int,
    total_batches: int,
) -> BatchResult:
    """Classify a batch of emails using the heuristic pipeline only."""
    batch = BatchResult(
        batch_number=batch_num,
        batch_size=len(emails),
        total_batches=total_batches,
    )
    start = time.monotonic()

    for email in emails:
        e_start = time.monotonic()
        try:
            result = classify_category_heuristic(
                subject=email["subject"],
                sender=email["sender"],
                label_ids=email["label_ids"],
            )
            elapsed = int((time.monotonic() - e_start) * 1000)
            batch.email_results.append(
                EmailResult(
                    email_id=email["id"],
                    subject=email["subject"],
                    sender=email["sender"],
                    label_ids=email["label_ids"],
                    category=result.category,
                    is_spam=result.is_spam,
                    is_phishing=result.is_phishing,
                    confident=result.confident,
                    reason=result.reason,
                    duration_ms=elapsed,
                )
            )
        except Exception as exc:
            batch.email_results.append(
                EmailResult(
                    email_id=email["id"],
                    subject=email["subject"],
                    sender=email["sender"],
                    status="error",
                    error=str(exc),
                    duration_ms=int((time.monotonic() - e_start) * 1000),
                )
            )

    batch.duration_ms = int((time.monotonic() - start) * 1000)
    # Extract categories used.
    categories = set()
    for er in batch.email_results:
        if er.category:
            categories.add(er.category)
    batch.categories = sorted(categories)
    return batch


# ---------------------------------------------------------------------------
# Full agent mode
# ---------------------------------------------------------------------------


def _run_full_agent(
    mbox_path: str,
    *,
    model_id: str,
    base_url: str,
    max_steps: int = 12,
    limit: int = 100,
    _batch_size: int = 20,
) -> RunResult:
    """Run the full EmailTriageAgent end-to-end.

    Instantiates the agent with FakeGmailBackend injected, calls
    ``triage_inbox``, and captures all token/duration metrics.
    """
    import json
    import uuid
    from datetime import datetime, timezone

    from gaia.agents.email.agent import EmailTriageAgent
    from gaia.agents.email.config import EmailAgentConfig
    from gaia.agents.email.fake_gmail import FakeCalendarBackend, FakeGmailBackend

    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{model_id.replace('/', '-')}-{uuid.uuid4().hex[:6]}"
    timestamp = datetime.now(timezone.utc).isoformat()

    # Build fake backends and pass them through the config.
    # CRITICAL: The agent's __init__ calls _register_tools() inside
    # super().__init__(), which captures self._gmail and self._calendar in
    # tool closures at registration time. Monkey-patching _gmail/_calendar
    # AFTER __init__ completes has no effect — the tools already hold
    # references to the original LiveGmailBackend/LiveCalendarBackend.
    # Passing fakes through the config ensures they are bound before
    # _register_tools() runs.
    fake = FakeGmailBackend(mbox_path=Path(mbox_path))
    fake_cal = FakeCalendarBackend()
    config = EmailAgentConfig(
        model_id=model_id,
        base_url=base_url,
        max_steps=max_steps,
        debug=True,  # Enable verbose logging for metrics capture
        gmail_backend=fake,
        calendar_backend=fake_cal,
    )
    agent = EmailTriageAgent(config=config)

    # Wall-clock timing — captures MBOX load, agent construction, and inference.
    start = time.monotonic()
    try:
        agent_result = agent.process_query(f"Triage my inbox ({limit} emails)")
    except Exception as exc:
        return RunResult(
            run_id=run_id,
            timestamp=timestamp,
            model=model_id,
            provider="lemonade",
            mbox_path=mbox_path,
            mode="full",
            status="error",
            error=str(exc),
            total_duration_ms=int((time.monotonic() - start) * 1000),
        )

    total_duration_ms = int((time.monotonic() - start) * 1000)

    # Guard against an empty agent result.
    if not agent_result:
        return RunResult(
            run_id=run_id,
            timestamp=timestamp,
            model=model_id,
            provider="lemonade",
            mbox_path=mbox_path,
            mode="full",
            status="error",
            error="agent returned no result",
            total_duration_ms=total_duration_ms,
        )

    # Extract token counts from the agent's return value.
    # process_query returns: {input_tokens, output_tokens, total_tokens, duration, ...}
    input_tokens = agent_result.get("input_tokens", 0) or 0
    output_tokens = agent_result.get("output_tokens", 0) or 0
    total_tokens = agent_result.get("total_tokens", 0) or 0

    # Extract triage results from the conversation. The triage_inbox tool
    # returns a JSON envelope {"ok": true, "data": {"results": [...], ...}}.
    # Walk the conversation to find the tool result from triage_inbox.
    # Also extract per-step performance stats from system entries.
    triage_results: list[dict] = []
    tool_error: str = ""
    step_results: list[StepResult] = []
    conversation = agent_result.get("conversation", [])
    step_num = 0
    total_reasoning_tokens = 0
    for msg in conversation:
        role = msg.get("role", "")

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
                        input_tokens=stats.get("input_tokens", 0) or 0,
                        output_tokens=stats.get("output_tokens", 0) or 0,
                        reasoning_tokens=_extract_reasoning_tokens(
                            _last_assistant_text(conversation, msg)
                        ),
                        total_tokens=stats.get("total_tokens", 0) or 0,
                        duration_ms=int(stats.get("duration", 0) * 1000),
                        time_to_first_token_ms=ttft_ms,
                        tokens_per_second=float(stats.get("tokens_per_second", 0) or 0),
                    )
                )
            continue

        if role == "tool" and msg.get("content"):
            content = msg["content"]
            # Content can be a string, list of content blocks, or a dict
            # (when _handle_large_tool_result re-parses after truncation).
            if isinstance(content, dict):
                text = json.dumps(content)
            elif isinstance(content, list):
                text = "".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict)
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
                        triage_results = data["results"]
                        break
                elif not envelope.get("ok") and "error" in envelope:
                    # Capture the tool error for reporting.
                    tool_error = envelope["error"]
            except (json.JSONDecodeError, TypeError):
                continue

    # If no triage results found and we have a tool error, use it.
    if not triage_results and tool_error:
        return RunResult(
            run_id=run_id,
            timestamp=timestamp,
            model=model_id,
            provider="lemonade",
            mbox_path=mbox_path,
            mode="full",
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
    email_results = []
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

    run = RunResult(
        run_id=run_id,
        timestamp=timestamp,
        model=model_id,
        provider="lemonade",
        mbox_path=mbox_path,
        mode="full",
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

    return run


# ---------------------------------------------------------------------------
# Interactive benchmark — multi-turn session tracking
# ---------------------------------------------------------------------------

# Default interactive scenario: a realistic email triage session.
# Each prompt is a separate turn; the agent retains context across turns.
DEFAULT_INTERACTIVE_SCENARIO = [
    "Triage my inbox ({limit} emails)",
    "Archive the low priority emails",
    "Star any urgent or actionable messages",
    "Show me a summary of what's left in my inbox",
]


def _extract_steps_from_result(agent_result: dict) -> list[StepResult]:
    """Extract per-step token/duration stats from an agent result."""
    steps = []
    step_num = 0
    conversation = agent_result.get("conversation", [])
    for msg in conversation:
        if msg.get("role") == "system" and isinstance(msg.get("content"), dict):
            content = msg["content"]
            if content.get("type") == "stats" and "performance_stats" in content:
                stats = content["performance_stats"]
                step_num += 1
                raw_ttft = stats.get("time_to_first_token")
                ttft_ms = float(raw_ttft) * 1000 if raw_ttft else 0.0
                steps.append(
                    StepResult(
                        step_number=step_num,
                        action="llm_call",
                        input_tokens=stats.get("input_tokens", 0) or 0,
                        output_tokens=stats.get("output_tokens", 0) or 0,
                        reasoning_tokens=_extract_reasoning_tokens(
                            _last_assistant_text(conversation, msg)
                        ),
                        total_tokens=stats.get("total_tokens", 0) or 0,
                        duration_ms=int(stats.get("duration", 0) * 1000),
                        time_to_first_token_ms=ttft_ms,
                        tokens_per_second=float(stats.get("tokens_per_second", 0) or 0),
                    )
                )
    return steps


def _extract_tools_called(agent_result: dict) -> list[str]:
    """Extract tool names called during this turn."""
    tools = []
    for msg in agent_result.get("conversation", []):
        if msg.get("role") == "assistant" and isinstance(msg.get("content"), dict):
            tool = msg["content"].get("tool", "")
            if tool and tool not in tools:
                tools.append(tool)
        # Also check for tool usage in other content formats
        elif msg.get("role") == "tool" and msg.get("name"):
            name = msg.get("name", "")
            if name and name not in tools:
                tools.append(name)
    return tools


def _extract_emails_affected(agent_result: dict) -> list[str]:
    """Extract email IDs that were affected by tool calls in this turn."""
    email_ids = set()
    for msg in agent_result.get("conversation", []):
        if msg.get("role") == "tool" and msg.get("content"):
            content = msg["content"]
            if isinstance(content, list):
                text = "".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict)
                )
            elif isinstance(content, str):
                text = content
            elif isinstance(content, dict):
                text = json.dumps(content)
            else:
                continue
            # Look for email IDs in tool result (they appear in results/ids)
            try:
                envelope = json.loads(text)
                if envelope.get("ok") and "data" in envelope:
                    data = envelope["data"]
                    if isinstance(data, dict):
                        if "results" in data:
                            for item in data["results"]:
                                if isinstance(item, dict) and "id" in item:
                                    email_ids.add(item["id"])
                        elif "ids" in data:
                            email_ids.update(data["ids"])
                        elif "message_id" in data:
                            email_ids.add(data["message_id"])
            except (json.JSONDecodeError, TypeError):
                pass
    return sorted(email_ids)


def run_interactive_benchmark(
    mbox_path: str,
    *,
    model_id: str,
    base_url: str,
    scenario: list[str] | None = None,
    limit: int = 100,
    max_steps: int = 12,
) -> dict:
    """Run an interactive multi-turn benchmark session.

    Each turn is a separate process_query() call. The agent retains context
    across turns via conversation_history.

    Returns a dict with:
    - turns: list of TurnResult objects
    - totals: aggregated token/time/action counts
    """
    import uuid
    from datetime import datetime, timezone

    from gaia.agents.email.agent import EmailTriageAgent
    from gaia.agents.email.config import EmailAgentConfig
    from gaia.agents.email.fake_gmail import FakeCalendarBackend, FakeGmailBackend

    run_id = f"run-interactive-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{model_id.replace('/', '-')}-{uuid.uuid4().hex[:6]}"
    timestamp = datetime.now(timezone.utc).isoformat()

    scenario = scenario or [p.format(limit=limit) for p in DEFAULT_INTERACTIVE_SCENARIO]

    fake = FakeGmailBackend(mbox_path=Path(mbox_path))
    fake_cal = FakeCalendarBackend()
    config = EmailAgentConfig(
        model_id=model_id,
        base_url=base_url,
        max_steps=max_steps,
        debug=True,
        gmail_backend=fake,
        calendar_backend=fake_cal,
    )
    agent = EmailTriageAgent(config=config)

    turns: list[TurnResult] = []
    total_start = time.monotonic()

    for i, prompt in enumerate(scenario):
        turn_num = i + 1
        print(f"\n{'='*60}")
        print(f"  Turn {turn_num}/{len(scenario)}")
        print(f"  Prompt: {prompt}")
        print(f"{'='*60}")

        turn_start = time.monotonic()
        try:
            agent_result = agent.process_query(prompt)
        except Exception as exc:
            print(f"  Turn {turn_num} FAILED: {exc}")
            turns.append(
                TurnResult(
                    turn_number=turn_num,
                    prompt=prompt,
                    status="error",
                    error=str(exc),
                )
            )
            continue

        turn_duration = int((time.monotonic() - turn_start) * 1000)

        steps = _extract_steps_from_result(agent_result)
        tools = _extract_tools_called(agent_result)
        email_ids = _extract_emails_affected(agent_result)
        input_tokens = agent_result.get("input_tokens", 0) or 0
        output_tokens = agent_result.get("output_tokens", 0) or 0
        total_tokens = agent_result.get("total_tokens", 0) or 0
        final = agent_result.get("result", "")

        # Persist conversation state for next turn.
        conversation = agent_result.get("conversation", [])
        if conversation:
            agent.conversation_history = conversation

        turn = TurnResult(
            turn_number=turn_num,
            prompt=prompt,
            step_results=steps,
            tools_called=tools,
            emails_affected=email_ids,
            duration_ms=turn_duration,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=sum(s.reasoning_tokens for s in steps),
            total_tokens=total_tokens,
            time_to_first_token_ms=round(
                sum(s.time_to_first_token_ms for s in steps) / max(len(steps), 1), 1
            ),
            tokens_per_second=round(
                sum(s.tokens_per_second for s in steps) / max(len(steps), 1), 1
            ),
            final_answer=str(final)[:500] if final else "",
            status="ok",
        )
        turns.append(turn)

        # Print per-turn summary.
        tool_str = ", ".join(tools) if tools else "(no tools)"
        print(f"  Duration: {turn_duration/1000:.1f}s")
        print(
            f"  Tokens:   {total_tokens:,} (in={input_tokens}, out={output_tokens}, reasoning={turn.reasoning_tokens})"
        )
        print(f"  Tools:    {tool_str}")
        print(f"  Emails:   {len(email_ids)} affected")
        if steps:
            for s in steps:
                time_str = (
                    f"{s.duration_ms}ms"
                    if s.duration_ms < 1000
                    else f"{s.duration_ms/1000:.1f}s"
                )
                ttft_str = (
                    f"{s.time_to_first_token_ms:.0f}ms"
                    if s.time_to_first_token_ms > 0
                    else "n/a"
                )
                tps_str = (
                    f"{s.tokens_per_second:.1f}t/s" if s.tokens_per_second > 0 else ""
                )
                perf = f"{ttft_str}"
                if tps_str:
                    perf += f" / {tps_str}"
                print(
                    f"    Step {s.step_number}: {s.input_tokens} in / {s.output_tokens} out / {s.reasoning_tokens} reasoning / {s.total_tokens} total / {time_str} / {perf}"
                )

    total_duration_ms = int((time.monotonic() - total_start) * 1000)
    total_tokens = sum(t.total_tokens for t in turns)
    total_input = sum(t.input_tokens for t in turns)
    total_output = sum(t.output_tokens for t in turns)
    total_reasoning = sum(t.reasoning_tokens for t in turns)
    ttft_vals = [
        t.time_to_first_token_ms for t in turns if t.time_to_first_token_ms > 0
    ]
    tps_vals = [t.tokens_per_second for t in turns if t.tokens_per_second > 0]
    avg_ttft = sum(ttft_vals) / len(ttft_vals) if ttft_vals else 0.0
    avg_tps = sum(tps_vals) / len(tps_vals) if tps_vals else 0.0
    all_emails = set()
    all_tools = []
    for t in turns:
        all_emails.update(t.emails_affected)
        for tool in t.tools_called:
            if tool not in all_tools:
                all_tools.append(tool)

    summary = {
        "run_id": run_id,
        "timestamp": timestamp,
        "model": model_id,
        "mbox_path": mbox_path,
        "turns": turns,
        "total_turns": len(turns),
        "total_emails_affected": len(all_emails),
        "total_tools_used": len(all_tools),
        "tools_used": all_tools,
        "total_duration_ms": total_duration_ms,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_reasoning_tokens": total_reasoning,
        "total_tokens": total_tokens,
        "avg_tokens_per_turn": round(total_tokens / max(len(turns), 1), 1),
        "avg_duration_per_turn_ms": round(total_duration_ms / max(len(turns), 1), 0),
        "avg_time_to_first_token_ms": round(avg_ttft, 1),
        "avg_tokens_per_second": round(avg_tps, 1),
    }

    # Print final summary.
    print(f"\n{'='*70}")
    print(f"  Interactive Benchmark — Summary")
    print(f"{'='*70}")
    print(f"  Run ID:    {run_id}")
    print(f"  Model:     {model_id}")
    print(f"  Turns:     {summary['total_turns']}")
    print(f"  Duration:  {total_duration_ms/1000:.1f}s total")
    print(f"  Tokens:    {total_tokens:,} total")
    print(f"    Input:    {total_input:,}")
    print(f"    Output:   {total_output:,}")
    print(f"    Reasoning: {total_reasoning:,}")
    print(
        f"  Avg/turn:  {summary['avg_tokens_per_turn']} tokens, {summary['avg_duration_per_turn_ms']}ms"
    )
    print(f"  Tools:     {', '.join(all_tools)}")
    print(f"  Emails:    {len(all_emails)} unique emails affected")
    print(f"{'='*70}\n")

    return summary


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_heuristic_benchmark(
    mbox_path: str,
    *,
    limit: int = 100,
    batch_size: int = 20,
    model: str = "heuristic-only",
    provider: str = "none",
) -> RunResult:
    """Run the heuristic benchmark against an MBOX file.

    This is the fast path — no LLM calls. Returns structured results
    ready for CSV/JSON/JSONL output.
    """
    import uuid
    from datetime import datetime, timezone

    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{model.replace('/', '-')}-{uuid.uuid4().hex[:6]}"
    timestamp = datetime.now(timezone.utc).isoformat()

    # Wall-clock timing — captures MBOX load, parsing, classification, and aggregation.
    start = time.monotonic()

    emails = load_emails_from_mbox(mbox_path, limit=limit)
    if not emails:
        return RunResult(
            run_id=run_id,
            timestamp=timestamp,
            model=model,
            provider=provider,
            mbox_path=mbox_path,
            mode="heuristic",
            status="error",
            error="No emails found in MBOX file",
            total_duration_ms=int((time.monotonic() - start) * 1000),
        )

    # Split into batches.
    batches = []
    for i in range(0, len(emails), batch_size):
        batch_emails = emails[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(emails) + batch_size - 1) // batch_size
        batches.append(_run_heuristic_batch(batch_emails, batch_num, total_batches))

    # Aggregate.
    category_counts: dict[str, int] = {}
    for b in batches:
        for er in b.email_results:
            if er.category:
                category_counts[er.category] = category_counts.get(er.category, 0) + 1

    # Wall-clock total — captures everything from MBOX load through aggregation.
    total_duration_ms = int((time.monotonic() - start) * 1000)
    total_tokens = 0  # Heuristic mode has no tokens.

    return RunResult(
        run_id=run_id,
        timestamp=timestamp,
        model=model,
        provider=provider,
        mbox_path=mbox_path,
        mode="heuristic",
        batch_results=batches,
        total_emails=sum(len(b.email_results) for b in batches),
        total_duration_ms=total_duration_ms,
        total_tokens=total_tokens,
        category_counts=category_counts,
        status="completed",
    )
