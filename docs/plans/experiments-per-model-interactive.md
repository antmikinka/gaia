# Plan: Integrating `--experiments-per-model` into `--mode interactive`

**Document Type**: Final Implementation Plan (Execution-Ready)
**Branch**: `feat/email-bench-visualizations`
**Date**: 2026-05-26
**Status**: Ready for implementation
**Reviewed by**: 5 agents (planning-analysis, program-manager, quality-reviewer, enhanced-senior-developer, testing-quality-specialist)

---

## 1. Problem Statement

When running `gaia email bench --mode interactive --experiments-per-model N`, the experiment count is silently ignored. The interactive handler in `bench_runner.py` returns after a single run (line 357), so `N > 1` has no effect. Users cannot measure variance across repeated interactive sessions, and cold-start vs warm-start performance cannot be compared.

The existing meta-bencher scripts (`smart-interactive-bencher.py` and 4 duplicates) pass `--experiments-per-model=3` to the inner command but get no experiment repetition in return.

---

## 2. Key Decisions (Consensus)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Approach B: experiment looping in meta-bencher** | `run_interactive_session()` uses `input()` which consumes piped stdin; a second call gets EOF immediately. Inner-loop experiments are infeasible. |
| 2 | **stdin guard in `bench_runner.py`** | If `--experiments-per-model > 1` in interactive mode, print a warning and run only experiment 1. Makes the limitation explicit. |
| 3 | **Consolidate 5 bencher files to 1** | 4 are byte-identical; 1 adds argparse + relative paths. Keep the argparse variant. |
| 4 | **Report generator: separate interactive path** | Interactive data shape (nested turns) is incompatible with JSONL report columns (`batch_results`-based). Requires a dedicated interactive report code path. |
| 5 | **Cold-start tagging via log naming + manifest** | First experiment = cold, subsequent = warm. Reflected in log file prefix and manifest field. |
| 6 | **3 commits** | (1) consolidate bencher + experiment loop, (2) bench_runner stdin guard + cold-start, (3) report generator interactive support. |

---

## 3. Current State

### 3.1 Bencher Files (5 duplicates)

| File | Lines | Notes |
|------|-------|-------|
| `benchmark_charts/smart-interactive-bencher.py` | 222 | Hardcoded JSONL path |
| `benchmark_charts/smart-interactive-bencher3.py` | 222 | Byte-identical to above |
| `benchmark_charts/smartinteractive-bencher/smart-interactive-bencher.py` | 222 | Byte-identical to above |
| `benchmark_charts/smartinteractive-bencher/smart-interactive-bencher (1).py` | 231 | **KEEP**: argparse + `__file__`-relative JSONL path |
| `.pyc` files | -- | Delete with duplicates |

### 3.2 bench_runner.py (`src/gaia/agents/email/bench/bench_runner.py`)

- **Interactive handler (lines 227-357)**: returns after 1 run, ignores `--experiments-per-model`
- **Full mode loop (lines 359-491)**: loops over experiments correctly, only for non-interactive
- **`run_interactive_session()` (runner.py:1344-1645)**: uses `input()` on line 1420

### 3.3 Report Generator (`src/gaia/agents/email/bench/report_generator.py`)

- `generate_reports()` (line 467): only globs `results_*.jsonl`
- Interactive runs produce `interactive_*.json` files -- completely excluded
- visualize.py already supports interactive charting (6 plot functions), but report CSV/variance/statistical paths do not

### 3.4 Existing Tests

| File | Coverage |
|------|----------|
| `tests/unit/agents/test_email_bench_runner_gaps.py` | PR1 regression tests (normalize, triage_prompt, sync_session_state) |
| `tests/unit/agents/test_email_bench_pr2_features.py` | PR2 smart-mode features |
| `tests/integration/test_email_bench_smart_integration.py` | Smart mode integration |
| `tests/unit/agents/test_email_agent_interactive_smart_triage.py` | Agent-level smart triage unit tests |

---

## 4. Implementation

### Commit 1: Consolidate Bencher + Add Experiment Loop

**Scope**: Delete 4 duplicate bencher files, keep 1 canonical copy, add outer experiment loop.

#### 4.1 File Operations

```
DELETE benchmark_charts/smart-interactive-bencher.py
DELETE benchmark_charts/smart-interactive-bencher3.py
DELETE benchmark_charts/smartinteractive-bencher/smart-interactive-bencher.py
DELETE benchmark_charts/smartinteractive-bencher/  (directory)
KEEP   benchmark_charts/smart-interactive-bencher.py  (renamed from "(1).py" variant)
```

#### 4.2 Changes to Canonical Bencher

The consolidated `benchmark_charts/smart-interactive-bencher.py` gains an outer experiment loop that wraps the existing model/limit/batch_size loop:

```python
for exp in range(1, EXPERIMENTS + 1):
    is_cold = exp == 1
    cold_label = "cold" if is_cold else "warm"
    print(f"\n{'='*70}")
    print(f"  EXPERIMENT {exp}/{EXPERIMENTS} [{'COLD START' if is_cold else 'WARM'}]")
    print(f"{'='*70}")

    exp_output = BASE_OUTPUT / f"exp{exp}_{cold_label}"
    exp_log = LOG_BASE / f"exp{exp}_{cold_label}"
    exp_output.mkdir(parents=True, exist_ok=True)
    exp_log.mkdir(parents=True, exist_ok=True)

    for model in MODELS:
        if not load_model(model):
            continue
        for limit in LIMITS:
            for batch_size in BATCH_SIZES:
                if batch_size > limit:
                    continue

                # Log file includes cold/warm label.
                log_file = exp_log / f"{slug(model)}_limit{limit}_batch{batch_size}_{timestamp}.log"

                # NOTE: --experiments-per-model=1 because outer loop owns experiments.
                cmd = [
                    "gaia", "email", "bench",
                    "--jsonl-path", str(JSONL_PATH),
                    "--model", model,
                    "--limit", str(limit),
                    "--batch-size", str(batch_size),
                    "--experiments-per-model", "1",
                    "--output-dir", str(exp_output),
                    "--mode", "interactive",
                    "--smart",
                ]

                stdin_data = build_scenario(limit)
                # ... subprocess.run(cmd, input=stdin_data, ...) as existing
```

**Key points**:
- `--experiments-per-model` is set to `1` in the inner command. The outer loop owns experiment counting.
- Log files include `cold`/`warm` label in the path: `exp1_cold/` vs `exp2_warm/`.
- Each experiment writes to a separate output subdirectory: `exp1_cold/`, `exp2_warm/`, etc.
- The manifest field `experiment` tracks the experiment number and `is_cold_start` boolean.
- Model load/unload happens per experiment (reload = cold start simulation).

#### 4.3 Argparse Enhancement

The canonical bencher's `main()` function gains argparse flags for all configurable parameters:

```python
parser.add_argument("--experiments", type=int, default=3,
                    help="Number of experiments per model/limit/batch-size combo")
parser.add_argument("--models", nargs="+", default=None,
                    help="Override default model list")
parser.add_argument("--limits", nargs="+", type=int, default=None,
                    help="Override default limit list")
parser.add_argument("--batch-sizes", nargs="+", type=int, default=None,
                    help="Override default batch size list")
```

---

### Commit 2: bench_runner.py Stdin Guard + Cold-Start Metadata

**Scope**: Add stdin guard to interactive handler, add cold-start tracking to manifest and output metadata.

#### 2.1 Stdin Guard in bench_runner.py

In `bench_runner.py`, within the `if args.mode == "interactive":` block (line 228), add a guard:

```python
if args.mode == "interactive":
    if args.experiments_per_model > 1:
        print(f"\n  WARNING: --experiments-per-model={args.experiments_per_model} "
              f"has no effect in interactive mode (stdin consumed after first run). "
              f"Running experiment 1 only.")
        print(f"  For multi-experiment interactive runs, use the meta-bencher script "
              f"which loops externally.")

    # ... existing interactive run code (unchanged) ...
    return 0
```

This makes the limitation explicit to anyone who tries `gaia email bench --mode interactive --experiments-per-model 3` directly.

#### 2.2 Cold-Start Metadata in Output

The interactive output JSON (written at `bench_runner.py:340-341`) gains two fields:

```python
output_data["is_cold_start"] = True  # Always True for bench_runner.py (single run)
output_data["experiment_number"] = 1  # Always 1 for bench_runner.py
```

These fields are always `True`/`1` for direct `bench_runner.py` calls. The meta-bencher scripts set them per subprocess invocation.

#### 2.3 Manifest Update

The `_write_generation_manifest()` call (line 343) gains:

```python
_write_generation_manifest(output_dir, {
    "run_id": summary["run_id"],
    "timestamp": summary["timestamp"],
    "model": model,
    "mode": "interactive" + ("-smart" if getattr(args, "smart", False) else ""),
    "output_files": [str(interactive_path.relative_to(output_dir))],
    "total_turns": summary["total_turns"],
    "total_emails_affected": summary["total_emails_affected"],
    "total_tokens": summary["total_tokens"],
    "heuristic_triaged": len(summary.get("heuristic_triaged", {})),
    "llm_triaged": len(summary.get("llm_triaged", {})),
    "experiment_number": 1,           # NEW
    "is_cold_start": True,            # NEW
})
```

---

### Commit 3: Report Generator Interactive Support

**Scope**: Add interactive JSON glob, normalize data shape, produce interactive-aware report CSV.

#### 3.1 Problem

The current report CSV columns assume `batch_results` (flat per-email records with `category`, `confident` flags). Interactive runs produce a nested JSON with `turns[]` containing `step_results[]`. The two shapes are incompatible.

#### 3.2 Solution: Separate Interactive Report Path

Add a function `_generate_interactive_report()` that:

1. Globs `interactive_*.json` files from the input directory
2. Normalizes the nested data into a flat row-per-turn shape
3. Produces `interactive_report.csv` with columns appropriate for interactive data

```python
INTERACTIVE_CSV_COLUMNS = [
    "model",
    "experiment_number",
    "is_cold_start",
    "turn_number",
    "prompt",
    "duration_ms",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "tools_called",
    "emails_affected",
    "heuristic_email_count",
    "llm_email_count",
    "status",
]


def _generate_interactive_report(
    input_dir: Path,
    output_dir: Path,
    *,
    skip_cold_start: bool = False,
) -> None:
    """Generate interactive_report.csv from interactive_*.json files."""
    paths = sorted(input_dir.glob("interactive_*.json"))
    if not paths:
        print("  No interactive_*.json files found. Skipping interactive report.")
        return

    rows = []
    for jp in paths:
        data = json.loads(jp.read_text(encoding="utf-8"))
        if skip_cold_start and data.get("is_cold_start"):
            continue
        for turn in data.get("turns", []):
            rows.append({
                "model": data.get("model", "unknown"),
                "experiment_number": data.get("experiment_number", 1),
                "is_cold_start": data.get("is_cold_start", False),
                "turn_number": turn.get("turn_number", 0),
                "prompt": turn.get("prompt", "")[:100],
                "duration_ms": turn.get("duration_ms", 0),
                "input_tokens": turn.get("input_tokens", 0),
                "output_tokens": turn.get("output_tokens", 0),
                "total_tokens": turn.get("total_tokens", 0),
                "tools_called": ", ".join(turn.get("tools_called", [])),
                "emails_affected": len(turn.get("emails_affected", [])),
                "heuristic_email_count": turn.get("heuristic_email_count", 0),
                "llm_email_count": turn.get("llm_email_count", 0),
                "status": turn.get("status", "unknown"),
            })

    output_path = output_dir / "interactive_report.csv"
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=INTERACTIVE_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Interactive report CSV saved to: {output_path}")
```

#### 3.3 Integration into generate_reports()

Add to the `generate_reports()` function (after the existing report CSV generation):

```python
# 7. interactive_report.csv (if interactive data present)
_generate_interactive_report(input_dir, output_dir, skip_cold_start=skip_cold_start)
```

#### 3.4 Variance Analysis for Interactive Data

Add `_generate_interactive_variance()` that computes variance across experiments for the same model/limit/batch-size combo, using the per-turn `total_tokens` and `duration_ms` as metrics:

```python
def _generate_interactive_variance(
    input_dir: Path,
    output_dir: Path,
) -> None:
    """Generate interactive_variance.json across experiments."""
    # Groups by (model, turn_number) across experiments.
    # Computes mean, stddev, CV for duration_ms and total_tokens.
    # Only meaningful when >= 2 experiments exist for the same config.
```

#### 3.5 Chart Generation

The existing `visualize.py` already handles interactive charting. The report generator's `_generate_charts()` call already passes interactive data through `generate_charts()`. No changes needed to the charting path -- only the CSV/variance paths need the new functions above.

---

## 5. File Change Summary

| File | Action | Lines Changed |
|------|--------|---------------|
| `benchmark_charts/smart-interactive-bencher.py` | **REWRITE** (from `(1).py` variant) | ~280 (add outer exp loop, argparse) |
| `benchmark_charts/smart-interactive-bencher3.py` | **DELETE** | -- |
| `benchmark_charts/smartinteractive-bencher/` | **DELETE** (entire directory) | -- |
| `src/gaia/agents/email/bench/bench_runner.py` | **MODIFY** | ~15 new (stdin guard, cold-start fields) |
| `src/gaia/agents/email/bench/report_generator.py` | **MODIFY** | ~120 new (interactive report path + variance) |
| `tests/unit/email/test_experiments_interactive.py` | **CREATE** | ~200 new (unit tests) |
| `tests/integration/test_interactive_experiments_e2e.py` | **CREATE** | ~100 new (2 e2e tests) |

---

## 6. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | Report CSV shape mismatch for interactive data | **High** | **Medium** | Separate interactive report path with turn-level columns (Section 3.2) |
| R2 | Bencher still passes `--experiments-per-model > 1` after consolidation | **Medium** | **Low** | Set to `1` explicitly; stdin guard catches any mistake |
| R3 | Model reload timing affects cold-start measurement | **Medium** | **Medium** | Document that "cold start" means "first experiment per model load"; true cold-start requires manual unload/reload between experiments |
| R4 | Interactive variance analysis needs >= 2 experiments | **High** | **Low** | Function returns early with info message if insufficient data |
| R5 | Log file naming collision across experiments | **Low** | **High** | Each experiment writes to separate subdirectory (`exp1_cold/`, `exp2_warm/`) |
| R6 | Chart generation path assumes single interactive file | **Low** | **Medium** | Report generator passes all interactive files; visualize.py already handles multi-file input |
| R7 | Stdin guard warning missed by users | **Low** | **Low** | Warning includes pointer to meta-bencher script; `WARNING:` prefix stands out |

---

## 7. Test Plan

### 7.1 Unit Tests (Mocked)

| # | Test | What | Priority |
|---|------|------|----------|
| T1 | `test_stdin_guard_warns_on_experiments_gt_1` | bench_runner prints warning when `--experiments-per-model > 1` in interactive mode | **P0** |
| T2 | `test_stdin_guard_runs_experiment_1` | bench_runner completes 1 run despite `--experiments-per-model > 1` | **P0** |
| T3 | `test_interactive_output_has_cold_start_field` | Output JSON includes `is_cold_start` and `experiment_number` | **P0** |
| T4 | `test_manifest_tracks_experiment_number` | Manifest entry includes experiment number and cold-start flag | **P0** |
| T5 | `test_interactive_report_csv_generated` | `interactive_report.csv` produced from `interactive_*.json` files | **P1** |
| T6 | `test_interactive_report_csv_columns` | CSV has correct columns (model, turn_number, duration_ms, etc.) | **P1** |
| T7 | `test_interactive_report_skip_cold_start` | `--skip-cold-start` excludes cold-start rows from interactive CSV | **P1** |
| T8 | `test_interactive_variance_groups_by_model_turn` | Variance JSON groups by (model, turn_number) across experiments | **P1** |
| T9 | `test_interactive_variance_needs_2_experiments` | Returns early with message when < 2 experiments | **P2** |
| T10 | `test_bencher_experiment_loop_outer` | Meta-bencher loops N times, each with separate output subdir | **P1** |
| T11 | `test_bencher_cold_warm_log_paths` | Log files in `exp1_cold/` vs `exp2_warm/` directories | **P1** |
| T12 | `test_bencher_passes_experiments_per_model_1` | Inner command gets `--experiments-per-model 1` | **P1** |

### 7.2 Integration Tests (2 e2e, rest mocked)

| # | Test | What | Priority |
|---|------|------|----------|
| I1 | `test_interactive_single_run` | Direct `gaia email bench --mode interactive` produces valid JSON | **P0** |
| I2 | `test_report_generator_handles_mixed_data` | Report generator produces both `report.csv` and `interactive_report.csv` from mixed input dir | **P1** |

### 7.3 Mock Strategy

All unit tests mock:
- `subprocess.run` (for bencher experiment loop)
- `input()` (for interactive session -- not needed since bench_runner guard is tested)
- `json.loads` / file I/O (for report generator)
- `Path.glob` (for report generator file discovery)

Only I1 and I2 run against real code paths (no subprocess mocking).

---

## 8. Commit Plan

### Commit 1: `refactor(email-bench): consolidate smart-interactive-bencher + add experiment loop`

- Delete 4 duplicate bencher files
- Keep canonical copy with argparse + relative paths
- Add outer experiment loop with cold/warm labeling
- Add argparse flags for experiments, models, limits, batch-sizes

### Commit 2: `fix(email-bench): add stdin guard for interactive mode + cold-start metadata`

- Add stdin guard to `bench_runner.py` interactive handler
- Add `is_cold_start` and `experiment_number` to interactive output JSON
- Add `is_cold_start` and `experiment_number` to manifest entries

### Commit 3: `feat(email-bench): add interactive report path to report generator`

- Add `interactive_*.json` glob to report generator
- Add `_generate_interactive_report()` function with turn-level CSV
- Add `_generate_interactive_variance()` for cross-experiment analysis
- Integrate into `generate_reports()` function

---

## 9. Acceptance Criteria

| Criterion | Measurement |
|-----------|-------------|
| Meta-bencher runs N experiments per model/limit/batch-size combo | N subprocess invocations, N output subdirectories |
| Each experiment produces valid `interactive_*.json` | JSON validates, contains `turns[]`, `is_cold_start`, `experiment_number` |
| Stdin guard prints warning for `--experiments-per-model > 1` | Warning text visible in output, run completes with 1 experiment |
| Report generator produces `interactive_report.csv` | File exists, has correct columns, row count matches turns across all interactive files |
| Report generator produces `interactive_variance.json` | File exists, contains per-model per-turn variance metrics (or early-exit message) |
| Cold-start vs warm-start distinguishable in output | `is_cold_start` field is `true` for experiment 1, `false` for subsequent |
| No regression on non-interactive modes | `--mode full` with `--experiments-per-model N` still works as before |
| Existing tests pass | All pre-existing test files pass without modification |

---

## 10. Out of Scope

| Item | Reason |
|------|--------|
| Modifying `run_interactive_session()` to support repeated stdin | Fundamental `input()` limitation; Approach B handles this correctly |
| Changing `--experiments-per-model` behavior in interactive mode | Would require architectural changes to stdin handling; deferred |
| Unified report CSV (JSONL + interactive in one file) | Data shapes are incompatible; separate files are the right approach |
| True cold-start (process restart between experiments) | Would require Lemonade Server restart; too slow for automated runs. Current approach (model reload) is the practical approximation. |
