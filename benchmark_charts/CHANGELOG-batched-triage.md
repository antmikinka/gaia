# Changelog: Batched Email Triage Implementation

**Date:** 2026-05-18
**Branch:** `feat/email-bench-visualizations`
**Author:** Anthony Mikinka

---

## Summary

Implemented batched email triage architecture to eliminate body truncation while preventing context overflow. Emails are processed in batches of 5 with fresh LLM context per batch; results persist in SQLite between batches.

---

## Changes by File

### `src/gaia/agents/email/config.py`
- Added `batch_size: int = 5` to `EmailAgentConfig` dataclass.
- Added `enable_batched_mode: bool = False` to `EmailAgentConfig` dataclass.

### `src/gaia/agents/email/bench/data_shapes.py`
- Added `llm_summary: str = ""` field to `EmailResult` dataclass.
- Added new `BatchResult` dataclass with fields: `batch_number`, `batch_size`, `total_batches`, `email_results`, `duration_ms`, `total_input_tokens`, `total_output_tokens`, `total_reasoning_tokens`, `total_tokens`, `avg_time_to_first_token_ms`, `avg_tokens_per_second`, `categories`, `status`, `error`.

### `src/gaia/agents/email/action_store.py`
- Added `EMAIL_TRIAGE_RESULTS_DDL` schema with `email_triage_results` table (11 columns: `triage_id`, `run_id`, `batch_number`, `email_id`, `thread_id`, `category`, `confident`, `llm_summary`, `body_preview`, `token_count`, `duration_secs`, `created_at`).
- Added indexes on `run_id` and `email_id`.
- Added `init_triage_schema()` helper for idempotent table creation.
- Added `record_triage_result()` — persists a single email's triage result.
- Added `fetch_triage_results()` — retrieves all results for a given `run_id`.
- Updated `init_schema()` to call `init_triage_schema()`.
- Updated `__all__` exports.

### `src/gaia/agents/email/tools/read_tools.py`
- Removed `DEFAULT_BODY_LIMIT_CHARS = 4000` constant.
- Removed `_truncate()` helper function.
- Removed `body_truncated` tracking from `_format_message_for_llm()`.
- Full email body now passed through unchanged (still wrapped in `<<<UNTRUSTED_EMAIL_BODY_*>>>` delimiters).

### `src/gaia/agents/email/agent.py`
- Added `process_batched_triage(max_messages=25)` — main entry point for batched flow. Generates unique `run_id`, splits heuristic triage results into batches, orchestrates processing, returns JSON summary.
- Added `_process_single_batch(batch, batch_number, run_id)` — classifies and summarizes a single batch of emails via LLM. Fetches full message bodies, sends classification prompt, parses JSON response, stores result in SQLite. Includes error handling per email (fetch failure, LLM failure, parse failure).
- Added `_produce_final_summary(run_id)` — reads all stored results from SQLite, aggregates category counts, duration, tokens, and per-email summaries. Returns summary dict.
- `force_llm=False` hardcoded in batched mode (heuristic-first path always used).

### `src/gaia/agents/email/bench/runner.py`
- Added `_run_batched_agent()` function — instantiates `EmailTriageAgent` with `enable_batched_mode=True`, calls `process_batched_triage()`, reads back SQLite results, constructs `RunResult` with `batch_results[]`.
- Imports `BatchResult`, `EmailResult`, `fetch_triage_results` from respective modules.

---

## Test Results Summary

| Area | Status | Notes |
|------|--------|-------|
| Body truncation removal | Verified | `_format_message_for_llm()` passes full body; no truncation constants remain |
| Config fields | Verified | `batch_size=5`, `enable_batched_mode=False` present in dataclass |
| SQLite schema | Verified | `email_triage_results` table DDL correct; indexes on `run_id`, `email_id` |
| Triaged result helpers | Verified | `record_triage_result()` and `fetch_triage_results()` wired to `init_triage_schema()` |
| Batched triage methods | Verified | All three methods present in `EmailTriageAgent` |
| Benchmark runner | Verified | `_run_batched_agent()` returns `RunResult` with correct shape |
| CLI flag + dispatch | Verified | `--batched` flag wired in `cli.py` and `bench_runner.py`; outputs to `results_<model>_batched.jsonl` |
| Progress reporting | Verified | `print(f"Processing batch N of M...")` in batch loop |
| No breaking changes | Verified | Existing `full` mode and `interactive` mode unchanged |

---

## Known Limitations

1. **No token budget enforcement** — `token_budget_per_batch` from the plan was not implemented. Batch size of 5 is a fixed guard. Very large MBOX emails (>10K tokens each) could still approach context limits.
2. **No SQLite cleanup** — Triage results persist indefinitely in `state.db`. Old runs accumulate and must be pruned manually.
3. **`force_llm=False` is hardcoded in batched mode** — Batched triage always uses heuristic-first classification. Benchmarking pure LLM classification in batched mode requires a separate code path.
4. **`--force-llm` flag accepted but ignored** — The `--force-llm` CLI flag is parsed but has no effect in batched mode; no warning is emitted.
5. **Subject/sender not populated in `EmailResult`** — The `_run_batched_agent()` constructor passes empty strings for `subject` and `sender` when building `EmailResult` from SQLite rows.
6. **Only single model per run** — Batched mode does not support `--experiments-per-model` or `--models` multi-model runs.

---

## Future Work

- Implement `token_budget_per_batch` with dynamic batch size reduction.
- Add SQLite cleanup function (e.g., `cleanup_triage_results(older_than_days=30)`).
- Add `force_llm` support in batched mode for pure LLM benchmarking.
- Populate `subject`/`sender` fields in batched `EmailResult` from heuristic triage data.
- Add warning when `--force-llm` is used with `--batched` (flag is currently silently ignored).
- Support multi-model runs and `--experiments-per-model` in batched mode.
- Consider parallel batch processing with multiple Lemonade model slots.
