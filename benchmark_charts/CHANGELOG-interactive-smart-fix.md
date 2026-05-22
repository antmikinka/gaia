# Changelog: Interactive Smart-Mode Token Explosion Fix

**Date:** 2026-05-21
**Branch:** `feat/email-bench-visualizations`
**Author:** Anthony Mikinka

---

## Summary

Fixed a token explosion bug in `--mode interactive --smart` where token consumption reached 400K-2M tokens at limit 100 (expected: <50K). The heuristic pre-filter, which classifies 60-90% of emails without LLM calls in single-turn modes, was completely bypassed because the interactive runner called `agent.process_query()` instead of dispatching to `process_interactive_smart_triage()`. Two pull requests address the fix.

- **PR1** -- Fix conversation history overwrite at 2 locations, add conditional smart-mode dispatch with triage-prompt keyword guard, and add 6 helper functions for smart-mode orchestration.
- **PR2** -- Add context compaction, tool-level LLM gate logging, `TurnResult` fields for per-turn heuristic/LLM splits, dual-path summary visualization, and fix `_is_triage_prompt` false positives.

---

## Root Causes Addressed

| ID | Root Cause | Fix |
|----|-----------|-----|
| RC-1 | `conversation_history` overwritten at end of each turn, discarding all prior context | Fix at 2 locations in runner.py: accumulate via `.extend()` instead of `=` assignment |
| RC-2 | No smart-mode dispatch -- runner calls `process_query()` unconditionally, bypassing heuristic fast-path | Add conditional dispatch: `enable_smart_mode and _is_triage_prompt()` -> `process_interactive_smart_triage()` |
| RC-3 | `_should_use_llm()` gate exists but is never consulted from the interactive path | New method calls `_should_use_llm()` for every email before deciding LLM vs heuristic |
| RC-4 | Smart mode instructions are advisory only -- LLM reads confident emails regardless | Heuristic results cached in `_smart_triaged_cache` and consulted before any LLM call |
| RC-5 | No context compaction -- tool results echoed verbatim in conversation history, causing 10x-20x growth | Context compaction truncates body/snippet text while preserving structural keys; `_is_triage_prompt` guard requires triage verb to prevent false-positive smart dispatch |

---

## Token Impact

| Mode | Before (limit 100) | After (limit 100) | Reduction |
|------|--------------------|-------------------|-----------|
| `--mode interactive --smart` | 400K-2M tokens | 20K-50K tokens | 80-95% |
| `--mode interactive --smart --force-llm` | 400K-2M tokens | 200K-400K tokens | 50-75% |

The exact reduction depends on inbox composition. Promotional inboxes with 80%+ heuristic-confident emails see the largest savings.

---

## Breaking Changes

### Conversation History Behavior

**Before:** Each turn's full conversation history (including all tool results with complete email bodies) was appended to `agent.conversation_history`. By turn 3-4, this typically exceeded 100K tokens of accumulated context.

**After:** Smart-mode turns return a compact structured dict. The runner accumulates entries via `.extend()` but context compaction truncates body/snippet fields. Prior-turn context is preserved structurally but with reduced verbosity.

**Impact:** The agent retains awareness of prior turns, but with bounded context. Multi-turn references like "archive the emails I flagged in turn 2" will work as long as the compacted summary contains the email IDs.

### `_is_triage_prompt` Behavior Change

The guard now requires a triage verb (`triage`, `categorize`, `classify`) rather than matching any prompt containing "inbox". Prompts like "show me my inbox" or "what's in my inbox" no longer trigger smart dispatch on Turn 1. This is a bug fix, not a regression, but may affect any automation that relied on the previous loose matching.

---

## Migration Notes

### No Action Required for Standard Users

If you run `gaia email bench --mode interactive --smart` on the `feat/email-bench-visualizations` branch after this fix, the dispatch is automatic. No flag changes are needed.

### Re-Run Old Benchmarks

Do not compare pre-fix and post-fix token counts directly. The measurement instrument changed fundamentally:

1. Re-run any saved benchmarks with the new code to get accurate baselines.
2. Label result files as pre-fix or post-fix to avoid mixing incomparable data.
3. Charts 24-29 will render correctly with post-fix data, but pre-fix bars will dominate the scale if mixed.

### Custom Scripts Calling `process_query()` Directly

If you have custom benchmarking scripts that call `agent.process_query()` for smart-mode scenarios:

1. Update to call `agent.process_interactive_smart_triage(user_prompt=..., max_messages=...)` on Turn 1.
2. The return type is a `dict` (not a JSON string) with keys: `conversation`, `result`, `input_tokens`, `output_tokens`, `total_tokens`, `total_emails`, `confident_count`, `needs_llm_count`, `triage_summary`, `run_id`.
3. After each turn, call `agent.sync_smart_triage_cache(heuristic_ids=..., llm_ids=...)` to bridge classification results into the agent cache.

---

## Known Limitations

1. **Token fields are 0 when no LLM is called** -- When all emails are heuristic-confident, `input_tokens`, `output_tokens`, and `total_tokens` in the turn result are 0. This is correct (no LLM was invoked) but may confuse downstream charting that assumes non-zero tokens.
2. **No per-email token granularity in heuristic results** -- Heuristic-classified emails get `token_count=0` in the SQLite `email_triage_results` table. There is no estimated token cost for what the LLM would have used.
3. **`force_llm_ids` empty dict normalization** -- The `or None` pattern means an empty dict becomes `None`. This is benign but could be cleaner.
