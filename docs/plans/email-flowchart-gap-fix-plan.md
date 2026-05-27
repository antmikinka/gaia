# Implementation Plan: Gap Fixes for `docs/email-agent-pipeline-flowchart.md`

> **Source:** Gap analysis from planning-analysis-v2 agent (20 gaps identified)
> **Target:** `C:\Users\antmi\gaia-visualizations\docs\email-agent-pipeline-flowchart.md`
> **Estimated effort:** 2-3 hours of focused editing

---

## Gap Priority Matrix

| Priority | Gaps | Impact | Effort |
|----------|------|--------|--------|
| CRITICAL | GAP-5, GAP-2 | Wrong chart listing, contradictory batched-mode description | Medium edits |
| HIGH | GAP-1, GAP-3, GAP-6 | Missing source modules, missing 5-step triage detail, missing run ID patterns | Medium edits |
| MEDIUM | GAP-4, 9-11, 7, 8, 12-17 | Missing helper docs, error/output details, cost/quality functions | Targeted edits |
| LOW | GAP-18, 19, 20 | Minor inaccuracies | Quick fixes |

---

## Phase 1: CRITICAL Fixes (Do First)

### Task 1.1: GAP-5 -- Chart Listing Completely Wrong (Section 15)

**Location:** Section 15 "Report Generation", chart list lines 1311-1323, and Section 16 "Output File Lineage" lines 1630-1642

**Problem:** The flowchart lists 10 hardcoded chart names (01-10) that don't match the actual `generate_charts()` function in `visualize.py`, which produces 30+ conditionally-generated charts with dynamic naming (not numbered 01-10).

**Actual chart generation logic** (from `visualize.py:3175-3638`):
- Charts are generated conditionally based on available data and mode
- Single-run charts (1-4, 9, 10) for full/interactive modes
- Variance trend charts (5, 8) when >= 2 runs in JSONL
- Interactive mode charts (6, 7, I2, I3, 27) when interactive path exists
- Multi-model charts (11-14, 17, 18, 22, 24-29) when >= 2 models
- Heuristic vs LLM escalation (always, when runs exist)
- Framework comparison charts (15, 16, 19-21) when ClawFlow present
- File names are descriptive (e.g., `category_distribution_abc123.png`), not numbered
- Chart index is written to `CHARTS.md` dynamically

**Edit type:** **Rewrite** -- replace the hardcoded chart listing block

**Specific changes:**
1. Replace lines 1311-1323 (the 10 numbered charts box) with a description of the conditional chart generation system
2. Replace lines 1630-1642 (the charts directory tree in Output File Lineage) with accurate chart categories
3. Update the "10 PNG visualizations" text at line 1542 to reference conditional generation

**New content structure for chart listing:**
```
9. Generate charts (if --charts):
   Auto-generated based on available data:
   - Single-run: category distribution, token composition, duration histogram,
     token-duration scatter, per-step TTFT/TPS
   - Multi-run (variance): non-determinism trends, category stability
   - Interactive: turn breakdown, token heatmap, LLM activity, context growth, tool calls
   - Multi-model: duration/token comparison, TTFT/TPS, run scatter, cold-start impact,
     planning heatmap, steps scaling, latency heuristic, performance radar
   - Heuristic escalation: stacked bar of heuristic vs LLM classification rate
   - Framework comparison (if ClawFlow): category comparison, architecture radar,
     duration/token by architecture, 4-panel dashboard
   Output: charts-{run_suffix}/ + CHARTS.md index
```

### Task 1.2: GAP-2 -- Batched Mode Heuristic Contradiction (Section 7)

**Location:** Section 7 "Batched Mode", lines 470-574

**Problem:** Two contradictions:
1. Line 485-486 says `triage_inbox_impl()` calls "heuristic classification on ALL emails" but then line 569 states "Every email gets LLM classification (no heuristic skip in pure batched mode)". The actual code at `bench_runner.py:128-137` shows `_run_batched_agent` calls `agent.process_batched_triage()` which internally calls `triage_inbox_impl()` with `force_llm=False` -- meaning the heuristic DOES run, but its results are used only for grouping, not final classification. The LLM then re-classifies everything via `_process_single_batch()`.
2. Missing delimiter stripping detail: the flowchart mentions "strip delimiter wrappers" at line 519 but doesn't explain what those delimiters are.

**Actual behavior** (from `agent.py:653-658`):
- Body extraction strips `<<<UNTRUSTED_EMAIL_BODY_START>>>\n` and `\n<<<UNTRUSTED_EMAIL_BODY_END>>>` delimiters
- Heuristic runs in `triage_inbox_impl` but results are not used as final classification -- LLM reclassifies all emails

**Edit type:** **Targeted edit**

**Specific changes:**
1. Fix line 485-486: Change "Calls heuristic classification on ALL emails" to "Calls triage_inbox_impl() which runs heuristic classification (results used for grouping only, not final output)"
2. Add a new sub-section after line 519 explaining the delimiter stripping:
   ```
   Body extraction strips I1 prompt-injection delimiters:
     body = raw_body
       .replace("<<<UNTRUSTED_EMAIL_BODY_START>>>\n", "")
       .replace("\n<<<UNTRUSTED_EMAIL_BODY_END>>>", "")
   These delimiters wrap email bodies in read_tools to prevent prompt injection.
   ```
3. Clarify line 569: Change to "Every email gets LLM classification via _process_single_batch(). Heuristic from triage_inbox_impl runs but is not used for final classification -- LLM reclassifies all emails."

---

## Phase 2: HIGH Priority Fixes

### Task 2.1: GAP-1 -- Missing Source Module References (Section 2 + Table of Contents)

**Location:** After Section 2 "Subcommand Dispatch", lines 96-132, and Table of Contents lines 7-24

**Problem:** The flowchart references `bench_runner.py`, `runner.py`, `report_generator.py`, and `clawflow_runner.py` but doesn't mention these key modules that are actively used:
- `trace_extractor.py` -- extracts RunResult from agent results (referenced implicitly but not named as source)
- `data_shapes.py` -- defines all dataclasses (RunResult, StepResult, TurnResult, etc.)
- `variance.py` -- statistical analysis (Mann-Whitney U, Cliff's delta, bootstrap CI)
- `output.py` -- CSV/JSON/JSONL formatters, print_summary, cost/quality computation
- `visualize.py` -- chart generation (30+ chart functions)

**Edit type:** **Targeted edit**

**Specific changes:**
1. Add a new "Source Module Map" sub-section after Section 2 (or as a new Section 2b):
   ```
   ### Source Module Map

   | Module | Purpose | Referenced In |
   |--------|---------|---------------|
   | `cli.py` | CLI entry point, arg parsing, subcommand dispatch | Section 1 |
   | `bench_runner.py` | Multi-model loop, mode dispatch, manifest writing | Section 3 |
   | `runner.py` | Agent execution functions, interactive sessions, extraction helpers | Sections 6-10 |
   | `trace_extractor.py` | extract_from_agent_result(), _extract_step_stats(), _find_triage_results | Section 13 |
   | `data_shapes.py` | RunResult, StepResult, TurnResult, EmailResult, BatchResult, SessionState dataclasses | Throughout |
   | `variance.py` | compare_runs(), mann_whitney_u(), cliffs_delta(), bootstrap_ci() | Section 15 |
   | `output.py` | save_jsonl(), print_summary(), to_csv(), _compute_cost(), _compute_quality() | Section 14 |
   | `visualize.py` | generate_charts(), 30+ plot functions | Section 15 |
   | `clawflow_runner.py` | ClawFlow benchmark adapter | Section 2 |
   | `report_generator.py` | Unified report CSV, variance.json, quality.json, statistical tests | Section 15 |
   ```

### Task 2.2: GAP-3 -- Missing process_interactive_smart_triage Detail (Section 9)

**Location:** Section 9 "Interactive Benchmark Mode", lines 653-759, specifically the dispatch block at lines 685-699

**Problem:** The flowchart shows `process_interactive_smart_triage()` as a single box but the actual implementation has 5 distinct steps (from `agent.py:410-561`):
1. Heuristic triage via `triage_inbox_impl()` (0 LLM tokens)
2. Partition into confident vs non-confident
3. Cache confident emails (heuristic-only, zero LLM cost) + record to action_store
4. Filter non-confident through `_should_use_llm()` (respects cross-turn cache)
5. LLM batch pipeline for remaining uncertain emails via `_process_single_batch()`

**Edit type:** **Targeted edit** -- expand the existing box

**Specific changes:**
Replace the dispatch block at lines 685-699 with an expanded version showing the 5 steps:
```
┌─── Smart-mode special: Turn 1 triage prompt ──┐
│ if enable_smart_mode AND turn_num == 1       │
│    AND _is_triage_prompt(prompt):            │
│                                              │
│   agent_result = agent.process_interactive_  │
│     smart_triage(user_prompt, max_messages)  │
│                                              │
│   Inside process_interactive_smart_triage:   │
│     Step 1: triage_inbox_impl()              │
│       → heuristic classification (0 LLM)     │
│     Step 2: split by confident flag          │
│     Step 3: cache confident emails           │
│       → record_triage_result (token_count=0) │
│     Step 4: _should_use_llm() filter         │
│       → skip if prior-turn cache hit         │
│     Step 5: _process_single_batch() loops    │
│       → LLM calls for remaining uncertain    │
│                                              │
│   _sync_session_state_from_smart_result()    │
│   agent.sync_smart_triage_cache(...)         │
│                                              │
│ else:                                        │
│   agent_result = agent.process_query(prompt) │
└──────────────────────────────────────────────┘
```

### Task 2.3: GAP-6 -- Output Directory Run ID Suffix Patterns (Section 14 + Section 16)

**Location:** Section 14 "Output Serialization" lines 1127-1138 and Section 16 "Output File Lineage" lines 1597-1644

**Problem:** The flowchart doesn't document the run ID suffix patterns used in output file naming and chart directory naming.

**Actual patterns** (verified from source):
- `bench_runner.py:145-146`: `results_{run_suffix}_batched.jsonl` where `run_suffix = _extract_run_suffix(result.run_id)`
- `bench_runner.py:203-204`: `results_{run_suffix}_smart.jsonl`
- `bench_runner.py:248-255`: `interactive_{model_slug}_{run_id_suffix}.json`
- `bench_runner.py:415-416`: `run_{run_suffix}.json` (per-run JSON in full mode)
- `visualize.py:3209`: `benchmark_charts-{run_id_suffix}/` or `benchmark_charts/`
- `report_generator.py:541`: `charts-{run_suffix}/` or `charts/`
- `visualize.py:142-152`: `_extract_run_suffix()` extracts the last hex segment from run_id

**Edit type:** **Targeted edit**

**Specific changes:**
1. Add a new sub-section in Section 14 after the output file types table:
   ```
   ### Run ID Suffix Patterns

   Output files embed a run ID suffix extracted via _extract_run_suffix():

   | Output File | Pattern | Source |
   |-------------|---------|--------|
   | Full mode JSONL | `results_{model_slug}.jsonl` | bench_runner.py |
   | Batched mode JSONL | `results_{run_suffix}_batched.jsonl` | bench_runner.py |
   | Smart mode JSONL | `results_{run_suffix}_smart.jsonl` | bench_runner.py |
   | Interactive JSON | `interactive_{model_slug}_{run_suffix}.json` | bench_runner.py |
   | Per-run JSON (full) | `run_{run_suffix}.json` | bench_runner.py |
   | Charts directory | `benchmark_charts-{run_suffix}/` or `benchmark_charts/` | visualize.py |
   | Report charts dir | `charts-{run_suffix}/` or `charts/` | report_generator.py |

   The _extract_run_suffix() function (visualize.py:142) extracts the last
   hex segment from a run_id (e.g., "a1b2c3" from "run-20260527-...-a1b2c3").
   When no suffix is extractable, falls back to model slug or "unknown".
   ```

2. Update the Output File Lineage tree in Section 16 to reflect the actual naming patterns.

---

## Phase 3: MEDIUM Priority Fixes

### Task 3.1: GAP-4 -- Missing _normalize_agent_result() Documentation (Section 13)

**Location:** Section 13 "Result Extraction Pipeline", after line 1043

**Problem:** No documentation of the `_normalize_agent_result()` helper in `runner.py:104-122` which handles the result shape mismatch between `process_smart_triage` (returns JSON string) and `process_query`/`process_interactive_smart_triage` (return dicts).

**Edit type:** **Targeted edit** -- add a small box after the "Three Extraction Functions" header

**New content:**
```
### Result Normalization: _normalize_agent_result()

Before extraction, agent results are normalized to a consistent dict shape:

  process_smart_triage()     → returns JSON string: {"ok": true, "data": {...}}
  process_query()            → returns dict directly
  process_interactive_smart_triage() → returns dict directly

  _normalize_agent_result(agent_result):
    if str: json.loads() → unwrap {"ok": ..., "data": ...} envelope
    if dict: return as-is
    else: raise TypeError

  This ensures downstream extraction code always receives a dict.
  (Risk 5 mitigation: result shape mismatch between smart and full modes)
```

### Task 3.2: GAP-9 -- Missing mark_for_escalation() Three-Path Logic (Section 10)

**Location:** Section 10 "Interactive Session Mode", lines 793-798 (the reclassify command block)

**Problem:** The flowchart shows `mark_for_escalation()` as a single action but the actual implementation has three distinct paths (from `runner.py:81-101`):

1. Email in `state.heuristic_triaged` → pop from heuristic, add to llm_triaged, set force_llm_ids
2. Email in `state.triaged_emails` (but not heuristic) → set force_llm_ids only
3. Email not found → return "not found" message

**Edit type:** **Targeted edit**

**Specific changes:**
Replace the reclassify block at lines 793-798 with:
```
│  │ if "reclassify <email_id>":                     │  │  │
│  │   mark_for_escalation(email_id, state, agent)   │  │  │
│  │   Three paths:                                  │  │  │
│  │   1. In heuristic_triaged:                      │  │  │
│  │      → pop from heuristic, add to llm_triaged   │  │  │
│  │      → set force_llm_ids[email_id]              │  │  │
│  │   2. In triaged_emails (not heuristic):         │  │  │
│  │      → set force_llm_ids[email_id] only         │  │  │
│  │   3. Not found: return "not found" message      │  │  │
```

### Task 3.3: GAP-10 -- Missing _sync_session_state_from_smart_result() Detail (Section 9)

**Location:** Section 9 "Interactive Benchmark Mode", lines 692-693

**Problem:** The flowchart shows `_sync_session_state_from_smart_result()` as a single line but doesn't document what it does. The actual implementation (`runner.py:125-162`) scans the agent's conversation for triage_inbox tool results, parses the JSON envelope, and populates SessionState.heuristic_triaged/llm_triaged/triaged_emails based on the confident flag.

**Edit type:** **Targeted edit**

**Specific changes:**
Add a detail callout after line 693:
```
_sync_session_state_from_smart_result() scans conversation for
triage_inbox tool messages, parses JSON envelope, and for each
result item:
  - state.triaged_emails[eid] = category
  - if confident: state.heuristic_triaged[eid] = category
    + state.llm_calls_saved += 1 (first-time entry only)
  - else: state.llm_triaged[eid] = category
```

### Task 3.4: GAP-11 -- Missing generate_interactive_smart_summary() Detail (Sections 9-10)

**Location:** Section 9 lines 728-737 (summary section) and Section 10 lines 824-825

**Problem:** The flowchart doesn't document the `generate_interactive_smart_summary()` function from `runner.py:165-200` which adds smart-mode keys to the base summary dict.

**Edit type:** **Targeted edit**

**Specific changes:**
Add a callout in Section 9 after the summary block:
```
generate_interactive_smart_summary() (runner.py:165) adds to base summary:
  - heuristic_triaged: dict(state.heuristic_triaged)
  - llm_triaged: dict(state.llm_triaged)
  - heuristic_only_count: len(state.heuristic_triaged)
  - llm_escalated_count: len(state.llm_triaged)
  - heuristic_savings: {
      llm_calls_saved, estimated_tokens_saved,
      estimated_output_tokens_avoided (h_count * 2048),
      saved_percentage (heuristic_est / (heuristic_est + total_tokens))
    }
```

### Task 3.5: GAP-7 -- Missing Multi-Model Loop Error Handling (Section 3)

**Location:** Section 3 "Mode Selection & Dispatch", the multi-model loop box at lines 168-178

**Problem:** The flowchart shows "on exception: write error record, --fail-fast?" but doesn't document the actual error handling pattern from `bench_runner.py:452-484`:
- Error record written to JSONL with `run_id = "error-{model_id}-{experiment}"`
- Error manifest entry written with status="error"
- `model_had_success` flag tracks per-model success
- Warning printed if all experiments for a model fail
- `last_successful_model` tracks the last model that had at least one success

**Edit type:** **Targeted edit**

**Specific changes:**
Expand the error handling line at line 177:
```
│     on exception:                                          │    │
│       error_run_id = "error-{model_id}-{i}"                │    │
│       write error record to results_{slug}.jsonl           │    │
│       write error manifest entry (status="error")          │    │
│       track model_had_success flag                         │    │
│       if --fail-fast: return 1 immediately                 │    │
│     after all experiments:                                 │    │
│       if !model_had_success: WARNING "all experiments failed" │ │
```

### Task 3.6: GAP-8 -- Missing Interactive Mode JSON Output Step (Section 10)

**Location:** Section 10 "Interactive Session Mode", after line 825

**Problem:** The flowchart shows "Return summary dict" but doesn't document that `run_interactive_session()` writes an interactive JSON file (as shown in `bench_runner.py:236-359`). The JSON output includes per_email_classification, session_state, and per-turn data.

**Edit type:** **Targeted edit**

**Specific changes:**
Add after line 825:
```
  6. Write interactive JSON output (bench_runner.py interactive handler):
     output_path = output_dir / "interactive_{model_slug}_{run_suffix}.json"
     JSON includes: run_id, timestamp, model, per-turn data,
     per_email_classification (heuristic vs LLM source),
     session_state (archived, starred, drafted, sent, marked_read, deleted),
     heuristic_savings
     Write manifest entry
```

### Task 3.7: GAP-12 -- Missing Category Validation in _process_single_batch() (Section 7)

**Location:** Section 7 "Batched Mode", the `_process_single_batch()` flow at lines 556-564

**Problem:** The flowchart doesn't show that `_process_single_batch()` validates the category from the LLM response against the allowed set. When the LLM returns an invalid category, it defaults to "informational".

**Edit type:** **Quick fix**

**Specific changes:**
Add a validation note after line 558:
```
    category = result.get("category", "informational")
    # Category validation: must be one of {urgent, actionable,
    #   informational, low priority}; invalid values default to "informational"
```

### Task 3.8: GAP-13 -- Missing print_summary() Console Output Format (Section 14)

**Location:** Section 14 "Output Serialization", after the JSONL/JSON shapes

**Problem:** The flowchart doesn't document the `print_summary()` function from `output.py:395-463` which produces formatted console output with different sections per mode.

**Edit type:** **Targeted edit**

**Specific changes:**
Add a new sub-section in Section 14:
```
### Console Output: print_summary() (output.py)

Human-readable summary printed after each run:
  - Header: mode, run_id, model, provider, mbox_path, emails, duration
  - Heuristic mode: "N/A (heuristic)"
  - Smart mode: heuristic count (zero LLM cost), LLM count, token totals
  - Full mode: token totals, per-step breakdown table (if step_results),
    performance metrics (TTFT, TPS if available)
  - Category distribution: count + percentage per category with openclaw mapping
```

### Task 3.9: GAP-14 -- Missing output.py Module Reference (Section 14 + Source Map)

**Location:** Section 14 header line 1127 and the Source Module Map (from Task 2.1)

**Problem:** Section 14 header says "Output Serialization" but doesn't reference `output.py` as the source module.

**Edit type:** **Quick fix**

**Specific changes:**
Change line 1127 from:
```
## 14. Output Serialization
```
to:
```
## 14. Output Serialization

**File:** `src/gaia/agents/email/bench/output.py`
```

### Task 3.10: GAP-15 -- Missing CSV Output Detail (Section 14)

**Location:** Section 14 "Output Serialization", after the JSONL/JSON shapes

**Problem:** The flowchart doesn't document CSV output generation (`output.py:49-247`) with 45 columns matching openclaw-eval layout.

**Edit type:** **Targeted edit**

**Specific changes:**
Add a CSV output sub-section:
```
### CSV Output (output.py)

to_csv() / save_csv() -- 45 columns matching openclaw-eval layout:
  - Run metadata: run_id, timestamp, model, source_framework, provider
  - Turn data: turn_number, turn_type, role, input/output text
  - Tool data: tool_name, tool_input, tool_output
  - Token data: turn/cumulative/total tokens (in, out, reasoning)
  - Email data: email_id, subject, sender, gaia_category, openclaw_category
  - Quality: is_spam, is_phishing, confident, reason, error
  - Summary row appended after all email rows

to_summary_csv() / save_summary_csv() -- spreadsheet format:
  - 17 metric rows: Email Triage, Model, Cost Per Turn, Quality, etc.
  - Two-column layout for side-by-side comparison
```

### Task 3.11: GAP-16 -- Missing _write_report_manifest() Distinction (Section 15)

**Location:** Section 15 "Report Generation", line 1325

**Problem:** The flowchart says "Write report generation entry to _manifest.json" but doesn't distinguish between the benchmark manifest writer (`bench_runner.py:57-73`) and the report manifest writer (`report_generator.py:35-47`). They have different entry shapes.

**Edit type:** **Targeted edit**

**Specific changes:**
Add a distinction callout:
```
### Manifest Entry Shapes

Benchmark runs (bench_runner._write_generation_manifest):
  {run_id, timestamp, model, experiment?, mode, output_files[],
   total_emails, total_tokens, heuristic_only?, llm_escalated?, status, error?}

Report generation (report_generator._write_report_manifest):
  {timestamp, source_run_ids[], source_jsonl_files[], output_files[],
   total_runs_processed, charts_generated, ground_truth_used?}

Both append to the same _manifest.json file in the output directory.
```

### Task 3.12: GAP-17 -- Missing Quality and Cost Computation Functions (Section 15)

**Location:** Section 15 "Report Generation", after the report pipeline

**Problem:** The flowchart mentions "compute cost, quality, escalation" at line 1286 but doesn't document the actual functions:
- `_compute_run_cost()` in `report_generator.py:126-134`
- `_compute_run_quality()` in `report_generator.py:137-156`
- `_compute_run_escalation()` in `report_generator.py:159-174`
- `_compute_cost()` in `output.py:550-559`
- `_compute_quality()` in `output.py:516-541`

**Edit type:** **Targeted edit**

**Specific changes:**
Add a sub-section:
```
### Cost and Quality Computation

_report_generator.py functions (for report.csv):
  _compute_run_cost(run, cost_per_1m_input, cost_per_1m_output):
    input_cost = total_input_tokens * cost_per_1m_input / 1_000_000
    output_cost = total_output_tokens * cost_per_1m_output / 1_000_000
    Returns 0.0 if both cost params are 0.0

  _compute_run_quality(run, ground_truth):
    Compares batch_results[].email_results[].category against
    ground_truth[email_id].category (case-insensitive match)
    Returns correct / max(total, 1)

  _compute_run_escalation(run):
    Counts confident (heuristic) vs non-confident (LLM) emails
    Returns {heuristic_classified, llm_escalated, llm_escalation_pct}

_output.py functions (for summary CSV):
  _compute_cost(run, cost_per_1m_input, cost_per_1m_output) -- same formula
  _compute_quality(run, ground_truth) -- compares against gt_categories dict
```

---

## Phase 4: LOW Priority Fixes

### Task 4.1: GAP-18 -- Missing Tool Hard Cap Detail (Section 4)

**Location:** Section 4 "Data Loading", the `--limit` Scope box at lines 279-281

**Problem:** The flowchart mentions "Tool hard cap: 100 on triage_inbox, list_inbox, search_messages" but this is a one-liner without context. The actual implementation at `read_tools.py:347` shows `max_messages = max(1, min(int(max_messages or 25), 100))`.

**Edit type:** **Quick fix**

**Specific changes:**
Expand the tool hard cap note:
```
  Tool hard cap: max(1, min(max_messages or 25, 100))
    Applied in triage_inbox, list_inbox, search_messages
    Enforced in read_tools.py:347 via min(..., 100)
    Prevents runaway LLM processing on large inboxes
```

### Task 4.2: GAP-19 -- Missing force_llm_ids Flow in Smart Mode (Section 8)

**Location:** Section 8 "Smart Mode", after the `_should_use_llm()` gate at lines 631-641

**Problem:** The flowchart doesn't show that `force_llm_ids` is checked in `_should_use_llm()` and respected in `process_interactive_smart_triage()`.

**Edit type:** **Quick fix**

**Specific changes:**
Add to the `_should_use_llm()` code block at line 635:
```python
    force_llm_ids = getattr(self.config, "force_llm_ids", None)
    if force_llm_ids and email_id in force_llm_ids:
        return True  # user-requested or admin-forced LLM review
```

And note that `force_llm_ids` is populated by:
- `--force-llm` CLI flag (bypasses heuristic for ALL emails)
- `mark_for_escalation()` in interactive mode (per-email override)

### Task 4.3: GAP-20 -- Planning Insights Script Location (Section 15)

**Location:** Section 15 "Planning Insights Report", line 1333

**Problem:** The flowchart says the planning insights script is at `benchmark_results/0_planning_insights.py`. The actual file is at `benchmark_results/0_planning_insights.py` (which exists) but there's also a newer version at `benchmark_charts/smartinteractive-bencher/v6_planning_analysis.py` and the git status shows `v3_planning_analysis.py` in the smartinteractive-bencher directory.

**Edit type:** **Quick fix**

**Specific changes:**
Change line 1333 from:
```
**File:** `benchmark_results/0_planning_insights.py`
```
to:
```
**File:** `benchmark_results/0_planning_insights.py` (legacy)
  Also: `benchmark_charts/smartinteractive-bencher/v3_planning_analysis.py`
  (evolving analysis scripts; numbering tracks iteration)
```

---

## Execution Order

The phases are ordered to minimize conflicts:

1. **Phase 1 first** -- CRITICAL gaps affect the most-read sections (chart listing, batched mode). These are standalone rewrites that won't conflict with other edits.
2. **Phase 2 second** -- HIGH gaps add new content (source module map, 5-step triage detail, run ID patterns). These are additive and won't conflict.
3. **Phase 3 third** -- MEDIUM gaps are targeted edits scattered across sections. Execute in order (3.1 through 3.12) as they reference each other's line numbers.
4. **Phase 4 last** -- LOW gaps are quick one-liner fixes. Safe to do in any order.

## Conflict Avoidance

- **No conflicts expected** between phases because:
  - Phase 1 edits are rewrites of self-contained blocks
  - Phase 2 adds new sections/sub-sections
  - Phase 3 edits are small insertions in specific locations
  - Phase 4 are line-level tweaks
- **Line number drift:** After each phase, re-read the file to get updated line numbers for subsequent edits. The line references in this plan are based on the current file state.
- **Recommended approach:** Complete one phase, review the file, then proceed to the next.

## Verification Checklist

After all edits, verify:
- [ ] Table of Contents reflects any new sections added
- [ ] All 20 gaps are addressed (trace each GAP-N to an edit)
- [ ] No contradictory statements remain (e.g., batched mode heuristic description is consistent)
- [ ] Chart listing accurately reflects `visualize.py:generate_charts()` behavior
- [ ] Source module map is complete (all .py files in bench/ directory accounted for)
- [ ] Run ID suffix patterns match actual code in bench_runner.py, visualize.py, report_generator.py
- [ ] No broken internal links (all `#section-name` anchors still valid)
- [ ] Code snippets in the flowchart match actual source code
