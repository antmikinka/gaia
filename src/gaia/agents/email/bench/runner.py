# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Core benchmark runner for the GAIA Email Triage Agent.

Supports two modes:
- ``full`` — End-to-end. Instantiates ``EmailTriageAgent`` with
  ``FakeGmailBackend`` injected, calls ``triage_inbox``, and captures
  token/duration metrics from the LLM round-trips.
- ``interactive`` — Multi-turn session with context retention across turns.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from gaia.agents.email.bench.data_shapes import (
    BatchResult,
    EmailResult,
    RunResult,
    SessionState,
    StepResult,
    TurnResult,
)
from gaia.agents.email.bench.trace_extractor import (
    _extract_reasoning_tokens,
    _last_assistant_text,
    extract_from_agent_result,
)

# Re-export dataclasses for backwards compatibility (downstream code imports from runner).
__all__ = [
    "BatchResult",
    "EmailResult",
    "RunResult",
    "SessionState",
    "StepResult",
    "TurnResult",
]


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


def load_emails_from_jsonl(
    jsonl_path: str,
    *,
    limit: int = 100,
) -> list[dict]:
    """Load emails from a JSONL file via FakeGmailBackend.

    Returns a list of dicts with: id, subject, from, label_ids, payload.
    The payload is in Gmail API v1 shape for direct use by the agent.
    """
    from gaia.agents.email.fake_gmail import FakeGmailBackend
    from gaia.agents.email.tools.triage_heuristics import LABEL_INBOX

    backend = FakeGmailBackend(jsonl_path=Path(jsonl_path))
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
# Full agent mode
# ---------------------------------------------------------------------------


def _run_full_agent(
    mbox_path: str = "",
    jsonl_path: str = "",
    *,
    model_id: str,
    base_url: str,
    max_steps: int = 12,
    limit: int = 100,
    force_llm: bool = False,
) -> RunResult:
    """Run the full EmailTriageAgent end-to-end.

    Instantiates the agent with FakeGmailBackend injected, calls
    ``triage_inbox``, and captures all token/duration metrics.

    Exactly one of ``mbox_path`` or ``jsonl_path`` must be provided.

    When ``force_llm=True``, bypasses the heuristic fast-path, forcing
    LLM classification of every email (benchmark mode for true inference).
    """
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
    if mbox_path and jsonl_path:
        raise ValueError("Specify either mbox_path or jsonl_path, not both")
    if mbox_path:
        fake = FakeGmailBackend(mbox_path=Path(mbox_path))
    elif jsonl_path:
        fake = FakeGmailBackend(jsonl_path=Path(jsonl_path))
    else:
        raise ValueError("Either mbox_path or jsonl_path must be provided")
    fake_cal = FakeCalendarBackend()
    config = EmailAgentConfig(
        model_id=model_id,
        base_url=base_url,
        max_steps=max_steps,
        debug=True,  # Enable verbose logging for metrics capture
        show_stats=True,  # Capture TTFT/TPS per LLM call for benchmark stats
        force_llm=force_llm,
        gmail_backend=fake,
        calendar_backend=fake_cal,
    )
    agent = EmailTriageAgent(config=config)

    # Wall-clock timing — captures data load, agent construction, and inference.
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
            jsonl_path=jsonl_path,
            data_source="jsonl" if jsonl_path else "mbox",
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
            jsonl_path=jsonl_path,
            data_source="jsonl" if jsonl_path else "mbox",
            mode="full",
            status="error",
            error="agent returned no result",
            total_duration_ms=total_duration_ms,
        )

    run = extract_from_agent_result(
        agent_result,
        run_id=run_id,
        timestamp=timestamp,
        model_id=model_id,
        mbox_path=mbox_path,
        mode="full",
        total_duration_ms=total_duration_ms,
        force_llm=force_llm,
    )
    # Populate JSONL-specific fields.
    if jsonl_path:
        run.jsonl_path = jsonl_path
        run.data_source = "jsonl"

    return run


# ---------------------------------------------------------------------------
# Batched agent mode
# ---------------------------------------------------------------------------


def _run_batched_agent(
    mbox_path: str = "",
    jsonl_path: str = "",
    *,
    model_id: str,
    base_url: str,
    max_steps: int = 12,
    limit: int = 100,
    batch_size: int = 5,
) -> RunResult:
    """Run the batched EmailTriageAgent end-to-end."""
    import uuid as _uuid
    from datetime import datetime, timezone

    from gaia.agents.email.agent import EmailTriageAgent
    from gaia.agents.email.config import EmailAgentConfig
    from gaia.agents.email.action_store import fetch_triage_results
    from gaia.agents.email.fake_gmail import FakeCalendarBackend, FakeGmailBackend
    from gaia.agents.email.bench.data_shapes import BatchResult, EmailResult

    run_id = f"run-batched-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{model_id.replace('/', '-')}-{_uuid.uuid4().hex[:6]}"
    timestamp = datetime.now(timezone.utc).isoformat()

    if mbox_path and jsonl_path:
        raise ValueError("Specify either mbox_path or jsonl_path, not both")
    if mbox_path:
        fake = FakeGmailBackend(mbox_path=Path(mbox_path))
    elif jsonl_path:
        fake = FakeGmailBackend(jsonl_path=Path(jsonl_path))
    else:
        raise ValueError("Either mbox_path or jsonl_path must be provided")
    fake_cal = FakeCalendarBackend()
    config = EmailAgentConfig(
        model_id=model_id,
        base_url=base_url,
        max_steps=max_steps,
        debug=True,
        show_stats=True,
        enable_batched_mode=True,
        batch_size=batch_size,
        gmail_backend=fake,
        calendar_backend=fake_cal,
    )
    agent = EmailTriageAgent(config=config)

    start = time.monotonic()
    try:
        result_str = agent.process_batched_triage(max_messages=limit)
    except Exception as exc:
        return RunResult(
            run_id=run_id, timestamp=timestamp, model=model_id,
            provider="lemonade", mbox_path=mbox_path, jsonl_path=jsonl_path,
            data_source="jsonl" if jsonl_path else "mbox", mode="batched",
            status="error", error=str(exc),
            total_duration_ms=int((time.monotonic() - start) * 1000),
        )

    total_duration_ms = int((time.monotonic() - start) * 1000)
    results = fetch_triage_results(agent, run_id=run_id)

    email_results: list[EmailResult] = []
    category_counts: dict[str, int] = {}
    for row in results:
        cat = row.get("category", "informational")
        category_counts[cat] = category_counts.get(cat, 0) + 1
        email_results.append(EmailResult(
            email_id=row["email_id"], subject="", sender="",
            category=cat, confident=row.get("confident", False),
            reason="", llm_summary=row.get("llm_summary", ""),
            status="ok",
            duration_ms=int((row.get("duration_secs", 0) or 0) * 1000),
            total_tokens=row.get("token_count", 0) or 0,
        ))

    batch_groups: dict[int, list[EmailResult]] = {}
    for idx, row in enumerate(results):
        bn = row.get("batch_number", 1)
        batch_groups.setdefault(bn, []).append(email_results[idx])

    total_batches = max(batch_groups.keys(), default=1)
    batch_results_list: list[BatchResult] = []
    for bn in sorted(batch_groups.keys()):
        group = batch_groups[bn]
        batch_results_list.append(BatchResult(
            batch_number=bn, batch_size=len(group), total_batches=total_batches,
            email_results=group,
            duration_ms=int(sum(e.duration_ms for e in group)),
            total_input_tokens=sum(e.total_tokens for e in group),
            total_output_tokens=0,
            total_tokens=sum(e.total_tokens for e in group),
            categories=list(set(e.category for e in group)),
            status="ok",
        ))

    total_input_tokens = sum(e.total_tokens for e in email_results)

    return RunResult(
        run_id=run_id, timestamp=timestamp, model=model_id, provider="lemonade",
        mbox_path=mbox_path, jsonl_path=jsonl_path,
        data_source="jsonl" if jsonl_path else "mbox", mode="batched",
        batch_results=batch_results_list, step_results=[],
        total_emails=len(email_results), total_duration_ms=total_duration_ms,
        total_input_tokens=total_input_tokens, total_output_tokens=0,
        total_tokens=total_input_tokens,
        category_counts=category_counts,
        estimated_steps=len(email_results),
        status="completed" if email_results else "error",
    )


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
    last_tool_name = ""
    conversation = agent_result.get("conversation", [])
    for msg in conversation:
        role = msg.get("role", "")

        # Track tool names from role=="tool" messages.
        if role == "tool" and msg.get("name"):
            last_tool_name = msg["name"]

        # Reset tool name when we see an assistant message (new LLM call, no tool yet).
        if role == "assistant":
            last_tool_name = ""

        if role == "system" and isinstance(msg.get("content"), dict):
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
                        elif "succeeded" in data:
                            for item in data["succeeded"]:
                                if isinstance(item, dict) and "message_id" in item:
                                    email_ids.add(item["message_id"])
            except (json.JSONDecodeError, TypeError):
                pass
    return sorted(email_ids)


def run_interactive_benchmark(
    mbox_path: str = "",
    jsonl_path: str = "",
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

    if mbox_path and jsonl_path:
        raise ValueError("Specify either mbox_path or jsonl_path, not both")
    if mbox_path:
        fake = FakeGmailBackend(mbox_path=Path(mbox_path))
    elif jsonl_path:
        fake = FakeGmailBackend(jsonl_path=Path(jsonl_path))
    else:
        raise ValueError("Either mbox_path or jsonl_path must be provided")
    fake_cal = FakeCalendarBackend()
    config = EmailAgentConfig(
        model_id=model_id,
        base_url=base_url,
        max_steps=max_steps,
        debug=True,
        show_stats=True,  # Capture TTFT/TPS per LLM call for benchmark stats
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
        "jsonl_path": jsonl_path,
        "data_source": "jsonl" if jsonl_path else "mbox",
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
# Interactive session — user-driven with state tracking
# ---------------------------------------------------------------------------


def _extract_actions(agent_result: dict, state: SessionState) -> None:
    """Parse tool calls/results to update SessionState."""
    for msg in agent_result.get("conversation", []):
        if msg.get("role") != "tool" or not msg.get("content"):
            continue
        content = msg["content"]
        if isinstance(content, list):
            text = "".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        elif isinstance(content, str):
            text = content
        elif isinstance(content, dict):
            text = json.dumps(content)
        else:
            continue

        tool_name = msg.get("name", "")
        try:
            envelope = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue

        if not envelope.get("ok") or "data" not in envelope:
            continue
        data = envelope["data"]

        # triage_inbox results — track categories.
        if tool_name == "triage_inbox" and isinstance(data, dict) and "results" in data:
            for item in data["results"]:
                if isinstance(item, dict) and "id" in item:
                    state.triaged_emails[item["id"]] = item.get("category", "unknown")

        # archive_message / archive_message_batch — track archived IDs.
        if tool_name in ("archive_message", "archive_message_batch") and isinstance(data, dict):
            msg_id = data.get("message_id", "") or data.get("id", "")
            if msg_id:
                state.archived.add(msg_id)

        # Draft/send.
        if tool_name in ("create_draft", "save_draft") and isinstance(data, dict):
            draft_id = data.get("id", "") or data.get("draft_id", "")
            if draft_id:
                state.drafted.add(draft_id)
        if tool_name in ("send_draft", "send_message") and isinstance(data, dict):
            msg_id = data.get("id", "") or data.get("message_id", "")
            if msg_id:
                state.sent.add(msg_id)

        # Star/unstar.
        if tool_name in ("add_star", "add_star_batch") and isinstance(data, dict):
            msg_id = data.get("id", "") or data.get("message_id", "")
            if msg_id:
                state.starred.add(msg_id)
        if tool_name in ("remove_star", "remove_star_batch") and isinstance(data, dict):
            msg_id = data.get("id", "") or data.get("message_id", "")
            if msg_id:
                state.starred.discard(msg_id)

        # Mark read/unread.
        if tool_name in ("mark_read", "mark_read_batch", "mark_as_read") and isinstance(data, dict):
            msg_id = data.get("id", "") or data.get("message_id", "")
            if msg_id:
                state.marked_read.add(msg_id)

        # Delete.
        if tool_name == "trash_message" and isinstance(data, dict):
            msg_id = data.get("id", "") or data.get("message_id", "")
            if msg_id:
                state.deleted.add(msg_id)


def _print_session_state(state: SessionState) -> None:
    """Print current session state."""
    print(f"\n{'─'*60}")
    print(f"  Session State")
    print(f"{'─'*60}")
    if state.triaged_emails:
        cats = {}
        for cat in state.triaged_emails.values():
            cats[cat] = cats.get(cat, 0) + 1
        print(f"  Triaged: {len(state.triaged_emails)} emails")
        for cat, cnt in sorted(cats.items(), key=lambda x: -x[1]):
            print(f"    {cat}: {cnt}")
    if state.archived:
        print(f"  Archived: {len(state.archived)} emails")
    if state.starred:
        print(f"  Starred:  {len(state.starred)} emails")
    if state.drafted:
        print(f"  Drafted:  {len(state.drafted)} emails")
    if state.sent:
        print(f"  Sent:     {len(state.sent)} emails")
    if state.marked_read:
        print(f"  Marked read: {len(state.marked_read)} emails")
    if state.deleted:
        print(f"  Deleted:  {len(state.deleted)} emails")
    if not any(
        [
            state.triaged_emails,
            state.archived,
            state.starred,
            state.drafted,
            state.sent,
            state.marked_read,
            state.deleted,
        ]
    ):
        print(f"  (no actions yet)")
    print(f"{'─'*60}")


def run_interactive_session(
    mbox_path: str = "",
    jsonl_path: str = "",
    *,
    model_id: str,
    base_url: str,
    limit: int = 100,
    max_steps: int = 12,
    force_llm: bool = False,
) -> dict:
    """Run a truly interactive email session with user input.

    Prompts the user for commands, executes them against the agent,
    and tracks session state (archived, starred, drafted, etc.) across turns.

    Type ``quit`` or ``exit`` to end the session.
    """
    import uuid
    from datetime import datetime, timezone

    from gaia.agents.email.agent import EmailTriageAgent
    from gaia.agents.email.config import EmailAgentConfig
    from gaia.agents.email.fake_gmail import FakeCalendarBackend, FakeGmailBackend

    run_id = f"run-interactive-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{model_id.replace('/', '-')}-{uuid.uuid4().hex[:6]}"
    timestamp = datetime.now(timezone.utc).isoformat()

    if mbox_path and jsonl_path:
        raise ValueError("Specify either mbox_path or jsonl_path, not both")
    if mbox_path:
        fake = FakeGmailBackend(mbox_path=Path(mbox_path))
    elif jsonl_path:
        fake = FakeGmailBackend(jsonl_path=Path(jsonl_path))
    else:
        raise ValueError("Either mbox_path or jsonl_path must be provided")
    fake_cal = FakeCalendarBackend()
    config = EmailAgentConfig(
        model_id=model_id,
        base_url=base_url,
        max_steps=max_steps,
        debug=True,
        show_stats=True,
        force_llm=force_llm,
        gmail_backend=fake,
        calendar_backend=fake_cal,
    )
    agent = EmailTriageAgent(config=config)

    state = SessionState()
    turns: list[TurnResult] = []
    total_start = time.monotonic()

    data_label = Path(jsonl_path).name if jsonl_path else Path(mbox_path).name
    print(f"\n{'='*70}")
    print(f"  GAIA Email — Interactive Session")
    print(f"{'='*70}")
    print(f"  Model:  {model_id}")
    print(f"  Data:   {data_label}")
    print(f"  Limit:  {limit} emails")
    print(f"  Type 'quit' or 'exit' to end the session.")
    print(f"{'='*70}")

    turn_num = 0
    while True:
        turn_num += 1
        print(f"\n{'─'*60}")
        try:
            prompt = input(f"  You (Turn {turn_num}): ")
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Session ended by user.")
            break

        prompt = prompt.strip()
        if not prompt:
            turn_num -= 1
            continue
        if prompt.lower() in ("quit", "exit", "q"):
            print("  Ending session.")
            turn_num -= 1
            break

        prompt = prompt.format(limit=limit)

        print(f"{'─'*60}")
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

        _extract_actions(agent_result, state)

        conversation = agent_result.get("conversation", [])
        if conversation:
            agent.conversation_history = conversation

        turns.append(
            TurnResult(
                turn_number=turn_num,
                prompt=prompt,
                step_results=steps,
                tools_called=tools,
                emails_affected=sorted(email_ids),
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
        )

        _print_session_state(state)

    # --- Final summary ---
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

    print(f"\n{'='*70}")
    print(f"  Interactive Session — Final Summary")
    print(f"{'='*70}")
    print(f"  Run ID:    {run_id}")
    print(f"  Model:     {model_id}")
    print(f"  Turns:     {len(turns)}")
    print(f"  Duration:  {total_duration_ms/1000:.1f}s total")
    print(f"  Tokens:    {total_tokens:,} total")
    print(f"    Input:    {total_input:,}")
    print(f"    Output:   {total_output:,}")
    print(f"    Reasoning: {total_reasoning:,}")
    print(f"  Tools:     {', '.join(all_tools) if all_tools else '(none)'}")
    print(f"  Emails:    {len(all_emails)} unique emails affected")
    _print_session_state(state)
    print(f"{'='*70}")

    return {
        "run_id": run_id,
        "timestamp": timestamp,
        "model": model_id,
        "mbox_path": mbox_path,
        "jsonl_path": jsonl_path,
        "data_source": "jsonl" if jsonl_path else "mbox",
        "mode": "interactive",
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
        "session_state": {
            "archived": sorted(state.archived),
            "starred": sorted(state.starred),
            "drafted": sorted(state.drafted),
            "sent": sorted(state.sent),
            "marked_read": sorted(state.marked_read),
            "deleted": sorted(state.deleted),
            "triaged": dict(state.triaged_emails),
        },
    }
