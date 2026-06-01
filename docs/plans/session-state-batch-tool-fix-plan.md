# Session State Batch Tool Fix Plan

**Date:** 2026-06-01
**Branch:** `feat/email-bench-visualizations`
**Status:** Ready for implementation

---

## Problem Summary

In every interactive email benchmark JSON output, `session_state` has 7 keys but 5 are always empty arrays even though the agent called the corresponding batch tools and `emails_affected` shows the emails were processed.

```
session_state:
  triaged:     { "UUID-1": "actionable", ... }  <-- WORKS (all 36 runs)
  archived:    ["UUID-X"]                        <-- Only 1 entry even when 100 archived
  starred:     []                                <-- ALWAYS EMPTY
  drafted:     []                                <-- ALWAYS EMPTY
  sent:        []                                <-- ALWAYS EMPTY
  marked_read: []                                <-- ALWAYS EMPTY
  deleted:     []                                <-- ALWAYS EMPTY
```

**Root cause:** `runner.py` function `_extract_actions()` (lines 1178-1268) only handles singleton tool names (`archive_message`, `add_star`, `mark_read`, `trash_message`). All `_batch` variants (`archive_message_batch`, `add_star_batch`, `mark_read_batch`, `mark_unread_batch`, `remove_star_batch`, `delete_message_batch`) fall through with no handler. Additionally, two state keys (`marked_unread`, `unstarred`) do not exist in the `SessionState` dataclass.

**Decisive proof (run `1bd680`):**
- Turn 2: `archive_message` -> 1 email added to `archived`
- Turn 4: `archive_message_batch` -> 100 emails in `emails_affected`, 0 added to `archived`

---

## Two Fixes

### Fix A -- Gaia Source (Permanent)

Modify the gaia source code to correctly extract multi-ID results from batch tool responses. This is the proper fix that corrects the data at the source.

### Fix B -- Analysis Pipeline (Immediate Workaround)

Create a synthesis module in this project's analysis infrastructure that reconstructs session state from `turns[].tools_called` + `turns[].emails_affected`. This provides immediate relief for existing data without waiting for a gaia release.

---

## Fix A -- Gaia Source Changes

### A.1: Fix `_extract_actions()` in `runner.py`

**File:** `C:\Users\antmi\gaia-visualizations\src\gaia\agents\email\bench\runner.py`
**Lines:** 1178-1268 (the `_extract_actions` function)
**Function:** `_extract_actions(agent_result: dict, state: SessionState) -> None`

**Change:** Replace the single-ID extraction pattern for all batch tool handlers with multi-ID extraction that mirrors the logic in `_extract_emails_affected()` (runner.py:812-850).

The current buggy pattern (example from lines 1229-1234):
```python
if tool_name in ("archive_message", "archive_message_batch") and isinstance(
    data, dict
):
    msg_id = data.get("message_id", "") or data.get("id", "")
    if msg_id:
        state.archived.add(msg_id)
```

This only extracts a single ID from `data.get("message_id")` or `data.get("id")`. Batch tool results return IDs in `data.ids`, `data.succeeded[*].message_id`, or `data.results[*].id`.

**New pattern to replace each handler:**

Add a helper function `_collect_ids(data: dict) -> set[str]` before `_extract_actions`:

```python
def _collect_ids(data: dict) -> set[str]:
    """Extract all email IDs from a tool result envelope, handling both
    singleton and batch response shapes.

    Singleton: {"message_id": "uuid"} or {"id": "uuid"}
    Batch ids: {"ids": ["uuid1", "uuid2", ...]}
    Batch succeeded: {"succeeded": [{"message_id": "uuid1"}, ...]}
    Batch results: {"results": [{"id": "uuid1"}, ...]}
    """
    ids: set[str] = set()

    # Batch: explicit ids list
    if "ids" in data and isinstance(data["ids"], list):
        ids.update(data["ids"])

    # Batch: succeeded array (mark_read_batch, mark_unread_batch, etc.)
    if "succeeded" in data and isinstance(data["succeeded"], list):
        for item in data["succeeded"]:
            if isinstance(item, dict) and "message_id" in item:
                ids.add(item["message_id"])

    # Batch: results array (archive_message_batch, triage_inbox, etc.)
    if "results" in data and isinstance(data["results"], list):
        for item in data["results"]:
            if isinstance(item, dict):
                if "id" in item:
                    ids.add(item["id"])
                elif "message_id" in item:
                    ids.add(item["message_id"])

    # Singleton fallback (when none of the batch fields are present)
    if not ids:
        msg_id = data.get("message_id", "") or data.get("id", "")
        if msg_id:
            ids.add(msg_id)

    return ids
```

**Then update each handler block in `_extract_actions()` to use `_collect_ids(data)`:**

#### archive_message / archive_message_batch (lines 1228-1234)

Replace:
```python
if tool_name in ("archive_message", "archive_message_batch") and isinstance(
    data, dict
):
    msg_id = data.get("message_id", "") or data.get("id", "")
    if msg_id:
        state.archived.add(msg_id)
```

With:
```python
if tool_name in ("archive_message", "archive_message_batch") and isinstance(
    data, dict
):
    state.archived.update(_collect_ids(data))
```

#### add_star / add_star_batch (lines 1247-1250)

Replace:
```python
if tool_name in ("add_star", "add_star_batch") and isinstance(data, dict):
    msg_id = data.get("id", "") or data.get("message_id", "")
    if msg_id:
        state.starred.add(msg_id)
```

With:
```python
if tool_name in ("add_star", "add_star_batch") and isinstance(data, dict):
    state.starred.update(_collect_ids(data))
```

#### remove_star / remove_star_batch (lines 1251-1254)

Replace:
```python
if tool_name in ("remove_star", "remove_star_batch") and isinstance(data, dict):
    msg_id = data.get("id", "") or data.get("message_id", "")
    if msg_id:
        state.starred.discard(msg_id)
```

With:
```python
if tool_name in ("remove_star", "remove_star_batch") and isinstance(data, dict):
    state.starred.difference_update(_collect_ids(data))
```

#### mark_read / mark_read_batch / mark_as_read (lines 1257-1262)

Replace:
```python
if tool_name in ("mark_read", "mark_read_batch", "mark_as_read") and isinstance(
    data, dict
):
    msg_id = data.get("id", "") or data.get("message_id", "")
    if msg_id:
        state.marked_read.add(msg_id)
```

With:
```python
if tool_name in ("mark_read", "mark_read_batch", "mark_as_read") and isinstance(
    data, dict
):
    state.marked_read.update(_collect_ids(data))
```

#### trash_message (lines 1265-1268)

Replace:
```python
if tool_name == "trash_message" and isinstance(data, dict):
    msg_id = data.get("id", "") or data.get("message_id", "")
    if msg_id:
        state.deleted.add(msg_id)
```

With:
```python
if tool_name == "trash_message" and isinstance(data, dict):
    state.deleted.update(_collect_ids(data))
```

### A.2: Add Missing Batch Handlers in `_extract_actions()`

After the existing `trash_message` handler (around line 1268), add these missing handlers:

```python
# Mark unread batch (no singleton variant observed in corpus).
if tool_name == "mark_unread_batch" and isinstance(data, dict):
    state.marked_unread.update(_collect_ids(data))

# Delete message batch (no singleton variant observed in corpus).
if tool_name == "delete_message_batch" and isinstance(data, dict):
    state.deleted.update(_collect_ids(data))
```

### A.3: Add New Fields to `SessionState` Dataclass

**File:** `C:\Users\antmi\gaia-visualizations\src\gaia\agents\email\bench\data_shapes.py`
**Lines:** 83-102 (the `SessionState` dataclass)

Add two new fields after `deleted`:

```python
@dataclass
class SessionState:
    """Tracks email actions across an interactive session."""

    archived: set = field(default_factory=set)
    starred: set = field(default_factory=set)
    drafted: set = field(default_factory=set)
    sent: set = field(default_factory=set)
    marked_read: set = field(default_factory=set)
    marked_unread: set = field(default_factory=set)  # NEW
    unstarred: set = field(default_factory=set)        # NEW
    deleted: set = field(default_factory=set)
    triaged_emails: dict = field(default_factory=dict)
    heuristic_triaged: dict = field(default_factory=dict)
    llm_triaged: dict = field(default_factory=dict)
    force_llm_ids: dict = field(default_factory=dict)
    llm_calls_saved: int = 0
    heuristic_token_estimate: int = 0
```

### A.4: Update Serialization in Summary Output

**File:** `C:\Users\antmi\gaia-visualizations\src\gaia\agents\email\bench\runner.py`
**Lines:** 1630-1638 (the `"session_state"` dict in the summary builder)

Replace:
```python
"session_state": {
    "archived": sorted(state.archived),
    "starred": sorted(state.starred),
    "drafted": sorted(state.drafted),
    "sent": sorted(state.sent),
    "marked_read": sorted(state.marked_read),
    "deleted": sorted(state.deleted),
    "triaged": dict(state.triaged_emails),
},
```

With:
```python
"session_state": {
    "archived": sorted(state.archived),
    "starred": sorted(state.starred),
    "drafted": sorted(state.drafted),
    "sent": sorted(state.sent),
    "marked_read": sorted(state.marked_read),
    "marked_unread": sorted(state.marked_unread),
    "unstarred": sorted(state.unstarred),
    "deleted": sorted(state.deleted),
    "triaged": dict(state.triaged_emails),
},
```

---

## Fix B -- Analysis Pipeline Workaround

### B.1: Create `shared/` Directory and `enrich.py`

**Directory:** `C:\Users\antmi\gaia-visualizations\benchmark_charts\smartinteractive-bencher\shared\`
**File:** `C:\Users\antmi\gaia-visualizations\benchmark_charts\smartinteractive-bencher\shared\enrich.py`

Create a new module that synthesizes session state from `turns[].tools_called` and `turns[].emails_affected`. This operates on the in-memory run dict that downstream chart code already uses.

```python
"""Synthesize missing session_state data from turn-level tool/affected records.

This module repairs the gap where gaia's _extract_actions only handles
singleton tool names. All _batch variants fall through in the gaia recorder,
leaving starred/drafted/sent/marked_read/deleted as empty arrays.

Usage:
    from shared.enrich import enrich_run, get_state

    enrich_run(run)
    archived = get_state(run, "archived")
"""

from __future__ import annotations

_TOOL_TO_STATE_KEY: dict[str, str] = {
    "archive_message":       "archived",
    "archive_message_batch": "archived",
    "add_star":              "starred",
    "add_star_batch":        "starred",
    "mark_read":             "marked_read",
    "mark_read_batch":       "marked_read",
    "mark_unread_batch":     "marked_unread",
    "remove_star":           "unstarred",
    "remove_star_batch":     "unstarred",
    "draft_message":         "drafted",
    "send_message":          "sent",
    "delete_message":        "deleted",
    "delete_message_batch":  "deleted",
    # triage_inbox maps to "triaged" which is a dict -- handled separately.
}

_ALL_STATE_KEYS: list[str] = [
    "archived", "starred", "marked_read", "marked_unread",
    "unstarred", "drafted", "sent", "deleted",
]


def _ordered_dedup(items: list[str]) -> list[str]:
    """Deduplicate while preserving first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for uid in items:
        if uid not in seen:
            seen.add(uid)
            result.append(uid)
    return result


def synth_session_state(run: dict) -> dict[str, list[str]]:
    """Build session state from turns[].tools_called + turns[].emails_affected.

    Args:
        run: A benchmark run dict (as loaded from JSON, wrapped by j_or_l).
            Expected to have a ``_raw`` key containing the original JSON
            with a ``turns`` array.

    Returns:
        Dict with keys matching session_state schema. Each value is an
        order-preserved, deduplicated list of email UUIDs.
    """
    synth: dict[str, list[str]] = {k: [] for k in _ALL_STATE_KEYS}

    raw_turns = (run.get("_raw") or {}).get("turns") or []
    for turn in raw_turns:
        affected: list[str] = turn.get("emails_affected") or []
        if not affected:
            continue
        for tool_name in turn.get("tools_called") or []:
            key = _TOOL_TO_STATE_KEY.get(tool_name)
            if key:
                synth[key].extend(affected)

    for key in _ALL_STATE_KEYS:
        synth[key] = _ordered_dedup(synth[key])

    return synth


def enrich_run(run: dict) -> None:
    """Attach synth_session_state to a run dict in-place.

    After calling this, use ``get_state(run, key)`` to read state values
    that automatically prefer the original when populated and fall back
    to the synthesized version when empty.
    """
    run["synth_session_state"] = synth_session_state(run)


def get_state(run: dict, key: str) -> list[str]:
    """Read a session_state key with automatic fallback to synthesized data.

    Returns the original session_state[key] if it is a non-empty list,
    otherwise falls back to synth_session_state[key]. Call enrich_run(run)
    first to ensure synth_session_state is populated.

    Args:
        run: A benchmark run dict.
        key: One of the session_state keys (e.g. "archived", "starred").

    Returns:
        List of email UUIDs (possibly empty).
    """
    raw = (run.get("session_state") or {}).get(key) or []
    if raw:
        return raw
    return (run.get("synth_session_state") or {}).get(key, [])
```

### B.2: Create `shared/__init__.py`

**File:** `C:\Users\antmi\gaia-visualizations\benchmark_charts\smartinteractive-bencher\shared\__init__.py`

```python
"""Shared utilities for the smart interactive benchmark analysis pipeline."""
```

### B.3: Downstream Consumer Migration

Any existing chart/analysis code that currently reads `run.get("session_state", {}).get(key, [])` should be updated to use `get_state(run, key)` instead. This is a backward-compatible change:

**Before:**
```python
archived = run.get("session_state", {}).get("archived", [])
```

**After:**
```python
from shared.enrich import get_state, enrich_run

enrich_run(run)  # Call once per run, before any get_state calls
archived = get_state(run, "archived")
```

No existing chart code needs to be changed immediately -- the `get_state()` helper encapsulates the fallback logic. When chart modules are refactored, they can adopt `get_state()` incrementally.

---

## Known Limitations

### Shared `emails_affected` Across Tools in One Turn

When a single turn calls multiple action tools (e.g., `archive_message_batch` AND `mark_read_batch`), both state keys receive the full `emails_affected` list for that turn. This is not a bug in the workaround -- it matches the actual gaia behavior for singleton tools (proven by run `c7cd1d` turn 2, where the same UUID appeared in both `archived` and `marked_read` when both `archive_message` and `mark_read` were called in the same turn).

For well-formed interactive scenarios where each turn's actions target the same email set, this produces correct results. If a future scenario requires per-tool granularity, the fix would need to parse individual tool result envelopes rather than using the turn-level `emails_affected` aggregate.

---

## Implementation Order

### Phase 1 -- Fix B (Workaround, Immediate)
1. Create `shared/__init__.py`
2. Create `shared/enrich.py` with `synth_session_state()`, `enrich_run()`, `get_state()`
3. Verify against existing data: run `1bd680` should show `len(synth_session_state["archived"]) >= 101` (1 singleton + 100 batch)

**Risk:** None. Creates new module, touches no existing code.

### Phase 2 -- Fix A (Gaia Source, Permanent)
1. Add `_collect_ids()` helper to `runner.py`
2. Update all 6 existing handler blocks to use `_collect_ids()`
3. Add 2 missing batch handlers (`mark_unread_batch`, `delete_message_batch`)
4. Add `marked_unread` and `unstarred` to `SessionState` dataclass
5. Update serialization dict in summary builder
6. Test with `--limit 5 --batch-size 5` and verify all state arrays are populated

**Risk:** Modifies gaia source. Requires review and testing. No breaking changes to JSON schema (additive only).

---

## Verification Checklist

### Fix A (gaia recorder):
- [ ] `_collect_ids()` correctly extracts from `data.ids`, `data.succeeded[*].message_id`, `data.results[*].id`, and singleton fallback
- [ ] Re-run bench with `--limit 5 --batch-size 5`
- [ ] Assert `len(session_state["archived"]) == total emails archived (singleton + batch combined)`
- [ ] Assert `len(session_state["starred"]) > 0` when `add_star` or `add_star_batch` was called
- [ ] Assert `len(session_state["marked_read"]) > 0` when `mark_read` or `mark_read_batch` was called
- [ ] Assert `len(session_state["marked_unread"]) > 0` when `mark_unread_batch` was called
- [ ] Assert `len(session_state["unstarred"]) > 0` when `remove_star_batch` was called
- [ ] Assert `len(session_state["deleted"]) > 0` when `trash_message` or `delete_message_batch` was called
- [ ] Confirm JSON serialization includes all 9 keys

### Fix B (pipeline workaround):
- [ ] `shared/enrich.py` imports cleanly: `python -c "from shared.enrich import synth_session_state, enrich_run, get_state"`
- [ ] Run `1bd680` verification: `archived` count should be >= 101 (1 singleton + 100 batch)
- [ ] All 8 state keys are present in `synth_session_state` output
- [ ] Deduplication works: same email starred in 2 turns appears once in output
- [ ] `get_state()` returns original when populated, synthesized when empty
- [ ] Downstream charts using `get_state()` show non-zero values for previously-empty keys

---

## File Change Summary

| File | Phase | Change Type | Lines Affected |
|------|-------|-------------|----------------|
| `src/gaia/agents/email/bench/runner.py` | A | Add `_collect_ids()` helper, update 6 handlers, add 2 handlers | ~1178-1270 |
| `src/gaia/agents/email/bench/runner.py` | A | Update serialization dict | ~1630-1638 |
| `src/gaia/agents/email/bench/data_shapes.py` | A | Add 2 fields to SessionState | ~83-102 |
| `benchmark_charts/smartinteractive-bencher/shared/__init__.py` | B | New file | -- |
| `benchmark_charts/smartinteractive-bencher/shared/enrich.py` | B | New file (~90 lines) | -- |
