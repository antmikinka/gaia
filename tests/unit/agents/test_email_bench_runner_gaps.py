# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""PR1 gap-fix regression tests.

Covers 3 gaps identified by code review:
1. _normalize_agent_result("") -- empty string handling
2. _is_triage_prompt false positives -- verb+target dual-requirement
3. _sync_session_state_from_smart_result -- malformed conversation shapes
"""

from __future__ import annotations

import pytest

from gaia.agents.email.bench.data_shapes import SessionState
from gaia.agents.email.bench.runner import (
    _is_triage_prompt,
    _normalize_agent_result,
    _sync_session_state_from_smart_result,
)


# ---------------------------------------------------------------------------
# 1. _normalize_agent_result empty string
# ---------------------------------------------------------------------------

class TestNormalizeAgentResultGaps:
    """_normalize_agent_result handles edge cases without crashing."""

    def test_empty_string_returns_empty_dict(self):
        """Empty string should return {}, not raise JSONDecodeError."""
        result = _normalize_agent_result("")
        assert result == {}

    def test_whitespace_only_returns_empty_dict(self):
        """Whitespace-only string should return {}."""
        result = _normalize_agent_result("   \n\t  ")
        assert result == {}

    def test_valid_dict_passes_through(self):
        """A dict input should be returned as-is."""
        data = {"key": "value"}
        assert _normalize_agent_result(data) is data

    def test_valid_json_string_unwraps_envelope(self):
        """JSON string with ok/data envelope should unwrap to inner data."""
        import json
        envelope = json.dumps({"ok": True, "data": {"results": []}})
        result = _normalize_agent_result(envelope)
        assert result == {"results": []}


# ---------------------------------------------------------------------------
# 2. _is_triage_prompt false positives
# ---------------------------------------------------------------------------

class TestIsTriagePromptNoFalsePositives:
    """_is_triage_prompt requires BOTH a triage verb AND a target keyword."""

    def test_show_me_my_inbox_is_false(self):
        """'show me my inbox' is a summary request, not triage."""
        assert _is_triage_prompt("show me my inbox") is False

    def test_whats_in_my_inbox_is_false(self):
        assert _is_triage_prompt("what's in my inbox") is False

    def test_count_emails_in_inbox_is_false(self):
        assert _is_triage_prompt("count emails in inbox") is False

    def test_clear_my_inbox_is_false(self):
        assert _is_triage_prompt("clear my inbox") is False

    def test_triage_my_inbox_is_true(self):
        assert _is_triage_prompt("triage my inbox") is True

    def test_categorize_these_emails_is_true(self):
        assert _is_triage_prompt("categorize these emails") is True

    def test_classify_my_inbox_is_true(self):
        assert _is_triage_prompt("classify my inbox") is True

    def test_triage_messages_is_true(self):
        assert _is_triage_prompt("triage my messages") is True

    def test_classify_documents_is_false(self):
        """Has 'classify' but no email target -- should be False."""
        assert _is_triage_prompt("classify these documents") is False


# ---------------------------------------------------------------------------
# 3. _sync_session_state malformed conversation shapes
# ---------------------------------------------------------------------------

class TestSyncSessionStateMalformedShapes:
    """_sync_session_state_from_smart_result handles bad shapes gracefully."""

    def test_missing_conversation_key(self):
        """Result with no conversation key should be a no-op."""
        state = SessionState()
        _sync_session_state_from_smart_result({"result": "done"}, state)
        assert len(state.heuristic_triaged) == 0
        assert len(state.llm_triaged) == 0

    def test_empty_conversation_list(self):
        state = SessionState()
        _sync_session_state_from_smart_result({"conversation": []}, state)
        assert len(state.heuristic_triaged) == 0

    def test_malformed_tool_content_not_json(self):
        """Tool content that is not valid JSON should be skipped."""
        state = SessionState()
        _sync_session_state_from_smart_result({
            "conversation": [{"role": "tool", "content": "not json"}],
        }, state)
        assert len(state.heuristic_triaged) == 0

    def test_tool_content_missing_ok_flag(self):
        """Tool content without ok=True should be skipped."""
        import json
        state = SessionState()
        _sync_session_state_from_smart_result({
            "conversation": [{
                "role": "tool",
                "content": json.dumps({"ok": False, "data": {"results": []}}),
            }],
        }, state)
        assert len(state.heuristic_triaged) == 0

    def test_tool_content_has_results(self):
        """Valid tool content with results should populate state."""
        import json
        state = SessionState()
        _sync_session_state_from_smart_result({
            "conversation": [{
                "role": "tool",
                "content": json.dumps({
                    "ok": True,
                    "data": {
                        "results": [
                            {"id": "m1", "category": "low priority", "confident": True},
                            {"id": "m2", "category": "urgent", "confident": False},
                        ]
                    },
                }),
            }],
        }, state)
        assert len(state.heuristic_triaged) == 1
        assert "m1" in state.heuristic_triaged
        assert len(state.llm_triaged) == 1
        assert "m2" in state.llm_triaged
