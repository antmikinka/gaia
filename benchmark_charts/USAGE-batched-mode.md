# Usage Guide: Email Benchmark Modes

> **Date:** 2026-05-18
> **Branch:** `feat/email-bench-visualizations`

## 1. Mode Comparison

| Aspect | Full Mode | Interactive Mode | Batched Mode |
|--------|-----------|------------------|--------------|
| CLI flag | `--mode full` (default) | `--mode interactive` | `--batched` |
| Body truncation | Full body (no truncation) | Full body (no truncation) | Full body, no truncation |
| Context management | Single agent session | Single multi-turn session | Fresh prompt per batch (no context accumulation) |
| `--force-llm` support | Yes | Yes | No (hardcoded `False`) |
| Multi-model runs | Yes (`--models` + `--experiments-per-model`) | No (single model) | No (single model) |
| Output format | `results_<model>.jsonl` | `interactive_<model>_<id>.json` | `results_<model>_batched.jsonl` |
| SQLite persistence | No | No | Yes (`email_triage_results` table) |
| Progress output | Per-experiment | Per-turn | Per-batch ("Processing batch N of M...") |
| Best for | Baseline performance, model comparison | Multi-turn conversation analysis | Large inbox triage with full context |

## 2. Full Mode (Default)

The standard benchmark mode. Processes all emails through a single agent session with heuristic-first classification and optional LLM escalation.

```bash
gaia email bench \
  --jsonl-path /path/to/stratified_1000.jsonl \
  --model <model-id> \
  --limit 100 \
  --experiments-per-model 3
```

Use `--force-llm` to mark all emails as `confident=False` (note: actual LLM re-classification depends on agent behavior).

## 3. Interactive Mode

Simulates a real user conversation across multiple turns. Retains context between turns.

```bash
gaia email bench \
  --jsonl-path /path/to/stratified_1000.jsonl \
  --mode interactive \
  --model <model-id> \
  --limit 100
```

## 4. Batched Mode

Processes all emails in batches with a single LLM call per batch. All emails in a batch are sent together in one combined prompt; the LLM responds with a JSON array of classifications. The same agent instance is reused across batches, but each batch sends a fresh prompt via `send_messages()` which does not accumulate conversation history — the LLM sees only the emails in the current batch. Full email bodies are sent without truncation. Results persist in SQLite. Default batch size is 5, configurable via `--batch-size`.

```bash
gaia email bench \
  --jsonl-path /path/to/stratified_1000.jsonl \
  --batched \
  --model <model-id> \
  --limit 100

# Custom batch size (e.g., 10 for JSONL data with small body_preview)
gaia email bench \
  --jsonl-path /path/to/stratified_1000.jsonl \
  --batched \
  --batch-size 10 \
  --model <model-id> \
  --limit 100
```

### Key Behaviors

- **Batch size:** Default 5, configurable via `--batch-size <N>` CLI flag
- **Progress output:** `Processing batch N of M...` printed for each batch
- **`--force-llm` is ignored:** Batched mode always uses heuristic-first classification
- **Output file:** `results_<model-slug>_batched.jsonl` in the output directory
- **SQLite:** Results stored in `email_triage_results` table; not auto-cleaned
- **All emails processed:** Unlike the original plan (which targeted only `confident=False` emails), batched mode sends ALL emails through the LLM classification prompt
- **No context accumulation:** Each batch's `send_messages()` call sends only that batch's emails — prior batch results are not included in the LLM context. Results are isolated per batch, accumulated only in SQLite

### When to Use Batched Mode

1. **Accuracy benchmarking** — full email bodies provide complete context for classification
2. **Large inbox testing** — avoids context overflow by processing in chunks
3. **Per-email LLM summary analysis** — each email gets an LLM-generated summary stored in `llm_summary` field

### When NOT to Use Batched Mode

1. **Multi-model comparison** — batched mode only supports one model per run
2. **Repeat experiments** — no `--experiments-per-model` support
3. **Quick baseline runs** — full mode is faster and sufficient for most comparisons

### Chart Compatibility

Batched mode produces data compatible with Charts 24-29, with mode-specific handling:

| Chart | Support | Notes |
|-------|---------|-------|
| 24 - Planning Steps Heatmap | YES | Uses `estimated_steps` field (one LLM call per batch + summary) |
| 25 - Tokens per Email | YES | Per-email `token_count` stored (character-length approximation) |
| 26 - Duration vs Heuristic | YES | `duration_secs` per email stored |
| 27 - Interactive LLM Activity | YES (variant) | New `27_batched_llm_activity` chart shows batch processing timeline |
| 28 - Model Performance Radar | YES | Uses `estimated_steps` for step count axis |
| 29 - Steps Scaling Heatmap | YES | Batch count + step data available |

### Known Limitations

1. **Token counts are approximated** — `token_count` per email is calculated as `len(prompt) // 4`, not measured from the LLM provider.
2. **No output token tracking** — `total_output_tokens` is always 0 in batched mode. All consumption is attributed to input tokens.
3. **`--force-llm` is silently ignored** — The flag is accepted but has no effect; no warning is emitted.

## 5. SQLite Schema Reference

The `email_triage_results` table (created automatically in batched mode):

| Column | Type | Description |
|--------|------|-------------|
| `triage_id` | TEXT | Primary key, unique per row |
| `run_id` | TEXT | Benchmark run identifier |
| `batch_number` | INTEGER | Batch sequence number (1-based) |
| `email_id` | TEXT | Original email identifier |
| `thread_id` | TEXT | Thread ID (nullable) |
| `category` | TEXT | Classification: urgent, actionable, informational, low priority |
| `confident` | BOOLEAN | Whether classification was confident |
| `llm_summary` | TEXT | LLM-generated email summary |
| `body_preview` | TEXT | Body preview (may be empty for JSONL data) |
| `token_count` | INTEGER | Tokens consumed for this email |
| `duration_secs` | REAL | Processing time in seconds |
| `created_at` | REAL | Unix timestamp |

Indexes on `(run_id)` and `(email_id)`.
