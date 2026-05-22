# Migration: Interactive Smart-Mode Token Fix

**Applies to:** Users running `gaia email bench --mode interactive --smart`
**Date:** 2026-05-21

---

## What Changed

If you were running `--mode interactive --smart` before this fix, your benchmark was **not using the heuristic fast-path**. Every turn called `agent.process_query()`, which runs the full agent planning loop with unconstrained LLM invocations. Token consumption was 400K-2M tokens at limit 100.

After this fix, `--mode interactive --smart` calls `agent.process_interactive_smart_triage()` instead. This method:

1. Runs the heuristic pre-filter on all emails (zero LLM tokens)
2. Skips LLM for emails the heuristic classified with confidence (typically 60-90%)
3. Only batches non-confident emails through the LLM
4. Returns a compact result dict (not the full conversation history)

**Expected token consumption after fix: 20K-50K tokens at limit 100** (80-95% reduction).

---

## What Did Not Change

| Feature | Status |
|---------|--------|
| `--mode full` | Unchanged — still calls `process_query()` |
| `--mode batched` | Unchanged — still calls `process_batched_triage()` |
| `--mode interactive` (without `--smart`) | Unchanged — still calls `process_query()` |
| `--mode smart` (without `--interactive`) | Unchanged — still calls `process_smart_triage()` |
| `--force-llm` flag | Works as before — bypasses heuristic, all emails use LLM |
| `--batch-size` flag | Still controls LLM batch size for non-confident emails |
| Session state tracking | Same `SessionState` model (archived, starred, drafted, etc.) |
| `reclassify` command | Same syntax: `reclassify <email_id>` |
| `state` / `status` commands | Same output format |

---

## Breaking Behavioral Change: Conversation History

**Before:** Each turn's full conversation history (including all tool results with complete email bodies) was appended to `agent.conversation_history`. By turn 3-4, this typically exceeded 100K tokens of accumulated context.

**After:** Each turn calls `process_interactive_smart_triage()` which returns a compact structured dict. The runner sets `agent.conversation_history` to this compact result, effectively **resetting context each turn**. Prior turn context is not available to the agent in subsequent turns.

**Impact:** The agent cannot reference emails or actions from previous turns. For example, "archive the emails I flagged in turn 2" will not work because the agent has no memory of turn 2's results.

**Workaround:** Use the `state` command to see the current session state (archived, starred, triaged emails). The runner maintains session state across turns — only the agent's conversation history is reset.

---

## How to Verify You Are Using the Fixed Path

### 1. Check the per-turn output

In the fixed path, each turn's output includes a smart-mode breakdown:

```
  Smart-Mode Breakdown
  ────────────────────────────────────────────────────
  Heuristic (confident): 7 emails
    [msg_1] -> informational (heuristic)
    [msg_2] -> informational (heuristic)
    ...
  LLM (non-confident): 3 emails
    [msg_5] -> actionable (llm)
    ...
  Heuristic savings:     ~150 tokens (7 LLM calls avoided)
```

If you see this output, you are on the fixed path. If you see only LLM planning steps with no heuristic breakdown, you are on the old path.

### 2. Check token counts per turn

In the fixed path, heuristic-only turns show `total_tokens: 0` or very low token counts (only the LLM-batched emails contribute tokens). If every turn shows 50K-200K tokens, you are on the old path.

### 3. Verify the code path

Check that `runner.py` line ~754 (in `run_interactive_benchmark`) or line ~1233 (in `run_interactive_session`) calls `agent.process_interactive_smart_triage()` when `enable_smart_mode=True`. If it calls `agent.process_query()` unconditionally, you are on the old path.

### 4. Check git log

```bash
git log --oneline --grep="interactive.*smart" -- src/gaia/agents/email/agent.py
```

You should see a commit adding `process_interactive_smart_triage` method.

---

## Migration Steps

No action is required if you are on the `feat/email-bench-visualizations` branch after this fix. The dispatch is automatic based on the `--smart` flag.

If you have **saved benchmark results** from before this fix:

1. **Do not compare old and new results directly** — the token counts are not comparable because the old path was not using the heuristic fast-path.
2. **Re-run old benchmarks** with the new code to get accurate baselines.
3. **Label your results** — add a note to your benchmark result files indicating whether they were run before or after the fix.

If you have **custom scripts** that call `agent.process_query()` directly for smart-mode benchmarking:

1. Update to call `agent.process_interactive_smart_triage(user_prompt=..., max_messages=...)` instead.
2. The return type is a `dict` (not a JSON string). Key fields: `conversation`, `result`, `input_tokens`, `output_tokens`, `total_tokens`, `total_emails`, `confident_count`, `needs_llm_count`, `triage_summary`, `run_id`.
3. After each turn, call `agent.sync_smart_triage_cache(heuristic_ids=..., llm_ids=...)` to bridge classification results into the agent's cache.
