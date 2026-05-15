# Issue: Repetition Loop on Mutation Tool Calls (mark_read, archive, star, delete)

**Observed:** 2026-05-13
**Model:** Qwen3.5-4B-GGUF
**Mode:** Interactive session (`--mode interactive`)
**Files:** `src/gaia/agents/base/agent.py` (lines 2883-2946)
**Classification:** **GAIA BASE AGENT BUG — missing dedup for mutation tools**

---

## Scope

This is a bug in the base `Agent` class (`src/gaia/agents/base/agent.py`). It is **NOT** caused by any benchmarking scripts. The benchmark reveals a latent weakness in how the agent framework handles repetition from small models on **mutation tool calls**.

The same issue occurs in **production `gaia email` usage**, not just during benchmarking. Any time a small model (4B-class) loses track of sequential state and repeats the same mutation tool call, the framework allows it to repeat up to 4 times before loop detection fires — and provides no early correction.

---

## Symptom

After the parallel tool call fix was applied, Turn 2 ("LETS MARK ALL AS READ") proceeded successfully for ~10 sequential `mark_read` operations. However, after the max_steps (12) limit was reached and extended:

- **Step 9:** `mark_read` on `ded9c6fc390e7cd7` (first occurrence)
- **Step 12:** `mark_read` on `ded9c6fc390e7cd7` (duplicate — already marked)
- **Step 13:** `mark_read` on `ded9c6fc390e7cd7` (duplicate)
- **Step 14:** `mark_read` on `ded9c6fc390e7cd7` (duplicate)
- **Step 15:** `mark_read` on `ded9c6fc390e7cd7` (duplicate)
- **Loop detection fires:** execution paused
- **Final state:** 9 of 10 emails marked read — 1 email never reached

The model entered a repetition loop on a single `message_id` instead of progressing to the remaining unread email.

---

## Root Cause

Two related gaps in `src/gaia/agents/base/agent.py`:

### Gap 1: Result-based dedup only covers query tools

At lines 2921-2946, the result-based dedup mechanism exists but is **limited to `_QUERY_TOOLS`**:

```python
_QUERY_TOOLS = (
    "query_documents",
    "query_specific_file",
    "query_indexed_documents",
)
```

This dedup detects when the same query tool returns the same result hash, and injects a correction message after 2 identical results. **But mutation tools like `mark_read`, `archive_message`, `star_message`, `delete_message` are NOT covered.**

For mutation tools, the same `(tool_name, tool_args)` pair can return the same successful `"ok": true` result indefinitely. There's no framework-level signal telling the model "this email is already marked as read — move to the next one."

### Gap 2: Loop detection is reactive, not corrective

At lines 2883-2913, loop detection works as a sliding window over the last 5 tool calls. It counts consecutive identical `(tool_name, tool_args)` pairs and stops at `max_consecutive_repeats` (default: 4).

**The problem:** this only stops the loop — it doesn't correct the model before the loop starts. The model has already wasted 4 steps (tokens + time) on identical calls before anything happens.

For query tools, result-based dedup fires after 2 identical results — much earlier. For mutation tools, there is no equivalent early detection.

---

## Why the Model Repeats

Small models (4B-class) exhibit strong repetition bias when uncertain:

1. **State loss:** After 12+ steps of conversation history, the model loses implicit tracking of which emails remain unread.
2. **Positional bias:** The model latches onto the last `message_id` it processed (`ded9c6fc390e7cd7`).
3. **No corrective signal:** The framework returns `"ok": true` for idempotent operations, which the model interprets as "success, keep going." There's no signal like "this email was already processed."
4. **Deterministic feedback loop:** Each identical result reinforces the model's confidence that it's doing the right thing.

---

## Impact

| Metric | Expected | Actual |
|--------|----------|--------|
| Steps to mark 10 emails read | ~10-12 sequential calls | 15+ (5 wasted on duplicates) |
| Unique emails marked | 10 | 9 (1 never reached) |
| Tokens consumed (wasted) | 0 | ~4 × 200 tokens = ~800 wasted |
| Time consumed (wasted) | 0 | ~4 × 40s = ~160s wasted |

This affects all batch mutation operations:
- `mark_read` / `mark_unread` (multiple emails)
- `archive_message` (multiple emails)
- `star_message` (multiple emails)
- `delete_message` (multiple emails)

---

## Required Fix

Extend the result-based dedup mechanism to cover mutation tools. The fix should:

1. **Track `(tool_name, tool_args)` result hashes for mutation tools**, not just query tools.
2. **Inject a correction message after the first duplicate result** (same as query tool behavior).
3. **The correction message should be specific to the tool type**, e.g.:
   ```
   [SYSTEM] You already called mark_read on message ded9c6fc390e7cd7 and it
   succeeded. There is no need to call it again on the same message.
   Move on to remaining messages or provide a final answer.
   ```
4. **Define the mutation tool list** alongside the existing `_QUERY_TOOLS` tuple.

---

## Fix Implementation

**Status:** **NOT APPLICABLE** — `src/gaia/agents/base/agent.py` cannot be modified.

The fix was implemented and then reverted. The base `Agent` class is a core shared component that is not within scope for modification.

### Why This Cannot Be Fixed in `agent.py`

`src/gaia/agents/base/agent.py` is the foundational base class for all GAIA agents. Changes to it have cross-cutting impact on every agent that inherits from it. This means:

- Any change must be validated across all 10+ agent implementations
- A regression in the base class affects production users immediately
- The change would need formal review and sign-off before merging

### Alternative Approaches (Not Yet Implemented)

**Option 1: Subclass override in the email agent**
Create a subclass of `Agent` for the email-specific agent that overrides `process_messages()` or `_execute_tool()` to add mutation dedup logic at the subclass level. This isolates the change to the email agent only, without touching the shared base class.

**Option 2: Tool-level dedup in the email backend**
Add dedup logic inside `FakeGmailBackend` / `LiveGmailBackend` methods. When `mark_read` is called with an already-processed `message_id`, return a different result (e.g., `"ok": true, "already_processed": true`) so the model gets a distinct signal. This doesn't require any `agent.py` changes.

**Option 3: Prompt engineering**
Add an explicit instruction to the email agent's system prompt reminding the model to track which emails it has already processed and not repeat operations on the same `message_id`. This is the lightest-touch approach but relies on model compliance.

### Proposed Fix (for reference — code was written then reverted)

### Changes Made

Two changes to `src/gaia/agents/base/agent.py`:

#### 1. Cache initialization (line 1909-1911)

```python
mutation_call_cache: dict[str, int] = (
    {}
)  # call_key → repeat count (result-based dedup for mutations)
```

Added alongside the existing `query_result_cache`. Both are scoped to a single turn — they reset when `process_messages()` is called for a new user command.

#### 2. Mutation tool dedup logic (line 2951-2979, inserted after query dedup)

```python
_MUTATION_TOOLS = (
    "mark_read",
    "mark_unread",
    "archive_message",
    "star_message",
    "delete_message",
)
if tool_name in _MUTATION_TOOLS:
    call_key = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
    if call_key in mutation_call_cache:
        repeat_count = mutation_call_cache[call_key] + 1
        mutation_call_cache[call_key] = repeat_count
        mutation_msg = (
            f"[SYSTEM] You already called {tool_name} with these exact "
            f"arguments and it succeeded. Repeating it will not change "
            f"anything. Call it on a different item, or provide a final "
            f"answer."
        )
        messages.append({"role": "user", "content": mutation_msg})
    else:
        mutation_call_cache[call_key] = 1
```

### Why This Fix (for reference)

**Why `(tool_name, tool_args)` as the key, not result hash?** For mutation tools, the result is always `{"ok": true, ...}` regardless of whether the target was already processed. The idempotent nature of these operations means the result can't distinguish "first time marking this email as read" from "third time marking the same email." Using `(tool_name, tool_args)` directly detects "you're asking me to do the same thing to the same thing again."

**Why not extend the existing `_QUERY_TOOLS` tuple?** Query tools and mutation tools have fundamentally different dedup needs:
- **Query tools:** Dedup on *result hash* — same data retrieved twice means nothing new was found
- **Mutation tools:** Dedup on *call identity* — same action on same target twice is a mistake

Keeping them separate preserves clarity about what each dedup is checking for.

**Why fire on first repeat (count=2), not after 4 like loop detection?** Loop detection is a safety net for infinite loops. This fix is an early correction for *mistakes*. The model makes the mistake once, gets a clear "you already did this" message, and can correct course. Waiting for 4 repeats wastes 3 additional steps before any signal reaches the model.

**Why these 5 tools and no others?** They are the only mutation tools in the email agent that operate on individual items and can be called in a loop. `send_email` is not included because it operates on different recipients/subjects each time — repetition would be a genuine multi-email send, not a loop.

**How this would complement loop detection:** The correction would fire first (step 13 on the first repeat). If the model ignores the correction and continues repeating, loop detection still fires at step 15 (4 consecutive identical calls). Two layers of protection instead of one.

### Expected Post-Fix Behavior (if Option 1 or Option 2 is pursued)

| Step | Action | Notes |
|------|--------|-------|
| 1-2 | Initial planning | — |
| 3-11 | `mark_read` on 9 unique emails | Sequential, one per step |
| 12 | `mark_read` on `ded9c6fc390e7cd7` (1st occurrence) | OK |
| 13 | `mark_read` on `ded9c6fc390e7cd7` (duplicate) | **NEW: correction injected** |
| 14 | Model marks remaining email OR gives final answer | Corrected behavior |

Expected improvement: 9→10 emails marked, 3-4 wasted steps eliminated.

---

## Verification Plan

This fix cannot be verified until a permitted approach (Option 1, 2, or 3) is implemented. Once implemented:
1. Triage 10 emails (Turn 1)
2. Mark all as read (Turn 2)
3. Verify no repetition loop occurs, all 10 emails are marked
4. Verify correction message or backend signal appears if a duplicate is attempted
5. Verify `[DEDUP]` or equivalent log message appears

---

## Related Issues

- **ISSUE-parallel-tool-calls.md** — Parallel tool call retry prompt bug (fixed in this branch)
- Both issues affect the same codebase area (`agent.py` tool execution loop)
- Both are revealed by the email benchmark with small models
- Both are framework-level bugs that also affect production `gaia email` usage
