# PR2 Description: Context Compaction + Gate Logging + Dual-Path Summary

## Why this matters

Before: After PR1's smart-mode dispatch fix, residual token growth remained unaddressed. Tool results echoed verbatim in conversation history, causing 10x-20x context growth across multi-turn sessions. The LLM gate (`_should_use_llm`) made silent decisions with no observability into why an email was routed to heuristic vs LLM. `TurnResult` lacked fields to track per-turn heuristic/LLM splits, making it impossible to visualize the dual-path breakdown. Non-triage prompts like "show me my inbox" could accidentally trigger smart dispatch on Turn 1 because the triage prompt guard only checked for the word "inbox".

After: Context compaction truncates only body/snippet text while preserving all structural keys, bounding conversation growth to under the raw accumulation baseline. Every LLM gate decision emits an INFO-level log with email ID, gate path, and confidence status. `TurnResult` gains `heuristic_email_count`, `llm_email_count`, and `gate_decisions` fields for per-turn granularity. The `_is_triage_prompt` guard now requires a triage verb (triage/categorize/classify), eliminating false positives. Chart 23 renders dual-path heuristic vs LLM breakdown for interactive smart runs. Non-smart modes remain completely unaffected.

## Test plan

- [ ] Context compaction preserves structural keys (role, tool name, metadata) while truncating body/snippet text
- [ ] Context compaction is a no-op when conversation is under the character limit
- [ ] Context compaction handles empty conversation lists without error
- [ ] LLM gate logs at INFO level for all 4 decision paths (heuristic-confident, LLM-escalation, force-LLM override, prior-turn cache)
- [ ] All gate log records are INFO level, not DEBUG
- [ ] `TurnResult` new fields default to zero/empty, not None
- [ ] Per-turn heuristic/LLM email counts are accurate after smart triage
- [ ] Non-triage turns have zero heuristic/LLM email counts
- [ ] `TurnResult.context_compacted` flag is set when compaction occurs
- [ ] `TurnResult.gate_decisions` list contains one entry per classified email
- [ ] `_is_triage_prompt` returns False for "show me my inbox", "what's in my inbox", "count emails in inbox", "clear my inbox"
- [ ] `_is_triage_prompt` returns True for "triage my inbox", "categorize these emails", "classify my inbox"
- [ ] `_normalize_agent_result` raises a clear error on empty string input
- [ ] Session state sync handles missing conversation key, empty list, and malformed tool content without crashing
- [ ] Smart summary round-trips through `json.dumps`/`json.loads` without error
- [ ] Smart summary contains all 24 base keys plus smart-mode keys (heuristic_triaged, llm_triaged, heuristic_savings)
- [ ] `heuristic_savings` sub-keys present: llm_calls_saved, estimated_tokens_saved, saved_percentage
- [ ] No double-counting: heuristic_triaged + llm_triaged == triaged_emails total
- [ ] Non-smart interactive mode output structure is unchanged (smart keys present but empty)
- [ ] Chart 23 renders correctly with interactive smart summary data
- [ ] Chart 23 handles edge cases: 100% heuristic, 100% LLM, empty runs, no triaged emails
- [ ] `plot_smart_turn_split` renders with multi-turn, single-turn, and missing smart-field data
- [ ] Full smart benchmark path: Turn 1 uses smart dispatch, Turns 2-4 fall through to process_query
- [ ] Token consumption at limit 100 stays under 100K target
- [ ] Heuristic classification rate >= 70% on stub dataset
- [ ] Context growth rate after compaction is <= 2x the raw token count per turn
- [ ] Non-smart batched mode is unaffected by smart-mode changes
