# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""Integration tests: full smart benchmark path + dual-path summary."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gaia.agents.email.bench.data_shapes import SessionState, TurnResult
from gaia.agents.email.bench.runner import (
    generate_interactive_smart_summary,
    run_interactive_benchmark,
    _sync_session_state_from_smart_result,
)


# ---------------------------------------------------------------------------
# 1. Full Smart Benchmark Path
# ---------------------------------------------------------------------------

class TestSmartBenchmarkPath:
    """Exercises run_interactive_benchmark end-to-end with smart mode."""

    def test_run_interactive_benchmark_smart_path_dispatch(self):
        """Smart dispatch on turn 1, fallback to process_query on turns 2-4."""
        with patch("gaia.agents.email.agent.EmailTriageAgent") as MockAgent:
            mock_agent = MockAgent.return_value
            mock_agent.conversation_history = []

            # Turn 1: smart dispatch
            mock_agent.process_interactive_smart_triage.return_value = {
                "result": "Triaged 10 emails",
                "conversation": [
                    {
                        "role": "tool",
                        "name": "triage_inbox",
                        "content": json.dumps({
                            "ok": True,
                            "data": {
                                "results": [
                                    {"id": f"m{i}", "category": "low priority", "confident": True}
                                    for i in range(1, 5)
                                ]
                                + [
                                    {"id": f"m{i}", "category": "informational", "confident": False}
                                    for i in range(5, 11)
                                ],
                            },
                        }),
                    },
                ],
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            }
            mock_agent.process_query.return_value = {
                "result": "Done",
                "conversation": [],
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
            }
            mock_agent.sync_smart_triage_cache = MagicMock()

            summary = run_interactive_benchmark(
                mbox_path="tests/fixtures/email/_stub_inbox.mbox",
                model_id="Qwen3.5-4B-GGUF",
                base_url="http://localhost:8000",
                scenario=[
                    "Triage my inbox (10 emails)",
                    "Archive the low priority emails",
                    "Star any urgent messages",
                    "Show me a summary",
                ],
                limit=10,
                enable_smart_mode=True,
            )

        # Turn 1 triggered smart dispatch
        assert mock_agent.process_interactive_smart_triage.call_count == 1
        # Turns 2-4 fell through to process_query
        assert mock_agent.process_query.call_count == 3

        # Smart-mode keys present
        assert len(summary["heuristic_triaged"]) == 4
        assert len(summary["llm_triaged"]) == 6
        assert summary["heuristic_only_count"] == 4
        assert summary["llm_escalated_count"] == 6

        # All base keys present
        base_keys = {
            "run_id", "timestamp", "model", "mbox_path", "jsonl_path",
            "data_source", "turns", "total_turns", "total_emails_affected",
            "total_tools_used", "tools_used", "total_duration_ms",
            "total_input_tokens", "total_output_tokens",
            "total_reasoning_tokens", "total_tokens", "avg_tokens_per_turn",
            "avg_duration_per_turn_ms", "avg_time_to_first_token_ms",
            "avg_tokens_per_second",
        }
        for key in base_keys:
            assert key in summary, f"Missing base key: {key}"

        # Smart-mode keys present
        smart_keys = {
            "heuristic_triaged", "llm_triaged", "heuristic_only_count",
            "llm_escalated_count", "heuristic_savings",
        }
        for key in smart_keys:
            assert key in summary, f"Missing smart key: {key}"

        # heuristic_savings has all sub-keys
        savings = summary["heuristic_savings"]
        assert "llm_calls_saved" in savings
        assert "estimated_tokens_saved" in savings
        assert "estimated_output_tokens_avoided" in savings
        assert "saved_percentage" in savings

    def test_no_double_counting_between_sync_and_extract(self):
        """_sync + _extract must not double-count emails."""
        state = SessionState()

        # Simulate turn 1 sync
        agent_result = {
            "conversation": [{
                "role": "tool",
                "name": "triage_inbox",
                "content": json.dumps({
                    "ok": True,
                    "data": {
                        "results": [
                            {"id": f"m{i}", "category": "low priority", "confident": True}
                            for i in range(1, 5)
                        ]
                        + [
                            {"id": f"m{i}", "category": "informational", "confident": False}
                            for i in range(5, 11)
                        ],
                    },
                }),
            }],
        }
        _sync_session_state_from_smart_result(agent_result, state)

        # Simulate turn 2+ extract (same data again)
        from gaia.agents.email.bench.runner import _extract_actions
        _extract_actions(agent_result, state)

        # No double counting
        total_smart = len(state.heuristic_triaged) + len(state.llm_triaged)
        assert total_smart == len(state.triaged_emails), (
            f"Double counting: heuristic({len(state.heuristic_triaged)}) "
            f"+ llm({len(state.llm_triaged)}) != triaged({len(state.triaged_emails)})"
        )

    def test_non_triage_first_turn_falls_through(self):
        """First prompt without triage keywords uses process_query even in smart mode."""
        with patch("gaia.agents.email.agent.EmailTriageAgent") as MockAgent:
            mock_agent = MockAgent.return_value
            mock_agent.conversation_history = []
            mock_agent.process_query.return_value = {
                "result": "Done",
                "conversation": [],
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
            }
            mock_agent.sync_smart_triage_cache = MagicMock()

            summary = run_interactive_benchmark(
                mbox_path="tests/fixtures/email/_stub_inbox.mbox",
                model_id="Qwen3.5-4B-GGUF",
                base_url="http://localhost:8000",
                scenario=["Show me a summary of my emails"],
                limit=5,
                enable_smart_mode=True,
            )

        # Smart dispatch was NOT called
        assert mock_agent.process_interactive_smart_triage.call_count == 0
        # process_query was used
        assert mock_agent.process_query.call_count >= 1


# ---------------------------------------------------------------------------
# 2. Dual-Path Summary + Visualization
# ---------------------------------------------------------------------------

class TestDualPathSummary:
    """generate_interactive_smart_summary output must be serializable."""

    def test_smart_summary_serializable(self):
        """The augmented summary must round-trip through json.dump."""
        base_summary = {
            "run_id": "test-123",
            "timestamp": "2026-05-21T00:00:00",
            "model": "Qwen3.5-4B-GGUF",
            "mbox_path": "/path/to/test.mbox",
            "turns": [
                TurnResult(
                    turn_number=1,
                    prompt="Triage my inbox",
                    heuristic_email_count=5,
                    llm_email_count=3,
                ),
                TurnResult(turn_number=2, prompt="Archive low priority"),
            ],
            "total_turns": 2,
            "total_emails_affected": 8,
            "total_tools_used": 2,
            "tools_used": ["triage_inbox", "archive_message"],
            "total_duration_ms": 5000,
            "total_input_tokens": 12000,
            "total_output_tokens": 3000,
            "total_reasoning_tokens": 500,
            "total_tokens": 15000,
            "avg_tokens_per_turn": 7500.0,
            "avg_duration_per_turn_ms": 2500.0,
            "avg_time_to_first_token_ms": 150.0,
            "avg_tokens_per_second": 25.0,
        }

        state = SessionState()
        state.heuristic_triaged = {f"m{i}": "low priority" for i in range(1, 6)}
        state.llm_triaged = {f"m{i}": "informational" for i in range(6, 9)}
        state.llm_calls_saved = 5
        state.heuristic_token_estimate = 250

        result = generate_interactive_smart_summary(base_summary, state, 15000)

        # Must be json-serializable (no sets, no custom objects)
        serialized = json.dumps(result, default=str)
        parsed = json.loads(serialized)

        # All smart keys present after round-trip
        assert parsed["heuristic_triaged"] == state.heuristic_triaged
        assert parsed["llm_triaged"] == state.llm_triaged
        assert parsed["heuristic_savings"]["llm_calls_saved"] == 5
        assert parsed["heuristic_savings"]["saved_percentage"] >= 0

    def test_smart_summary_contains_all_base_keys(self):
        """Smart summary adds keys but does not remove base keys."""
        base_summary = {
            "run_id": "test", "timestamp": "now", "model": "X",
            "mbox_path": "", "turns": [], "total_turns": 0,
            "total_emails_affected": 0, "total_tools_used": 0,
            "tools_used": [], "total_duration_ms": 0,
            "total_input_tokens": 0, "total_output_tokens": 0,
            "total_reasoning_tokens": 0, "total_tokens": 0,
            "avg_tokens_per_turn": 0, "avg_duration_per_turn_ms": 0,
            "avg_time_to_first_token_ms": 0, "avg_tokens_per_second": 0,
        }
        state = SessionState()
        result = generate_interactive_smart_summary(base_summary, state, 0)

        # Base keys preserved
        for key in base_summary:
            assert key in result, f"Base key lost: {key}"

        # Smart keys added
        assert "heuristic_triaged" in result
        assert "llm_triaged" in result
        assert "heuristic_savings" in result
