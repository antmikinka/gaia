# Problem B — Fix Document: Empty session_state Arrays
**Date:** 2026-06-01
**Status:** Root cause confirmed. Two fixes described: one for the gaia recorder source (permanent), one for the analysis pipeline on this machine (immediate workaround).

---

## 1. Exact Problem Statement

In every `interactive_qwen3.5-*.json` run file, `session_state` has 7 keys. Five of them are always empty lists even though the agent called the corresponding tools and affected emails:

```json
"session_state": {
  "triaged":     { "UUID-1": "actionable", "UUID-2": "low priority", ... },  ← WORKS
  "archived":    ["UUID-X"],   ← ONLY 1 entry even when 100 emails were archived
  "starred":     [],           ← ALWAYS EMPTY even when emails were starred
  "drafted":     [],           ← ALWAYS EMPTY
  "sent":        [],           ← ALWAYS EMPTY
  "marked_read": [],           ← ALWAYS EMPTY
  "deleted":     []            ← ALWAYS EMPTY
}
```

---

## 2. Confirmed Root Cause

The gaia recorder dispatcher handles **only the singleton form** of each tool. All `_batch` variants fall through with no handler. Evidence across all 36 runs:

| tool_name | Expected state key | Dispatcher handles it? | Proven by |
|-----------|-------------------|----------------------|-----------|
| `triage_inbox` | `triaged` | ✅ YES | 36/36 runs populated |
| `archive_message` | `archived` | ✅ YES | 1bd680 turn 2 → 1 UUID appears |
| `add_star` | `starred` | ✅ YES | 1f17ba / 5167fa / 89e3be |
| `mark_read` | `marked_read` | ✅ YES | c7cd1d turn 2 → 1 UUID appears |
| **`archive_message_batch`** | `archived` | **❌ NO** | 1bd680 turn 4: 100 `emails_affected`, 0 added to `archived` |
| **`add_star_batch`** | `starred` | **❌ NO** | 0b280b / 632839 / 84fc0b: 25 `emails_affected`, `starred=[]` |
| **`mark_read_batch`** | `marked_read` | **❌ NO** | c7cd1d turn 3: 100 `emails_affected`, `marked_read` unchanged |
| **`mark_unread_batch`** | *(no key exists)* | **❌ NO** | No `marked_unread` key in schema |
| **`remove_star_batch`** | *(no key exists)* | **❌ NO** | No `unstarred` key in schema |
| `move_to_label` | *(no key exists)* | N/A | No state key in schema |

**Tools never called in the 36-run corpus** (cannot confirm/deny): `draft_message`, `send_message`, `delete_message`, `delete_message_batch`.

### Decisive single-run proof (run `1bd680`):
```
Turn 2:  tools_called=['archive_message']        emails_affected=['39dd601b']  (1 email)
Turn 4:  tools_called=['archive_message_batch']  emails_affected=[100 UUIDs]

session_state.archived = ['39dd601b']   ← only the singleton's email
                                         the 100 batch emails are completely missing
```

### Proof that singletons from the same turn BOTH get recorded (run `c7cd1d`):
```
Turn 2:  tools_called=['mark_read', 'archive_message']  emails_affected=['39dd601b']  (1 email)

session_state.archived    = ['39dd601b']  ✅
session_state.marked_read = ['39dd601b']  ✅
```
Same UUID appears in BOTH keys because the dispatcher fires for BOTH `mark_read` AND `archive_message`. This confirms the recorder has access to `emails_affected` at the turn level and routes it to multiple keys correctly — the mechanism works, it just lacks `_batch` branches.

---

## 3. Exact JSON Data Structure (what the recorder has access to)

Every JSON run file has this structure in `turns[]`:

```json
{
  "turns": [
    {
      "turn_number": 1,
      "tools_called": ["triage_inbox"],
      "emails_affected": ["UUID-A", "UUID-B", "UUID-C", ...]
    },
    {
      "turn_number": 2,
      "tools_called": ["search_messages", "archive_message", "list_inbox"],
      "emails_affected": ["UUID-X"]
    },
    {
      "turn_number": 3,
      "tools_called": ["mark_read_batch", "mark_unread_batch", "remove_star_batch"],
      "emails_affected": ["UUID-1", "UUID-2", ..., "UUID-100"]
    },
    {
      "turn_number": 4,
      "tools_called": ["triage_inbox", "archive_message_batch"],
      "emails_affected": ["UUID-D", "UUID-E", ..., "UUID-100"]
    }
  ]
}
```

**Critical facts:**
- Key is `turn_number` (integer, 1-based). `turn_index` is `null` in the JSON — do NOT use it.
- `emails_affected` is a flat `list[str]` of UUID strings for the whole turn (not per-tool).
- `tools_called` is a `list[str]` of tool names for the whole turn.
- When multiple action tools appear in one turn, `emails_affected` is shared across them — the same UUIDs get routed to multiple state keys. This is already the correct gaia behavior for singletons (proven by c7cd1d turn 2 above).

---

## 4. Fix A — Gaia Recorder Source (Permanent Fix, Requires Gaia Machine)

Find the file that owns this logic in the gaia package. It will look like:

```python
# CURRENT (partial/buggy) dispatcher — pseudocode of what exists:
if tool_name == "triage_inbox":
    for email_id, category in result.items():
        session_state["triaged"][email_id] = category
elif tool_name == "archive_message":
    session_state["archived"].append(email_id_from_result)
elif tool_name == "add_star":
    session_state["starred"].append(email_id_from_result)
elif tool_name == "mark_read":
    session_state["marked_read"].append(email_id_from_result)
# ALL BATCH VARIANTS ARE MISSING — they fall through here
```

**Add these branches** (exact field names for `result` must be verified from gaia tool schemas):

```python
# ADD THESE MISSING BRANCHES:
elif tool_name == "archive_message_batch":
    # result likely has a list of archived email IDs
    # Use emails_affected from the turn if result field name is uncertain
    session_state["archived"].extend(emails_affected_this_turn)

elif tool_name == "add_star_batch":
    session_state["starred"].extend(emails_affected_this_turn)

elif tool_name == "mark_read_batch":
    session_state["marked_read"].extend(emails_affected_this_turn)

elif tool_name == "mark_unread_batch":
    # NOTE: no "marked_unread" key exists in current schema — ADD IT
    session_state.setdefault("marked_unread", []).extend(emails_affected_this_turn)

elif tool_name == "remove_star_batch":
    # NOTE: no "unstarred" key exists in current schema — ADD IT
    # OR: remove from session_state["starred"] instead
    session_state.setdefault("unstarred", []).extend(emails_affected_this_turn)

# If these are also called (not yet in corpus but likely exist):
elif tool_name == "draft_message":
    session_state["drafted"].append(draft_id_from_result)

elif tool_name == "send_message":
    session_state["sent"].append(message_id_from_result)

elif tool_name in ("delete_message", "delete_message_batch"):
    session_state["deleted"].extend(emails_affected_this_turn)
```

**Schema change required:** Add `marked_unread` and `unstarred` keys to the initial `session_state` dict if they don't already exist:
```python
session_state = {
    "triaged":       {},
    "archived":      [],
    "starred":       [],
    "drafted":       [],
    "sent":          [],
    "marked_read":   [],
    "marked_unread": [],   # NEW — add this
    "unstarred":     [],   # NEW — add this
    "deleted":       [],
}
```

**Verification after fix:** Re-run bench with `--limit 5 --batch-size 5`. In the output JSON, `len(session_state["archived"])` must equal the number of emails archived (including via `archive_message_batch`). Currently it captures only singleton calls.

---

## 5. Fix B — Analysis Pipeline Workaround (Immediate, This Machine)

Since gaia source is unavailable here, synthesize the missing state arrays inside `shared/enrich.py` from the data that IS in every JSON: `turns[].turn_number`, `turns[].tools_called`, `turns[].emails_affected`.

**File:** `C:\Users\amikinka\Downloads\interactive-smart - Copy\interactive-smart - Copy\shared\enrich.py`
**Where:** Add a new block after line 69 (after `run["stage_time_s"]` is set), still inside `enrich_run()`.

```python
# --- synth_session_state: repair missing batch-tool entries ---------------
# The gaia recorder only wires singleton tool names into session_state.
# All _batch variants fall through. We reconstruct from turns[].emails_affected.
# Result is stored as synth_session_state; raw session_state is untouched.

_TOOL_TO_STATE_KEY: dict[str, str] = {
    "archive_message":       "archived",
    "archive_message_batch": "archived",
    "add_star":              "starred",
    "add_star_batch":        "starred",
    "mark_read":             "marked_read",
    "mark_read_batch":       "marked_read",
    "mark_unread_batch":     "marked_unread",
    "remove_star_batch":     "unstarred",
    "draft_message":         "drafted",
    "send_message":          "sent",
    "delete_message":        "deleted",
    "delete_message_batch":  "deleted",
}

synth: dict[str, list[str]] = {
    "archived": [], "starred": [], "marked_read": [], "marked_unread": [],
    "unstarred": [], "drafted": [], "sent": [], "deleted": [],
}
for raw_turn in (run.get("_raw") or {}).get("turns") or []:
    affected: list[str] = raw_turn.get("emails_affected") or []
    if not affected:
        continue
    for tool_name in raw_turn.get("tools_called") or []:
        key = _TOOL_TO_STATE_KEY.get(tool_name)
        if key:
            synth[key].extend(affected)

# Deduplicate while preserving order (a UUID can be starred across multiple turns)
for key in synth:
    seen: set[str] = set()
    deduped = []
    for uid in synth[key]:
        if uid not in seen:
            seen.add(uid)
            deduped.append(uid)
    synth[key] = deduped

run["synth_session_state"] = synth
```

**Known limitation of this workaround:** `emails_affected` is per-turn, not per-tool. If a turn calls both `archive_message_batch` AND `mark_read_batch`, both keys get all of `emails_affected` for that turn. This matches actual gaia behavior for singletons (proven: c7cd1d turn 2, same UUID in both `archived` and `marked_read`). It is correct for well-formed turns where each action targets the same email set.

**After implementing:** Any downstream chart reading `session_state` should fall back to `synth_session_state[key]` when the original is empty:
```python
def get_state(run, key):
    raw = (run.get("session_state") or {}).get(key) or []
    if raw:
        return raw
    return (run.get("synth_session_state") or {}).get(key, [])
```

---

## 6. Verification Checklist

### Fix A (gaia recorder):
- [ ] Re-run bench with small settings (`--limit 5 --batch-size 5`)
- [ ] Assert `len(session_state["archived"]) == total emails archived (singleton + batch combined)`
- [ ] Assert `len(session_state["starred"]) == total emails starred`
- [ ] Assert `len(session_state["marked_read"]) == total emails marked read`
- [ ] Assert `"marked_unread"` key exists if `mark_unread_batch` was called
- [ ] Assert `"unstarred"` key exists if `remove_star_batch` was called

### Fix B (pipeline workaround):
- [ ] Run: `python -c "import sys; sys.path.insert(0, '.'); from shared.j_or_l import load_json_runs; from shared.enrich import enrich_run; runs = load_json_runs('.'); [enrich_run(r) for r in runs]; r = [x for x in runs if '1bd680' in str(x.get('json_filename',''))][0]; print(len(r['synth_session_state']['archived']), 'should be 101 (1 singleton + 100 batch)')"`
- [ ] Re-run `run_charts.py --mode full` and confirm downstream charts that use session_state now have non-zero values

---

## 7. Complete Tool Name Reference

All tool names observed across the 36-run corpus:

**Action tools (affect session_state):**
```
archive_message         → archived      ✅ wired
archive_message_batch   → archived      ❌ NOT wired  ← FIX REQUIRED
add_star               → starred       ✅ wired
add_star_batch         → starred       ❌ NOT wired  ← FIX REQUIRED
mark_read              → marked_read   ✅ wired
mark_read_batch        → marked_read   ❌ NOT wired  ← FIX REQUIRED
mark_unread_batch      → marked_unread ❌ NOT wired, key doesn't exist ← FIX REQUIRED
remove_star_batch      → unstarred     ❌ NOT wired, key doesn't exist ← FIX REQUIRED
move_to_label          → (no key)      NOT wired, no state key exists
```

**Read-only tools (no state expected):**
```
get_message
get_thread
list_calendar_events
list_inbox
list_labels
search_messages
triage_inbox            → triaged      ✅ wired (dict, not list)
```

**Not observed in corpus (handle defensively):**
```
draft_message          → drafted
send_message           → sent
delete_message         → deleted
delete_message_batch   → deleted

```