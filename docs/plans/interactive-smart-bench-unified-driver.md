# Unified Implementation Driver: Interactive Smart Bench

**Document Type**: Implementation Driver (Execution-Ready)
**Target**: Software Program Manager
**Source Branch**: `feat/email-bench-visualizations`
**Date**: 2026-05-21
**Status**: Ready for execution planning

---

## 1. Executive Summary

Interactive Smart Bench enables a hybrid heuristic + selective LLM escalation path for email triage benchmarking. The agent already implements `process_interactive_smart_triage()` (agent.py:410-561) and the runner already extracts `confident` flags from triage results (runner.py:968-985). **Two blocking defects prevent this from working end-to-end:**

1. **BLOCKING BUG**: `runner.py:1264` overwrites `agent.conversation_history` with the last turn's minimal single-element conversation list, discarding all prior turn context.
2. **BLOCKING GAP**: `runner.py:1233` (`run_interactive_session`) and `runner.py:754` (`run_interactive_benchmark`) call `agent.process_query()` unconditionally -- they never dispatch to `process_interactive_smart_triage()` when `enable_smart_mode=True`.

Fix these two items first. Everything else builds on top.

---

## 2. Priority Order

| Priority | Task | Files | Blocking? | PR |
|----------|------|-------|-----------|-----|
| **P0-A** | Fix `conversation_history` overwrite at runner.py:1264 | `runner.py` | YES -- blocks multi-turn smart | PR1 |
| **P0-B** | Add conditional smart-mode dispatch in runner turn loop | `runner.py` | YES -- blocks smart triage | PR1 |
| **P1** | Harden `process_interactive_smart_triage` + session state wiring | `agent.py`, `data_shapes.py`, `runner.py` | No | PR1 |
| **P2** | Context compaction + tool-level LLM gate + token tracking | `agent.py`, `runner.py`, `data_shapes.py` | No | PR2 |
| **P3** | Dual-path summary generation + visualization support | `runner.py`, `visualize.py`, `output.py` | No | PR2 |

---

## 3. P0: Blocking Bug Fixes (PR1)

### P0-A: Fix conversation_history overwrite (runner.py:1264)

**Location**: `src/gaia/agents/email/bench/runner.py`, lines 1264-1266 (within `run_interactive_session`)

**Current code:**
```python
conversation = agent_result.get("conversation", [])
if conversation:
    agent.conversation_history = conversation
```

**Problem**: This replaces the entire `agent.conversation_history` with whatever the last turn returned. In smart mode, `process_interactive_smart_triage()` returns a single-element list containing only the `triage_inbox` tool result. Prior turns' assistant messages and user prompts are lost, so the LLM has no memory of what was said before.

**Same pattern exists in `run_interactive_benchmark`** at lines 786-788 (same file, same bug).

**Fix**: Accumulate rather than replace. Append the new turn's conversation entries to the existing history:

```python
conversation = agent_result.get("conversation", [])
if conversation:
    # Accumulate: preserve prior turns, add new entries.
    agent.conversation_history.extend(conversation)
```

**Impact**: Without this fix, multi-turn smart sessions lose all context after Turn 1. The LLM cannot reference prior classifications, actions, or user instructions.

---

### P0-B: Add conditional smart-mode dispatch (runner.py:1233, runner.py:754)

**Locations**:
- `runner.py:1233` -- `run_interactive_session` turn loop
- `runner.py:754` -- `run_interactive_benchmark` turn loop

**Current code** (both locations):
```python
agent_result = agent.process_query(prompt)
```

**Problem**: `process_query()` enters the full agent loop (LLM planning, tool selection, execution). In smart mode, the first turn should use `process_interactive_smart_triage()` which bypasses the LLM for confident emails and only uses LLM batches for non-confident ones. The unconditional `process_query()` call wastes tokens and does not produce the structured result shape that smart-mode extraction expects.

**Fix**: In `run_interactive_session`, add a mode-aware dispatch in the turn loop:

```python
if enable_smart_mode and turn_num == 1:
    # First turn in smart mode: use the direct triage path
    # (bypasses full agent loop, respects heuristic confident flag).
    agent_result = agent.process_interactive_smart_triage(
        user_prompt=prompt,
        max_messages=limit,
    )
else:
    agent_result = agent.process_query(prompt)
```

**Rationale for `turn_num == 1` guard**: The first turn is "Triage my inbox" which maps directly to `process_interactive_smart_triage`. Subsequent turns ("Archive the low priority emails", "Star urgent messages") are action-oriented and must go through the full agent loop to plan and execute tool calls. The triage results from Turn 1 are cached in `_smart_triaged_cache` and inform `_should_use_llm()` on subsequent turns.

**For `run_interactive_benchmark`**: Apply the same pattern at line 754.

**Session state synchronization**: After the smart-mode first turn, the runner's `SessionState` must be populated from the agent's internal cache. Add this after the smart-mode dispatch:

```python
if enable_smart_mode and turn_num == 1:
    # ... dispatch to process_interactive_smart_triage ...
    # Sync SessionState from agent's cache.
    for eid, entry in agent._smart_triaged_cache.items():
        cat = entry.get("category", "unknown")
        state.triaged_emails[eid] = cat
        if entry.get("source") == "heuristic":
            if eid not in state.heuristic_triaged:
                state.llm_calls_saved += 1
                state.heuristic_token_estimate += 50
            state.heuristic_triaged[eid] = cat
        else:
            state.llm_triaged[eid] = cat
```

---

## 4. P1: Harden process_interactive_smart_triage + Session State Wiring (PR1)

### 4.1 Function: split_by_confidence(results)

**Where**: Runner-level helper in `runner.py` (not an agent method).

**Rationale**: The partitioning logic `[e for e in all_emails if e.get("confident")]` currently lives inside `process_interactive_smart_triage()` (agent.py:468-469). Extracting it as a runner-level helper allows:
- The runner to independently validate the partition before and after the agent call
- Test harnesses to verify partitioning without mocking the agent
- Future visualization code to access the split for dual-path output

**Implementation**:
```python
def split_by_confidence(
    triage_results: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Partition triage_inbox results into confident (heuristic) and
    non-confident (needs LLM) lists.

    Returns (confident_emails, needs_llm_emails).
    """
    confident = [e for e in triage_results if e.get("confident")]
    needs_llm = [e for e in triage_results if not e.get("confident")]
    return confident, needs_llm
```

**Usage**: Called by the runner after `triage_inbox` returns, and optionally by visualization code to annotate dual-path charts.

---

### 4.2 Function: mark_for_escalation(email_id, state)

**Where**: `SessionState` update in `runner.py` (already partially implemented).

**Current state**: The `reclassify` command in `run_interactive_session` (runner.py:1200-1218) already handles escalation:
```python
if enable_smart_mode and prompt.lower().startswith("reclassify "):
    email_id = prompt.split(None, 1)[1].strip()
    if email_id in state.heuristic_triaged:
        cat = state.heuristic_triaged.pop(email_id)
        state.llm_triaged[email_id] = cat
        state.force_llm_ids[email_id] = "user-requested"
        agent.config.force_llm_ids[email_id] = "user-requested"
```

**Gap**: This only works for emails already in `state.heuristic_triaged`. It should also handle emails that were classified as confident by `process_interactive_smart_triage` but not yet synced to `state`. The fix is to check `agent._smart_triaged_cache` as a fallback:

```python
def mark_for_escalation(email_id: str, state: SessionState, agent) -> str:
    """Mark an email for LLM re-classification on the next triage.

    Returns a status message for the user.
    """
    # Already in session state?
    if email_id in state.heuristic_triaged:
        cat = state.heuristic_triaged.pop(email_id)
        state.llm_triaged[email_id] = cat
        state.force_llm_ids[email_id] = "user-requested"
        agent.config.force_llm_ids[email_id] = "user-requested"
        return f"Marked [{email_id}] for LLM reclassification (next triage will use LLM)."
    # Check agent cache (from current turn's smart triage).
    entry = getattr(agent, "_smart_triaged_cache", {}).get(email_id)
    if entry and entry.get("confident"):
        entry["confident"] = False
        state.force_llm_ids[email_id] = "user-requested"
        agent.config.force_llm_ids[email_id] = "user-requested"
        return f"Marked [{email_id}] for LLM reclassification."
    # Already in triaged_emails (from a prior full-mode turn).
    if email_id in state.triaged_emails:
        state.force_llm_ids[email_id] = "user-requested"
        agent.config.force_llm_ids[email_id] = "user-requested"
        return f"Marked [{email_id}] for user-requested LLM review."
    return f"Email [{email_id}] not found in triaged results."
```

---

### 4.3 Function: generate_interactive_smart_summary()

**Where**: `runner.py` output function (not an agent method).

**Rationale**: The summary should be generated by the runner after the session completes, using the accumulated `SessionState` and `TurnResult` data. This keeps the summary format decoupled from the agent's internal representation and allows visualization code to consume a standardized shape.

**Implementation**:
```python
def generate_interactive_smart_summary(
    state: SessionState,
    turns: list[TurnResult],
    run_id: str,
    model_id: str,
    total_duration_ms: int,
) -> dict:
    """Produce the dual-path summary for an interactive smart session.

    Returns a dict suitable for JSON serialization and chart generation.
    """
    total_tokens = sum(t.total_tokens for t in turns)
    total_input = sum(t.input_tokens for t in turns)
    total_output = sum(t.output_tokens for t in turns)

    h_count = len(state.heuristic_triaged)
    l_count = len(state.llm_triaged)
    total_processed = h_count + l_count

    return {
        "run_id": run_id,
        "model": model_id,
        "total_turns": len(turns),
        "total_duration_ms": total_duration_ms,
        "total_tokens": total_tokens,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        # Dual-path breakdown.
        "heuristic_count": h_count,
        "llm_count": l_count,
        "heuristic_pct": round(h_count / total_processed * 100, 1) if total_processed else 0,
        "llm_pct": round(l_count / total_processed * 100, 1) if total_processed else 0,
        # Per-email classification (for visualization).
        "per_email_classification": [
            {"email_id": eid, "category": cat, "confident": True, "source": "heuristic"}
            for eid, cat in sorted(state.heuristic_triaged.items())
        ] + [
            {"email_id": eid, "category": cat, "confident": False, "source": "llm"}
            for eid, cat in sorted(state.llm_triaged.items())
        ],
        # Token efficiency.
        "llm_calls_saved": state.llm_calls_saved,
        "heuristic_token_estimate": state.heuristic_token_estimate,
        # Session actions.
        "session_state": {
            "archived": sorted(state.archived),
            "starred": sorted(state.starred),
            "drafted": sorted(state.drafted),
            "sent": sorted(state.sent),
            "marked_read": sorted(state.marked_read),
            "deleted": sorted(state.deleted),
            "triaged": dict(state.triaged_emails),
        },
        "turns": turns,
    }
```

**Integration**: Replace the current inline summary construction at `runner.py:1360-1399` with a call to this function. The existing return dict shape must be preserved for backward compatibility with `bench_runner.py:191-288`.

---

## 5. P2: Context Compaction + Tool-Level LLM Gate + Token Tracking (PR2)

### 5.1 Structured JSON Compaction

**Problem**: The `conversation_history` grows unbounded across turns. Each turn appends the full tool result JSON (which can be 10K+ tokens for triage_inbox results on large inboxes).

**Fix**: When appending to `conversation_history` (per P0-A fix), compact tool result content to a structured summary:

```python
def _compact_tool_result(content: str | dict | list, max_chars: int = 500) -> str:
    """Compact a tool result for context retention.

    Preserves the JSON structure keys but truncates large values.
    """
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            return json.dumps(_compact_dict(parsed, max_chars))
        except json.JSONDecodeError:
            return content[:max_chars]
    if isinstance(content, dict):
        return json.dumps(_compact_dict(content, max_chars))
    if isinstance(content, list):
        return json.dumps([_compact_dict(item, max_chars) if isinstance(item, dict) else item for item in content[:10]])
    return str(content)[:max_chars]
```

**When**: Applied during `conversation_history.extend()` in the turn loop.

### 5.2 Tool-Level LLM Gate Logging

**Location**: `agent.py:_should_use_llm()` (lines 563-578)

**Current**: Returns `True`/`False` with no logging.

**Fix**: Add INFO-level logging for gate decisions:

```python
def _should_use_llm(self, email_id: str) -> bool:
    if not getattr(self.config, "enable_smart_mode", False):
        return True
    if getattr(self.config, "force_llm", False):
        logger.info("LLM gate: force_llm=True -> use LLM for %s", email_id)
        return True
    triaged = getattr(self, "_smart_triaged_cache", {})
    entry = triaged.get(email_id)
    if entry is None:
        logger.info("LLM gate: unknown email %s -> use LLM", email_id)
        return True
    if entry.get("confident"):
        logger.info("LLM gate: %s confident=True (source=%s) -> skip LLM", email_id, entry.get("source"))
        return False
    logger.info("LLM gate: %s confident=False -> use LLM", email_id)
    return True
```

### 5.3 Per-Turn Token Budget Tracking

**Add to data_shapes.py**: `TurnResult` gains two new fields:

```python
@dataclass
class TurnResult:
    # ... existing fields ...
    # Smart-mode additions.
    heuristic_email_count: int = 0   # emails handled by heuristic only this turn
    llm_email_count: int = 0         # emails sent to LLM this turn
    smart_mode: bool = False         # whether this turn used smart-mode dispatch
```

**Population**: In `run_interactive_session`, after the smart-mode dispatch:
```python
if enable_smart_mode and turn_num == 1:
    heuristic_email_count = result.get("confident_count", 0)
    llm_email_count = result.get("needs_llm_count", 0)
```

---

## 6. P3: Dual-Path Summary Generation + Visualization Support (PR2)

### 6.1 Dual-Path Output

The `generate_interactive_smart_summary()` function (Section 4.3) produces a dual-path breakdown:

- **Heuristic path**: `heuristic_count`, `heuristic_pct`, per-email list with `confident=True`
- **LLM path**: `llm_count`, `llm_pct`, per-email list with `confident=False`

This is already partially supported by the existing `bench_runner.py:265-284` output serialization (which writes `heuristic_triaged`, `llm_triaged`, `per_email_classification` to JSON).

### 6.2 Visualization Hooks

**Chart 23 (Heuristic vs LLM escalation)** already exists in `visualize.py`. Verify it consumes the correct fields:
- `heuristic_only_count` -> maps to `summary["heuristic_only_count"]`
- `llm_escalated_count` -> maps to `summary["llm_escalated_count"]`

**New visualization**: Per-turn heuristic/LLM split waterfall. Add to `visualize.py`:
```python
def plot_smart_turn_split(interactive: dict, output_dir: Path) -> Path | None:
    """Stacked bar showing heuristic vs LLM emails per turn."""
    # Uses turns[].heuristic_email_count and turns[].llm_email_count
```

---

## 7. Success Criteria (Merged)

| Criterion | Source | Measurement |
|-----------|--------|-------------|
| **>=70% emails handled by heuristic only** | User spec | `heuristic_count / total_processed >= 0.70` |
| **confident flag accurately stored** | User spec | `state.heuristic_triaged` matches `agent._smart_triaged_cache` entries with `confident=True` |
| **Dual-path output** | User spec | Summary JSON contains both `heuristic_count` and `llm_count` with non-zero values (assuming mixed inbox) |
| **Works in single+multi-turn** | User spec | Turn 1 uses smart dispatch; Turns 2+ use full agent loop with cached triage results |
| **<100K total tokens at limit 100** | Pipeline | `total_tokens < 100_000` in summary output |
| **No regression on non-smart mode** | Pipeline | `--mode interactive` without `--smart` produces identical results as before |
| **Context growth bounded** | Pipeline | `len(agent.conversation_history)` does not exceed `max_turns * compacted_entry_size` |

---

## 8. Test Plan

### 8.1 Existing Tests (35+ cases designed)

The file `tests/unit/agents/test_email_agent_interactive_smart_triage.py` already contains 7 test cases covering:

| Test | What it validates | Status |
|------|-------------------|--------|
| `test_mixed_emails_confident_cached_llm_batched` | Confident cached, non-confident batched | PASS |
| `test_all_confident_no_llm` | All confident -> no LLM call | PASS |
| `test_no_confident_all_llm` | No confident -> all go to LLM | PASS |
| `test_empty_inbox` | Empty inbox -> zero counts | PASS |
| `test_prior_turn_cached_emails_skipped` | Prior turn cache respected | PASS |
| `test_force_llm_bypasses_cache` | force_llm overrides cache | PASS |
| `test_process_smart_triage_still_returns_json_string` | No regression on process_smart_triage | PASS |
| `test_smart_triaged_cache_shared_between_methods` | Cache shared across methods | PASS |

### 8.2 Additional Tests Required (PR1)

| # | Test | File | What |
|---|------|------|------|
| T1 | `test_split_by_confidence` | `test_runner.py` | Verify partitioning logic |
| T2 | `test_conversation_history_accumulates` | `test_runner.py` | P0-A fix: history grows, not replaced |
| T3 | `test_smart_mode_dispatch_first_turn` | `test_runner.py` | P0-B fix: Turn 1 uses smart triage |
| T4 | `test_subsequent_turns_use_process_query` | `test_runner.py` | P0-B: Turns 2+ use full agent loop |
| T5 | `test_session_state_synced_after_smart_triage` | `test_runner.py` | SessionState populated from agent cache |
| T6 | `test_mark_for_escalation_from_cache` | `test_runner.py` | mark_for_escalation checks agent cache |
| T7 | `test_generate_interactive_smart_summary` | `test_runner.py` | Summary shape and dual-path counts |
| T8 | `test_no_regression_non_smart_mode` | `test_runner.py` | `--mode interactive` without `--smart` unchanged |
| T9 | `test_compact_tool_result_truncates_large_content` | `test_runner.py` | Context compaction works |
| T10 | `test_llm_gate_logging_at_info_level` | `test_agent.py` | LLM gate logs at INFO level |

### 8.3 Integration Tests

| # | Test | What |
|---|------|------|
| I1 | `test_interactive_smart_end_to_end` | Full session: triage -> archive -> summary, verify >=70% heuristic |
| I2 | `test_interactive_smart_reclassify` | Triage -> reclassify email -> re-triage, verify LLM processes reclassified email |
| I3 | `test_interactive_smart_token_budget` | 100 emails, verify total_tokens < 100K |
| I4 | `test_interactive_smart_context_bounded` | 4-turn session, verify conversation_history length bounded |

---

## 9. File Change Summary

| File | Changes | Lines |
|------|---------|-------|
| `src/gaia/agents/email/bench/runner.py` | P0-A: fix conversation overwrite (2 locations); P0-B: add smart-mode dispatch; add `split_by_confidence()`, `mark_for_escalation()`, `generate_interactive_smart_summary()`; SessionState sync; context compaction | ~80 new/modified |
| `src/gaia/agents/email/agent.py` | P2: add LLM gate logging at INFO; no structural changes to `process_interactive_smart_triage` (already implemented) | ~15 new |
| `src/gaia/agents/email/bench/data_shapes.py` | P2: add `heuristic_email_count`, `llm_email_count`, `smart_mode` to `TurnResult` | ~5 new |
| `tests/unit/agents/test_email_agent_interactive_smart_triage.py` | Existing tests (no changes needed) | -- |
| `tests/unit/email/test_runner_smart_mode.py` | New test file for T1-T10 | ~200 new |
| `tests/integration/test_email_interactive_smart_e2e.py` | New integration test file for I1-I4 | ~100 new |

---

## 10. Execution Sequence

```
PR1 (Blocking Fixes + Session State)
=====================================
1. Fix conversation_history overwrite at runner.py:1264 and runner.py:786
2. Add conditional smart-mode dispatch at runner.py:1233 and runner.py:754
3. Add SessionState sync after smart-mode first turn
4. Add split_by_confidence() helper to runner.py
5. Add mark_for_escalation() helper to runner.py
6. Add generate_interactive_smart_summary() to runner.py
7. Run existing unit tests (all must pass)
8. Run new unit tests T1-T8 (all must pass)
9. Manual verification: gaia email bench --mode interactive --smart --mbox-path <path> --model <model>

PR2 (Context + Gate + Visualization)
=====================================
1. Add context compaction to conversation_history accumulation
2. Add INFO-level logging to _should_use_llm()
3. Add token budget fields to TurnResult
4. Add dual-path visualization support to visualize.py
5. Run new unit tests T9-T10 (all must pass)
6. Run integration tests I1-I4 (all must pass)
7. Manual verification: verify charts show dual-path breakdown
```

---

## 11. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Conversation history fix breaks existing non-smart mode | Low | High | T8 regression test guards this; manual verification required |
| Smart-mode dispatch on Turn 1 conflicts with non-triage prompts | Medium | Medium | Guard: only dispatch if prompt contains "triage" or "inbox" keyword; fallback to process_query otherwise |
| Context compaction loses information needed by LLM | Medium | High | Compaction must preserve structural keys (id, category, confident); only truncate body/snippet text |
| Token budget <100K not achievable with large inboxes | Low | Medium | Criterion applies at limit=100; adjust threshold for higher limits |
| Heuristic rate <70% on certain email datasets | Medium | Low | Criterion is target, not hard gate; report actual rate in summary |
