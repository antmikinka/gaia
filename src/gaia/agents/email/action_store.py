# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Persistent action log for the Email Triage Agent.

The agent's tools record every state-mutating action here BEFORE returning
the action_id to the caller. The undo flow looks up the action by id,
inverts the recorded payload, calls the appropriate Gmail backend method,
and marks the row as undone.

Two tables:

- ``email_actions`` — every reversible mutation (archive, label add/remove,
  trash, mark read/unread, star/unstar). Includes an optional ``batch_id``
  so the bulk-undo follow-up has the schema in place; #962 itself does
  not expose bulk operations.
- ``email_drafts`` — every draft created. Lets ``send_draft`` look up the
  draft for the confirmation dialog (recipient + subject + body preview)
  and lets the integration test sweep up orphans on teardown.

Ordering invariant (Adversarial B2): the calling tool MUST execute the
Gmail API call FIRST and only ``record_action`` on success. Phantom rows
in ``email_actions`` for actions that never happened are a state-corruption
class — see ``test_email_agent_soft_delete.py``.

All public helpers are pure functions taking a ``DatabaseMixin``-typed
first argument. They never reach into the agent class.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

EMAIL_ACTIONS_DDL = """
CREATE TABLE IF NOT EXISTS email_actions (
    action_id    TEXT PRIMARY KEY,
    action_type  TEXT NOT NULL,
    message_id   TEXT NOT NULL,
    thread_id    TEXT,
    payload_json TEXT NOT NULL,
    batch_id     TEXT,
    created_at   REAL NOT NULL,
    undone_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_email_actions_message
    ON email_actions(message_id);
CREATE INDEX IF NOT EXISTS idx_email_actions_created
    ON email_actions(created_at);
"""

EMAIL_DRAFTS_DDL = """
CREATE TABLE IF NOT EXISTS email_drafts (
    draft_id      TEXT PRIMARY KEY,
    to_addr       TEXT NOT NULL,
    subject       TEXT NOT NULL,
    body_preview  TEXT NOT NULL,
    in_reply_to   TEXT,
    created_at    REAL NOT NULL,
    sent_at       REAL
);
"""

EMAIL_TRIAGE_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS email_triage_results (
    triage_id      TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    batch_number   INTEGER NOT NULL,
    email_id       TEXT NOT NULL,
    thread_id      TEXT,
    category       TEXT NOT NULL,
    confident      BOOLEAN NOT NULL,
    llm_summary    TEXT NOT NULL DEFAULT '',
    body_preview   TEXT NOT NULL DEFAULT '',
    token_count    INTEGER,
    duration_secs  REAL,
    created_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_triage_results_run
    ON email_triage_results(run_id);
CREATE INDEX IF NOT EXISTS idx_triage_results_email
    ON email_triage_results(email_id);
"""


# 100 chars max — see plan A4 + adversarial S15. Email bodies routinely
# carry MFA codes, password reset URLs, banking transaction summaries; a
# longer preview would silently capture them in the unencrypted SQLite.
BODY_PREVIEW_MAX_CHARS = 100


def init_schema(db) -> None:
    """Create all tables if they don't exist. Idempotent."""
    db.execute(EMAIL_ACTIONS_DDL)
    db.execute(EMAIL_DRAFTS_DDL)
    init_triage_schema(db)


def init_triage_schema(db) -> None:
    """Create the email_triage_results table if it doesn't exist. Idempotent."""
    db.execute(EMAIL_TRIAGE_RESULTS_DDL)


# ---------------------------------------------------------------------------
# email_actions API
# ---------------------------------------------------------------------------


def record_action(
    db,
    *,
    action_type: str,
    message_id: str,
    thread_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    batch_id: Optional[str] = None,
) -> str:
    """Insert a row, return the new action_id.

    ``payload`` carries the data needed to reverse the action — e.g. for
    ``trash`` the message id is enough; for ``add_label`` we record the
    added label id so undo can ``remove_label`` exactly that one.
    """
    action_id = uuid.uuid4().hex
    db.insert(
        "email_actions",
        {
            "action_id": action_id,
            "action_type": action_type,
            "message_id": message_id,
            "thread_id": thread_id,
            "payload_json": json.dumps(payload or {}),
            "batch_id": batch_id,
            "created_at": time.time(),
            "undone_at": None,
        },
    )
    return action_id


def fetch_undoable(
    db, *, action_id: str, window_seconds: int
) -> Optional[Dict[str, Any]]:
    """Return the action row if it exists, has not been undone, and is
    within the window; otherwise None.

    The window check is server-time relative — clock skew is acceptable
    because the SQLite is on the same machine.
    """
    row = db.query(
        "SELECT * FROM email_actions WHERE action_id = :id",
        {"id": action_id},
        one=True,
    )
    if row is None:
        return None
    if row["undone_at"] is not None:
        return None
    if time.time() - row["created_at"] > window_seconds:
        return None
    payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
    return {
        "action_id": row["action_id"],
        "action_type": row["action_type"],
        "message_id": row["message_id"],
        "thread_id": row["thread_id"],
        "payload": payload,
        "batch_id": row["batch_id"],
        "created_at": row["created_at"],
    }


def mark_undone(db, *, action_id: str) -> None:
    """Mark an action as undone. Idempotent — re-marking is a no-op.

    Use ``COALESCE`` so the first-undo timestamp is preserved even if
    a buggy caller re-undoes.
    """
    db.update(
        "email_actions",
        {"undone_at": time.time()},
        "action_id = :id AND undone_at IS NULL",
        {"id": action_id},
    )


# ---------------------------------------------------------------------------
# email_drafts API
# ---------------------------------------------------------------------------


def record_draft(
    db,
    *,
    draft_id: str,
    to: str,
    subject: str,
    body: str,
    in_reply_to: Optional[str] = None,
) -> None:
    """Persist a draft's metadata for confirmation + cleanup.

    Body is truncated to ``BODY_PREVIEW_MAX_CHARS`` BEFORE write — never
    persist the full body of a draft, which would make ``state.db`` a
    treasure trove of MFA codes, reset URLs, and confidential snippets.
    """
    db.insert(
        "email_drafts",
        {
            "draft_id": draft_id,
            "to_addr": to,
            "subject": subject,
            "body_preview": body[:BODY_PREVIEW_MAX_CHARS],
            "in_reply_to": in_reply_to,
            "created_at": time.time(),
            "sent_at": None,
        },
    )


def mark_draft_sent(db, *, draft_id: str) -> None:
    """Mark a draft as sent (idempotent)."""
    db.update(
        "email_drafts",
        {"sent_at": time.time()},
        "draft_id = :id AND sent_at IS NULL",
        {"id": draft_id},
    )


def fetch_draft(db, *, draft_id: str) -> Optional[Dict[str, Any]]:
    return db.query(
        "SELECT * FROM email_drafts WHERE draft_id = :id",
        {"id": draft_id},
        one=True,
    )


# ---------------------------------------------------------------------------
# email_triage_results API
# ---------------------------------------------------------------------------


def record_triage_result(
    db,
    *,
    triage_id: str,
    run_id: str,
    batch_number: int,
    email_id: str,
    thread_id: Optional[str] = None,
    category: str = "informational",
    confident: bool = False,
    llm_summary: str = "",
    body_preview: str = "",
    token_count: Optional[int] = None,
    duration_secs: float = 0.0,
) -> None:
    """Persist a single email's triage result."""
    db.insert(
        "email_triage_results",
        {
            "triage_id": triage_id,
            "run_id": run_id,
            "batch_number": batch_number,
            "email_id": email_id,
            "thread_id": thread_id,
            "category": category,
            "confident": confident,
            "llm_summary": llm_summary,
            "body_preview": body_preview,
            "token_count": token_count,
            "duration_secs": duration_secs,
            "created_at": time.time(),
        },
    )


def fetch_triage_results(db, *, run_id: str) -> List[Dict[str, Any]]:
    """Return all triage results for a given run_id."""
    rows = db.query(
        "SELECT * FROM email_triage_results WHERE run_id = :run_id "
        "ORDER BY batch_number, email_id",
        {"run_id": run_id},
    )
    return list(rows) if rows else []


__all__ = [
    "BODY_PREVIEW_MAX_CHARS",
    "EMAIL_ACTIONS_DDL",
    "EMAIL_DRAFTS_DDL",
    "EMAIL_TRIAGE_RESULTS_DDL",
    "fetch_draft",
    "fetch_triage_results",
    "fetch_undoable",
    "init_schema",
    "init_triage_schema",
    "mark_draft_sent",
    "mark_undone",
    "record_action",
    "record_draft",
    "record_triage_result",
]
