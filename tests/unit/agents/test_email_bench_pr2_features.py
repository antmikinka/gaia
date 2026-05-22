# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""PR2 unit tests: context compaction, gate logging, TurnResult fields."""

from __future__ import annotations

import json
import logging

import pytest

from gaia.agents.email.bench.data_shapes import TurnResult
from gaia.agents.email.bench.runner import compact_context


# ---------------------------------------------------------------------------
# Context Compaction Tests
# ---------------------------------------------------------------------------

class TestContextCompaction:
    """Context compaction preserves structure while reducing token footprint."""

    def test_empty_conversation_returns_empty(self):
        """Empty list should pass through unchanged."""
        assert compact_context([], max_chars=100) == []

    def test_short_conversation_unchanged(self):
        """Short conversations pass through without modification."""
        conversation = [
            {"role": "user", "content": "Triage my inbox"},
            {"role": "assistant", "content": "Done"},
        ]
        compacted = compact_context(conversation, max_chars=1000)
        assert compacted == conversation

    def test_preserves_structural_keys(self):
        """System messages, role, and tool metadata are never truncated."""
        conversation = [
            {
                "role": "system",
                "content": {"type": "stats", "performance_stats": {"input_tokens": 100}},
            },
            {"role": "user", "content": "Triage my inbox"},
            {"role": "assistant", "content": {"tool": "triage_inbox"}},
            {
                "role": "tool",
                "name": "triage_inbox",
                "content": json.dumps({
                    "ok": True,
                    "data": {"results": [{"id": "m1", "category": "low priority"}]},
                }),
            },
        ]
        compacted = compact_context(conversation, max_chars=500)

        assert len(compacted) == len(conversation)
        assert compacted[0]["role"] == "system"
        assert compacted[0]["content"]["type"] == "stats"
        assert compacted[1]["content"] == "Triage my inbox"
        assert compacted[2]["content"]["tool"] == "triage_inbox"

    def test_truncates_long_assistant_string(self):
        """Long assistant content strings are truncated with marker."""
        long_body = "x" * 5000
        conversation = [
            {"role": "assistant", "content": f"Here is the full analysis: {long_body}"},
        ]
        compacted = compact_context(conversation, max_chars=200)

        total_len = sum(len(str(m.get("content", ""))) for m in compacted)
        assert total_len <= 220  # within limit + truncation marker
        assert "Here is the" in str(compacted[0]["content"])
        assert "[truncated]" in str(compacted[0]["content"])

    def test_truncates_long_tool_string(self):
        """Long tool result strings are truncated with marker."""
        long_result = "y" * 5000
        conversation = [
            {
                "role": "tool",
                "name": "triage_inbox",
                "content": json.dumps({"ok": True, "data": {"results": long_result}}),
            },
        ]
        compacted = compact_context(conversation, max_chars=500)

        content = compacted[0]["content"]
        assert "[truncated]" in content

    def test_truncates_tool_content_list_blocks(self):
        """Tool content as list of blocks has text truncated per block."""
        long_text = "z" * 3000
        conversation = [
            {
                "role": "tool",
                "name": "some_tool",
                "content": [{"type": "text", "text": long_text}],
            },
        ]
        compacted = compact_context(conversation, max_chars=500)

        block = compacted[0]["content"][0]
        assert "[truncated]" in block["text"]
        assert len(block["text"]) < 600

    def test_truncates_assistant_dict_analysis_field(self):
        """Large analysis/reasoning fields in assistant dicts are truncated."""
        long_analysis = "a" * 3000
        conversation = [
            {
                "role": "assistant",
                "content": {
                    "tool": "triage_inbox",
                    "analysis": long_analysis,
                },
            },
        ]
        compacted = compact_context(conversation, max_chars=500)

        content = compacted[0]["content"]
        assert content["tool"] == "triage_inbox"  # structural key preserved
        assert "[truncated]" in content["analysis"]
        assert len(content["analysis"]) < 250


# ---------------------------------------------------------------------------
# TurnResult New Fields Tests
# ---------------------------------------------------------------------------

class TestTurnResultFields:
    """TurnResult new fields have correct defaults and accurate counts."""

    def test_new_fields_have_zero_defaults(self):
        """New fields default to empty/zero, not None."""
        tr = TurnResult(turn_number=1, prompt="test")
        assert tr.heuristic_email_count == 0
        assert tr.llm_email_count == 0
        assert tr.context_compacted is False
        assert tr.gate_decisions == []

    def test_per_turn_heuristic_llm_counts(self):
        """After a smart triage turn, TurnResult reflects accurate split."""
        tr = TurnResult(
            turn_number=1,
            prompt="Triage my inbox",
            heuristic_email_count=5,
            llm_email_count=3,
        )
        assert tr.heuristic_email_count == 5
        assert tr.llm_email_count == 3
        assert tr.heuristic_email_count + tr.llm_email_count == 8

    def test_non_triage_turn_has_zero_smart_counts(self):
        """Follow-up turns (non-triage) have zero heuristic/LLM email counts."""
        tr = TurnResult(
            turn_number=2,
            prompt="Archive low priority",
        )
        assert tr.heuristic_email_count == 0
        assert tr.llm_email_count == 0

    def test_context_compacted_flag(self):
        """TurnResult.context_compacted = True when context was compacted."""
        tr = TurnResult(
            turn_number=4,
            prompt="Summary",
            context_compacted=True,
        )
        assert tr.context_compacted is True

    def test_gate_decisions_list_populated(self):
        """TurnResult.gate_decisions contains one entry per classified email."""
        tr = TurnResult(
            turn_number=1,
            prompt="Triage my inbox",
            gate_decisions=[
                {"email_id": "m1", "gate": "heuristic", "confident": True},
                {"email_id": "m2", "gate": "llm", "confident": False},
            ],
        )
        assert len(tr.gate_decisions) == 2
        assert tr.gate_decisions[0]["email_id"] == "m1"
        assert tr.gate_decisions[1]["gate"] == "llm"

    def test_turnresult_json_serializable(self):
        """TurnResult with all new fields round-trips through json.dumps."""
        tr = TurnResult(
            turn_number=1,
            prompt="Triage my inbox",
            heuristic_email_count=50,
            llm_email_count=30,
            context_compacted=True,
            gate_decisions=[
                {"email_id": "m1", "gate": "heuristic", "confident": True},
            ],
        )
        serialized = json.dumps(tr.__dict__, default=str)
        parsed = json.loads(serialized)
        assert parsed["heuristic_email_count"] == 50
        assert parsed["llm_email_count"] == 30
        assert parsed["context_compacted"] is True
