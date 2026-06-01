# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
synth_session_state: reconstruct missing batch-tool entries from turns[].

The gaia recorder only wires singleton tool names into session_state.
All _batch variants fall through. This module reconstructs the complete
state from turns[].tools_called + turns[].emails_affected, which IS
correctly populated by the runner.

Result is stored as synth_session_state; raw session_state is untouched.
Downstream code should use get_state(run, key) to get the best available
value (original when populated, synthesized fallback otherwise).

Known limitations:
- emails_affected is per-turn, not per-tool. If a turn calls both
  archive_message_batch AND mark_read_batch, both keys get all of
  emails_affected. This matches actual gaia behavior for singletons.
- The "triaged" key uses a dict schema (id -> category) and is already
  correctly populated by the source. get_state() should NOT be called
  with key="triaged".
- No batch variants exist for create_draft/save_draft/send_draft/send_message
  in the observed corpus; their singleton-only behavior is intentional.
"""

from __future__ import annotations

from typing import Any

# Maps tool names to their corresponding session_state list key.
# Does NOT include triage_inbox (maps to "triaged" which is a dict).
TOOL_TO_STATE_KEY: dict[str, str] = {
    "archive_message":       "archived",
    "archive_message_batch": "archived",
    "add_star":              "starred",
    "add_star_batch":        "starred",
    "mark_read":             "marked_read",
    "mark_read_batch":       "marked_read",
    "mark_as_read":          "marked_read",
    "mark_unread_batch":     "marked_unread",
    "remove_star":           "unstarred",
    "remove_star_batch":     "unstarred",
    "trash_message":         "deleted",
    "delete_message":        "deleted",
    "delete_message_batch":  "deleted",
    "create_draft":          "drafted",
    "save_draft":            "drafted",
    "send_message":          "sent",
}

_ALL_STATE_KEYS = {
    "archived", "starred", "marked_read", "marked_unread",
    "unstarred", "drafted", "sent", "deleted",
}


def synth_session_state(run: dict[str, Any]) -> dict[str, list[str]]:
    """Reconstruct session state from turns[].tools_called + emails_affected.

    Reads raw turns from run["_raw"]["turns"] (the original JSON structure).
    Returns a dict mapping state key -> deduplicated ordered list of UUIDs.
    """
    synth: dict[str, list[str]] = {
        "archived": [], "starred": [], "marked_read": [], "marked_unread": [],
        "unstarred": [], "drafted": [], "sent": [], "deleted": [],
    }

    raw = run.get("_raw")
    if raw is None:
        return synth

    turns = raw.get("turns") or []
    for turn in turns:
        affected: list[str] = turn.get("emails_affected") or []
        if not affected:
            continue
        for tool_name in turn.get("tools_called") or []:
            key = TOOL_TO_STATE_KEY.get(tool_name)
            if key:
                synth[key].extend(affected)

    # Deduplicate while preserving insertion order.
    for key in synth:
        seen: set[str] = set()
        deduped: list[str] = []
        for uid in synth[key]:
            if uid not in seen:
                seen.add(uid)
                deduped.append(uid)
        synth[key] = deduped

    return synth


def get_state(run: dict[str, Any], key: str) -> list[str]:
    """Get a session_state list value, falling back to synthesized data.

    Args:
        run: An enriched run dict (must have been passed through enrich_run).
        key: One of the 8 state list keys (archived, starred, marked_read,
             marked_unread, unstarred, drafted, sent, deleted).
             NOTE: Do NOT call with key="triaged" -- that key uses a dict
             schema and is already correctly populated by the source.

    Returns:
        The original session_state value if populated, otherwise the
        synthesized fallback.
    """
    assert key in _ALL_STATE_KEYS, (
        f"Invalid state key: {key!r}. Must be one of {_ALL_STATE_KEYS}. "
        "Do NOT use get_state() with key='triaged'."
    )

    raw = (run.get("session_state") or {}).get(key) or []
    if raw:
        return list(raw)

    return (run.get("synth_session_state") or {}).get(key, [])


def enrich_run(run: dict[str, Any]) -> dict[str, Any]:
    """Enrich a loaded run dict with synthesized session state.

    Mutates the run dict in place and returns it for chaining.
    After calling, run["synth_session_state"] contains the reconstructed
    state from turns, and run["stage_time_s"] contains the stage time.

    Usage:
        runs = load_json_runs(".")
        for r in runs:
            enrich_run(r)
    """
    # Stage time (preserve existing computation if present).
    if "stage_time_s" not in run:
        total_ms = run.get("total_duration_ms", 0) or 0
        run["stage_time_s"] = total_ms / 1000.0

    # Synthesize session state.
    run["synth_session_state"] = synth_session_state(run)

    return run
