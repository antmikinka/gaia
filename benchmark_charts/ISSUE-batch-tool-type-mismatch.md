# Issue: Batch Tools Broken — LLM Sends String, Python Iterates Characters

**Observed:** 2026-05-14
**Affected command:** `gaia email bench --mode interactive` AND `gaia email -i` (live interactive)
**Files:** `src/gaia/agents/email/tools/organize_tools.py`, `src/gaia/agents/base/agent.py`, `src/gaia/agents/base/tools.py`

**Classification:** **CRITICAL BUG — type coercion gap in all 7 batch tools; 0% success rate with real LLM input**

---

## Observed Behavior

During an interactive benchmark session with Qwen3.5-4B-GGUF on 10 emails, Turn 2 ("LETS MARK THOSE 10 AS READ") exhibited:

| Step | Tool | Args Type | Errors | Succeeded |
|------|------|-----------|--------|-----------|
| 1 | `mark_read_batch` | `str` (comma-separated) | **169** | **0** |
| 2 | `mark_read_batch` | `str` (identical retry) | **169** | **0** |

**Result: 338 total errors, zero messages marked read, LLM stuck in retry loop.**

The LLM called `mark_read_batch` exactly as intended — once for all 10 emails — but the tool processed each character of the comma-separated string as a separate message ID.

---

## Step-by-Step Reconstruction

### Step 1: LLM constructs the tool call

The LLM correctly identifies the batch tool and passes 10 message IDs, but as a **comma-separated string**:

```json
{
  "tool": "mark_read_batch",
  "arguments": {
    "message_ids": "377bc3bc44e6a005,3fa9f7a6d7b0fad4,75579fcfbcd1f272,60f9d4ef6bf62b7f,805c8132c6c5d46c,13b2d378cd54759c,ded9c6fc390e7cd7,70945c159af861c2,9a3ce896b18fbff1,185c85c463d69ce0"
  }
}
```

Expected (correct Python type):
```json
{
  "tool": "mark_read_batch",
  "arguments": {
    "message_ids": ["377bc3bc44e6a005", "3fa9f7a6d7b0fad4", "75579fcfbcd1f272", ...]
  }
}
```

### Step 2: Base agent passes args without type checking

`agent.py:1431` calls `tool(**tool_args)` directly:
```python
result = tool(**tool_args)
```

The `@tool` decorator (`tools.py`) registers parameter type annotations but performs **zero runtime coercion**. The tool receives `message_ids: str` despite the signature declaring `list[str]`.

### Step 3: `_run_batch` iterates the string character-by-character

`organize_tools.py:224`:
```python
for mid in message_ids:  # message_ids is str → iterates chars!
    try:
        gmail_op(mid)    # gmail.mark_read("3") → KeyError
```

In Python, `for c in "abc"` yields `"a"`, `"b"`, `"c"`. The 169-character string produces 169 iterations, each passing a single hex character as a message ID.

### Step 4: All 169 iterations fail with KeyError

```
KeyError: "FakeGmailBackend: no message '3'"
KeyError: "FakeGmailBackend: no message '7'"
KeyError: "FakeGmailBackend: no message 'b'"
...
```

Error log excerpt:
```
[ERROR] batch op failed for 3     ← first char of "377bc3bc44e6a005"
[ERROR] batch op failed for 7     ← second char
[ERROR] batch op failed for 7     ← third char
[ERROR] batch op failed for b     ← fourth char
...
[ERROR] batch op failed for ,     ← first comma separator
[ERROR] batch op failed for 3     ← first char of next ID
```

### Step 5: Tool returns error envelope (still marked `"ok": true`)

```json
{
  "ok": true,
  "data": {
    "total": 10,
    "succeeded": [],
    "failed": [
      {"message_id": "3", "error": "KeyError: no message '3'"},
      {"message_id": "7", "error": "KeyError: no message '7'"},
      ... 167 more items
    ]
  }
}
```

Note: `"total": 10` is `len(message_ids)` — but `len("id1,id2,...")` is the character count (169), not the ID count. Wait — the output shows `"total": 169` in the actual error. Actually, looking at the code:

```python
"total": len(message_ids)  # len("377bc3bc...") = 169 characters
```

So `"total": 169` is returned, not 10.

### Step 6: LLM retries identically

The LLM sees 169 failures but the error messages (`"no message '3'"`) suggest individual messages don't exist, not that the argument type is wrong. The LLM calls `mark_read_batch` again with the identical string argument — producing 169 more errors.

---

## Root Cause: Type Coercion Gap

### Layer 1: Tool decorator does not coerce types

**File:** `src/gaia/agents/base/tools.py`, lines 47-68

The `@tool` decorator extracts type annotations for registration:
```python
if param.annotation == str:
    param_info["type"] = "string"
elif param.annotation == int:
    param_info["type"] = "integer"
```

But these are **metadata only** — used for tool description/schema, not runtime validation. When the agent executes `tool(**tool_args)`, Python does not enforce type annotations.

### Layer 2: LLMs send lists as comma-separated strings

LLMs (especially smaller models like 4B) naturally represent lists in two ways:
1. **JSON array:** `["id1", "id2", "id3"]` — what the tool expects
2. **Comma-separated string:** `"id1,id2,id3"` — what the LLM actually sends

The JSON array format requires the LLM to understand Python/JSON syntax for arrays. The comma-separated string is natural language — it's how humans write lists. The LLM defaults to the latter.

### Layer 3: Python string iteration silently produces wrong values

When `_run_batch` does `for mid in message_ids:`, Python accepts the string and iterates it. No TypeError is raised because strings are iterable. The code silently processes garbage input without detecting the type mismatch.

---

## Intuition: The Menu Analogy

**Serial tools (before batch):** You order 9 dishes by telling the waiter one dish at a time. Slow but correct.

**Batch tools (after batch, current):** You hand the waiter one order slip listing all 9 dishes: "steak,salad,soup,pasta,pie,coffee,tea,water,bread". But the waiter can't read words — they read **individual letters**. The kitchen receives: 's', 't', 'e', 'a', 'k', ',', 's', 'a', 'l', ... — 169 individual letters instead of 9 dishes. Every item fails because the kitchen has no menu items called "s" or "t".

**Batch tools (fixed):** You hand the waiter the same order slip. This time, the waiter **parses the comma-separated list into individual dish names** before going to the kitchen. One trip, 9 correct dishes.

---

## Impact

### All 7 batch tools are non-functional

| Batch Tool | Expected Input | Actual Input | Success Rate |
|-----------|---------------|--------------|--------------|
| `mark_read_batch` | `list[str]` | `str` | 0% |
| `mark_unread_batch` | `list[str]` | `str` | 0% |
| `add_star_batch` | `list[str]` | `str` | 0% |
| `remove_star_batch` | `list[str]` | `str` | 0% |
| `archive_message_batch` | `list[str]` | `str` | 0% |
| `label_message_batch` | `list[str], str` | `str, str` | 0% |
| `move_to_label_batch` | `list[str], str` | `str, str` | 0% |

All 7 tools share the same `_run_batch` or `_run_batch_with_prior` helper. Both iterate `message_ids` with `for mid in message_ids:` — both are vulnerable.

### Unit tests passed because they use proper types

The test file `test_email_batch_organize.py` passes `message_ids=["id1", "id2", "id3"]` — proper Python lists. The tests never exercise the string→list path because the test harness constructs proper Python objects, not LLM-generated JSON.

**This is a test-reality gap:** the tests verify the internal logic works with correct inputs, but never verify the tool accepts the format real LLMs produce.

### Token waste

Each failed batch call produces:
- 1 LLM step to call the tool
- 1 LLM step to retry (identical failure)
- Potentially more retries before the LLM gives up or hits `max_steps`

This is **worse** than the serial loop (ISSUE-serial-tool-execution.md) because:
- Serial: 13 steps, but 9 emails actually get marked read
- Broken batch: 2+ steps, 0 emails get marked read

---

## Candidate Fixes

### Option 1: Coerce string→list in `_run_batch` (Recommended)

Add one line at the top of `_run_batch` and `_run_batch_with_prior`:

```python
def _run_batch(..., message_ids: list[str], ...):
    # LLMs send comma-separated strings; coerce to list
    if isinstance(message_ids, str):
        message_ids = [x.strip() for x in message_ids.split(",") if x.strip()]
    ...
```

**Pros:**
- Single location protects all 7 batch tools (all call `_run_batch`)
- No changes to base agent loop or tool decorator
- Works with both formats: if LLM sends proper list, no coercion occurs
- Handles edge cases: empty strings, trailing commas, whitespace

**Cons:**
- Silent coercion hides the type mismatch (but the alternative is complete failure)
- Doesn't fix the root cause in the tool decorator

**Estimated effort:** ~4 lines across `_run_batch` and `_run_batch_with_prior`.

### Option 2: Add type coercion to base `@tool` decorator

Extend `tools.py` to coerce argument types at runtime based on registered annotations:

```python
for name, value in tool_args.items():
    expected = params[name]["type"]
    if expected == "array" and isinstance(value, str):
        tool_args[name] = [x.strip() for x in value.split(",")]
```

**Pros:**
- Fixes ALL tools, not just email batch tools
- Prevents this class of bug from recurring
- Centralized in one location

**Cons:**
- Affects ALL agents (chat, code, blender, jira)
- Requires careful handling of edge cases (nested arrays, objects)
- Could mask legitimate type errors
- More complex than Option 1

**Estimated effort:** ~30 lines + testing across all agent types.

### Option 3: System prompt to require JSON array format

Update the email agent system prompt to explicitly instruct:
"When using batch tools, pass message_ids as a JSON array: [\"id1\", \"id2\"]"

**Pros:**
- No code changes
- May help larger models (Claude, GPT-4) that follow instructions better

**Cons:**
- Does NOT fix the bug — just hopes the LLM complies
- Small models (4B) are unreliable at following type format instructions
- Even if the LLM sends JSON array syntax, the Python type coercion gap remains
- This is a band-aid on a type safety issue

**Estimated effort:** ~5 lines in system prompt. Insufficient.

### Option 4: Add validation with descriptive error

Before iterating, check the type and return a helpful error:

```python
if not isinstance(message_ids, list):
    return _envelope_err(
        f"message_ids must be a JSON array of strings, "
        f"not a {type(message_ids).__name__}. "
        f"Example: [\"id1\", \"id2\", \"id3\"]"
    )
```

**Pros:**
- Clear error message that helps the LLM understand the issue
- Fast failure instead of 169 individual errors
- The LLM may learn to send proper arrays after 1-2 retries

**Cons:**
- Still requires the LLM to retry correctly (small models may not)
- Better than Option 3 but not as reliable as Option 1
- Pairs well with Option 1 (coerce + validate fallback)

**Estimated effort:** ~6 lines.

---

## Recommendation

**Implement Option 1 as the primary fix.** Silent string→list coercion is the most reliable approach — it works regardless of what the LLM sends and requires minimal code.

**Implement Option 4 as a fallback validation.** If the coercion produces an empty list (e.g., empty string input), return a descriptive error. This helps debugging.

**Do NOT implement Option 3 alone.** Prompt-only fixes are unreliable with small models and don't address the underlying type safety gap.

**Consider Option 2 as a longer-term architectural improvement.** Type coercion at the tool decorator level benefits all agents but requires careful testing.

---

## Fix Scope

| File | Change | Lines |
|------|--------|-------|
| `src/gaia/agents/email/tools/organize_tools.py` | Add string→list coercion in `_run_batch` and `_run_batch_with_prior` | ~8 |
| `tests/unit/agents/test_email_batch_organize.py` | Add tests for string input coercion | ~20 |
| `src/gaia/agents/email/agent.py` | Optional: update system prompt to show JSON array example | ~3 |

**Total: ~30 lines across 2-3 files.**

---

## Related Issues

- **ISSUE-serial-tool-execution.md** — The original issue that motivated batch tools
- **ISSUE-parallel-tool-calls.md** — Parallel tool call support in base agent

---

## Validation Checklist

- [ ] String→list coercion added to `_run_batch`
- [ ] String→list coercion added to `_run_batch_with_prior`
- [ ] Unit tests for string input (all 7 batch tools)
- [ ] Unit tests for edge cases: empty string, trailing comma, whitespace
- [ ] Interactive benchmark re-run confirms 10 emails marked read in 1 tool call
- [ ] No regression in existing list-input tests
