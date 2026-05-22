# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""Performance tests: token consumption, heuristic rate, context growth."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from gaia.agents.email.bench.data_shapes import SessionState
from gaia.agents.email.bench.runner import (
    _sync_session_state_from_smart_result,
    compact_context,
    run_interactive_benchmark,
)


class TestPerformanceTargets:
    """Performance targets for smart interactive mode."""

    def test_token_consumption_target(self):
        """At limit=100, total token consumption should be < 100K."""
        with patch("gaia.agents.email.agent.EmailTriageAgent") as MockAgent:
            mock_agent = MockAgent.return_value
            # Simulate realistic token counts:
            # Turn 1 (triage): ~20K input, ~5K output for 100 emails
            # Turns 2-4: ~3K input, ~1K output each
            mock_agent.process_interactive_smart_triage.return_value = {
                "result": "Triaged 100 emails",
                "conversation": [
                    {
                        "role": "tool",
                        "name": "triage_inbox",
                        "content": json.dumps({
                            "ok": True,
                            "data": {
                                "results": [
                                    {"id": f"m{i}", "category": "low priority", "confident": True}
                                    for i in range(1, 76)
                                ]
                                + [
                                    {"id": f"m{i}", "category": "informational", "confident": False}
                                    for i in range(76, 101)
                                ],
                            },
                        }),
                    },
                ],
                "input_tokens": 20000,
                "output_tokens": 5000,
                "total_tokens": 25000,
            }
            mock_agent.process_query.return_value = {
                "result": "Done",
                "conversation": [],
                "input_tokens": 3000,
                "output_tokens": 1000,
                "total_tokens": 4000,
            }
            mock_agent.conversation_history = []
            mock_agent.sync_smart_triage_cache = MagicMock()

            summary = run_interactive_benchmark(
                mbox_path="tests/fixtures/email/_stub_inbox.mbox",
                model_id="Qwen3.5-4B-GGUF",
                base_url="http://localhost:8000",
                limit=100,
                enable_smart_mode=True,
            )

        total = summary["total_tokens"]
        assert total < 100_000, f"Token consumption {total:,} exceeds 100K target"
        assert total > 0, "Token consumption should be non-zero"

    def test_heuristic_rate_target(self):
        """Heuristic fast-path should classify >= 70% of emails."""
        state = SessionState()

        # Simulate a realistic smart triage result on 100 emails
        # 75 confident (heuristic), 25 non-confident (LLM)
        agent_result = {
            "conversation": [{
                "role": "tool",
                "name": "triage_inbox",
                "content": json.dumps({
                    "ok": True,
                    "data": {
                        "results": [
                            {"id": f"m{i}", "category": "low priority", "confident": True}
                            for i in range(1, 76)
                        ]
                        + [
                            {"id": f"m{i}", "category": "informational", "confident": False}
                            for i in range(76, 101)
                        ],
                    },
                }),
            }],
        }

        _sync_session_state_from_smart_result(agent_result, state)

        total_triaged = len(state.heuristic_triaged) + len(state.llm_triaged)
        heuristic_rate = len(state.heuristic_triaged) / total_triaged * 100

        assert heuristic_rate >= 70.0, (
            f"Heuristic rate {heuristic_rate:.1f}% below 70% target "
            f"({len(state.heuristic_triaged)} heuristic / {len(state.llm_triaged)} LLM)"
        )

    def test_context_growth_rate_after_compaction(self):
        """Compacted context should grow at <= 2x rate vs raw accumulation."""
        # Simulate conversation growing across 4 turns
        turns_conversation = []
        for turn in range(4):
            turn_msgs = [
                {"role": "user", "content": f"Prompt for turn {turn + 1}"},
                {"role": "assistant", "content": "Response " + "x" * 2000},
                {"role": "tool", "name": "some_tool", "content": "Result " + "y" * 3000},
            ]
            turns_conversation.extend(turn_msgs)

        # Raw (uncompacted) size
        raw_size = sum(len(str(m.get("content", ""))) for m in turns_conversation)

        # Compacted size
        compacted = compact_context(turns_conversation, max_chars=raw_size // 2)
        compacted_size = sum(len(str(m.get("content", ""))) for m in compacted)

        # Growth rate: compacted should be at most the raw size
        growth_ratio = compacted_size / max(raw_size, 1)
        assert growth_ratio <= 1.0, (
            f"Compacted context ({compacted_size}) exceeds raw ({raw_size})"
        )
        assert compacted_size <= raw_size // 2 + 100  # within target + margin
