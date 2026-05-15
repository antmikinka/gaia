# Issue: Misleading Retry Prompt for Parallel Tool Call Failures

**Observed:** 2026-05-13
**Model:** Qwen3.5-4B-GGUF
**Mode:** Interactive session (`--mode interactive`)
**Files:** `src/gaia/agents/base/agent.py`
**Classification:** **GAIA BASE AGENT BUG — not a benchmarking script issue**

---

## Scope

This is a bug in the **original GAIA email agent** — specifically the base `Agent` class in `src/gaia/agents/base/agent.py`. It is **NOT** caused by any of the benchmarking scripts (`bench/runner.py`, `bench/bench_runner.py`, `bench/cli.py`). The benchmark merely **reveals** a latent bug that exists in the upstream agent framework.

This means the same failure occurs in **production `gaia email` usage**, not just during benchmarking. Any time the email agent tries to batch-process multiple emails (archive, star, delete), the 4B model emits parallel tool calls, the base agent rejects them, and the misleading retry prompt causes infinite retry loops with zero results.

---

## Not a FakeGmailBackend / MBOX Issue

This failure has **nothing to do with FakeGmailBackend or MBOX files**. The call chain is:

1. **LLM generates response** → 5 parallel `archive_message` tool calls in a single API response
2. **`agent.py:1029`** parses the LLM response, sees `len(tool_calls) > 1` → raises `ValueError`
3. Retry loop — LLM is told "malformed arguments" → tries again → same parallel calls

The failure happens at the **LLM response parsing layer** in the base `Agent` class. The `FakeGmailBackend` (or `LiveGmailBackend` in production) is **never even called** — the tool calls are rejected before they reach the backend.

The model decides to call 5 tools in parallel based on its training. This happens regardless of whether it's backed by MBOX or real Gmail. **The bug would occur identically with a live Gmail API connection.**

---

## Symptom

When the agent asks the LLM to archive multiple emails (or perform any batch action), the model generates **multiple parallel tool calls** in a single response. The agent framework rejects this with a `ValueError`, then retries with a **generic retry prompt** that says:

> "Your last tool call had malformed arguments. Please try again. Use ONLY the documented enum values..."

The model keeps retrying the same parallel approach, exhausting all `max_steps` (typically 12), and producing zero progress.

**Example from Turn 2 ("Archive the low priority emails"):**
- Step 1: Model generates 5 parallel `archive_message` calls → rejected → retry prompt says "malformed arguments"
- Step 3: Model generates 5 parallel `archive_message` calls → rejected → retry prompt says "malformed arguments"
- Step 5: Model generates 5 parallel `archive_message` calls → rejected → retry prompt says "malformed arguments"
- **Result:** max_steps exhausted, turn completes with 0 archives, ~1,914 tokens wasted.

---

## Root Cause

Two problems in `src/gaia/agents/base/agent.py`:

### Problem 1: Parallel tool calls are silently converted to a generic error

At line ~1029:
```python
raise ValueError(
    "Parallel tool calls (multiple tool_calls in one response) are not yet supported. "
    f"Received {len(tool_calls)} tool calls."
)
```

This `ValueError` propagates to the catch block at line ~2573:
```python
except ValueError as parse_exc:
    logger.warning(
        "Tool-call parse failed (step %d): %s — recovering with retry prompt",
        steps_taken,
        parse_exc,
    )
```

The original error text (`"Parallel tool calls..."`) is logged but **never communicated to the model**.

### Problem 2: The retry prompt text is wrong

At line ~2609, the appended user message always says:
```
"Your last tool call had malformed arguments. "
"Please try again. Use ONLY the documented enum "
"values for each argument (e.g. 'brief', "
"'detailed', 'bullets' — never a long sentence). "
"If you don't need a tool, answer in plain text."
```

This prompt is designed for **JSON syntax errors** in tool arguments. But it gets reused for **parallel tool call rejections** too — telling the model "malformed arguments" when the real issue is "you can only call ONE tool at a time."

**The model is being lied to.** It correctly formatted its arguments, but is told they're malformed. It keeps trying the same parallel strategy because the retry message doesn't explain the actual constraint.

---

## Impact

| Metric | Expected | Actual |
|--------|----------|--------|
| Steps to archive 5 emails | ~5-10 sequential calls | 0 (all rejected) |
| Tokens consumed | ~500-1,000 | ~1,914 (wasted) |
| Time consumed | ~60-120s | ~131s (wasted) |
| Emails archived | 5 | 0 |

This affects any batch operation:
- `archive_message` (multiple emails)
- `star_message` (multiple emails)
- `delete_message` (multiple emails)
- `mark_read` / `mark_unread` (multiple emails)

---

## Required Fix

The retry prompt must differentiate between error types:

**For JSON parsing failures (current behavior, correct):**
```
"Your last tool call had malformed arguments..."
```

**For parallel tool call failures (new, needed):**
```
"You tried to call {N} tools at once. I can only execute one tool call at a time.
Please call ONE tool per response, then wait for the result before calling the next."
```

This requires capturing the error type from the `ValueError` at the catch site and selecting the appropriate retry message text.

---

## Proposed Patch Location

`src/gaia/agents/base/agent.py`, around line 2573-2618:

The `except ValueError as parse_exc:` block needs to inspect `str(parse_exc)` to determine if it's a parallel tool call error, and append a different user message for that case.
