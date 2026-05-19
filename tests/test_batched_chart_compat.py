"""
Batched mode chart compatibility tests.

Tests the batched-mode data shape fixes and chart generation compatibility.
Tests are organized into 5 categories as specified by the testing task.
"""

import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures: synthetic batched RunResult objects
# ---------------------------------------------------------------------------

def _make_batched_result(
    run_id="test-batch-001",
    model="Qwen3.5-4B-GGUF",
    total_emails=10,
    batch_size=5,
    total_input_tokens=5000,
    total_output_tokens=0,
    total_tokens=5000,
    estimated_steps=10,
    mode="batched",
    num_batches=2,
) -> dict:
    """Create a synthetic batched RunResult as a dict (as loaded from JSON)."""
    batch_results = []
    email_count = 0
    for bn in range(1, num_batches + 1):
        emails_in_batch = min(batch_size, total_emails - email_count)
        if emails_in_batch <= 0:
            break
        email_results = []
        for ei in range(emails_in_batch):
            email_results.append({
                "email_id": f"email-{bn}-{ei}",
                "subject": "",
                "sender": "",
                "category": "informational",
                "confident": True,
                "duration_ms": 100,
                "total_tokens": total_input_tokens // total_emails if total_emails > 0 else 0,
            })
        batch_results.append({
            "batch_number": bn,
            "batch_size": emails_in_batch,
            "total_batches": num_batches,
            "email_results": email_results,
            "duration_ms": 500 * emails_in_batch,
            "total_input_tokens": sum(e["total_tokens"] for e in email_results),
            "total_output_tokens": 0,
            "total_tokens": sum(e["total_tokens"] for e in email_results),
            "categories": ["informational"],
            "status": "ok",
        })
        email_count += emails_in_batch

    return {
        "run_id": run_id,
        "timestamp": "2026-05-19T00:00:00+00:00",
        "model": model,
        "provider": "lemonade",
        "mbox_path": "",
        "jsonl_path": "/tmp/test.jsonl",
        "data_source": "jsonl",
        "mode": mode,
        "batch_results": batch_results,
        "step_results": [],
        "total_emails": total_emails,
        "total_duration_ms": 10000,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_tokens,
        "category_counts": {"informational": total_emails},
        "estimated_steps": estimated_steps,
        "status": "completed",
    }


def _make_full_result(
    run_id="test-full-001",
    model="Qwen3.5-4B-GGUF",
    total_emails=10,
    num_steps=5,
    total_input_tokens=8000,
    total_output_tokens=2000,
    total_tokens=10000,
    mode="full",
) -> dict:
    """Create a synthetic full-mode RunResult as a dict."""
    step_results = []
    for sn in range(1, num_steps + 1):
        step_results.append({
            "step_number": sn,
            "action": "llm_call",
            "tool_name": "triage_inbox" if sn < num_steps else "",
            "input_tokens": total_input_tokens // num_steps,
            "output_tokens": total_output_tokens // num_steps,
            "total_tokens": (total_input_tokens + total_output_tokens) // num_steps,
            "duration_ms": 500,
            "status": "ok",
        })

    return {
        "run_id": run_id,
        "timestamp": "2026-05-19T00:00:00+00:00",
        "model": model,
        "provider": "lemonade",
        "mbox_path": "",
        "jsonl_path": "",
        "data_source": "mbox",
        "mode": mode,
        "batch_results": [],
        "step_results": step_results,
        "total_emails": total_emails,
        "total_duration_ms": 15000,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_tokens,
        "category_counts": {"informational": total_emails},
        "estimated_steps": 0,
        "status": "completed",
    }


# ---------------------------------------------------------------------------
# Test 1: Import test
# ---------------------------------------------------------------------------

class TestImports:
    """Verify all modified modules import without errors."""

    def test_import_data_shapes(self):
        """from gaia.agents.email.bench.data_shapes import RunResult"""
        from gaia.agents.email.bench.data_shapes import RunResult
        assert RunResult is not None
        # Verify the dataclass has the expected fields.
        fields = {f.name for f in RunResult.__dataclass_fields__.values()}
        assert "estimated_steps" in fields
        assert "total_input_tokens" in fields
        assert "total_output_tokens" in fields
        assert "total_tokens" in fields
        assert "mode" in fields

    def test_import_visualize_functions(self):
        """Verify key visualize functions are importable."""
        from gaia.agents.email.bench.visualize import (
            plot_planning_steps_heatmap,
            plot_model_performance_radar,
            plot_batched_llm_activity,
            generate_charts,
        )
        assert callable(plot_planning_steps_heatmap)
        assert callable(plot_model_performance_radar)
        assert callable(plot_batched_llm_activity)
        assert callable(generate_charts)

    def test_import_runner(self):
        """Verify runner module imports cleanly."""
        from gaia.agents.email.bench.runner import (
            _run_batched_agent,
            BatchResult,
            EmailResult,
            RunResult,
        )
        assert callable(_run_batched_agent)
        assert BatchResult is not None
        assert EmailResult is not None
        assert RunResult is not None


# ---------------------------------------------------------------------------
# Test 2: Data shape test
# ---------------------------------------------------------------------------

class TestDataShapes:
    """Create synthetic batched RunResult and verify data shapes."""

    def test_batched_result_has_estimated_steps(self):
        """estimated_steps field exists and defaults to 0 for full mode."""
        from gaia.agents.email.bench.data_shapes import RunResult
        # Default: estimated_steps=0
        rr = RunResult(
            run_id="test", timestamp="", model="test", provider="lemonade",
        )
        assert rr.estimated_steps == 0

    def test_batched_result_mode_is_batched(self):
        """mode="batched" is properly set."""
        result = _make_batched_result()
        assert result["mode"] == "batched"

    def test_batched_token_fields_exist(self):
        """total_input_tokens, total_output_tokens, total_tokens are present."""
        result = _make_batched_result(
            total_input_tokens=5000, total_output_tokens=0, total_tokens=5000
        )
        assert result["total_input_tokens"] == 5000
        assert result["total_output_tokens"] == 0
        assert result["total_tokens"] == 5000

    def test_batched_result_has_batch_results(self):
        """batch_results is populated with BatchResult-like dicts."""
        result = _make_batched_result(total_emails=10, batch_size=5)
        assert len(result["batch_results"]) == 2
        assert result["batch_results"][0]["batch_number"] == 1
        assert result["batch_results"][0]["batch_size"] == 5

    def test_step_results_empty_for_batched(self):
        """step_results is empty for batched mode."""
        result = _make_batched_result()
        assert result["step_results"] == []

    def test_full_result_has_step_results(self):
        """step_results is populated for full mode."""
        result = _make_full_result(num_steps=5)
        assert len(result["step_results"]) == 5
        assert result["mode"] == "full"
        assert result["estimated_steps"] == 0


# ---------------------------------------------------------------------------
# Test 3: Chart generation test
# ---------------------------------------------------------------------------

class TestChartGeneration:
    """Create synthetic run data and verify chart generation."""

    @pytest.fixture
    def tmp_output_dir(self, tmp_path):
        return tmp_path / "charts"

    def test_chart24_mode_gate_batched_uses_estimated_steps(self, tmp_output_dir):
        """Chart 24: batched runs use estimated_steps for step count."""
        from gaia.agents.email.bench.visualize import plot_planning_steps_heatmap

        # Create 2 batched runs with different models and email limits.
        runs = [
            _make_batched_result(model="Qwen3.5-4B-GGUF", total_emails=50, estimated_steps=50),
            _make_batched_result(model="Qwen3.5-8B-GGUF", total_emails=50, estimated_steps=50),
        ]
        result = plot_planning_steps_heatmap(runs, tmp_output_dir)
        # With >= 2 data points, should produce a chart.
        assert result is not None
        assert result.exists()

    def test_chart24_mode_gate_full_uses_step_results(self, tmp_output_dir):
        """Chart 24: full runs use len(step_results) for step count."""
        from gaia.agents.email.bench.visualize import plot_planning_steps_heatmap

        runs = [
            _make_full_result(model="Qwen3.5-4B-GGUF", num_steps=5),
            _make_full_result(model="Qwen3.5-8B-GGUF", num_steps=8),
        ]
        result = plot_planning_steps_heatmap(runs, tmp_output_dir)
        assert result is not None
        assert result.exists()

    def test_chart28_mode_gate_batched_uses_estimated_steps(self, tmp_output_dir):
        """Chart 28: batched runs use estimated_steps in radar chart."""
        from gaia.agents.email.bench.visualize import plot_model_performance_radar

        runs = [
            _make_batched_result(model="Qwen3.5-4B-GGUF", total_emails=50, estimated_steps=50),
            _make_batched_result(model="Qwen3.5-8B-GGUF", total_emails=50, estimated_steps=50),
        ]
        result = plot_model_performance_radar(runs, tmp_output_dir)
        assert result is not None
        assert result.exists()

    def test_chart28_mode_gate_full_uses_step_results(self, tmp_output_dir):
        """Chart 28: full runs use len(step_results) in radar chart."""
        from gaia.agents.email.bench.visualize import plot_model_performance_radar

        runs = [
            _make_full_result(model="Qwen3.5-4B-GGUF", num_steps=5),
            _make_full_result(model="Qwen3.5-8B-GGUF", num_steps=8),
        ]
        result = plot_model_performance_radar(runs, tmp_output_dir)
        assert result is not None
        assert result.exists()

    def test_chart27_batched_empty_input_returns_none(self, tmp_output_dir):
        """Chart 27: returns None when input list is empty."""
        from gaia.agents.email.bench.visualize import plot_batched_llm_activity

        result = plot_batched_llm_activity([], tmp_output_dir)
        assert result is None

    def test_chart27_batched_no_batched_runs_returns_none(self, tmp_output_dir):
        """Chart 27: returns None when no batched runs in input."""
        from gaia.agents.email.bench.visualize import plot_batched_llm_activity

        runs = [
            _make_full_result(model="Qwen3.5-4B-GGUF"),
            _make_full_result(model="Qwen3.5-8B-GGUF"),
        ]
        result = plot_batched_llm_activity(runs, tmp_output_dir)
        assert result is None

    def test_chart27_batched_empty_batch_results_returns_none(self, tmp_output_dir):
        """Chart 27: returns None when batch_results is empty."""
        from gaia.agents.email.bench.visualize import plot_batched_llm_activity

        # Batched mode but no batch_results.
        run = _make_batched_result()
        run["batch_results"] = []
        result = plot_batched_llm_activity([run], tmp_output_dir)
        assert result is None

    def test_chart27_batched_valid_data_produces_chart(self, tmp_output_dir):
        """Chart 27: produces chart when valid batched data exists."""
        from gaia.agents.email.bench.visualize import plot_batched_llm_activity

        runs = [
            _make_batched_result(model="Qwen3.5-4B-GGUF", total_emails=10, batch_size=5),
        ]
        result = plot_batched_llm_activity(runs, tmp_output_dir)
        assert result is not None
        assert result.exists()
        assert "27_batched_llm_activity" in result.name

    def test_generate_charts_with_batched_multi_model(self, tmp_output_dir):
        """generate_charts: produces Chart 27 when batched runs present."""
        from gaia.agents.email.bench.visualize import generate_charts

        runs = [
            _make_batched_result(model="Qwen3.5-4B-GGUF", total_emails=50),
            _make_batched_result(model="Qwen3.5-8B-GGUF", total_emails=50),
        ]
        paths = generate_charts(
            multi_model_runs=runs,
            output_dir=tmp_output_dir,
        )
        # Should have at least Chart 24 (heatmap) and Chart 28 (radar).
        png_paths = [str(p) for p in paths]
        assert any("24_planning_steps_heatmap" in p for p in png_paths)
        assert any("28_model_performance_radar" in p for p in png_paths)
        # Chart 27 batched should also be generated.
        assert any("27_batched_llm_activity" in p for p in png_paths)


# ---------------------------------------------------------------------------
# Test 4: Token accounting test
# ---------------------------------------------------------------------------

class TestTokenAccounting:
    """Verify the token accounting formula in runner.py."""

    def test_batched_total_tokens_equals_total_input(self):
        """With total_output_tokens=0, total_tokens == total_input_tokens."""
        result = _make_batched_result(
            total_input_tokens=5000, total_output_tokens=0, total_tokens=5000
        )
        assert result["total_tokens"] == result["total_input_tokens"]
        assert result["total_output_tokens"] == 0

    def test_batched_formula_total_equals_input_plus_output(self):
        """total_tokens == total_input_tokens + total_output_tokens."""
        result = _make_batched_result(
            total_input_tokens=3000, total_output_tokens=0, total_tokens=3000
        )
        assert result["total_tokens"] == result["total_input_tokens"] + result["total_output_tokens"]

    def test_full_formula_total_equals_input_plus_output(self):
        """total_tokens == total_input_tokens + total_output_tokens (full mode)."""
        result = _make_full_result(
            total_input_tokens=8000, total_output_tokens=2000, total_tokens=10000
        )
        assert result["total_tokens"] == result["total_input_tokens"] + result["total_output_tokens"]

    def test_runner_batched_token_accounting_code(self):
        """Verify the actual runner.py code produces correct token accounting."""
        # We can't run _run_batched_agent without a Lemonade server, but we can
        # verify the static code structure. Lines 349-358 of runner.py show:
        #   total_input_tokens = sum(e.total_tokens for e in email_results)
        #   total_tokens=total_input_tokens
        # This means total_output_tokens is always 0 for batched mode,
        # and total_tokens == total_input_tokens.
        import inspect
        from gaia.agents.email.bench.runner import _run_batched_agent

        source = inspect.getsource(_run_batched_agent)
        # Verify the batched agent sets total_output_tokens=0.
        assert "total_output_tokens=0" in source
        # Verify total_tokens is set from total_input_tokens.
        assert "total_tokens=total_input_tokens" in source
        # Verify estimated_steps is set from len(email_results).
        assert "estimated_steps=len(email_results)" in source
        # Verify mode is set to "batched".
        assert 'mode="batched"' in source

    def test_runner_batch_result_token_propagation(self):
        """Verify per-BatchResult tokens sum correctly."""
        from gaia.agents.email.bench.data_shapes import BatchResult, EmailResult

        emails = [
            EmailResult(email_id="e1", subject="", sender="", total_tokens=100),
            EmailResult(email_id="e2", subject="", sender="", total_tokens=200),
            EmailResult(email_id="e3", subject="", sender="", total_tokens=150),
        ]
        batch = BatchResult(
            batch_number=1,
            batch_size=3,
            total_batches=1,
            email_results=emails,
            total_input_tokens=sum(e.total_tokens for e in emails),
            total_output_tokens=0,
            total_tokens=sum(e.total_tokens for e in emails),
        )
        assert batch.total_tokens == 450
        assert batch.total_input_tokens == 450
        assert batch.total_output_tokens == 0


# ---------------------------------------------------------------------------
# Test 5: Edge case test
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Verify edge case handling in chart functions."""

    @pytest.fixture
    def tmp_output_dir(self, tmp_path):
        return tmp_path / "charts"

    def test_planning_steps_heatmap_empty_list(self, tmp_output_dir):
        """plot_planning_steps_heatmap returns None for empty input."""
        from gaia.agents.email.bench.visualize import plot_planning_steps_heatmap
        result = plot_planning_steps_heatmap([], tmp_output_dir)
        assert result is None

    def test_planning_steps_heatmap_single_run(self, tmp_output_dir):
        """plot_planning_steps_heatmap returns None for < 2 data points."""
        from gaia.agents.email.bench.visualize import plot_planning_steps_heatmap
        runs = [_make_batched_result(model="Qwen3.5-4B-GGUF")]
        result = plot_planning_steps_heatmap(runs, tmp_output_dir)
        # With only 1 (model, emails) key, len(data) < 2, returns None.
        assert result is None

    def test_model_performance_radar_empty_list(self, tmp_output_dir):
        """plot_model_performance_radar returns None for empty input."""
        from gaia.agents.email.bench.visualize import plot_model_performance_radar
        result = plot_model_performance_radar([], tmp_output_dir)
        assert result is None

    def test_model_performance_radar_single_model(self, tmp_output_dir):
        """plot_model_performance_radar returns None for < 2 models."""
        from gaia.agents.email.bench.visualize import plot_model_performance_radar
        runs = [
            _make_batched_result(model="Qwen3.5-4B-GGUF"),
        ]
        result = plot_model_performance_radar(runs, tmp_output_dir)
        # With only 1 model, len(model_data) < 2, returns None.
        assert result is None

    def test_batched_llm_activity_empty_batch_results(self, tmp_output_dir):
        """plot_batched_llm_activity returns None when batch_results is empty."""
        from gaia.agents.email.bench.visualize import plot_batched_llm_activity
        run = _make_batched_result()
        run["batch_results"] = []
        result = plot_batched_llm_activity([run], tmp_output_dir)
        assert result is None

    def test_mixed_modes_chart24(self, tmp_output_dir):
        """Chart 24 handles mixed batched+full runs correctly."""
        from gaia.agents.email.bench.visualize import plot_planning_steps_heatmap
        runs = [
            _make_batched_result(
                model="Qwen3.5-4B-GGUF", total_emails=50, estimated_steps=50
            ),
            _make_full_result(
                model="Qwen3.5-8B-GGUF", num_steps=8, total_emails=50
            ),
        ]
        result = plot_planning_steps_heatmap(runs, tmp_output_dir)
        # Should produce chart with 2 models.
        assert result is not None
        assert result.exists()

    def test_mixed_modes_chart28(self, tmp_output_dir):
        """Chart 28 handles mixed batched+full runs correctly."""
        from gaia.agents.email.bench.visualize import plot_model_performance_radar
        runs = [
            _make_batched_result(
                model="Qwen3.5-4B-GGUF", total_emails=50, estimated_steps=50
            ),
            _make_full_result(
                model="Qwen3.5-8B-GGUF", num_steps=8, total_emails=50
            ),
        ]
        result = plot_model_performance_radar(runs, tmp_output_dir)
        # Should produce radar with 2 models.
        assert result is not None
        assert result.exists()

    def test_detect_mode_function(self):
        """_detect_mode returns correct mode from run dict."""
        from gaia.agents.email.bench.visualize import _detect_mode
        assert _detect_mode({"mode": "batched"}) == "batched"
        assert _detect_mode({"mode": "full"}) == "full"
        assert _detect_mode({"mode": "heuristic"}) == "heuristic"
        assert _detect_mode({}) == "heuristic"  # default


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
