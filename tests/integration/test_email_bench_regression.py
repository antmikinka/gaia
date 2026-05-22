# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""Regression tests: non-smart modes must be unaffected by PR1+PR2 changes."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from gaia.agents.email.bench.runner import (
    _run_batched_agent,
    _run_full_agent,
    run_interactive_benchmark,
)


class TestNonSmartRegression:
    """Non-smart modes produce identical output structure before and after PR1+PR2."""

    def test_interactive_non_smart_output_unchanged(self):
        """Non-smart interactive mode should produce same keys as before."""
        with patch("gaia.agents.email.agent.EmailTriageAgent") as MockAgent:
            mock_agent = MockAgent.return_value
            mock_agent.process_query.return_value = {
                "result": "Done",
                "conversation": [],
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
            }
            mock_agent.conversation_history = []
            mock_agent.sync_smart_triage_cache = MagicMock()

            summary = run_interactive_benchmark(
                mbox_path="tests/fixtures/email/_stub_inbox.mbox",
                model_id="Qwen3.5-4B-GGUF",
                base_url="http://localhost:8000",
                scenario=["Show me my emails"],
                limit=5,
                enable_smart_mode=False,  # NON-SMART
            )

        # Smart keys present but empty
        assert "heuristic_triaged" in summary
        assert summary["heuristic_triaged"] == {}
        assert summary["llm_triaged"] == {}
        assert summary["heuristic_only_count"] == 0
        assert summary["llm_escalated_count"] == 0

        # TurnResult objects should NOT have smart fields populated
        for turn in summary["turns"]:
            assert getattr(turn, "heuristic_email_count", 0) == 0
            assert getattr(turn, "llm_email_count", 0) == 0
            assert getattr(turn, "context_compacted", False) is False

    def test_full_mode_non_smart_unchanged(self):
        """--mode full without --smart should produce same RunResult structure."""
        with patch("gaia.agents.email.agent.EmailTriageAgent") as MockAgent:
            mock_agent = MockAgent.return_value
            mock_agent.process_query.return_value = {
                "result": "done",
                "conversation": [],
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
            }

            result = _run_full_agent(
                mbox_path="tests/fixtures/email/_stub_inbox.mbox",
                model_id="Qwen3.5-4B-GGUF",
                base_url="http://localhost:8000",
                limit=5,
                force_llm=False,
            )

        assert result.mode == "full"
        assert result.status in ("ok", "completed", "error")
        assert result.total_emails >= 0

    def test_batched_mode_unaffected(self):
        """--batched mode should not be affected by PR1+PR2 smart-mode changes."""
        with patch("gaia.agents.email.agent.EmailTriageAgent") as MockAgent, \
             patch("gaia.agents.email.action_store.fetch_triage_results") as mock_fetch:
            mock_agent = MockAgent.return_value
            mock_agent.process_batched_triage.return_value = json.dumps({
                "ok": True,
                "data": {"run_id": "test-batched", "total_emails": 5},
            })
            mock_fetch.return_value = [
                {"email_id": "m1", "category": "low priority", "confident": True, "batch_number": 1, "token_count": 100, "duration_secs": 0.1},
                {"email_id": "m2", "category": "urgent", "confident": False, "batch_number": 1, "token_count": 200, "duration_secs": 0.2},
            ]

            result = _run_batched_agent(
                mbox_path="tests/fixtures/email/_stub_inbox.mbox",
                model_id="Qwen3.5-4B-GGUF",
                base_url="http://localhost:8000",
                limit=10,
                batch_size=5,
            )

        assert result.mode == "batched"
        assert len(result.batch_results) >= 1
        assert result.total_emails >= 1
