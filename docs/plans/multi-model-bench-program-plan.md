# Multi-Model Benchmark + ClawFlow Integration Program Plan

**Program Manager:** software-program-manager agent
**Date:** 2026-05-11
**Status:** DRAFT -- awaiting stakeholder review

---

## 1. Executive Summary

This program delivers two capabilities:
1. **Multi-model benchmark support** for `gaia email bench` -- run the same MBOX against N models sequentially, compare results, with per-email TTFT/TPS metrics and cold-start isolation.
2. **ClawFlow CLI integration** -- invoke the external agentic-framework-test task runner after GAIA bench completes, parse its JSON output, normalize to GAIA RunResult shape, and produce cross-framework comparison charts.

The work is split into **5 phases** delivered as **5 sequential PRs**. Each phase has its own acceptance criteria, rollback plan, and documentation update checklist.

---

## 2. Phase Ordering and Dependencies

```
PR1 (Bug Fixes) ──► PR3 (CLI) ──► PR4 (Variance) ──► PR5 (Visualization)
      ║
      ║ (parallel, must merge after PR1)
      ▼
PR2 (ClawFlow Adapter)
```

### Critical Path
PR1 -> PR3 -> PR4 -> PR5 (4 PRs, sequential)
PR2 runs in parallel with PR1 but must not merge until PR1 lands (output.py schema stability).

### Phase Detail

| Phase | PR Title | Files Changed | Depends On | Est. Effort |
|-------|----------|---------------|------------|-------------|
| **PR1** | fix(email-bench): per-email TTFT/TPS, cold-start isolation, fail-fast | `runner.py`, `output.py`, `cli.py` | None | 2-3 days |
| **PR2** | feat(email-bench): ClawFlow adapter module | `clawflow_adapter.py` (new), test file | PR1 merged | 1 day |
| **PR3** | feat(email-bench): multi-model CLI flags + ClawFlow orchestration | `cli.py`, `runner.py` | PR1 + PR2 | 2 days |
| **PR4** | feat(email-bench): per-model variance analysis | `variance.py`, `cli.py` | PR3 | 1-2 days |
| **PR5** | feat(email-bench): cross-framework comparison charts | `visualize.py`, new chart functions | PR4 | 3-4 days |

### Parallelization Opportunities
- **PR1 sub-tasks**: Per-email TTFT extraction and cold-start isolation touch different code paths in `runner.py` and can be developed in parallel. Fail-fast is a CLI-level change (`cli.py`) independent of both.
- **PR2** is entirely independent of PR1's code changes; it only depends on the `RunResult` dataclass shape which is stable (PR1 adds fields, doesn't remove).
- **PR5 chart development**: The 8 new charts can be developed in 2 batches -- metrics charts (duration, cost, TTFT, TPS) first, taxonomy/radar charts second.

---

## 3. Acceptance Criteria Per Phase

### PR1: Bug Fixes (runner.py, output.py, cli.py)

**AC-1.1 Per-email TTFT/TPS in CSV:**
- Every per-email CSV row contains the individual email's `duration_per_email_ms` (already present) AND the individual TTFT/TPS if available from per-step stats.
- The SUMMARY row's `duration_per_email_ms` is clearly labelled as an average (already `total_duration_ms // max(total_emails, 1)`).
- Verified: `diff` of existing single-model output shape is identical except for added TTFT/TPS columns where previously absent.

**AC-1.2 Cold-start TTFT isolation:**
- When running multiple models sequentially, the first email of each model run is flagged in the output with `cold_start: true` (new CSV column) so downstream analysis can exclude or annotate it.
- The `--skip-cold-start` CLI flag (planned for PR3) is documented but not yet implemented in PR1.

**AC-1.3 Failed model runs do not abort suite:**
- Existing behavior: if iteration N fails and `all_runs` is empty, return 1; if `all_runs` has prior results, continue.
- New behavior: per-model failure in a `--models` run logs the error to a `model_failures` list, continues to the next model, and exits 0 with a warning if any model failed. (Implementation in PR3; PR1 ensures the data path supports it.)

**AC-1.4 Backwards compatibility:**
- `gaia email bench --mbox-path X --model Y` produces identical CSV/JSON/JSONL output as before (verified by golden-file comparison on a fixed MBOX).

### PR2: ClawFlow Adapter Module

**AC-2.1 probe_clawflow():**
- Returns `(True, version_string)` if `run-tasks.ps1` is found at the configured path and is executable.
- Returns `(False, error_string)` if the path doesn't exist, isn't executable, or PowerShell isn't available.
- Does NOT raise exceptions; returns tuple on all code paths.

**AC-2.2 run_clawflow():**
- Invokes `powershell.exe -ExecutionPolicy Bypass -File run-tasks.ps1` with `--Provider`, `--Model`, `--Output`, and `--DryRun` flags as appropriate.
- Default timeout: 3600 seconds (configurable via parameter).
- On timeout: kills the process tree, returns `ClawflowRunResult(status="timeout", ...)`.
- On non-zero exit: captures stderr, returns `ClawflowRunResult(status="error", ...)`.
- On success: reads the output JSON, returns `ClawflowRunResult(status="success", raw_json=...)`.

**AC-2.3 parse_clawflow_output():**
- Accepts ClawFlow JSON (schema v1.1 as observed; handles v2.0 fields if present).
- Maps to GAIA `RunResult`-compatible dict:
  | ClawFlow field | GAIA field | Transform |
  |---|---|---|
  | `summary.total_latency_ms` | `total_duration_ms` | direct |
  | `summary.total_tokens` | `total_tokens` | direct |
  | `summary.total_tokens_in` | `total_input_tokens` | direct |
  | `summary.total_tokens_out` | `total_output_tokens` | direct |
  | `summary.avg_tokens_per_sec` | `avg_tokens_per_second` | direct |
  | `tasks[].ttft_ms` (if non-null) | `avg_time_to_first_token_ms` | mean of non-null |
  | `tasks[].latency_ms` | per-email `duration_ms` | mapped to EmailResult |
  | `tasks[].task_category` | `category` | taxonomy mapping applied |
  | `tasks[].tokens_total` | `total_tokens` (per-email) | direct |
  | `model` | `model` | direct |
  | `provider` | `provider` | direct |
  | `run_id` | `run_id` | prefix with `clawflow-` |
- Returns dict compatible with `compare_runs()` and `generate_charts()`.

**AC-2.4 Taxonomy mapping:**
- ClawFlow categories (UPPERCASE: `URGENT`, `NEEDS_RESPONSE`, `FYI`, `NOISE`, `PROMOTIONAL`, etc.) map to GAIA categories (lowercase: `urgent`, `actionable`, `informational`, `low priority`) via a bidirectional mapping table.
- Unmapped categories pass through with a warning logged.

**AC-2.5 Unit tests:**
- Tests for all 4 failure modes: missing binary, timeout, non-zero exit, invalid JSON.
- Tests for successful parse with sample ClawFlow JSON (using the existing `results-anthropic-amd-claude-sonnet-4-20260407-223655.json` as fixture).
- All tests run on CI without PowerShell or Lemonade Server.

### PR3: Multi-Model CLI

**AC-3.1 New flags all parse correctly:**
- `--models MODEL1 MODEL2 ...` (repeated, replaces singular `--model` when present)
- `--iterations-per-model N` (default 1)
- `--clawflow` (flag, enables ClawFlow run after all models complete)
- `--clawflow-timeout SECONDS` (default 3600)
- `--clawflow-workflow NAME` (default: all workflows in run-tasks.ps1)
- `--clawflow-path PATH` (default: auto-detect from `OPENCLAW_EVAL_ROOT` or adjacent path)
- `--fail-fast` (abort on first model failure, default: continue)
- `--skip-cold-start` (skip first email of each model to avoid cold-start TTFT contamination)

**AC-3.2 Sequential execution:**
- Models run one at a time. No parallel `gaia eval` invocations (per CLAUDE.md rule).
- Output files are written per-model: `results-{model_safe}-{iterN}.csv`, `results-{model_safe}-{iterN}.json`.
- A combined `results-all.json` contains all model results.

**AC-3.3 ClawFlow orchestration:**
- When `--clawflow` is set, ClawFlow runs after the last model completes.
- ClawFlow results are saved as `clawflow-results.json` and included in the combined output.

**AC-3.4 Help text:**
- `gaia email bench -h` shows all new flags with descriptions and defaults.

**AC-3.5 CLI integration tests:**
- Tests for `--models` with 2 models (mocked runner).
- Tests for `--fail-fast` aborting on first failure.
- Tests for `--clawflow` with mocked adapter.

### PR4: Per-Model Variance Analysis

**AC-4.1 Per-model variance, not cross-model:**
- `compare_runs()` accepts a `group_by_model` parameter.
- When set, variance is computed within each model group independently.
- Output includes a `per_model_variance` dict keyed by model name.

**AC-4.2 Confidence intervals:**
- For models with >= 3 iterations, 95% CI is computed and reported.
- For models with < 3 iterations, CI is omitted with a note.

**AC-4.3 High-variance flagging:**
- Runs with CV% > 20% on any metric are flagged in the variance report.
- Flagged metrics include a recommendation ("increase iterations" or "check cold-start").

### PR5: Cross-Framework Comparison Charts

**AC-5.1 8 new charts generated:**

| # | Chart | Type | Data Source |
|---|-------|------|-------------|
| 11 | Duration comparison (GAIA models + ClawFlow) | Grouped bar | `total_duration_ms` per model |
| 12 | Token cost comparison | Stacked bar | input/output/reasoning tokens |
| 13 | TTFT comparison (per-model, cold-start excluded) | Box plot | `avg_time_to_first_token_ms` |
| 14 | TPS comparison | Box plot | `avg_tokens_per_second` |
| 15 | Framework category comparison (GAIA vs ClawFlow taxonomies) | Side-by-side donut | category counts, normalized |
| 16 | Architecture radar (GAIA vs ClawFlow dimensions) | Radar/spider | normalized scores across dimensions |
| 17 | Per-model variance (CV% heat map) | Heatmap | CV% from variance analysis |
| 18 | Cold-start impact (first-email TTFT delta) | Waterfall | cold-start vs warm TTFT |

**AC-5.2 Architecture radar dimensions:**
The radar chart compares GAIA and ClawFlow across these dimensions (normalized 0-1):
- Email classification accuracy (from ground truth comparison)
- TTFT consistency (inverse of CV% on TTFT)
- Token efficiency (tokens per email, lower is better)
- Category coverage (number of distinct categories assigned)
- Throughput (tokens per second)
- Variance stability (inverse of overall CV%)

**AC-5.3 Taxonomy normalization footnote:**
- Chart 15 (category comparison) includes a footnote: "GAIA categories mapped to ClawFlow taxonomy via output.py GAIA_TO_OPENCLAW mapping. Unmapped categories shown as-is."

**AC-5.4 Synthetic data validation:**
- All 8 charts render correctly from a synthetic multi-model + ClawFlow dataset.
- No NaN, Infinity, or division-by-zero in any chart.
- All charts saved to the configured `--chart-dir`.

---

## 4. Risk Register

| ID | Risk | Probability | Impact | Mitigation | Owner |
|----|------|-------------|--------|------------|-------|
| **R1** | ClawFlow schema changes between v1.1 (observed) and integration | Medium | High | `probe_clawflow()` reads `schema_version` from output JSON. If >= 2.0 or unknown, log warning and apply best-effort parse. Do NOT fail the GAIA run. | PR2 |
| **R2** | Lemonade Server model eviction between benchmark runs inflates TTFT for subsequent models | High | Medium | `--skip-cold-start` flag. Document warmup procedure. Per-model `cold_start` flag in CSV. | PR1+PR3 |
| **R3** | Context window overflow for smaller models on long emails | Medium | Medium | Truncate email body with warning in CSV. Flag oversized emails in variance report. | PR3 |
| **R4** | Different category taxonomies between GAIA EmailTriageAgent and ClawFlow InboxZeroAgent making comparison misleading | High | High | Explicit bidirectional taxonomy mapping in `output.py` and `clawflow_adapter.py`. Chart footnote documents normalization. Unmapped categories pass through with warning. | PR2+PR5 |
| **R5** | ClawFlow subprocess hangs, consuming resources | Low | High | Hard timeout with process tree kill (`subprocess.Popen` + `psutil` or Windows `taskkill /T`). Configurable per-user. | PR2 |
| **R6** | Backwards compatibility break for existing single-model benchmarks | Low | High | New code gated behind `--models` flag. Existing `--model` path untouched. Golden-file test on every PR. | PR1 |
| **R7** | CI/CD pipeline lacks Lemonade Server hardware | Known | Low | Mark tests as `require_lemonade` fixture. Run on demand/nightly, not on every PR. | All |
| **R8** | Output file bloat with many models x iterations | Low | Low | Streaming writes to CSV/JSONL. Optional `--compress` flag for gzip output. | PR3 |
| **R9** | ClawFlow uses `run-tasks.ps1` (PowerShell), not a `clawflow` binary | Known | Medium | Adapter invokes `powershell.exe -ExecutionPolicy Bypass -File run-tasks.ps1` on Windows, `pwsh` on Unix. Probe checks for script, not binary. | PR2 |
| **R10** | ClawFlow sample data is all `dry-run` (skipped: 20, passed: 0) | Known | Low | Adapter handles all-zero summaries gracefully. Integration tests use real (non-dry-run) fixtures when available. | PR2 |

---

## 5. Rollback Plan Per Phase

| Phase | Rollback Action | Data Impact | User Impact |
|-------|-----------------|-------------|-------------|
| **PR1** | `git revert` the PR. Restores run-average TTFT/TPS behavior. | Existing CSV files unchanged. | Users lose per-email TTFT accuracy. |
| **PR2** | Delete `clawflow_adapter.py` and its test file. No other files reference it. | ClawFlow integration data remains in output dir but is unused. | `--clawflow` flag (PR3) will fail gracefully with "ClawFlow adapter not found" warning. |
| **PR3** | Revert CLI changes. `--models` flag removed. | Output files with per-model naming remain on disk. | Users revert to `--model` single-model mode. |
| **PR4** | Revert `variance.py` changes. | Existing `variance.json` files remain on disk. | Variance reports continue to use cross-model (pre-PR4) logic. |
| **PR5** | Delete new chart functions from `visualize.py`. | Existing chart PNGs remain in chart-dir. | Only the 8 new charts disappear; original 10 charts unaffected. |

**Overall rollback strategy:** Each phase is a separate PR. No phase introduces a hard dependency on a later phase's code. If PR3 is merged but PR2 is not, `--clawflow` produces a warning and continues without ClawFlow.

---

## 6. Documentation Update Checklist

| Document | Change | Phase |
|----------|--------|-------|
| `docs/reference/cli.mdx` | Add new flags: `--models`, `--iterations-per-model`, `--clawflow`, `--clawflow-timeout`, `--clawflow-workflow`, `--clawflow-path`, `--fail-fast`, `--skip-cold-start` | PR3 |
| `docs/guides/eval.mdx` | New section: "Multi-Model Benchmark" with example commands and output interpretation | PR3 |
| `docs/guides/eval.mdx` | New section: "Cross-Framework Comparison (GAIA vs ClawFlow)" with chart examples | PR5 |
| `CLAUDE.md` | Add `clawflow_adapter.py` to file reference table under email bench | PR2 |
| `docs/spec/` | New spec: `email-bench-schema.mdx` documenting RunResult fields, cold-start flag, ClawFlow schema mapping | PR2 |
| `docs/guides/eval.mdx` | Update "Variance Analysis" section to describe per-model variance | PR4 |
| `src/gaia/agents/email/bench/__init__.py` | Export new `clawflow_adapter` public API | PR2 |
| `docs/reference/faq.mdx` | Add FAQ: "Why are my TTFT values different between models?" (cold-start explanation) | PR1 |
| `docs/reference/troubleshooting.mdx` | Add troubleshooting: "ClawFlow integration fails" and "Model run fails in multi-model suite" | PR3 |
| New: `docs/guides/bench-compare.mdx` | Guide for interpreting cross-framework comparison charts | PR5 |

---

## 7. CI/CD Impact Assessment

### Existing CI (no changes required)
- `python util/lint.py --all` -- runs on every PR. No lint impact from new code (follows existing patterns).
- `python -m pytest tests/unit/` -- runs on every PR. New unit tests must pass.

### New test files (run on every PR, no hardware required)
| Test File | What It Tests | Est. Duration |
|-----------|---------------|---------------|
| `tests/unit/test_clawflow_adapter.py` | probe, run, parse with mocked subprocess | < 30s |
| `tests/unit/test_email_bench_per_email.py` | Per-email TTFT extraction, cold-start flag | < 15s |
| `tests/unit/test_email_bench_cli.py` | New flag parsing, `--models`, `--fail-fast` | < 15s |
| `tests/unit/test_email_bench_variance.py` | Per-model variance, CI computation | < 15s |
| `tests/unit/test_email_bench_visualize.py` | Chart rendering with synthetic multi-model data | < 30s |

### Integration tests (require hardware, gated by fixture)
| Test File | What It Tests | Fixture | Runs On |
|-----------|---------------|---------|---------|
| `tests/integration/test_multi_model_bench.py` | End-to-end multi-model run | `require_lemonade` | Nightly / on-demand |
| `tests/integration/test_clawflow_integration.py` | Real ClawFlow subprocess | `require_clawflow` (new fixture) | Nightly / on-demand |

### New GHA fixture
```python
# tests/conftest.py
@pytest.fixture
def require_clawflow():
    """Skip if ClawFlow run-tasks.ps1 is not available."""
    clawflow_path = os.environ.get("CLAWFLOW_PATH")
    if not clawflow_path or not Path(clawflow_path).exists():
        pytest.skip("CLAWFLOW_PATH not set or run-tasks.ps1 not found")
```

### No new GHA workflows needed
- All new tests fit into the existing `pytest` workflow.
- Hardware-dependent tests are skipped automatically by fixtures.
- No changes to `.github/workflows/` required.

---

## 8. Stakeholder Communication Plan

| Stakeholder | What They Need to Know | When | Channel |
|-------------|----------------------|------|---------|
| **@kovtcharov-amd** | Architecture decisions: taxonomy mapping approach, ClawFlow subprocess model, cold-start flag design | Before PR1 merges | Issue comment or direct message |
| **eval-engineer agent** | Benchmark methodology: per-email TTFT accuracy, variance computation changes, ground truth compatibility | PR1 + PR4 review | PR review comments |
| **CLI developer** | New CLI flag design, backwards compatibility guarantees | PR3 review | PR review comments |
| **architecture-reviewer** | Cross-framework comparison design, schema mapping correctness, mixin composition | PR2 + PR5 review | PR review comments |
| **code-reviewer** | All PRs for code quality, lint compliance, error handling | Each PR | PR review (automated) |
| **External: ClawFlow maintainers** | Schema v2.0 stability notification | Before PR2 | Out-of-band |

---

## 9. File Reference

### Existing files (modified)
| File | Phases |
|------|--------|
| `C:\Users\antmi\gaia-main\src\gaia\agents\email\bench\runner.py` | PR1, PR3 |
| `C:\Users\antmi\gaia-main\src\gaia\agents\email\bench\output.py` | PR1 (cold-start column) |
| `C:\Users\antmi\gaia-main\src\gaia\agents\email\bench\variance.py` | PR4 |
| `C:\Users\antmi\gaia-main\src\gaia\agents\email\bench\visualize.py` | PR5 |
| `C:\Users\antmi\gaia-main\src\gaia\agents\email\bench\cli.py` | PR1, PR3 |
| `C:\Users\antmi\gaia-main\tests\conftest.py` | CI/CD (new fixture) |

### New files
| File | Phase | Purpose |
|------|-------|---------|
| `C:\Users\antmi\gaia-main\src\gaia\agents\email\bench\clawflow_adapter.py` | PR2 | ClawFlow probe, run, parse |
| `C:\Users\antmi\gaia-main\tests\unit\test_clawflow_adapter.py` | PR2 | Unit tests for adapter |
| `C:\Users\antmi\gaia-main\tests\unit\test_email_bench_per_email.py` | PR1 | Per-email TTFT tests |
| `C:\Users\antmi\gaia-main\tests\unit\test_email_bench_cli.py` | PR3 | CLI flag tests |
| `C:\Users\antmi\gaia-main\tests\unit\test_email_bench_variance.py` | PR4 | Per-model variance tests |
| `C:\Users\antmi\gaia-main\tests\unit\test_email_bench_visualize.py` | PR5 | Chart rendering tests |
| `C:\Users\antmi\gaia-main\tests\integration\test_multi_model_bench.py` | PR3 | Integration test |
| `C:\Users\antmi\gaia-main\tests\integration\test_clawflow_integration.py` | PR3 | ClawFlow integration test |

### ClawFlow reference (read-only)
| File | Purpose |
|------|---------|
| `C:\Users\antmi\openclaw-eval\scripts\agentic-framework-test\scripts\ps1\run-tasks.ps1` | ClawFlow task runner (invoked via subprocess) |
| `C:\Users\antmi\openclaw-eval\scripts\agentic-framework-test\docs\OPENCLAW-GAIA-KPI-DATA-DICTIONARY.md` | KPI mapping reference |
| `C:\Users\antmi\openclaw-eval\scripts\agentic-framework-test\config\schemas\gaia-feed-1.0.schema.json` | GAIA feed schema (for comparison) |

---

## 10. Key Design Decisions

### D1: ClawFlow is invoked via PowerShell subprocess, not a Python import
**Decision:** Use `subprocess.run(["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", "run-tasks.ps1", ...])`.
**Rationale:** ClawFlow is a PowerShell-based framework. Its task runner (`run-tasks.ps1`) is the entry point. There is no `clawflow` binary or Python package to import.
**Alternative considered:** Rewriting the task runner in Python. Rejected: out of scope, duplicates logic.

### D2: Taxonomy mapping is bidirectional and documented
**Decision:** The existing `GAIA_TO_OPENCLAW` mapping in `output.py` is extended to cover ClawFlow categories. A companion `OPENCLAW_TO_GAIA` mapping exists. Unmapped categories pass through with a warning.
**Rationale:** GAIA uses lowercase categories (`urgent`, `actionable`, `informational`, `low priority`). ClawFlow uses UPPERCASE (`URGENT`, `NEEDS_RESPONSE`, `FYI`, `NOISE`). Direct comparison requires normalization.
**Alternative considered:** Force both frameworks to use a common taxonomy. Rejected: out of scope for this program; would require changing both agents' prompts.

### D3: Per-model variance is computed independently
**Decision:** Variance analysis groups runs by model name and computes statistics within each group. Cross-model variance is not computed (apples-to-oranges).
**Rationale:** Mixing models in variance computation conflates model performance differences with LLM non-determinism. Per-model variance isolates the non-determinism signal.

### D4: Cold-start TTFT is flagged, not excluded
**Decision:** The first email of each model run gets `cold_start: true` in the CSV. It is NOT excluded from averages by default. Users can exclude it via post-processing or the planned `--skip-cold-start` flag.
**Rationale:** Exclusion changes the benchmark scope. Flagging preserves data integrity and lets users decide.

### D5: Schema v2.0 is not assumed
**Decision:** The adapter reads `schema_version` from ClawFlow JSON and applies best-effort parsing. If the version is unrecognized, it logs a warning but does not fail.
**Rationale:** The observed schema is v1.1. The planning document mentioned v2.0 with `PerformanceMetrics(ttft_ms, tokens_per_second)`. The actual data uses flat fields. The adapter handles both shapes.

---

## 11. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Per-email TTFT accuracy | 100% of emails have individual TTFT where available | CSV column check |
| Multi-model run success rate | > 95% of model runs complete without aborting | Exit code + `model_failures` count |
| ClawFlow integration success rate | > 90% of `--clawflow` runs produce parseable output | `clawflow-results.json` exists and is valid JSON |
| Chart generation success rate | 100% of charts render without errors | No exceptions in `generate_charts()` |
| Backwards compatibility | 100% of existing single-model benchmarks produce identical output | Golden-file diff |
| CI pass rate | 100% of new unit tests pass on every PR | GHA workflow status |
