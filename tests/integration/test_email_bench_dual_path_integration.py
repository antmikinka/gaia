# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""Integration tests: Chart 23 dual-path visualization + plot_smart_turn_split."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


class TestChart23DualPath:
    """Chart 23 (plot_heuristic_vs_llm_escalation) handles interactive data."""

    def test_chart_23_interactive_data(self):
        """Chart 23 must handle interactive summary data, not just batch_results."""
        from gaia.agents.email.bench.visualize import (
            plot_heuristic_vs_llm_escalation,
        )

        interactive_runs = [{
            "run_id": "run-interactive-abc123",
            "model": "Qwen3.5-4B-GGUF",
            "heuristic_triaged": {f"m{i}": "low priority" for i in range(1, 61)},
            "llm_triaged": {f"m{i}": "informational" for i in range(61, 101)},
            "batch_results": [],
            "mode": "smart",
        }]

        with tempfile.TemporaryDirectory() as tmpdir:
            result = plot_heuristic_vs_llm_escalation(
                interactive_runs, Path(tmpdir)
            )
            assert result is not None
            assert result.exists()

    def test_chart_23_all_heuristic(self):
        """100% heuristic, 0% LLM -- chart should show full green bar."""
        from gaia.agents.email.bench.visualize import (
            plot_heuristic_vs_llm_escalation,
        )

        runs = [{
            "run_id": "run-all-heuristic",
            "model": "Qwen3.5-4B-GGUF",
            "heuristic_triaged": {"m1": "low priority"},
            "llm_triaged": {},
            "batch_results": [],
        }]
        with tempfile.TemporaryDirectory() as tmpdir:
            result = plot_heuristic_vs_llm_escalation(runs, Path(tmpdir))
            assert result is not None

    def test_chart_23_all_llm(self):
        """0% heuristic, 100% LLM -- chart should show full orange bar."""
        from gaia.agents.email.bench.visualize import (
            plot_heuristic_vs_llm_escalation,
        )

        runs = [{
            "run_id": "run-all-llm",
            "model": "Qwen3.5-4B-GGUF",
            "heuristic_triaged": {},
            "llm_triaged": {"m1": "actionable"},
            "batch_results": [],
        }]
        with tempfile.TemporaryDirectory() as tmpdir:
            result = plot_heuristic_vs_llm_escalation(runs, Path(tmpdir))
            assert result is not None

    def test_chart_23_empty_runs(self):
        """Empty runs list should return None."""
        from gaia.agents.email.bench.visualize import (
            plot_heuristic_vs_llm_escalation,
        )

        assert plot_heuristic_vs_llm_escalation([], Path("/tmp")) is None

    def test_chart_23_no_triaged_emails(self):
        """No triaged emails should return None."""
        from gaia.agents.email.bench.visualize import (
            plot_heuristic_vs_llm_escalation,
        )

        runs = [{
            "run_id": "empty",
            "model": "X",
            "heuristic_triaged": {},
            "llm_triaged": {},
            "batch_results": [],
        }]
        with tempfile.TemporaryDirectory() as tmpdir:
            result = plot_heuristic_vs_llm_escalation(runs, Path(tmpdir))
            assert result is None


class TestPlotSmartTurnSplit:
    """plot_smart_turn_split handles multi-turn, single-turn, and missing fields."""

    def test_plot_smart_turn_split_multi_turn(self):
        """Per-turn breakdown with heuristic and LLM classification."""
        from gaia.agents.email.bench.visualize import plot_smart_turn_split

        interactive = {
            "turns": [
                {
                    "turn_number": 1,
                    "prompt": "Triage my inbox",
                    "heuristic_email_count": 50,
                    "llm_email_count": 30,
                    "total_tokens": 8000,
                },
                {
                    "turn_number": 2,
                    "prompt": "Archive low priority",
                    "heuristic_email_count": 0,
                    "llm_email_count": 0,
                    "total_tokens": 2000,
                },
                {
                    "turn_number": 3,
                    "prompt": "Re-triage remaining",
                    "heuristic_email_count": 10,
                    "llm_email_count": 10,
                    "total_tokens": 3000,
                },
            ],
            "model": "Qwen3.5-4B-GGUF",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            result = plot_smart_turn_split(interactive, Path(tmpdir))
            assert result is not None
            assert result.exists()

    def test_plot_smart_turn_split_single_turn(self):
        """Works with only one turn."""
        from gaia.agents.email.bench.visualize import plot_smart_turn_split

        interactive = {
            "turns": [
                {
                    "turn_number": 1,
                    "heuristic_email_count": 0,
                    "llm_email_count": 5,
                    "total_tokens": 1000,
                },
            ],
            "model": "X",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            result = plot_smart_turn_split(interactive, Path(tmpdir))
            assert result is not None

    def test_plot_smart_turn_split_no_smart_fields(self):
        """Gracefully handles turns without smart-mode fields."""
        from gaia.agents.email.bench.visualize import plot_smart_turn_split

        interactive = {
            "turns": [{"turn_number": 1, "total_tokens": 1000}],
            "model": "X",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            result = plot_smart_turn_split(interactive, Path(tmpdir))
            assert result is not None  # should still render, with zeros
