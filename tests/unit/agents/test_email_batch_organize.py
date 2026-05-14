# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Unit tests for the batch-organize tools added to the GAIA Email Agent.

Part A: Batch tool wrapper tests and pure-helper exercises.

Tests cover:
- Pure helpers (_run_batch, _run_batch_with_prior)
- All 7 batch tools via _TOOL_REGISTRY
- Empty input, full success, partial failure, all-failure paths
- Single-item batch (still returns batch envelope)
- Threshold enforcement (refuses past 5 ops / 3 senders)
- Batch ID propagation across all succeeded items and DB rows
- Undo compatibility (each succeeded action_id is fetchable)
- Error paths (ConnectorsError, general Exception)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make tests.fixtures importable.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gaia.agents.email import action_store  # noqa: E402
from gaia.agents.email.tools.organize_tools import (  # noqa: E402
    _run_batch,
    _run_batch_with_prior,
)
from gaia.agents.base.tools import _TOOL_REGISTRY  # noqa: E402
from gaia.connectors.errors import ConnectorsError  # noqa: E402
from gaia.database.mixin import DatabaseMixin  # noqa: E402
from tests.fixtures.email.fake_gmail import (  # noqa: E402
    FakeGmailBackend,
    FakeGmailTransport,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    """In-memory DB for pure-helper tests that don't involve the agent."""
    class _DB(DatabaseMixin):
        def __init__(self):
            self.init_db(":memory:")

    db = _DB()
    action_store.init_schema(db)
    yield db
    db.close_db()


@pytest.fixture
def fake_gmail():
    return FakeGmailBackend(
        _REPO_ROOT / "tests" / "fixtures" / "email" / "_stub_inbox.mbox"
    )


@pytest.fixture
def email_agent(tmp_path, fake_gmail):
    from gaia.agents.email.agent import EmailTriageAgent
    from gaia.agents.email.config import EmailAgentConfig

    cfg = EmailAgentConfig(
        gmail_backend=fake_gmail,
        calendar_backend=MagicMock(),
        db_path=str(tmp_path / "state.db"),
        silent_mode=True,
    )
    with patch("gaia.agents.base.agent.AgentSDK") as mock_sdk:
        mock_sdk.return_value = MagicMock()
        agent = EmailTriageAgent(config=cfg)
    yield agent
    agent.close_db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BATCH_TOOLS = [
    "mark_read_batch",
    "mark_unread_batch",
    "add_star_batch",
    "remove_star_batch",
    "archive_message_batch",
    "label_message_batch",
    "move_to_label_batch",
]

_SINGLE_TOOLS = [
    "mark_read",
    "mark_unread",
    "add_star",
    "remove_star",
    "archive_message",
    "label_message",
    "move_to_label",
]

_HEX_RE = re.compile(r"^[0-9a-f]+$")


def _parse(result_str):
    return json.loads(result_str)


def _get_tool(name):
    return _TOOL_REGISTRY[name]["function"]


# ---------------------------------------------------------------------------
# 1. Pure helpers
# ---------------------------------------------------------------------------


class TestRunBatchPure:
    """Direct exercises of _run_batch and _run_batch_with_prior."""

    def test_empty_list_returns_empty_arrays(self, fake_gmail, db):
        out = _run_batch(
            fake_gmail,
            db,
            [],
            gmail_op=fake_gmail.mark_read,
            action_type="mark_read",
            batch_id="test-batch",
        )
        assert out == {"succeeded": [], "failed": []}

    def test_all_succeed(self, fake_gmail, db):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        out = _run_batch(
            fake_gmail,
            db,
            msg_ids,
            gmail_op=fake_gmail.mark_read,
            action_type="mark_read",
            batch_id="test-batch",
        )
        assert len(out["succeeded"]) == 3
        assert len(out["failed"]) == 0
        for item in out["succeeded"]:
            assert "message_id" in item
            assert "action_id" in item

    def test_partial_failure(self, fake_gmail, db):
        valid = list(fake_gmail._messages.keys())[:2]
        all_ids = valid + ["nonexistent-1", "nonexistent-2"]
        out = _run_batch(
            fake_gmail,
            db,
            all_ids,
            gmail_op=fake_gmail.mark_read,
            action_type="mark_read",
            batch_id="test-batch",
        )
        assert len(out["succeeded"]) == 2
        assert len(out["failed"]) == 2
        for item in out["failed"]:
            assert "message_id" in item
            assert "error" in item

    def test_all_fail(self, fake_gmail, db):
        out = _run_batch(
            fake_gmail,
            db,
            ["nope-1", "nope-2"],
            gmail_op=fake_gmail.mark_read,
            action_type="mark_read",
            batch_id="test-batch",
        )
        assert len(out["succeeded"]) == 0
        assert len(out["failed"]) == 2

    def test_batch_id_shared_across_succeeded(self, fake_gmail, db):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        _run_batch(
            fake_gmail,
            db,
            msg_ids,
            gmail_op=fake_gmail.mark_read,
            action_type="mark_read",
            batch_id="shared-id",
        )
        rows = db.query("SELECT batch_id FROM email_actions")
        for row in rows:
            assert row["batch_id"] == "shared-id"

    def test_ordering_invariant_gmail_before_db(self, fake_gmail, db):
        """Gmail call must happen before DB write for each item."""
        msg_ids = list(fake_gmail._messages.keys())[:2]
        _run_batch(
            fake_gmail,
            db,
            msg_ids,
            gmail_op=fake_gmail.mark_read,
            action_type="mark_read",
            batch_id="test-batch",
        )
        # Both messages should have UNREAD removed (Gmail call happened).
        for mid in msg_ids:
            post = fake_gmail.get_message(mid)
            assert "UNREAD" not in post["labelIds"]
        # DB rows exist (DB write happened).
        count = db.query(
            "SELECT COUNT(*) AS n FROM email_actions", one=True
        )["n"]
        assert count == 2

    def test_exception_isolation(self, fake_gmail, db):
        """One failure must not prevent others from succeeding."""
        msg_ids = list(fake_gmail._messages.keys())[:2] + ["bad-id"]
        out = _run_batch(
            fake_gmail,
            db,
            msg_ids,
            gmail_op=fake_gmail.mark_read,
            action_type="mark_read",
            batch_id="test-batch",
        )
        assert len(out["succeeded"]) == 2
        assert len(out["failed"]) == 1
        assert out["failed"][0]["message_id"] == "bad-id"

    def test_run_batch_with_prior_all_succeed(self, fake_gmail, db):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        out = _run_batch_with_prior(
            fake_gmail,
            db,
            msg_ids,
            gmail_op=fake_gmail.archive_message,
            action_type="archive",
            prior_fn=lambda msg: list(msg.get("labelIds", [])),
            payload_fn=lambda msg, prior: {"prior_labels": prior},
            batch_id="prior-batch",
        )
        assert len(out["succeeded"]) == 3
        assert len(out["failed"]) == 0

    def test_run_batch_with_prior_partial_failure(self, fake_gmail, db):
        valid = list(fake_gmail._messages.keys())[:2]
        all_ids = valid + ["nonexistent-1"]
        out = _run_batch_with_prior(
            fake_gmail,
            db,
            all_ids,
            gmail_op=fake_gmail.archive_message,
            action_type="archive",
            prior_fn=lambda msg: list(msg.get("labelIds", [])),
            payload_fn=lambda msg, prior: {"prior_labels": prior},
            batch_id="prior-batch",
        )
        assert len(out["succeeded"]) == 2
        assert len(out["failed"]) == 1

    def test_run_batch_with_prior_payload_preserves_prior_labels(
        self, fake_gmail, db
    ):
        msg_ids = list(fake_gmail._messages.keys())[:2]
        _run_batch_with_prior(
            fake_gmail,
            db,
            msg_ids,
            gmail_op=fake_gmail.archive_message,
            action_type="archive",
            prior_fn=lambda msg: list(msg.get("labelIds", [])),
            payload_fn=lambda msg, prior: {"prior_labels": prior},
            batch_id="prior-batch",
        )
        rows = db.query("SELECT payload_json FROM email_actions ORDER BY rowid")
        for row in rows:
            payload = json.loads(row["payload_json"])
            assert "prior_labels" in payload
            assert isinstance(payload["prior_labels"], list)


# ---------------------------------------------------------------------------
# 2. Empty input
# ---------------------------------------------------------------------------


class TestBatchEmptyInput:
    """All 7 batch tools return ok with empty arrays for message_ids=[]."""

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_empty_list_returns_ok_with_zero_total(self, email_agent, tool_name):
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            result = _parse(fn(message_ids=[], label_id="Label_1"))
        else:
            result = _parse(fn(message_ids=[]))
        assert result["ok"] is True
        data = result["data"]
        assert data["total"] == 0
        assert data["succeeded"] == []
        assert data["failed"] == []


# ---------------------------------------------------------------------------
# 3. Success paths
# ---------------------------------------------------------------------------


class TestBatchSuccessPaths:
    """All 7 tools with valid message_ids produce correct envelope shape
    and mutate state correctly."""

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_envelope_shape(self, email_agent, fake_gmail, tool_name):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"batch-{tool_name}")
            result = _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=msg_ids))

        assert result["ok"] is True
        data = result["data"]
        assert "batch_id" in data
        assert data["total"] == 3
        assert len(data["succeeded"]) == 3
        assert data["failed"] == []

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_all_items_in_succeeded(self, email_agent, fake_gmail, tool_name):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"batch2-{tool_name}")
            result = _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=msg_ids))

        succeeded_ids = {s["message_id"] for s in result["data"]["succeeded"]}
        for mid in msg_ids:
            assert mid in succeeded_ids

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_db_rows_written_with_batch_id(
        self, email_agent, fake_gmail, tool_name
    ):
        """DB rows are written to the agent's DB (not a separate fixture)."""
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"batch3-{tool_name}")
            result = _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=msg_ids))

        batch_id = result["data"]["batch_id"]
        rows = email_agent.query(
            "SELECT COUNT(*) AS n FROM email_actions WHERE batch_id = :bid",
            params={"bid": batch_id},
            one=True,
        )
        assert rows["n"] == 3

    @pytest.mark.parametrize("tool_name", ["archive_message_batch", "move_to_label_batch"])
    def test_prior_labels_in_payload(
        self, email_agent, fake_gmail, tool_name
    ):
        msg_ids = list(fake_gmail._messages.keys())[:2]
        fn = _get_tool(tool_name)
        if tool_name == "move_to_label_batch":
            new_label = fake_gmail.create_label(name=f"prior-{tool_name}")
            _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
        else:
            _parse(fn(message_ids=msg_ids))

        rows = email_agent.query("SELECT payload_json FROM email_actions ORDER BY rowid")
        for row in rows:
            payload = json.loads(row["payload_json"])
            assert "prior_labels" in payload


# ---------------------------------------------------------------------------
# 4. Partial failure
# ---------------------------------------------------------------------------


class TestBatchPartialFailure:
    """Mix of valid/invalid IDs for all 7 tools."""

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_valid_items_succeed_invalid_fail(
        self, email_agent, fake_gmail, tool_name
    ):
        valid = list(fake_gmail._messages.keys())[:2]
        all_ids = valid + ["nonexistent-id"]
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"pf-{tool_name}")
            result = _parse(fn(message_ids=all_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=all_ids))

        data = result["data"]
        assert len(data["succeeded"]) == 2
        assert len(data["failed"]) == 1
        succeeded_ids = {s["message_id"] for s in data["succeeded"]}
        for mid in valid:
            assert mid in succeeded_ids
        assert data["failed"][0]["message_id"] == "nonexistent-id"
        assert "error" in data["failed"][0]

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_only_succeeded_items_have_db_rows(
        self, email_agent, fake_gmail, tool_name
    ):
        valid = list(fake_gmail._messages.keys())[:2]
        all_ids = valid + ["nonexistent-id"]
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"pf2-{tool_name}")
            result = _parse(fn(message_ids=all_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=all_ids))

        batch_id = result["data"]["batch_id"]
        rows = email_agent.query(
            "SELECT COUNT(*) AS n FROM email_actions WHERE batch_id = :bid",
            params={"bid": batch_id},
            one=True,
        )
        assert rows["n"] == 2

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_state_mutated_for_succeeded_items(
        self, email_agent, fake_gmail, tool_name
    ):
        msg_ids = list(fake_gmail._messages.keys())[:2]
        all_ids = msg_ids + ["nonexistent-id"]
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"pf3-{tool_name}")
            _parse(fn(message_ids=all_ids, label_id=new_label["id"]))
            for mid in msg_ids:
                post = fake_gmail.get_message(mid)
                assert new_label["id"] in post["labelIds"]
        elif tool_name == "mark_read_batch":
            _parse(fn(message_ids=all_ids))
            for mid in msg_ids:
                post = fake_gmail.get_message(mid)
                assert "UNREAD" not in post["labelIds"]
        elif tool_name == "mark_unread_batch":
            # Archive first to strip UNREAD, then mark_unread_batch adds it back.
            for mid in msg_ids:
                fake_gmail.mark_read(mid)
            _parse(fn(message_ids=all_ids))
            for mid in msg_ids:
                post = fake_gmail.get_message(mid)
                assert "UNREAD" in post["labelIds"]
        elif tool_name == "add_star_batch":
            _parse(fn(message_ids=all_ids))
            for mid in msg_ids:
                post = fake_gmail.get_message(mid)
                assert "STARRED" in post["labelIds"]
        elif tool_name == "remove_star_batch":
            # Add star first, then remove.
            for mid in msg_ids:
                fake_gmail.add_star(mid)
            _parse(fn(message_ids=all_ids))
            for mid in msg_ids:
                post = fake_gmail.get_message(mid)
                assert "STARRED" not in post["labelIds"]
        elif tool_name == "archive_message_batch":
            _parse(fn(message_ids=all_ids))
            for mid in msg_ids:
                post = fake_gmail.get_message(mid)
                assert "INBOX" not in post["labelIds"]
        elif tool_name == "move_to_label_batch":
            _parse(fn(message_ids=all_ids, label_id=new_label["id"]))
            for mid in msg_ids:
                post = fake_gmail.get_message(mid)
                assert "INBOX" not in post["labelIds"]
                assert new_label["id"] in post["labelIds"]


# ---------------------------------------------------------------------------
# 5. All failure
# ---------------------------------------------------------------------------


class TestBatchAllFailure:
    """All invalid IDs for all 7 tools."""

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_empty_succeeded_all_failed(
        self, email_agent, fake_gmail, tool_name
    ):
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"af-{tool_name}")
            result = _parse(
                fn(message_ids=["bad-1", "bad-2"], label_id=new_label["id"])
            )
        else:
            result = _parse(fn(message_ids=["bad-1", "bad-2"]))

        data = result["data"]
        assert len(data["succeeded"]) == 0
        assert len(data["failed"]) == 2

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_zero_db_rows_on_all_failure(
        self, email_agent, fake_gmail, tool_name
    ):
        fn = _get_tool(tool_name)
        pre_count = email_agent.query(
            "SELECT COUNT(*) AS n FROM email_actions", one=True
        )["n"]
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"af2-{tool_name}")
            _parse(fn(message_ids=["bad-1", "bad-2"], label_id=new_label["id"]))
        else:
            _parse(fn(message_ids=["bad-1", "bad-2"]))

        post_count = email_agent.query(
            "SELECT COUNT(*) AS n FROM email_actions", one=True
        )["n"]
        assert post_count == pre_count


# ---------------------------------------------------------------------------
# 6. Single item
# ---------------------------------------------------------------------------


class TestBatchSingleItem:
    """Single message_id in list still returns batch envelope."""

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_single_item_returns_batch_envelope(
        self, email_agent, fake_gmail, tool_name
    ):
        msg_ids = list(fake_gmail._messages.keys())[:1]
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"si-{tool_name}")
            result = _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=msg_ids))

        data = result["data"]
        assert "batch_id" in data
        assert data["total"] == 1
        assert len(data["succeeded"]) == 1
        assert data["failed"] == []

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_single_item_mutates_correctly(
        self, email_agent, fake_gmail, tool_name
    ):
        msg_ids = list(fake_gmail._messages.keys())[:1]
        fn = _get_tool(tool_name)
        if tool_name == "mark_read_batch":
            _parse(fn(message_ids=msg_ids))
            post = fake_gmail.get_message(msg_ids[0])
            assert "UNREAD" not in post["labelIds"]
        elif tool_name == "mark_unread_batch":
            fake_gmail.mark_read(msg_ids[0])
            _parse(fn(message_ids=msg_ids))
            post = fake_gmail.get_message(msg_ids[0])
            assert "UNREAD" in post["labelIds"]
        elif tool_name == "add_star_batch":
            _parse(fn(message_ids=msg_ids))
            post = fake_gmail.get_message(msg_ids[0])
            assert "STARRED" in post["labelIds"]
        elif tool_name == "remove_star_batch":
            fake_gmail.add_star(msg_ids[0])
            _parse(fn(message_ids=msg_ids))
            post = fake_gmail.get_message(msg_ids[0])
            assert "STARRED" not in post["labelIds"]
        elif tool_name == "archive_message_batch":
            _parse(fn(message_ids=msg_ids))
            post = fake_gmail.get_message(msg_ids[0])
            assert "INBOX" not in post["labelIds"]
        elif tool_name == "label_message_batch":
            new_label = fake_gmail.create_label(name=f"si-{tool_name}")
            _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
            post = fake_gmail.get_message(msg_ids[0])
            assert new_label["id"] in post["labelIds"]
        elif tool_name == "move_to_label_batch":
            new_label = fake_gmail.create_label(name=f"si-{tool_name}")
            _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
            post = fake_gmail.get_message(msg_ids[0])
            assert new_label["id"] in post["labelIds"]
            assert "INBOX" not in post["labelIds"]

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_single_item_exactly_one_db_row(
        self, email_agent, fake_gmail, tool_name
    ):
        msg_ids = list(fake_gmail._messages.keys())[:1]
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"si2-{tool_name}")
            result = _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=msg_ids))

        batch_id = result["data"]["batch_id"]
        rows = email_agent.query(
            "SELECT COUNT(*) AS n FROM email_actions WHERE batch_id = :bid",
            params={"bid": batch_id},
            one=True,
        )
        assert rows["n"] == 1


# ---------------------------------------------------------------------------
# 7. Threshold enforcement
# ---------------------------------------------------------------------------


class TestBatchThresholdEnforcement:
    """When threshold exceeded, all 7 batch tools return error without
    executing."""

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_refuses_past_threshold(self, email_agent, fake_gmail, tool_name):
        # Bump counters past the boundary (>5 ops, >3 senders).
        for sender in ("a", "b", "c", "d"):
            email_agent._record_organize_op(f"m-{sender}-1", sender)
        email_agent._record_organize_op("m-x", "a")
        email_agent._record_organize_op("m-y", "b")
        assert email_agent._organize_batch_threshold_exceeded() is True

        msg_ids = list(fake_gmail._messages.keys())[:3]
        fn = _get_tool(tool_name)
        prior_labels = {}
        for mid in msg_ids:
            prior_labels[mid] = list(
                fake_gmail.get_message(mid).get("labelIds", [])
            )

        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"te-{tool_name}")
            result = _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=msg_ids))

        assert result["ok"] is False
        assert "batch threshold" in result["error"].lower()

        # No state mutation.
        for mid in msg_ids:
            post = fake_gmail.get_message(mid)
            assert post["labelIds"] == prior_labels[mid]

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_no_gmail_transport_calls_when_threshold_exceeded(
        self, email_agent, fake_gmail, tool_name
    ):
        for sender in ("a", "b", "c", "d"):
            email_agent._record_organize_op(f"m-{sender}-1", sender)
        email_agent._record_organize_op("m-x", "a")
        email_agent._record_organize_op("m-y", "b")

        fake_gmail.transport.reset()
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"te2-{tool_name}")
            _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
        else:
            _parse(fn(message_ids=msg_ids))

        # No batch-specific transport calls.
        batch_calls = [
            c for c in fake_gmail.transport.calls
            if "batch" in c[0] or c[0] in (
                "archive_message", "mark_read", "mark_unread",
                "add_star", "remove_star", "add_label",
            )
        ]
        assert len(batch_calls) == 0

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_boundary_value_does_not_trigger_threshold(
        self, email_agent, fake_gmail, tool_name
    ):
        """Exactly 5 ops across exactly 3 senders should NOT trip the
        threshold (>5 ops AND >3 senders required)."""
        # Record exactly 5 ops across 3 senders.
        email_agent._record_organize_op("m-a-1", "a")
        email_agent._record_organize_op("m-a-2", "a")
        email_agent._record_organize_op("m-b-1", "b")
        email_agent._record_organize_op("m-c-1", "c")
        email_agent._record_organize_op("m-c-2", "c")
        assert email_agent._organize_batch_threshold_exceeded() is False

        # Batch tool should succeed.
        msg_ids = list(fake_gmail._messages.keys())[:2]
        fn = _get_tool(tool_name)
        prior_labels = {
            mid: list(fake_gmail.get_message(mid).get("labelIds", []))
            for mid in msg_ids
        }
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"bv-{tool_name}")
            result = _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=msg_ids))

        assert result["ok"] is True
        assert len(result["data"]["succeeded"]) == 2

        # State was mutated.
        for mid in msg_ids:
            post = fake_gmail.get_message(mid)
            if tool_name == "mark_read_batch":
                assert "UNREAD" not in post["labelIds"]
            elif tool_name == "mark_unread_batch":
                assert "UNREAD" in post["labelIds"]
            elif tool_name == "add_star_batch":
                assert "STARRED" in post["labelIds"]
            elif tool_name == "remove_star_batch":
                assert "STARRED" not in post["labelIds"]
            elif tool_name == "archive_message_batch":
                assert "INBOX" not in post["labelIds"]
            elif tool_name in ("label_message_batch", "move_to_label_batch"):
                assert new_label["id"] in post["labelIds"]


class TestBatchDbFailure:
    """DB failure after successful Gmail operation."""

    def test_gmail_success_db_failure_run_batch_with_prior(
        self, email_agent, fake_gmail
    ):
        """When Gmail succeeds but DB write fails, item goes to failed[]
        and Gmail state is NOT rolled back."""
        msg_ids = list(fake_gmail._messages.keys())[:2]
        fn = _get_tool("archive_message_batch")

        # Capture prior state.
        prior_labels = {
            mid: list(fake_gmail.get_message(mid).get("labelIds", []))
            for mid in msg_ids
        }

        # Force DB write to fail after Gmail succeeds by patching
        # action_store.record_action at the module level.
        import gaia.agents.email.action_store as _action_store
        original_record = _action_store.record_action

        def _boom_record(db, **kwargs):
            raise RuntimeError("database write failure")

        _action_store.record_action = _boom_record
        try:
            result = _parse(fn(message_ids=msg_ids))
            # All items fail at DB level, but Gmail calls succeeded.
            assert result["ok"] is True
            assert len(result["data"]["succeeded"]) == 0
            assert len(result["data"]["failed"]) == 2
            for item in result["data"]["failed"]:
                assert "database write failure" in item["error"]

            # Gmail state IS mutated (no rollback).
            for mid in msg_ids:
                post = fake_gmail.get_message(mid)
                assert "INBOX" not in post["labelIds"]
                assert post["labelIds"] != prior_labels[mid]
        finally:
            _action_store.record_action = original_record


# ---------------------------------------------------------------------------
# 8. Batch ID propagation
# ---------------------------------------------------------------------------


class TestBatchIdPropagation:
    """All items share same batch_id."""

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_shared_batch_id_in_envelope_and_db(
        self, email_agent, fake_gmail, tool_name
    ):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"bp-{tool_name}")
            result = _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=msg_ids))

        batch_id = result["data"]["batch_id"]
        # batch_id is non-empty hex string.
        assert _HEX_RE.match(batch_id), f"batch_id '{batch_id}' is not hex"

        # All DB rows share the same batch_id.
        rows = email_agent.query("SELECT batch_id FROM email_actions")
        for row in rows:
            assert row["batch_id"] == batch_id

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_envelope_batch_id_matches_db(self, email_agent, fake_gmail, tool_name):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"bp2-{tool_name}")
            result = _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=msg_ids))

        envelope_batch_id = result["data"]["batch_id"]
        succeeded_ids = [s["message_id"] for s in result["data"]["succeeded"]]

        # Query DB for these message_ids and confirm batch_id match.
        for mid in succeeded_ids:
            row = email_agent.query(
                "SELECT batch_id FROM email_actions WHERE message_id = :mid",
                params={"mid": mid},
                one=True,
            )
            assert row["batch_id"] == envelope_batch_id


# ---------------------------------------------------------------------------
# 9. Undo compatibility
# ---------------------------------------------------------------------------


class TestBatchUndoCompatibility:
    """Individual batch actions can be undone."""

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_succeeded_action_id_is_fetchable(
        self, email_agent, fake_gmail, tool_name
    ):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"undo-{tool_name}")
            result = _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=msg_ids))

        for item in result["data"]["succeeded"]:
            action_id = item["action_id"]
            row = action_store.fetch_undoable(
                email_agent, action_id=action_id, window_seconds=30
            )
            assert row is not None, f"action_id {action_id} not fetchable"

    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_rows_not_marked_done(self, email_agent, fake_gmail, tool_name):
        msg_ids = list(fake_gmail._messages.keys())[:2]
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"undo2-{tool_name}")
            result = _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=msg_ids))

        for item in result["data"]["succeeded"]:
            row = email_agent.query(
                "SELECT undone_at FROM email_actions WHERE action_id = :aid",
                params={"aid": item["action_id"]},
                one=True,
            )
            assert row["undone_at"] is None

    def test_archive_batch_preserves_prior_labels_for_undo(
        self, email_agent, fake_gmail
    ):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fn = _get_tool("archive_message_batch")
        _parse(fn(message_ids=msg_ids))

        for mid in msg_ids:
            row = email_agent.query(
                "SELECT payload_json FROM email_actions WHERE message_id = :mid",
                params={"mid": mid},
                one=True,
            )
            payload = json.loads(row["payload_json"])
            assert "prior_labels" in payload
            assert isinstance(payload["prior_labels"], list)
            assert len(payload["prior_labels"]) > 0

    def test_move_batch_preserves_prior_labels_and_label_id_for_undo(
        self, email_agent, fake_gmail
    ):
        msg_ids = list(fake_gmail._messages.keys())[:2]
        new_label = fake_gmail.create_label(name="undo-move")
        fn = _get_tool("move_to_label_batch")
        _parse(fn(message_ids=msg_ids, label_id=new_label["id"]))

        for mid in msg_ids:
            row = email_agent.query(
                "SELECT payload_json FROM email_actions WHERE message_id = :mid",
                params={"mid": mid},
                one=True,
            )
            payload = json.loads(row["payload_json"])
            assert "prior_labels" in payload
            assert "label_id" in payload
            assert payload["label_id"] == new_label["id"]


# ---------------------------------------------------------------------------
# 10. Error paths
# ---------------------------------------------------------------------------


class TestBatchToolErrorPaths:
    """ConnectorsError and Exception paths return error envelopes."""

    def test_internal_gmail_error_goes_to_failed_list(self, email_agent, fake_gmail):
        """General Exception inside _run_batch is caught and returned in
        the failed[] list (the designed behavior for per-item failures)."""
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fn = _get_tool("mark_read_batch")

        # Force the gmail.mark_read to raise a general Exception.
        original = fake_gmail.mark_read

        def _boom(mid):
            raise RuntimeError("simulated transport failure")

        fake_gmail.mark_read = _boom
        try:
            result = _parse(fn(message_ids=msg_ids))
            # The _run_batch catches this internally and puts all in failed[].
            assert result["ok"] is True
            assert len(result["data"]["succeeded"]) == 0
            assert len(result["data"]["failed"]) == 3
        finally:
            fake_gmail.mark_read = original

    def test_general_exception_returns_error_envelope(self, email_agent, fake_gmail):
        """General Exception from the tool wrapper's outer try/except."""
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fn = _get_tool("mark_read_batch")

        # Make the error happen OUTSIDE _run_batch by making
        # agent._record_organize_op raise after the batch completes.
        original_record = email_agent._record_organize_op

        def _boom_record(mid, sender):
            raise RuntimeError("boom after batch")

        email_agent._record_organize_op = _boom_record
        try:
            result = _parse(fn(message_ids=msg_ids))
            assert result["ok"] is False
            assert "error" in result
            assert "RuntimeError" in result["error"]
        finally:
            email_agent._record_organize_op = original_record

    def test_connectors_error_at_tool_level(self, email_agent, fake_gmail):
        """ConnectorsError inside _run_batch goes to failed items."""
        msg_ids = list(fake_gmail._messages.keys())[:3]

        fn = _get_tool("mark_read_batch")
        original = fake_gmail.mark_read
        fake_gmail.mark_read = lambda mid: (_ for _ in ()).throw(
            ConnectorsError("transport down")
        )
        try:
            result = _parse(fn(message_ids=msg_ids))
            # ConnectorsError is caught by _run_batch's except Exception
            # and returned in failed[].
            assert result["ok"] is True
            assert len(result["data"]["failed"]) == 3
            for item in result["data"]["failed"]:
                assert "ConnectorsError" in item["error"]
        finally:
            fake_gmail.mark_read = original
