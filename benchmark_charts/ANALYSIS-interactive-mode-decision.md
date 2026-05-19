# Analysis: Interactive Mode, Full Mode, and `--force-llm`

> **Date:** 2026-05-18
> **Branch:** `feat/email-bench-visualizations`
> **Data source:** `stratified_1000.jsonl` (`C:\Users\antmi\Downloads\stratified_1000.jsonl`)
> **Method:** 3-agent analysis cycle (planning, program management, quality review)

---

## 1. What `--mode full` Actually Does ("One-Shot Triage")

### Flow

```
agent.process_query("Triage my inbox ({limit} emails)")
  └─ Step 1: LLM planning call → decides to call triage_inbox tool
  └─ Step 2: triage_inbox(max_messages=limit)
       └─ Pure Python loop — ZERO LLM calls
       └─ For each email: classify_category_heuristic(subject, from, labels)
       └─ Returns: [{id, subject, from, category, confident, is_spam, is_phishing, rationale}]
  └─ Step 3+: For emails with confident=False, agent MAY call get_message to read body
  └─ Step N: Summary generation
```

"One-shot" means one `process_query()` call. The agent's internal planning loop then makes **1 + N + 1** LLM calls:
- **1** planning call (decides to call triage_inbox)
- **N** re-classification calls (one per escalated email where `confident=False`)
- **1** summary call

### What `--force-llm` Does

At `read_tools.py:206-208`:
```python
if force_llm and heuristic.confident:
    heuristic.confident = False
    heuristic.reason = f"forced LLM bypass (was: {heuristic.reason})"
```

With `--force-llm=True`, every email is marked `confident=False`. The intent is to force LLM re-classification of every email.

### Critical Finding: The Agent Has No Instruction to Re-Classify

**The system prompt (`agent.py:72-112`) contains no instruction telling the agent to fetch and re-classify `confident=False` emails.** This gap was already documented in `TRIAGE-METHODOLOGY.md:47`:

> "The system prompt never instructs the agent what to do when `confident=False`. There is no explicit instruction to re-classify those emails, and no shared category vocabulary for the LLM to use."

**Empirical data** from prior runs shows 100% of emails were classified as `confident=True` in full mode — the LLM made **zero** per-email classification calls. The token cost came entirely from planning + summary.

**Consequence:** `--force-llm=True` changes the `confident` label in the output, but does **not guarantee** the LLM actually fetches bodies and re-classifies. Whether it does depends entirely on the agent's autonomous planning behavior, which is non-deterministic and model-dependent.

**Batched mode bypasses this issue entirely.** Since `_process_single_batch()` sends all emails in a single combined prompt with explicit classification instructions (not relying on the agent's autonomous planning), the LLM classifies every email directly. There is no `confident=False` -> `get_message` -> re-classify chain. This makes batched mode more deterministic for benchmarking but means every email incurs LLM cost regardless of heuristic confidence.

### Recommendation for `--force-llm`

| Setting | What it measures | When to use |
|---------|-----------------|-------------|
| `--force-llm=False` (default) | Real-world hybrid performance (heuristic + LLM) | Primary benchmark — this is what users experience |
| `--force-llm=True` | All emails marked `confident=False`; LLM *may* follow up | Labeling change only unless system prompt is updated |

**To make `--force-llm=True` meaningful**, add a system prompt instruction:
> "For emails where `confident=False`, call `get_message` to read the body and re-classify using these categories: urgent, actionable, informational, low priority."

Without this, `force_llm` is a data-label change, not a behavioral change.

---

## 2. Context Overflow Issue — Is It Still Relevant?

### Original Issue (2026-05-13)

84K tokens from 10 MBOX promotional emails vs 32K context window. Failure on turn 4 of interactive session.

### Root Cause Re-Analysis

**The `triage_inbox` tool result does NOT include email bodies.** At `read_tools.py:215-225`, each result entry contains only:

| Field | Size (bytes) |
|-------|-------------|
| `id` | ~16 |
| `thread_id` | ~16 |
| `subject` | ~50 |
| `from` | ~40 |
| `category` | ~10 |
| `is_spam` / `is_phishing` / `confident` | ~5 each |
| `rationale` | ~40 |
| **Total per entry** | **~200** |

The tool fetches full messages internally via `gmail.get_message()` but only extracts headers — bodies are never sent to the LLM in the triage result.

### But `get_message` DOES Send Bodies to the LLM

When the agent calls `get_message` for emails, the full body IS sent to the LLM via `_format_message_for_llm()`. The truncation limit (`DEFAULT_BODY_LIMIT_CHARS = 4000`) was **removed** as part of the batched mode implementation — bodies are now sent in full. Batch size controls context instead.

**NOTE:** `DEFAULT_BODY_LIMIT_CHARS`, `_truncate()`, and `body_truncated` were deleted from `read_tools.py`. Full email bodies are passed through with untrusted-input delimiters (`wrap_untrusted_body()`).

### MBOX vs JSONL: Body Size Comparison

| Aspect | MBOX (`load_mbox`) | JSONL (`load_jsonl`) |
|--------|-------------------|---------------------|
| Body source | Full MIME tree via `_walk_mime_to_payload` (line 125) | `body_preview` field only (~200 chars) |
| Body content | Complete HTML with tracking URLs, CSS, unsubscribe footers | Plain text preview |
| Per-email body in store | 5K-10K tokens (full HTML) | ~50-100 tokens (preview) |
| Body sent via `get_message` | Up to 4000 chars truncated (≈1000 tokens) | Up to 4000 chars (but body_preview is only ~200 chars) |

### Context Size Estimates: MBOX vs JSONL

**Triage result (sent to LLM in tool output):**

| Data source | `--limit` | Triage result (est.) | Tokens (est.) |
|-------------|-----------|---------------------|---------------|
| JSONL | 100 | ~20 KB | ~5K |
| JSONL | 200 | ~40 KB | ~10K |
| JSONL | 500 | ~100 KB | ~25K |
| JSONL | 1000 | ~200 KB | ~54K |
| MBOX | 100 | ~20 KB | ~5K |
| MBOX | 200 | ~40 KB | ~10K |
| MBOX | 500 | ~100 KB | ~25K |
| MBOX | 1000 | ~200 KB | ~54K |

The triage result size is the same for both — header-only, no bodies.

**Escalated email bodies (sent via `get_message` when agent calls it):**

| Data source | `--limit` | Escalated emails | Body tokens (est.) |
|-------------|-----------|-----------------|-------------------|
| JSONL | 100 | 0 (no system prompt to re-classify) | 0 |
| JSONL | 100 | 30 (if force_llm=True + agent follows up) | ~3K (200 chars each) |
| MBOX | 100 | 0 (no system prompt to re-classify) | 0 |
| MBOX | 100 | 30 (if force_llm=True + agent follows up) | ~30K (1000 tokens each) |
| MBOX | 1000 | 100 (if force_llm=True + agent follows up) | ~100K (1000 tokens each) |

**Critical:** With MBOX at `--limit 1000` and `--force-llm=True`, if the agent follows up on even 30 emails: 30 × 1000 = 30K tokens from bodies alone — **already at the 32K limit** before counting the triage result (5K), system prompt (3K), and conversation history.

### The Real Overflow Risk: Two Sources

**Source 1: Triage result dict at high limits**
- At `--limit 1000`: ~54K tokens for the triage JSON alone → **guaranteed overflow at 32K** regardless of data source.

**Source 2: `get_message` body accumulation (MBOX only)**
- Each escalated email via `get_message` adds ~1000 tokens of HTML body (truncated to 4000 chars).
- At `--limit 100` with 30 escalated: ~30K tokens → **near or at 32K limit**.
- JSONL is safe here because body_preview is only ~200 chars per email.

**Source 3: Conversation history accumulation (interactive mode)**
- Dominant across turns: assistant reasoning/thinking blocks.

| Turn | What the LLM sees |
|------|-------------------|
| Turn 1 | System prompt + user prompt + assistant reasoning + triage tool result |
| Turn 2 | All of Turn 1 + new user prompt + assistant reasoning + archive tool result |
| Turn 3 | All of Turns 1-2 + new user prompt + assistant reasoning + star tool result |
| Turn 4 | All of Turns 1-3 + new user prompt + assistant reasoning + summary tool result |

### Verdict

| Data source | Limit | Mode | Overflow risk with 32K context |
|-------------|-------|------|-------------------------------|
| JSONL (`stratified_1000.jsonl`) | 100 | full | **Low** — triage ~5K, no bodies sent |
| JSONL | 100 | interactive | **Low** — same, plus small conversation history |
| JSONL | 200 | full | **Low-Moderate** — triage ~10K |
| JSONL | 500 | full | **High** — triage ~25K, near limit |
| JSONL | 1000 | any | **Certain** — triage ~54K > 32K |
| MBOX | 10 | interactive | **High** — per original ISSUE: 84K tokens |
| MBOX | 50 | full | **High** — full HTML bodies in store, `get_message` returns large payloads |
| MBOX | 100 | full | **Certain** — 100 × 5-10K bodies in store; `get_message` at 4K truncation × 30 emails = 30K+ |

**The ISSUE doc remains fully valid for MBOX data.** The context overflow risk is real and significant. The triage tool itself is header-light, but the MBOX payloads are loaded into the FakeGmailBackend store with full HTML bodies, and `get_message` returns them (truncated to 4000 chars) to the LLM. With enough emails, overflow is guaranteed.

**For JSONL data at `--limit 100-200`: the risk is minimal.** The body_preview is only ~200 chars, and the triage result is header-only.

---

## 3. Merging Full-Mode Data Into Interactive Mode

### Current Gap

Both modes call the same `triage_inbox` tool, which returns `confident` per email. But:

| Mode | What `_extract_actions()` captures |
|------|-----------------------------------|
| Full | All fields via `extract_from_agent_result()` → `EmailResult` objects |
| Interactive | Only `category` → `state.triaged_emails[id] = category` — **`confident` is discarded** |

### The Fix: ~15-20 Lines Across 2 Files

#### Change 1: `runner.py:611` — Capture `confident` (1 line → 3 lines)

```python
# BEFORE:
state.triaged_emails[item["id"]] = item.get("category", "unknown")

# AFTER:
email_id = item["id"]
state.triaged_emails[email_id] = {
    "category": item.get("category", "unknown"),
    "confident": item.get("confident", False),
}
```

#### Change 2: `runner.py:658-660` — Fix print loop (was string, now dict)

```python
# BEFORE:
cats = {}
for cat in state.triaged_emails.values():
    cats[cat] = cats.get(cat, 0) + 1

# AFTER:
cats = {}
for entry in state.triaged_emails.values():
    cat = entry["category"] if isinstance(entry, dict) else entry
    cats[cat] = cats.get(cat, 0) + 1
```

#### Change 3: `visualize.py` — Add fallback to `_count_confident()` (~8 lines)

```python
# After the existing batch_results loop in _count_confident():
if total == 0:
    triaged = run.get("session_state", {}).get("triaged", {})
    for entry in triaged.values():
        total += 1
        if isinstance(entry, dict) and entry.get("confident", False):
            confident += 1
```

### After the Fix: Interactive Output Shape

```json
{
  "session_state": {
    "triaged": {
      "email_id_1": {"category": "informational", "confident": true},
      "email_id_2": {"category": "urgent", "confident": false}
    }
  }
}
```

This makes `_count_confident()` usable for interactive data, enabling heuristic-based charts.

---

## 4. Chart Feasibility Matrix (Charts 24-29)

| Chart | Full-mode JSONL | Interactive | Interactive (after fix) | **Batched Mode** | Additional data needed |
|-------|----------------|-------------|------------------------|-----------------|----------------------|
| **24 - Planning Steps Heatmap** | YES | NO | NO | **YES** (uses `estimated_steps`) | Multi-run at varying limits |
| **25 - Tokens per Email** | YES | NO | PARTIALLY | **YES** (approximated tokens) | Per-email token attribution |
| **26 - Duration vs Heuristic** | YES | NO | PARTIALLY | **YES** | Turn 1 duration mapping |
| **27 - Interactive LLM Activity** | N/A | YES | YES | **YES** (new batched variant) | Already works |
| **28 - Model Performance Radar** | YES | NO | PARTIALLY | **YES** (uses `estimated_steps`) | Multi-run for CV% axis |
| **29 - Steps Scaling Heatmap** | YES | NO | NO | **YES** (batch count) | Multi-run at varying limits |

### Key Insight

Charts 24 and 29 are **multi-run, multi-model comparison charts**. A single interactive session JSON is one data point — it cannot produce a heatmap. The question is not whether interactive mode captures `confident` data; it is whether interactive mode produces the right **shape** of data for these charts.

Charts 25, 26, and 28 need `confident` counts. The ~15-line fix enables them partially for interactive data.

Chart 27 already works with existing interactive data.

---

## 5. Recommended Action Sequence

### Immediate (No Code Changes)

```bash
# Run full-mode benchmark with stratified_1000.jsonl
gaia email bench \
  --jsonl-path "C:\Users\antmi\Downloads\stratified_1000.jsonl" \
  --mode full \
  --models "<model-id>" \
  --limit 100 \
  --experiments-per-model 3

# Generate charts
gaia email report --input-dir benchmark_results --charts
```

This produces Charts 24-29 from full-mode JSONL data. No code changes needed.

### Quick Win (After 15-line fix)

```bash
# Run interactive benchmark
gaia email bench \
  --jsonl-path "C:\Users\antmi\Downloads\stratified_1000.jsonl" \
  --mode interactive \
  --model "<model-id>" \
  --limit 100

# Regenerate charts — Chart 27 + partial 25/26/28
gaia email report --input-dir benchmark_results --charts
```

### Multi-Limit Scaling (For Charts 24 and 29)

Repeat full-mode runs at different limits to populate the heatmap Y-axis:

```bash
gaia email bench --jsonl-path stratified_1000.jsonl --mode full --models "<model>" --limit 50  --experiments-per-model 3
gaia email bench --jsonl-path stratified_1000.jsonl --mode full --models "<model>" --limit 100 --experiments-per-model 3
gaia email bench --jsonl-path stratified_1000.jsonl --mode full --models "<model>" --limit 200 --experiments-per-model 3
```

---

## 6. Files Modified by the Confident Capture Fix

| File | Lines | Change |
|------|-------|--------|
| `src/gaia/agents/email/bench/runner.py` | 611 | Store `{category, confident}` dict |
| `src/gaia/agents/email/bench/runner.py` | 658-663 | Print loop handles dict-or-string |
| `src/gaia/agents/email/bench/visualize.py` | ~104 | `_count_confident()` fallback |

Total: ~15 lines across 2 files. Zero risk to existing charts — additive only.

---

## 7. Quality Review Findings

### What Both Agents Got Wrong

1. **Neither verified that the LLM actually follows up on `confident=False` emails.** The `TRIAGE-METHODOLOGY.md` already documents that the system prompt has no category taxonomy and no instruction to re-classify. `--force-llm=True` changes labels but may not change behavior.

2. **Both underestimated the change scope.** The `_print_session_state()` function will produce garbled output if `triaged_emails` values change from strings to dicts. Actual change is ~15-20 lines, not 7.

3. **Neither identified reasoning-block accumulation as the primary overflow risk.** Assistant thinking blocks are the dominant context consumer across turns, not the triage result size.

### Dissenting Opinion from Quality Reviewer

The quality reviewer disagrees with deferring the confident capture fix as "future work." At 15 lines, the scope impact is negligible. The fix should be done in the same PR as the interactive benchmark run. The chart implementations for interactive variants (24i, 25i, 29i) can wait — but the data capture should happen now.

---

## 8. Summary

| Question | Answer |
|----------|--------|
| Does `--force-llm` play a big role? | It changes the `confident` label in output but may not change agent behavior. The system prompt lacks instructions to re-classify `confident=False` emails. |
| Is `--mode` necessary? | Yes. Full and interactive produce structurally incompatible data answering different questions. |
| Is context overflow still relevant? | **For JSONL at `--limit 100-200`: no.** Body_preview is ~200 chars, triage is header-only. **For MBOX: yes, absolutely.** Full HTML bodies loaded into store; `get_message` returns up to 4000 chars per escalated email. At `--limit 100` with 30 escalated = ~30K tokens from bodies alone. At `--limit 1000` any source: ~54K tokens from triage result alone. |
| Should we merge full-mode data into interactive? | Yes — 15-line fix. Enables partial support for Charts 25/26/28 from interactive data. |
| Do charts 24-29 make more sense with interactive? | No. Charts 24/29 need multi-run data. Charts 25/26/28 need `confident` which the fix enables. Chart 27 already uses interactive data. |
