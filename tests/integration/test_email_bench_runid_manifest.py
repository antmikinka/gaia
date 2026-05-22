# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""End-to-end test: bench_runner CLI path with run IDs and manifest tracking."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gaia.agents.email.bench.data_shapes import RunResult


class TestRunIdAndManifest:
    """Verify run IDs appear in all output filenames and _manifest.json is written."""

    def _make_run_result(self, run_id="run-full-20260521-120000-test-abc123"):
        return RunResult(
            run_id=run_id,
            timestamp="2026-05-21T12:00:00",
            model="Qwen3.5-4B-GGUF",
            provider="lemonade",
            mbox_path="tests/fixtures/email/_stub_inbox.mbox",
            mode="full",
            status="ok",
            total_emails=10,
            total_duration_ms=5000,
            total_input_tokens=10000,
            total_output_tokens=3000,
            total_tokens=13000,
        )

    def test_manifest_written_for_full_mode(self):
        """Multi-model loop writes _manifest.json entries."""
        from gaia.agents.email.bench.bench_runner import _write_generation_manifest

        with pytest.MonkeyPatch.context() as mp:
            with patch("gaia.agents.email.bench.bench_runner._run_single_iteration") as mock_run:
                mock_run.return_value = self._make_run_result()

                from gaia.agents.email.bench.bench_runner import main

                import tempfile
                with tempfile.TemporaryDirectory() as tmpdir:
                    argv = [
                        "--mbox-path", "tests/fixtures/email/_stub_inbox.mbox",
                        "--models", "Qwen3.5-4B-GGUF",
                        "--limit", "10",
                        "--output-dir", tmpdir,
                    ]
                    result = main(argv)
                    assert result == 0

                    manifest_path = Path(tmpdir) / "_manifest.json"
                    assert manifest_path.exists(), "Manifest not written"
                    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
                    assert len(entries) >= 1
                    assert entries[0]["run_id"].startswith("run-full-")
                    assert entries[0]["mode"] == "full"
                    assert "run_abc123.json" in entries[0]["output_files"][1]

                    # Per-run JSON file exists
                    per_run_files = list(Path(tmpdir).glob("run_abc123.json"))
                    assert len(per_run_files) == 1, f"Per-run file not found: {list(Path(tmpdir).glob('run_*.json'))}"
