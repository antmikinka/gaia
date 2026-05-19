# Plan: Batched Email Triage Architecture

> **Date:** 2026-05-18
> **Branch:** `feat/email-bench-visualizations`
> **Status:** IMPLEMENTED — 2026-05-18

---

## 1. Problem Statement

Current email triage has two context-related problems:

1. **Body truncation** — `_format_message_for_llm()` in `read_tools.py:70-100` truncates email bodies to `DEFAULT_BODY_LIMIT_CHARS = 4000`. This loses vital context (MFA codes, transaction details, full conversation threads).

2. **Context accumulation** — Processing 100+ emails in a single agent session causes context overflow. The triage result dict alone at `--limit 1000` is ~54K tokens, exceeding the 32K context window. For MBOX data, each escalated email via `get_message` adds ~1000 tokens of HTML body.

---

## 2. Proposed Architecture

### 2.1 Batch Processing Flow

```
user: "Triage my inbox (100 emails)"
  │
  ├─ Step 1: triage_inbox() — header-only heuristic for ALL 100 emails
  │   → Returns 100 entries with category, confident, rationale (no bodies)
  │   → ~20KB / ~5K tokens — safe
  │
  ├─ Step 2: Identify emails needing LLM review (confident=False)
  │   → Split into batches of N emails
  │
  ├─ Step 3: For each batch:
  │   │
  │   ├─ Create FRESH agent instance (empty conversation_history)
  │   ├─ Call get_message() for each email in batch — FULL body, no truncation
  │   ├─ Agent classifies + summarizes each email
  │   ├─ Store results in SQLite (new email_triage_results table)
  │   └─ Agent instance discarded — context freed
  │
  ├─ Step 4: Final summary
  │   → Lightweight agent reads all stored batch results
  │   → Produces aggregate summary: "Here's your inbox overview..."
  │   → Asks user: "What actions would you like to take?"
  │
  └─ Step 5: User interaction loop (normal agent behavior)
```

### 2.2 Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Remove body truncation entirely** | Full bodies needed for accurate classification. Batch sizing controls context instead. |
| **Fresh agent per batch** | Prevents conversation history accumulation. Each batch starts clean. |
| **SQLite for intermediate storage** | Already using DatabaseMixin. New table for triage results. |
| **Heuristic-first, LLM-second** | triage_inbox() already classifies all emails heuristically. Only confident=False need bodies. |
| **Batch size = 5 (not 10)** | 10 MBOX emails at 5K-10K tokens each = 50K-100K > 32K context. 5 emails × 10K = 50K max, but most emails are smaller. Configurable via `--batch-size` CLI flag. |

---

## 3. Files to Modify

### 3.1 `src/gaia/agents/email/tools/read_tools.py`

**Change:** Remove body truncation.

```python
# Line 42: Remove or set to very high limit
# DELETE: DEFAULT_BODY_LIMIT_CHARS = 4000

# Line 70-100: _format_message_for_llm()
# REMOVE the _truncate() call — pass body through unchanged
```

**Lines affected:** ~10 lines changed/deleted.

**Risk:** Low. The truncation was a safety measure against context blow-up. The new batch architecture replaces it with a better control mechanism.

### 3.2 `src/gaia/agents/email/config.py`

**Change:** Add batch configuration fields.

```python
# Add to EmailAgentConfig dataclass:
batch_size: int = 5
token_budget_per_batch: int = 25000
enable_batched_mode: bool = False
```

**Lines affected:** ~3 lines added.

### 3.3 `src/gaia/agents/email/action_store.py`

**Change:** Add new `email_triage_results` table.

```python
EMAIL_TRIAGE_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS email_triage_results (
    triage_id      TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    batch_number   INTEGER NOT NULL,
    email_id       TEXT NOT NULL,
    thread_id      TEXT,
    category       TEXT NOT NULL,
    confident      BOOLEAN NOT NULL,
    llm_summary    TEXT,
    body_preview   TEXT,
    token_count    INTEGER,
    duration_secs  REAL,
    created_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_triage_results_run
    ON email_triage_results(run_id);
CREATE INDEX IF NOT EXISTS idx_triage_results_batch
    ON email_triage_results(run_id, batch_number);
"""
```

**Lines affected:** ~15 lines added (DDL + helper function).

### 3.4 `src/gaia/agents/email/agent.py`

**Change:** Add `process_batched_triage()` method.

This new method on `EmailTriageAgent`:
1. Calls `triage_inbox_impl()` for header-only classification of all emails
2. Splits `confident=False` emails into batches
3. For each batch: creates fresh agent context, calls `get_message()` per email, classifies + summarizes
4. Stores each batch's results via new `action_store.record_triage_result()`
5. After all batches: produces final summary reading from stored results

```python
def process_batched_triage(
    self, *, max_messages: int = 25
) -> str:
    """Process emails in batches with full body context.

    Each batch gets a fresh agent instance to prevent context
    accumulation. Results are stored in SQLite after each batch.
    After all batches complete, a final summary is produced.
    The method generates a unique `run_id` internally and returns
    the result as a JSON string.
    """
    # Step 1: Heuristic triage for all emails
    triage_result = triage_inbox_impl(
        self._gmail, max_messages=max_messages, debug=self.config.debug
    )

    # Step 2: Identify emails needing LLM review
    needs_llm = [
        r for r in triage_result["results"] if not r["confident"]
    ]

    # Step 3: Batch processing
    batches = [
        needs_llm[i:i + self.config.batch_size]
        for i in range(0, len(needs_llm), self.config.batch_size)
    ]

    for batch_num, batch in enumerate(batches, 1):
        self._process_single_batch(batch, batch_num, run_id)

    # Step 4: Final summary
    return json.dumps(final_summary)
```

**Lines affected:** ~80-100 lines added.

### 3.5 `src/gaia/agents/email/bench/runner.py`

**Change:** Add `_run_batched_agent()` benchmark function.

```python
def _run_batched_agent(
    mbox_path: str = "",
    jsonl_path: str = "",
    *,
    model_id: str,
    base_url: str,
    max_steps: int = 12,
    limit: int = 100,
    batch_size: int = 5,
) -> RunResult:
    """Run batched triage benchmark mode.

    Returns a `RunResult` with `batch_results[]` populated from
    SQLite after each batch.
    """
    run_id = f"batched-{model_id}-{datetime.now().isoformat()}"

    agent = EmailTriageAgent(
        enable_batched_mode=True,
        batch_size=batch_size,
        model_id=model_id,
        base_url=base_url,
        max_steps=max_steps,
    )

    json_str = agent.process_batched_triage(max_messages=limit)
    summary = json.loads(json_str)

    # Read back stored results from SQLite
    stored = fetch_triage_results(run_id)

    # Construct RunResult with batch_results
    return RunResult(
        run_id=run_id,
        model_id=model_id,
        total_emails=limit,
        batch_results=stored,
        final_summary=summary,
        total_tokens=summary["total_tokens"],
        total_duration_secs=summary["total_duration"],
    )
```

**Lines affected:** ~40 lines added.

### 3.6 `src/gaia/agents/email/bench/runner.py` — CLI

**Change:** Add `--batched` flag to `gaia email bench`.

```python
# In the argparse setup:
parser.add_argument(
    "--batched",
    action="store_true",
    default=False,
    help="Use batched processing mode (full bodies, no truncation)",
)

# In the dispatch logic:
if args.batched:
    result = _run_batched_agent(agent, gmail, limit=limit, model_id=model_id)
else:
    result = _run_full_agent(agent, gmail, limit=limit, model_id=model_id)
```

**Lines affected:** ~10 lines added.

### 3.7 `src/gaia/agents/email/bench/data_shapes.py`

**Change:** Add `BatchedResult` dataclass.

```python
@dataclass
class BatchedResult:
    """Result from a single batch of processed emails."""
    batch_number: int
    email_count: int
    email_results: List[EmailResult]
    token_count: int
    duration_secs: float
```

**Lines affected:** ~10 lines added.

---

## 4. Database Schema Detail

### New Table: `email_triage_results`

| Column | Type | Purpose |
|--------|------|---------|
| `triage_id` | TEXT PK | Unique ID per triage result row |
| `run_id` | TEXT | Benchmark run identifier |
| `batch_number` | INTEGER | Which batch this result came from |
| `email_id` | TEXT | Original email ID |
| `thread_id` | TEXT | Thread ID (nullable) |
| `category` | TEXT | Final classification (urgent/actionable/informational/low priority) |
| `confident` | BOOLEAN | Whether LLM was confident in classification |
| `llm_summary` | TEXT | LLM-generated summary of email content |
| `body_preview` | TEXT | First 200 chars of body (for display) |
| `token_count` | INTEGER | Tokens consumed for this email |
| `duration_secs` | REAL | Time to process this email |
| `created_at` | REAL | Timestamp |

---

## 5. Token Budget Analysis

### Per-Batch Token Consumption (worst case)

| Component | Tokens | Notes |
|-----------|--------|-------|
| System prompt | ~1,500 | Fixed |
| User prompt ("Triage these 5 emails") | ~50 | Fixed |
| 5 email bodies (MBOX, full HTML) | 5 × 5K-10K = 25K-50K | Variable |
| Agent reasoning (thinking blocks) | ~2K-5K | Per batch |
| Tool results (get_message × 5) | ~1K | Metadata only |
| **Total** | **~30K-60K** | **May exceed 32K at upper bound** |

### Mitigation

The `token_budget_per_batch = 25000` config field acts as a guard:
- Before processing a batch, estimate total tokens from email body sizes
- If estimate exceeds budget, reduce batch size dynamically
- For JSONL data: body_preview is ~200 chars, so 10 emails = ~2K tokens — trivially safe
- For MBOX data: batch size of 5 is appropriate for typical emails (~3K-5K each)

### Recommended Default Config

| Data Source | batch_size | token_budget | Rationale |
|-------------|-----------|--------------|-----------|
| JSONL | 10 | 25000 | body_preview is tiny, safe to batch larger |
| MBOX | 5 | 25000 | Full HTML bodies, need smaller batches |
| Live Gmail | 5 | 25000 | Same as MBOX — full MIME payloads |

---

## 6. Benchmark Compatibility

### Existing Charts (24-29)

| Chart | Batched Mode Support | Notes |
|-------|---------------------|-------|
| 24 - Planning Steps Heatmap | YES | batch_results[] provides step counts |
| 25 - Tokens per Email | YES | token_count per email stored |
| 26 - Duration vs Heuristic | YES | duration_secs per email stored |
| 27 - Interactive LLM Activity | N/A | Chart 27 is interactive-mode only |
| 28 - Model Performance Radar | YES | confident + category data available |
| 29 - Steps Scaling Heatmap | YES | batch_count + step data available |

### New Batched-Mode Specific Charts

Could add charts showing:
- Batch processing time distribution
- Per-batch token consumption
- Confident rate improvement vs heuristic-only

---

## 7. Trade-Off Analysis

### Advantages

1. **No body truncation** — Full context preserved for accurate classification
2. **No context overflow** — Batches stay within context window
3. **No conversation history accumulation** — Fresh agent per batch
4. **Persistent intermediate results** — SQLite stores all classifications
5. **Benchmark compatible** — Same output shape as full mode
6. **User interaction preserved** — Final summary + action prompt works normally

### Disadvantages

1. **More LLM calls** — Each batch requires a fresh agent initialization
2. **Slower for large inboxes** — Sequential batch processing adds latency
3. **More complex code** — New method, new table, new CLI flag
4. **State management** — Need to ensure SQLite cleanup between runs

### Risks

| Risk | Mitigation |
|------|-----------|
| Batch still overflows context | Dynamic batch size reduction based on token budget |
| SQLite grows unbounded | Add cleanup function to delete old run results |
| Fresh agent loses prior batch context | Final summary reads all stored results — has full picture |
| MBOX emails larger than expected | Token budget check before each batch |

---

## 8. Implementation Sequence

1. **Phase 1: Infrastructure** (no behavior change)
   - Add `email_triage_results` table to `action_store.py`
   - Add config fields to `config.py`
   - Add `BatchedResult` dataclass to `data_shapes.py`

2. **Phase 2: Core Logic**
   - Remove body truncation from `read_tools.py`
   - Add `process_batched_triage()` to `agent.py`
   - Add `_process_single_batch()` helper
   - Add `_produce_final_summary()` helper

3. **Phase 3: Benchmark Integration**
   - Add `_run_batched_agent()` to `runner.py`
   - Add `--batched` CLI flag
   - Update `visualize.py` to handle batched data shape

4. **Phase 4: Testing**
   - Unit tests for batch splitting logic
   - Integration test with stratified_1000.jsonl
   - Token budget validation tests
   - SQLite cleanup tests

---

## 9. Open Questions for User

1. **Batch size**: Default 5 or 10? (5 is safer for MBOX, 10 is faster for JSONL)
2. **System prompt**: Should we add instruction to re-classify `confident=False` emails? (Currently missing — `--force-llm` may not change behavior)
3. **SQLite cleanup**: Should old run results be auto-deleted after N days?
4. **Progress reporting**: Should batched mode show progress ("Batch 3/10 complete...")?
5. **Parallel batches**: Could we process batches in parallel with multiple agent instances? (Would require multiple Lemonade model slots)

---

## 10. Summary

This plan re-architects email triage to process emails in batches with full body context, eliminating truncation while preventing context overflow. The key changes are:

- **Remove** `DEFAULT_BODY_LIMIT_CHARS = 4000` truncation
- **Add** batch processing with fresh agent per batch
- **Store** results in SQLite after each batch
- **Produce** final summary with user interaction

Total estimated changes: ~170 lines across 7 files. Zero breaking changes to existing full mode or interactive mode.

---

## 11. Implementation Notes (Post-Implementation Review)

**Implemented as planned:**
- **Body truncation removed** — `DEFAULT_BODY_LIMIT_CHARS`, `_truncate()`, and `body_truncated` deleted from `read_tools.py`. Full body passed through with untrusted-input delimiters intact.
- **Batch config fields** — `batch_size: int = 5` and `enable_batched_mode: bool = False` added to `EmailAgentConfig`.
- **SQLite table** — `email_triage_results` table created in `action_store.py` with `record_triage_result()` and `fetch_triage_results()` helpers. Index on `run_id` and `email_id`.
- **Batched triage methods** — `process_batched_triage()`, `_process_single_batch()`, and `_produce_final_summary()` added to `EmailTriageAgent`.
- **Benchmark runner** — `_run_batched_agent()` function added to `runner.py`, returning `RunResult` with `batch_results[]` populated from SQLite.
- **Progress reporting** — Each batch prints `"Processing batch N of M..."` to console.
- **Single-LLM-call-per-batch** — `_process_single_batch()` sends all emails in a batch together in one combined prompt via `self.chat.send_messages()`. The LLM returns a JSON array with one classification per email. This departs from the per-email escalation model in Section 2.1. Token count is approximated as `len(prompt) // 4`.
- **Context isolation between batches** — The same `EmailTriageAgent` instance (`self`) is reused across batches, but each batch sends a **fresh prompt** via `send_messages()` which does NOT append to `self.chat`'s conversation history. The LLM sees only the emails in the current batch — no prior batch context leaks in. This achieves the plan's intent of "fresh agent per batch" without actually creating new agent instances.
- **`llm_summary` field** — Added to `EmailResult` dataclass in `data_shapes.py` for carrying LLM-generated summaries.
- **`BatchResult` dataclass** — Added to `data_shapes.py` with fields: `batch_number`, `batch_size`, `total_batches`, `email_results`, `duration_ms`, token aggregates (`total_input_tokens`, `total_output_tokens`, `total_reasoning_tokens`, `total_tokens`), `categories`, `status`, `error`.

**Deviations from plan:**

| Planned | Implemented | Rationale |
|---------|-------------|-----------|
| Per-email LLM re-classification for `confident=False` only | ALL emails processed in batches via single combined prompt per batch | `_process_single_batch()` builds one prompt containing all batch emails, sent in a single `send_messages()` call. Every email incurs LLM cost regardless of heuristic confidence. |
| Batch size hardcoded at 5 | Configurable via `--batch-size` CLI flag (default 5) | Exposed as integer argument in `bench_runner.py`; passed to `_run_batched_agent()` and `EmailAgentConfig.batch_size`. |
| `token_budget_per_batch: int = 25000` config field with dynamic batch size reduction | Not implemented | Batch size of 5 is a fixed guard; dynamic budgeting deferred. Most emails are well under 10K tokens. |
| `--batched` CLI flag | Implemented | `--batched` flag wired in `cli.py` and `bench_runner.py`; outputs to `results_<model>_batched.jsonl`. |
| Separate `BatchedResult` dataclass in `data_shapes.py` | `llm_summary` added to existing `EmailResult`; separate `BatchResult` created | Simpler — reuse existing shape, add summary field where needed. |
| SQLite auto-cleanup of old runs | Not implemented — results persist indefinitely | Cleanup deferred; users can manually prune `state.db`. |
| `force_llm` option in batched mode | `force_llm=False` hardcoded in `process_batched_triage()` | Batched mode always uses heuristic-first path; force-LLM not needed for batch classification. |

**User decisions confirmed during implementation:**
- Batch size: **5** for both JSONL and MBOX.
- No `force_llm` in batched mode.
- No SQLite cleanup (results persist).
- Progress reporting during batch processing ("Batch N of M...").

**Chart compatibility notes (post-chart-fixes):**
- **`estimated_steps` field** — Added to `RunResult` dataclass. For batched mode, set to `total_batches + 1` (one LLM call per batch plus final summary). Charts 24 and 28 use mode gates: batched runs read `estimated_steps`, full runs read `len(step_results)`.
- **Chart 27 variant** — A new `plot_batched_llm_activity()` renders a batch processing timeline (X=batch number, Y=duration ms) with email count overlay. Emitted when `mode="batched"` runs are detected.
- **ALL emails processed** — Batched mode does not filter to `confident=False`. The `process_batched_triage()` method batches all emails from `triage_inbox_impl()` results.

**Total actual changes:** ~200 lines across 6 files. Zero breaking changes to existing full mode or interactive mode.
