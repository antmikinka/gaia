# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Tests for ``EmailTriageAgent.process_interactive_smart_triage``.

Validates the new interactive smart triage entry point:

1. Mix of confident and non-confident emails — confident cached without
   LLM, non-confident sent to ``_process_single_batch``.
2. All confident emails — ``_process_single_batch`` MUST NOT be called.
3. No confident emails — behaves like batched triage (all go to LLM).
4. Empty inbox — returns zero counts, no LLM call.
5. Non-confident emails previously cached (from prior turns) are skipped
   per ``_should_use_llm()``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Make tests.fixtures.email importable.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gaia.agents.email.agent import EmailTriageAgent  # noqa: E402
from gaia.agents.email.config import EmailAgentConfig  # noqa: E402
from tests.fixtures.email.fake_gmail import (  # noqa: E402
    FakeCalendarBackend,
    FakeGmailBackend,
)


def _make_triaged_email(
    email_id: str,
    *,
    confident: bool,
    category: str = "informational",
    rationale: str = "",
):
    """Build a single result entry matching triage_inbox_impl's output shape."""
    return {
        "id": email_id,
        "thread_id": f"thread-{email_id}",
        "subject": f"Test email {email_id}",
        "from": f"sender-{email_id}@example.com",
        "category": category,
        "is_spam": False,
        "is_phishing": False,
        "confident": confident,
        "rationale": rationale
        or ("heuristic label match" if confident else "no heuristic match"),
    }


@pytest.fixture
def fake_gmail():
    fixture_path = _REPO_ROOT / "tests" / "fixtures" / "email" / "_stub_inbox.mbox"
    return FakeGmailBackend(fixture_path)


@pytest.fixture
def fake_calendar():
    return FakeCalendarBackend()


@pytest.fixture
def agent(fake_gmail, fake_calendar, tmp_path):
    """Construct an ``EmailTriageAgent`` against fake backends with smart mode on."""
    cfg = EmailAgentConfig(
        gmail_backend=fake_gmail,
        calendar_backend=fake_calendar,
        db_path=str(tmp_path / "state.db"),
        silent_mode=True,
        debug=False,
        enable_smart_mode=True,
        batch_size=5,
    )
    with patch("gaia.agents.base.agent.AgentSDK") as mock_sdk:
        mock_sdk.return_value = MagicMock()
        a = EmailTriageAgent(config=cfg)
        a._mock_chat = mock_sdk.return_value
    yield a
    a.close_db()


class TestProcessInteractiveSmartTriage:
    """Validate ``process_interactive_smart_triage`` across email distributions."""

    # --- Test 1: Mix of confident and non-confident emails ---

    def test_mixed_emails_confident_cached_llm_batched(self, agent, tmp_path):
        """Confident emails are cached without LLM; non-confident go to batch."""
        confident = [_make_triaged_email("m1", confident=True, category="low priority")]
        needs_llm = [
            _make_triaged_email("m2", confident=False),
            _make_triaged_email("m3", confident=False),
        ]
        triage_data = {"results": confident + needs_llm, "grouped": {"total": 3}}

        with patch(
            "gaia.agents.email.tools.read_tools.triage_inbox_impl",
            return_value=triage_data,
        ) as mock_triage:
            with patch.object(agent, "_process_single_batch") as mock_batch:
                result = agent.process_interactive_smart_triage(
                    user_prompt="Triage my inbox", max_messages=25
                )

        mock_triage.assert_called_once()
        assert mock_batch.call_count == 1

        # One batch containing both non-confident emails.
        batched_emails = mock_batch.call_args.kwargs["batch"]
        assert len(batched_emails) == 2
        assert {e["id"] for e in batched_emails} == {"m2", "m3"}

        # Confident emails cached.
        assert "m1" in agent._smart_triaged_cache
        assert agent._smart_triaged_cache["m1"]["confident"] is True
        assert agent._smart_triaged_cache["m1"]["source"] == "heuristic"

        # Result dict shape.
        assert result["total_emails"] == 3
        assert result["confident_count"] == 1
        assert result["needs_llm_count"] == 2
        assert result["run_id"] is not None
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert result["total_tokens"] == 0
        assert result["triage_summary"] == {"total": 3}

        # Conversation contains triage_inbox tool call result.
        assert len(result["conversation"]) == 1
        tool_msg = result["conversation"][0]
        assert tool_msg["role"] == "tool"
        assert tool_msg["name"] == "triage_inbox"

    # --- Test 2: All confident emails (LLM must NOT be called) ---

    def test_all_confident_no_llm(self, agent):
        """When every email is confident, _process_single_batch is never called."""
        emails = [
            _make_triaged_email(f"m{i}", confident=True, category="low priority")
            for i in range(1, 6)
        ]
        triage_data = {"results": emails, "grouped": {"total": 5}}

        with patch(
            "gaia.agents.email.tools.read_tools.triage_inbox_impl",
            return_value=triage_data,
        ):
            with patch.object(agent, "_process_single_batch") as mock_batch:
                result = agent.process_interactive_smart_triage(
                    user_prompt="Triage my inbox", max_messages=25
                )

        mock_batch.assert_not_called()

        assert result["total_emails"] == 5
        assert result["confident_count"] == 5
        assert result["needs_llm_count"] == 0

        # All 5 emails cached as heuristic.
        for i in range(1, 6):
            eid = f"m{i}"
            assert agent._smart_triaged_cache[eid]["confident"] is True
            assert agent._smart_triaged_cache[eid]["source"] == "heuristic"

    # --- Test 3: No confident emails (all go to LLM batches) ---

    def test_no_confident_all_llm(self, agent):
        """When no email is confident, all are batched for LLM processing."""
        emails = [_make_triaged_email(f"m{i}", confident=False) for i in range(1, 8)]
        triage_data = {"results": emails, "grouped": {"total": 7}}

        with patch(
            "gaia.agents.email.tools.read_tools.triage_inbox_impl",
            return_value=triage_data,
        ):
            with patch.object(agent, "_process_single_batch") as mock_batch:
                result = agent.process_interactive_smart_triage(
                    user_prompt="Triage my inbox", max_messages=25
                )

        assert result["total_emails"] == 7
        assert result["confident_count"] == 0
        assert result["needs_llm_count"] == 7

        # batch_size=5 => 2 batches: [m1..m5], [m6, m7]
        assert mock_batch.call_count == 2
        first_batch = mock_batch.call_args_list[0].kwargs["batch"]
        second_batch = mock_batch.call_args_list[1].kwargs["batch"]
        assert len(first_batch) == 5
        assert len(second_batch) == 2

    # --- Test 4: Empty inbox ---

    def test_empty_inbox(self, agent):
        """Empty inbox returns zero counts, no LLM call."""
        triage_data = {"results": [], "grouped": {"total": 0}}

        with patch(
            "gaia.agents.email.tools.read_tools.triage_inbox_impl",
            return_value=triage_data,
        ):
            with patch.object(agent, "_process_single_batch") as mock_batch:
                result = agent.process_interactive_smart_triage(
                    user_prompt="Triage my inbox", max_messages=25
                )

        mock_batch.assert_not_called()

        assert result["total_emails"] == 0
        assert result["confident_count"] == 0
        assert result["needs_llm_count"] == 0
        assert result["conversation"] == []
        assert result["result"] == "No emails found."

    # --- Test 5: Previously cached non-confident emails skipped ---

    def test_prior_turn_cached_emails_skipped(self, agent):
        """Non-confident emails already in _smart_triaged_cache from a
        prior turn (with confident=True) are NOT re-sent to LLM."""
        # Simulate prior turn: m2 was LLM-classified and cached as confident.
        agent._smart_triaged_cache["m2"] = {
            "category": "actionable",
            "confident": True,
            "source": "llm",
        }

        # Current triage: m2 appears non-confident (heuristic changed its mind),
        # but _should_use_llm() will return False because it's cached as confident.
        emails = [
            _make_triaged_email("m1", confident=False),
            _make_triaged_email("m2", confident=False),
            _make_triaged_email("m3", confident=False),
        ]
        triage_data = {"results": emails, "grouped": {"total": 3}}

        with patch(
            "gaia.agents.email.tools.read_tools.triage_inbox_impl",
            return_value=triage_data,
        ):
            with patch.object(agent, "_process_single_batch") as mock_batch:
                result = agent.process_interactive_smart_triage(
                    user_prompt="Triage my inbox", max_messages=25
                )

        # Only m1 and m3 should go to LLM (m2 is cached as confident).
        assert result["needs_llm_count"] == 2
        batched = mock_batch.call_args.kwargs["batch"]
        assert {e["id"] for e in batched} == {"m1", "m3"}

        # m2 was re-cached as heuristic (since _should_use_llm returned False).
        assert agent._smart_triaged_cache["m2"]["source"] == "heuristic"


class TestProcessInteractiveSmartTriageRespectsShouldUseLlm:
    """Ensure _should_use_llm() gating is respected per-email."""

    def test_force_llm_bypasses_cache(self, fake_gmail, fake_calendar, tmp_path):
        """When force_llm=True, all emails go to LLM regardless of cache."""
        cfg = EmailAgentConfig(
            gmail_backend=fake_gmail,
            calendar_backend=fake_calendar,
            db_path=str(tmp_path / "state.db"),
            silent_mode=True,
            enable_smart_mode=True,
            force_llm=True,
            batch_size=5,
        )
        with patch("gaia.agents.base.agent.AgentSDK") as mock_sdk:
            mock_sdk.return_value = MagicMock()
            agent = EmailTriageAgent(config=cfg)

        # Even if cache says confident, force_llm overrides.
        agent._smart_triaged_cache["m1"] = {
            "category": "low priority",
            "confident": True,
            "source": "heuristic",
        }

        # force_llm=True in config means triage_inbox_impl marks all as non-confident.
        emails = [_make_triaged_email("m1", confident=False)]
        triage_data = {"results": emails, "grouped": {"total": 1}}

        with patch(
            "gaia.agents.email.tools.read_tools.triage_inbox_impl",
            return_value=triage_data,
        ):
            with patch.object(agent, "_process_single_batch") as mock_batch:
                result = agent.process_interactive_smart_triage(
                    user_prompt="Triage my inbox", max_messages=25
                )

        # force_llm should cause _should_use_llm to return True.
        assert agent._should_use_llm("m1") is True
        assert result["needs_llm_count"] == 1
        mock_batch.assert_called_once()

        agent.close_db()


class TestProcessInteractiveSmartTriageNoRegression:
    """Ensure existing process_smart_triage / process_query paths are unchanged."""

    def test_process_smart_triage_still_returns_json_string(self, agent):
        """process_smart_triage() must still return a JSON string, not a dict."""
        import json as _json

        # Patch triage_inbox_impl at the import location inside process_smart_triage.
        triage_data = {
            "results": [_make_triaged_email("m1", confident=True)],
            "grouped": {"total": 1},
        }
        with patch(
            "gaia.agents.email.tools.read_tools.triage_inbox_impl",
            return_value=triage_data,
        ):
            result = agent.process_smart_triage(max_messages=25)

        # Must be a JSON string parseable as {"ok": true, "data": ...}.
        assert isinstance(result, str)
        parsed = _json.loads(result)
        assert parsed["ok"] is True
        assert "data" in parsed

    def test_smart_triaged_cache_shared_between_methods(self, agent):
        """process_interactive_smart_triage and process_smart_triage share
        the same _smart_triaged_cache — results from one affect the other."""
        # Run interactive first.
        triage_data_1 = {
            "results": [_make_triaged_email("m1", confident=True)],
            "grouped": {"total": 1},
        }
        with patch(
            "gaia.agents.email.tools.read_tools.triage_inbox_impl",
            return_value=triage_data_1,
        ):
            with patch.object(agent, "_process_single_batch"):
                agent.process_interactive_smart_triage(
                    user_prompt="Triage", max_messages=25
                )

        assert "m1" in agent._smart_triaged_cache
        assert agent._should_use_llm("m1") is False

        # Now run process_smart_triage — m1 should be skipped.
        triage_data_2 = {
            "results": [_make_triaged_email("m1", confident=True)],
            "grouped": {"total": 1},
        }
        with patch(
            "gaia.agents.email.tools.read_tools.triage_inbox_impl",
            return_value=triage_data_2,
        ):
            with patch.object(agent, "_process_single_batch") as mock_batch:
                agent.process_smart_triage(max_messages=25)

        # m1 is confident -> no LLM batch needed.
        mock_batch.assert_not_called()


class TestSmartModeRunnerHelpers:
    """Validate the new runner.py helper functions for smart-mode dispatch."""

    def test_is_triage_prompt_matches_keywords(self):
        """_is_triage_prompt returns True for triage-related keywords."""
        from gaia.agents.email.bench.runner import _is_triage_prompt

        assert _is_triage_prompt("Triage my inbox") is True
        assert _is_triage_prompt("TRIAGE MY INBOX") is True
        assert _is_triage_prompt("Categorize these emails") is True
        assert _is_triage_prompt("classify my inbox") is True
        assert _is_triage_prompt("archive the low priority emails") is False
        assert _is_triage_prompt("show me a summary") is False
        assert _is_triage_prompt("star urgent messages") is False

    def test_split_by_confidence_partitions_results(self):
        """split_by_confidence separates confident from needs-LLM emails."""
        from gaia.agents.email.bench.runner import split_by_confidence

        results = [
            {"id": "m1", "confident": True, "category": "low priority"},
            {"id": "m2", "confident": False, "category": "informational"},
            {"id": "m3", "confident": True, "category": "promotions"},
            {"id": "m4", "confident": False, "category": "actionable"},
        ]
        confident, needs_llm = split_by_confidence(results)

        assert len(confident) == 2
        assert {e["id"] for e in confident} == {"m1", "m3"}
        assert len(needs_llm) == 2
        assert {e["id"] for e in needs_llm} == {"m2", "m4"}

    def test_mark_for_escalation_moves_from_heuristic_to_llm(self, agent):
        """mark_for_escalation moves an email from heuristic_triaged to
        llm_triaged and wires force_llm_ids into agent config."""
        from gaia.agents.email.bench.data_shapes import SessionState
        from gaia.agents.email.bench.runner import mark_for_escalation

        state = SessionState()
        state.heuristic_triaged["m1"] = "low priority"
        state.triaged_emails["m1"] = "low priority"

        msg = mark_for_escalation("m1", state, agent)

        assert "m1" not in state.heuristic_triaged
        assert state.llm_triaged["m1"] == "low priority"
        assert state.force_llm_ids["m1"] == "user-requested"
        assert agent.config.force_llm_ids["m1"] == "user-requested"
        assert "LLM reclassification" in msg

        # Test not-found case.
        msg2 = mark_for_escalation("nonexistent", state, agent)
        assert "not found" in msg2

    def test_normalize_agent_result_handles_json_string_and_dict(self):
        """_normalize_agent_result unwraps JSON strings from process_smart_triage
        and passes through dicts from process_query/process_interactive_smart_triage."""
        import json
        from gaia.agents.email.bench.runner import _normalize_agent_result

        # JSON string with outer envelope (process_smart_triage format).
        json_str = json.dumps({
            "ok": True,
            "data": {"run_id": "test-123", "total_emails": 5},
        })
        result = _normalize_agent_result(json_str)
        assert result["run_id"] == "test-123"
        assert result["total_emails"] == 5

        # Direct dict (process_query format).
        dict_result = {"result": "done", "conversation": [], "total_tokens": 42}
        result2 = _normalize_agent_result(dict_result)
        assert result2["total_tokens"] == 42
        assert result2["result"] == "done"

        # Invalid type should raise.
        with pytest.raises(TypeError, match="Expected dict or JSON string"):
            _normalize_agent_result(123)
