# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Unit tests for ``FakeGmailBackend`` batch methods.

Part B: Behavioral parity, transport recording, and state mutation.

Tests cover:
1. Behavioral parity -- batch method produces same state as looping single methods
2. Transport recording -- batch call recorded with full message_ids
3. State mutation -- correct label changes on all messages

Uses the source ``FakeGmailBackend`` from ``gaia.agents.email.fake_gmail``
which includes the batch method implementations.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make tests.fixtures importable.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gaia.agents.email.fake_gmail import FakeGmailBackend  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_gmail():
    return FakeGmailBackend(
        _REPO_ROOT / "tests" / "fixtures" / "email" / "_stub_inbox.mbox"
    )


# ---------------------------------------------------------------------------
# 1. Behavioral parity -- batch == loop of single methods
# ---------------------------------------------------------------------------


class TestBatchParity:
    """Batch method must produce the same final state as looping single
    method calls."""

    def test_mark_read_batch_parity(self):
        msg_ids = self._first_n(3)

        batch_gmail = self._load()
        batch_gmail.mark_read_batch(msg_ids)

        single_gmail = self._load()
        for mid in msg_ids:
            single_gmail.mark_read(mid)

        for mid in msg_ids:
            batch_labels = set(batch_gmail.get_message(mid)["labelIds"])
            single_labels = set(single_gmail.get_message(mid)["labelIds"])
            assert batch_labels == single_labels

    def test_mark_unread_batch_parity(self):
        msg_ids = self._first_n(3)

        batch_gmail = self._load()
        for mid in msg_ids:
            batch_gmail.mark_read(mid)
        batch_gmail.mark_unread_batch(msg_ids)

        single_gmail = self._load()
        for mid in msg_ids:
            single_gmail.mark_read(mid)
            single_gmail.mark_unread(mid)

        for mid in msg_ids:
            assert set(batch_gmail.get_message(mid)["labelIds"]) == set(
                single_gmail.get_message(mid)["labelIds"]
            )

    def test_add_star_batch_parity(self):
        msg_ids = self._first_n(3)

        batch_gmail = self._load()
        batch_gmail.add_star_batch(msg_ids)

        single_gmail = self._load()
        for mid in msg_ids:
            single_gmail.add_star(mid)

        for mid in msg_ids:
            assert set(batch_gmail.get_message(mid)["labelIds"]) == set(
                single_gmail.get_message(mid)["labelIds"]
            )

    def test_remove_star_batch_parity(self):
        msg_ids = self._first_n(3)

        batch_gmail = self._load()
        for mid in msg_ids:
            batch_gmail.add_star(mid)
        batch_gmail.remove_star_batch(msg_ids)

        single_gmail = self._load()
        for mid in msg_ids:
            single_gmail.add_star(mid)
            single_gmail.remove_star(mid)

        for mid in msg_ids:
            assert set(batch_gmail.get_message(mid)["labelIds"]) == set(
                single_gmail.get_message(mid)["labelIds"]
            )

    def test_archive_message_batch_parity(self):
        msg_ids = self._first_n(3)

        batch_gmail = self._load()
        batch_gmail.archive_message_batch(msg_ids)

        single_gmail = self._load()
        for mid in msg_ids:
            single_gmail.archive_message(mid)

        for mid in msg_ids:
            assert set(batch_gmail.get_message(mid)["labelIds"]) == set(
                single_gmail.get_message(mid)["labelIds"]
            )

    def test_add_label_batch_parity(self):
        msg_ids = self._first_n(3)

        batch_gmail = self._load()
        label = batch_gmail.create_label(name="parity-test")
        batch_gmail.add_label_batch(msg_ids, label["id"])

        single_gmail = self._load()
        label2 = single_gmail.create_label(name="parity-test-2")
        for mid in msg_ids:
            single_gmail.add_label(mid, label2["id"])

        for mid in msg_ids:
            batch_labels = set(batch_gmail.get_message(mid)["labelIds"])
            single_labels = set(single_gmail.get_message(mid)["labelIds"])
            assert label["id"] in batch_labels
            assert label2["id"] in single_labels

    def test_remove_label_batch_parity(self):
        msg_ids = self._first_n(3)

        batch_gmail = self._load()
        batch_gmail.remove_label_batch(msg_ids, "INBOX")

        single_gmail = self._load()
        for mid in msg_ids:
            single_gmail.remove_label(mid, "INBOX")

        for mid in msg_ids:
            assert set(batch_gmail.get_message(mid)["labelIds"]) == set(
                single_gmail.get_message(mid)["labelIds"]
            )

    # -- Helpers ----------------------------------------------------------

    @staticmethod
    def _load():
        return FakeGmailBackend(
            _REPO_ROOT / "tests" / "fixtures" / "email" / "_stub_inbox.mbox"
        )

    @staticmethod
    def _first_n(n):
        gmail = FakeGmailBackend(
            _REPO_ROOT / "tests" / "fixtures" / "email" / "_stub_inbox.mbox"
        )
        return list(gmail._messages.keys())[:n]


# ---------------------------------------------------------------------------
# 2. Transport recording
# ---------------------------------------------------------------------------


class TestTransportRecording:
    """Batch calls are recorded with the full message_ids list."""

    def test_mark_read_batch_records_transport(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fake_gmail.mark_read_batch(msg_ids)

        calls = fake_gmail.transport.calls
        batch_calls = [c for c in calls if c[0] == "mark_read_batch"]
        assert len(batch_calls) == 1
        assert batch_calls[0][1]["message_ids"] == msg_ids

    def test_mark_unread_batch_records_transport(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fake_gmail.mark_unread_batch(msg_ids)

        calls = fake_gmail.transport.calls
        batch_calls = [c for c in calls if c[0] == "mark_unread_batch"]
        assert len(batch_calls) == 1
        assert batch_calls[0][1]["message_ids"] == msg_ids

    def test_add_star_batch_records_transport(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fake_gmail.add_star_batch(msg_ids)

        calls = fake_gmail.transport.calls
        batch_calls = [c for c in calls if c[0] == "add_star_batch"]
        assert len(batch_calls) == 1
        assert batch_calls[0][1]["message_ids"] == msg_ids

    def test_remove_star_batch_records_transport(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fake_gmail.remove_star_batch(msg_ids)

        calls = fake_gmail.transport.calls
        batch_calls = [c for c in calls if c[0] == "remove_star_batch"]
        assert len(batch_calls) == 1
        assert batch_calls[0][1]["message_ids"] == msg_ids

    def test_archive_message_batch_records_transport(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fake_gmail.archive_message_batch(msg_ids)

        calls = fake_gmail.transport.calls
        batch_calls = [c for c in calls if c[0] == "archive_message_batch"]
        assert len(batch_calls) == 1
        assert batch_calls[0][1]["message_ids"] == msg_ids

    def test_add_label_batch_records_transport(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        label = fake_gmail.create_label(name="transport-test")
        fake_gmail.add_label_batch(msg_ids, label["id"])

        calls = fake_gmail.transport.calls
        batch_calls = [c for c in calls if c[0] == "add_label_batch"]
        assert len(batch_calls) == 1
        assert batch_calls[0][1]["message_ids"] == msg_ids
        assert batch_calls[0][1]["label_id"] == label["id"]

    def test_remove_label_batch_records_transport(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fake_gmail.remove_label_batch(msg_ids, "INBOX")

        calls = fake_gmail.transport.calls
        batch_calls = [c for c in calls if c[0] == "remove_label_batch"]
        assert len(batch_calls) == 1
        assert batch_calls[0][1]["message_ids"] == msg_ids
        assert batch_calls[0][1]["label_id"] == "INBOX"


# ---------------------------------------------------------------------------
# 3. State mutation
# ---------------------------------------------------------------------------


class TestStateMutation:
    """Batch methods correctly mutate labels on all messages."""

    def test_mark_read_batch_removes_unread(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fake_gmail.mark_read_batch(msg_ids)
        for mid in msg_ids:
            assert "UNREAD" not in fake_gmail.get_message(mid)["labelIds"]

    def test_mark_unread_batch_adds_unread(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        for mid in msg_ids:
            fake_gmail.mark_read(mid)
        fake_gmail.mark_unread_batch(msg_ids)
        for mid in msg_ids:
            assert "UNREAD" in fake_gmail.get_message(mid)["labelIds"]

    def test_add_star_batch_adds_starred(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fake_gmail.add_star_batch(msg_ids)
        for mid in msg_ids:
            assert "STARRED" in fake_gmail.get_message(mid)["labelIds"]

    def test_remove_star_batch_removes_starred(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        for mid in msg_ids:
            fake_gmail.add_star(mid)
        fake_gmail.remove_star_batch(msg_ids)
        for mid in msg_ids:
            assert "STARRED" not in fake_gmail.get_message(mid)["labelIds"]

    def test_archive_message_batch_removes_inbox(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fake_gmail.archive_message_batch(msg_ids)
        for mid in msg_ids:
            assert "INBOX" not in fake_gmail.get_message(mid)["labelIds"]

    def test_add_label_batch_adds_label(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        label = fake_gmail.create_label(name="mutation-test")
        fake_gmail.add_label_batch(msg_ids, label["id"])
        for mid in msg_ids:
            assert label["id"] in fake_gmail.get_message(mid)["labelIds"]

    def test_remove_label_batch_removes_label(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        fake_gmail.remove_label_batch(msg_ids, "INBOX")
        for mid in msg_ids:
            assert "INBOX" not in fake_gmail.get_message(mid)["labelIds"]

    def test_batch_returns_results_list(self, fake_gmail):
        msg_ids = list(fake_gmail._messages.keys())[:3]
        result = fake_gmail.mark_read_batch(msg_ids)
        assert "results" in result
        assert len(result["results"]) == 3

    def test_batch_with_empty_message_ids(self, fake_gmail):
        result = fake_gmail.mark_read_batch([])
        assert result["results"] == []

    def test_batch_with_nonexistent_id_raises(self, fake_gmail):
        with pytest.raises(KeyError):
            fake_gmail.mark_read_batch(["nonexistent-id"])
