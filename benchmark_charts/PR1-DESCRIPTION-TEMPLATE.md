## PR Description Template: PR1 — Interactive Smart-Mode Triage

---

### Why this matters

Before: `--mode interactive --smart` consumed 400K-2M tokens at limit 100 because it bypassed the heuristic pre-filter and ran the full agent planning loop for every turn. The `confident` flags from `triage_inbox` were advisory metadata that the LLM ignored — it classified every email regardless.

After: `--mode interactive --smart` consumes 20K-50K tokens at limit 100 (80-95% reduction). A new `process_interactive_smart_triage()` method runs heuristic classification directly (zero LLM tokens), skips LLM for confident emails (60-90% of typical inboxes), and only batches uncertain emails through the LLM. Context is bounded per turn instead of accumulating across turns.

### Test plan

- [ ] `process_interactive_smart_triage()` classifies confident emails without LLM calls (unit test)
- [ ] Non-confident emails are batched through `_process_single_batch()` with correct batch size (unit test)
- [ ] `_should_use_llm()` returns False for cached confident emails, True for unknown emails (unit test)
- [ ] `_should_use_llm()` respects `force_llm=True` config override (unit test)
- [ ] `_should_use_llm()` respects `force_llm_ids` per-email override (unit test)
- [ ] `sync_smart_triage_cache()` correctly populates agent cache from runner state (unit test)
- [ ] Runner dispatches to `process_interactive_smart_triage()` when `enable_smart_mode=True` (integration test)
- [ ] Runner dispatches to `process_query()` when `enable_smart_mode=False` (integration test)
- [ ] Token fields in turn result reflect actual LLM usage (0 for heuristic-only, real counts for LLM batches) (integration test)
- [ ] `reclassify` command moves email from heuristic to LLM cache and wires `force_llm_ids` (integration test)
- [ ] End-to-end 4-turn session: turn 1 classifies all, turns 2-4 hit cache (integration test)
- [ ] No regression: `--mode full` and `--mode batched` produce identical results to pre-fix baseline

### Scope

3 files changed:

| File | Change |
|------|--------|
| `src/gaia/agents/email/agent.py` | Added `process_interactive_smart_triage()`, `_should_use_llm()`, `sync_smart_triage_cache()` |
| `src/gaia/agents/email/bench/runner.py` | Conditional dispatch to new method for smart mode; cache sync after each turn |
| `tests/unit/agents/test_email_agent_interactive_smart_triage.py` | New test file (35+ test cases) |

No changes to `--mode full`, `--mode batched`, or `--mode smart` (single-turn) paths.
