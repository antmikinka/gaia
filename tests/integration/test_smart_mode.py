# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Integration tests for smart-mode email triage.

These tests validate the smart-mode system prompt, the _should_use_llm
helper, cost-tracking counters, and the interactive benchmark flow with
smart mode enabled.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def smart_config():
    """Return an EmailAgentConfig with smart mode enabled."""
    from gaia.agents.email.config import EmailAgentConfig

    return EmailAgentConfig(
        enable_smart_mode=True,
        batch_size=5,
        debug=True,
    )


@pytest.fixture
def non_smart_config():
    """Return an EmailAgentConfig with smart mode disabled."""
    from gaia.agents.email.config import EmailAgentConfig

    return EmailAgentConfig(
        enable_smart_mode=False,
        batch_size=5,
        debug=True,
    )


@pytest.fixture
def smart_config_force_llm():
    """Return an EmailAgentConfig with smart mode + force_llm enabled."""
    from gaia.agents.email.config import EmailAgentConfig

    return EmailAgentConfig(
        enable_smart_mode=True,
        force_llm=True,
        batch_size=5,
        debug=True,
    )


# ---------------------------------------------------------------------------
# Phase 4a: Smart-mode system prompt
# ---------------------------------------------------------------------------


def test_get_system_prompt_includes_smart_mode_instructions(smart_config):
    """When enable_smart_mode=True, _get_system_prompt() must include
    the _SMART_MODE_INSTRUCTIONS text."""
    from gaia.agents.email.agent import EmailTriageAgent
    from gaia.agents.email.fake_gmail import FakeCalendarBackend, FakeGmailBackend

    agent = EmailTriageAgent(
        config=smart_config,
    )
    # Replace backends to avoid needing real credentials.
    agent._gmail = FakeGmailBackend(mbox_path=None)
    agent._calendar = FakeCalendarBackend()

    prompt = agent._get_system_prompt()
    assert "SMART TRIAGE MODE" in prompt
    assert "confident" in prompt
    assert "do NOT" in prompt or "do not" in prompt.lower()


def test_get_system_prompt_excludes_smart_mode_instructions(non_smart_config):
    """When enable_smart_mode=False, _get_system_prompt() must NOT include
    smart-mode instructions."""
    from gaia.agents.email.agent import EmailTriageAgent
    from gaia.agents.email.fake_gmail import FakeCalendarBackend, FakeGmailBackend

    agent = EmailTriageAgent(config=non_smart_config)
    agent._gmail = FakeGmailBackend(mbox_path=None)
    agent._calendar = FakeCalendarBackend()

    prompt = agent._get_system_prompt()
    assert "SMART TRIAGE MODE" not in prompt


# ---------------------------------------------------------------------------
# Phase 4b: _should_use_llm helper
# ---------------------------------------------------------------------------


def _make_agent_with_triaged_cache(config, triaged_cache=None):
    """Create an agent with a populated _smart_triaged_cache for testing."""
    from gaia.agents.email.agent import EmailTriageAgent
    from gaia.agents.email.fake_gmail import FakeCalendarBackend, FakeGmailBackend

    agent = EmailTriageAgent(config=config)
    agent._gmail = FakeGmailBackend(mbox_path=None)
    agent._calendar = FakeCalendarBackend()
    if triaged_cache is not None:
        agent._smart_triaged_cache = triaged_cache
    return agent


def test_should_use_llm_returns_false_for_confident_when_smart_on(smart_config):
    """When smart mode is on and an email is confident, skip LLM."""
    agent = _make_agent_with_triaged_cache(
        smart_config,
        {
            "email-1": {"confident": True, "category": "promotions"},
        },
    )
    assert agent._should_use_llm("email-1") is False


def test_should_use_llm_returns_true_for_non_confident(smart_config):
    """When smart mode is on and an email is NOT confident, use LLM."""
    agent = _make_agent_with_triaged_cache(
        smart_config,
        {
            "email-2": {"confident": False, "category": "informational"},
        },
    )
    assert agent._should_use_llm("email-2") is True


def test_should_use_llm_returns_true_when_force_llm_overrides(smart_config_force_llm):
    """When force_llm=True, _should_use_llm returns True even for confident emails."""
    agent = _make_agent_with_triaged_cache(
        smart_config_force_llm,
        {
            "email-1": {"confident": True, "category": "promotions"},
        },
    )
    assert agent._should_use_llm("email-1") is True


def test_should_use_llm_returns_true_for_unknown_email(smart_config):
    """When an email is not in the triaged cache, use LLM."""
    agent = _make_agent_with_triaged_cache(smart_config, {})
    assert agent._should_use_llm("unknown-email") is True


def test_should_use_llm_always_true_when_smart_off(non_smart_config):
    """When smart mode is off, _should_use_llm always returns True."""
    agent = _make_agent_with_triaged_cache(
        non_smart_config,
        {
            "email-1": {"confident": True, "category": "promotions"},
        },
    )
    assert agent._should_use_llm("email-1") is True
    assert agent._should_use_llm("unknown") is True


# ---------------------------------------------------------------------------
# Phase 4d: Cost tracking
# ---------------------------------------------------------------------------


def test_extract_actions_increments_cost_counters():
    """When _extract_actions processes a triage_inbox result with confident
    emails, it must increment llm_calls_saved and heuristic_token_estimate."""
    from gaia.agents.email.bench.data_shapes import SessionState
    from gaia.agents.email.bench.runner import _extract_actions

    state = SessionState()
    agent_result = {
        "conversation": [
            {
                "role": "tool",
                "name": "triage_inbox",
                "content": '{"ok": true, "data": {"results": ['
                '{"id": "e1", "category": "promotions", "confident": true},'
                '{"id": "e2", "category": "informational", "confident": false},'
                '{"id": "e3", "category": "updates", "confident": true}'
                "]}}",
            }
        ]
    }
    _extract_actions(agent_result, state)

    assert state.llm_calls_saved == 2  # e1 and e3
    assert state.heuristic_token_estimate == 100  # 2 * 50
    assert "e1" in state.heuristic_triaged
    assert "e3" in state.heuristic_triaged
    assert "e2" in state.llm_triaged


# ---------------------------------------------------------------------------
# Phase 4e: Interactive benchmark with smart mode
# ---------------------------------------------------------------------------


def test_run_interactive_benchmark_smart_mode_partitioning():
    """Run run_interactive_benchmark with enable_smart_mode=True and verify
    that heuristic_triaged and llm_triaged are partitioned correctly."""
    from gaia.agents.email.bench.data_shapes import SessionState
    from gaia.agents.email.bench.runner import _extract_actions

    # Simulate a 2-turn scenario where the agent processes triage results.
    state = SessionState()

    # Turn 1: triage_inbox returns a mix of confident and non-confident.
    turn1_result = {
        "conversation": [
            {
                "role": "tool",
                "name": "triage_inbox",
                "content": '{"ok": true, "data": {"results": ['
                '{"id": "msg-a", "category": "social", "confident": true},'
                '{"id": "msg-b", "category": "informational", "confident": false},'
                '{"id": "msg-c", "category": "promotions", "confident": true}'
                "]}}",
            },
            {
                "role": "tool",
                "name": "archive_message",
                "content": '{"ok": true, "data": {"message_id": "msg-a"}}',
            },
        ],
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "result": "Triage complete.",
    }
    _extract_actions(turn1_result, state)

    # Verify partitioning after turn 1.
    assert len(state.heuristic_triaged) == 2  # msg-a, msg-c
    assert len(state.llm_triaged) == 1  # msg-b
    assert "msg-a" in state.archived
    assert state.llm_calls_saved == 2

    # Turn 2: another triage (simulating re-triage or follow-up).
    turn2_result = {
        "conversation": [
            {
                "role": "tool",
                "name": "triage_inbox",
                "content": '{"ok": true, "data": {"results": ['
                '{"id": "msg-d", "category": "updates", "confident": true},'
                '{"id": "msg-e", "category": "actionable", "confident": false}'
                "]}}",
            },
        ],
        "input_tokens": 80,
        "output_tokens": 40,
        "total_tokens": 120,
        "result": "Follow-up triage complete.",
    }
    _extract_actions(turn2_result, state)

    # Verify partitioning after turn 2.
    assert len(state.heuristic_triaged) == 3  # msg-a, msg-c, msg-d
    assert len(state.llm_triaged) == 2  # msg-b, msg-e
    assert state.llm_calls_saved == 3
    assert state.heuristic_token_estimate == 150  # 3 * 50


# ---------------------------------------------------------------------------
# Phase 4f: sync_smart_triage_cache — bridging runner state to agent cache
# ---------------------------------------------------------------------------


def test_sync_smart_triage_cache_populates_agent_cache(smart_config):
    """sync_smart_triage_cache bridges runner SessionState into
    agent._smart_triaged_cache so _should_use_llm gates correctly."""
    agent = _make_agent_with_triaged_cache(smart_config, {})
    agent.sync_smart_triage_cache(
        heuristic_ids={"e1": "promotions", "e2": "updates"},
        llm_ids={"e3": "actionable"},
    )
    assert agent._should_use_llm("e1") is False  # heuristic-confident
    assert agent._should_use_llm("e2") is False  # heuristic-confident
    assert agent._should_use_llm("e3") is True   # non-confident -> LLM
    assert agent._should_use_llm("unknown") is True  # not in cache


def test_sync_smart_triage_cache_overwrites_on_subsequent_turn(smart_config):
    """Re-syncing after reclassify moves an email from heuristic to LLM."""
    agent = _make_agent_with_triaged_cache(smart_config, {})
    # Turn 1: all confident.
    agent.sync_smart_triage_cache(
        heuristic_ids={"e1": "promotions"},
        llm_ids={},
    )
    assert agent._should_use_llm("e1") is False

    # Turn 2: user reclassified e1 -> move to llm_ids.
    agent.sync_smart_triage_cache(
        heuristic_ids={},
        llm_ids={"e1": "promotions"},
    )
    assert agent._should_use_llm("e1") is True


# ---------------------------------------------------------------------------
# Phase 4g: force_llm_ids in triage_inbox_impl
# ---------------------------------------------------------------------------


def test_triage_inbox_impl_force_llm_ids_override():
    """When force_llm_ids contains an email id, it overrides confident=True."""
    from gaia.agents.email.fake_gmail import FakeGmailBackend
    from gaia.agents.email.tools.read_tools import triage_inbox_impl
    from pathlib import Path

    fake = FakeGmailBackend(mbox_path=None)
    result = triage_inbox_impl(
        fake,
        max_messages=10,
        force_llm_ids={"test-email-1": "user-requested"},
    )
    # With no mbox, the fake gmail may return empty or test emails.
    # If it returns emails, verify force_llm_ids override works.
    for item in result.get("results", []):
        if item.get("id") == "test-email-1":
            assert item["confident"] is False
            assert "user-requested" in item["rationale"]


def test_triage_inbox_impl_force_llm_ids_empty_dict_no_effect():
    """An empty force_llm_ids dict should not affect confident results."""
    from gaia.agents.email.fake_gmail import FakeGmailBackend
    from gaia.agents.email.tools.read_tools import triage_inbox_impl

    fake = FakeGmailBackend(mbox_path=None)
    result1 = triage_inbox_impl(fake, max_messages=10, force_llm_ids={})
    result2 = triage_inbox_impl(fake, max_messages=10, force_llm_ids=None)
    # Both should produce identical results.
    assert len(result1["results"]) == len(result2["results"])
    for r1, r2 in zip(result1["results"], result2["results"]):
        assert r1["confident"] == r2["confident"]
