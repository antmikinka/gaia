# PR1 Description: Interactive Smart-Mode Token Explosion Fix

## Why this matters

Before: `--mode interactive --smart` consumed 400K-2M tokens at limit 100. The runner called `agent.process_query()` unconditionally, which runs the full agent planning loop with unconstrained LLM invocations. The heuristic pre-filter -- which classifies 60-90% of emails without LLM calls in single-turn modes -- was completely bypassed. Two blocking defects prevented smart mode from working: (1) `conversation_history` was overwritten with only the last turn's data, discarding all prior context, and (2) no dispatch logic routed smart-mode requests to the heuristic fast-path.

After: `--mode interactive --smart` consumes 20K-50K tokens at limit 100 (80-95% reduction). The runner dispatches Turn 1 to `process_interactive_smart_triage()`, which runs heuristic classification directly (zero LLM tokens), skips LLM for confident emails, and only batches non-confident ones through the LLM. Conversation history accumulates correctly across turns. Non-smart modes are unaffected.

## Test plan

- [ ] `process_interactive_smart_triage()` classifies confident emails without LLM calls
- [ ] Non-confident emails are batched through LLM with correct batch size
- [ ] `_should_use_llm()` gate returns False for cached confident emails
- [ ] `_should_use_llm()` respects `force_llm=True` and `force_llm_ids` overrides
- [ ] `sync_smart_triage_cache()` correctly populates agent cache from runner state
- [ ] Runner dispatches to smart triage on Turn 1 when `enable_smart_mode=True`
- [ ] Runner dispatches to `process_query()` on Turns 2+ for action-oriented prompts
- [ ] Runner falls through to `process_query()` when `enable_smart_mode=False`
- [ ] Conversation history accumulates (not overwrites) across turns at both locations
- [ ] Token fields reflect actual LLM usage (0 for heuristic-only, real counts for LLM batches)
- [ ] `reclassify` command moves email from heuristic to LLM cache with `force_llm_ids` wiring
- [ ] End-to-end 4-turn session: Turn 1 classifies all, Turns 2-4 hit prior-turn cache
- [ ] No regression: `--mode full`, `--mode batched`, and `--mode interactive` (no `--smart`) produce identical results to pre-fix baseline
- [ ] `_is_triage_prompt` has no false positives on summary/action prompts like "show me my inbox"
- [ ] `_normalize_agent_result` handles empty string input without crashing
