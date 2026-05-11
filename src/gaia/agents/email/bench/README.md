# GAIA Email Triage Benchmark

Benchmark harness for the GAIA Email Triage Agent. Measures classification accuracy, token consumption, wall-clock latency, and agent behavior across three modes: **heuristic** (no LLM), **full** (single LLM turn), and **interactive** (multi-turn session).

## Quick Reference

| Mode | LLM? | What it measures | Speed |
|------|------|------------------|-------|
| `heuristic` | No | Rule-based classification speed & accuracy | < 1s |
| `full` | Yes | End-to-end triage + summarization tokens | ~30-60s |
| `interactive` | Yes | Multi-turn session: triage → organize → summarize | ~90-180s |

---

## 1. Heuristic Mode (Fast, No LLM)

Classifies emails using only Gmail labels and header heuristics. No LLM involved — zero tokens consumed. Ideal for baseline accuracy and large MBOX files.

```bash
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode heuristic \
  --limit 100 \
  --output-dir benchmark_results
```

**What it measures:**
- Per-email classification (urgent, actionable, informational, low priority)
- Spam/phishing detection
- Wall-clock time for classification
- Category distribution across inbox

**Use cases:**
- Baseline accuracy before adding LLM overhead
- Large MBOX files (thousands of emails)
- Reproducible, deterministic results

---

## 2. Full Mode (Single LLM Turn)

End-to-end agent invocation: the LLM plans the triage, calls `triage_inbox`, and produces a summary. Captures token counts for the entire agent loop.

```bash
gaia email bench --mbox-path "path/to/your.mbox" --mode full --model "Qwen3.5-4B-GGUF" --limit 10 --output-dir benchmark_results_full
```

**What it measures:**
- Everything from heuristic mode, PLUS:
- Total input/output tokens for the LLM round-trip
- Per-step token breakdown (planning call + summary call)
- Wall-clock time including LLM inference

**Per-step output example:**
```
  Per-Step Token Breakdown:
  ──────────────────────────────────────────────────────────────
  Step    Action        Input    Output     Total      Time
    1     llm_call        2500       150      2650       8.2s
    2     llm_call        2400       127      2527       5.1s
  ──────────────────────────────────────────────────────────────
```

**Use cases:**
- Measuring LLM token cost per triage session
- Comparing different models on the same inbox
- Capturing the full agent loop overhead

### Custom LLM server

```bash
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode full \
  --model "Qwen3.5-4B-GGUF" \
  --base-url "http://localhost:13305/api/v1" \
  --limit 10
```

---

## 3. Interactive Mode (Multi-Turn Session)

Simulates a realistic multi-turn email session. The agent retains context across turns, and tokens are tracked per-turn, per-step, and per-email.

```bash
gaia email bench --mbox-path "path/to/your.mbox" --mode interactive --model "Qwen3.5-4B-GGUF" --limit 10 --output-dir benchmark_results_interactive
```

**Default scenario (4 turns):**

| Turn | Prompt | Expected Actions |
|------|--------|-----------------|
| 1 | "Triage my inbox (10 emails)" | Classify all emails |
| 2 | "Archive the low priority emails" | Archive promotional emails |
| 3 | "Star any urgent or actionable messages" | Star important emails |
| 4 | "Show me a summary of what's left in my inbox" | Final summary |

**Per-turn output example:**
```
============================================================
  Turn 1/4
  Prompt: Triage my inbox (10 emails)
============================================================
  Duration: 18.5s
  Tokens:   2,650 (in=2500, out=150)
  Tools:    triage_inbox
  Emails:   10 affected
    Step 1: 2500 in / 150 out / 2650 total / 8.2s

============================================================
  Turn 2/4
  Prompt: Archive the low priority emails
============================================================
  Duration: 12.3s
  Tokens:   1,842 (in=1700, out=142)
  Tools:    archive_message
  Emails:   3 affected
```

**Final summary:**
```
======================================================================
  Interactive Benchmark — Summary
======================================================================
  Run ID:    run-interactive-20260509-...
  Model:     Qwen3.5-4B-GGUF
  Turns:     4
  Duration:  72.4s total
  Tokens:    8,234 total
    Input:   7,800
    Output:  434
  Avg/turn:  2058.5 tokens, 18100.0ms
  Tools:     triage_inbox, archive_message, add_star
  Emails:    10 unique emails affected
======================================================================
```

**Output file:** `interactive.json` with full per-turn, per-step, and per-email action data.

**Use cases:**
- Measuring total token cost of a complete email session
- Tracking which tools the agent calls across turns
- Understanding per-email action history (which emails got archived, starred, etc.)

---

## 4. Variance Analysis (Multiple Iterations)

Run the same benchmark multiple times to measure consistency and variance.

```bash
gaia email bench --mbox-path "path/to/your.mbox" --mode full --model "Qwen3.5-4B-GGUF" --limit 10 --iterations 5 --output-dir benchmark_results
```

**Automatically produces:**
- `results.json` / `results.jsonl` — appended results from all iterations
- `variance.json` — statistical report with mean, stdev, min, max, CV%

**Variance report example:**
```
  Variance Summary (across all runs):
  ──────────────────────────────────────────────────────────────
  total_duration_mins           : μ=      0.70  σ=        0.02  min=    0.67  max=    0.73  CV=  2.9%
  total_input_tokens            : μ=     2500.0  σ=        0.0  min= 2500.0  max= 2500.0  CV=  0.0%
  total_output_tokens           : μ=      150.0  σ=        5.2  min=  142.0  max=  158.0  CV=  3.5%
  total_tokens                  : μ=     2650.0  σ=        5.2  min= 2642.0  max= 2658.0  CV=  0.2%
  total_emails                  : μ=       10.0  σ=        0.0  min=   10.0  max=   10.0  CV=  0.0%
  avg_duration_per_email_mins   : μ=      0.07  σ=        0.00  min=    0.07  max=    0.07  CV=  2.9%
  avg_input_tokens_per_email    : μ=      250.0  σ=        0.0  min=  250.0  max=  250.0  CV=  0.0%
  avg_output_tokens_per_email   : μ=       15.0  σ=        0.5  min=   14.2  max=   15.8  CV=  3.5%
  avg_total_tokens_per_email    : μ=      265.0  σ=        0.5  min=  264.2  max=  265.8  CV=  0.2%
  ```

**Use cases:**
- Measuring LLM output consistency across runs
- Detecting token count drift between model versions
- Validating that results are reproducible

### Variance-only mode (re-analyze existing results)

```bash
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --variance-only \
  --jsonl-path benchmark_results/results.jsonl \
  --output-dir benchmark_results
```

---

## 5. Mode Comparison (Heuristic vs Full)

Diff heuristic and full mode results to see exactly what the LLM adds.

```bash
# Step 1: Run heuristic baseline
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode heuristic \
  --limit 10 \
  --output-dir benchmark_results_heuristic

# Step 2: Run full mode
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode full \
  --model "Qwen3.5-4B-GGUF" \
  --limit 10 \
  --output-dir benchmark_results_full

# Step 3: Compare them
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --compare \
    benchmark_results_heuristic/results.json \
    benchmark_results_full/results.json \
  --output-dir benchmark_results_compare
```

**Comparison output:**
```
======================================================================
  GAIA Email Triage Benchmark — Mode Comparison
======================================================================
  MBOX:    path/to/your.mbox
  Emails:  10 (heuristic) vs 10 (full)

  ──────────────────────────────────────────────────────────────
  Totals:
                              heuristic          full       delta
  ──────────────────────────────────────────────────────────────
    Duration (ms)                    31         41907      +41876
    Duration (s)                   0.0          41.9        +41.9
    Input tokens                      0          2500       +2500
    Output tokens                     0           150        +150
    Total tokens                      0          2650       +2650

  ──────────────────────────────────────────────────────────────
  Per-Email Averages:
                              heuristic          full
  ──────────────────────────────────────────────────────────────
    Time per email (ms)               3.1        4190.7
    Time per email (s)              0.003         4.191
    Input tokens/email                0.0         250.0
    Output tokens/email               0.0          15.0
    Total tokens/email                0.0         265.0

  ──────────────────────────────────────────────────────────────
  Full Mode Efficiency:
  ──────────────────────────────────────────────────────────────
    ms per token:        15.8
    tokens per second:   63.2
    Time overhead vs heuristic:  135243% slower

  ──────────────────────────────────────────────────────────────
  Category Distribution:
                      heuristic          full       delta
  ──────────────────────────────────────────────────────────────
    informational                7             7         +0
    low priority                 3             3         +0

  ──────────────────────────────────────────────────────────────
  Per-Email Classification Agreement:
    Same category:      10/10 (100%)
    Different category: 0/10 (0%)
======================================================================
```

**Output file:** `comparison.json` with detailed per-email mismatches.

---

## 6. Ground Truth Quality Scoring

Provide a ground truth JSON to measure classification accuracy.

```bash
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode full \
  --model "Qwen3.5-4B-GGUF" \
  --limit 10 \
  --ground-truth "path/to/ground_truth.json" \
  --output-dir benchmark_results
```

**Ground truth format:**
```json
{
  "377bc3bc44e6a005": {"category": "informational"},
  "60f9d4ef6bf62b7f": {"category": "low priority"}
}
```

**Quality score:** Fraction of emails classified correctly (0.0–1.0), included in `summary.csv`.

---

## 7. Cost Estimation

For paid API models, estimate the cost of running the benchmark.

```bash
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode full \
  --model "claude-sonnet-4-6" \
  --limit 100 \
  --cost-per-1m-input 3.0 \
  --cost-per-1m-output 15.0 \
  --output-dir benchmark_results
```

Cost appears in `summary.csv` as `Cost Per Turn` and `Total Cost`.

---

## 8. Charts (Visualizations)

Generate static PNG charts from benchmark output for reports, dashboards, and presentations. Uses matplotlib with the Agg backend (no display required).

```bash
# Auto-generate charts after a benchmark run
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode full \
  --model "Qwen3.5-4B-GGUF" \
  --limit 10 \
  --iterations 5 \
  --visualize \
  --chart-dir benchmark_charts

# Post-hoc: generate charts from existing output files
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --visualize \
  --chart-dir benchmark_charts

# Standalone chart generation (no benchmark run)
gaia email bench \
  --visualize \
  --json-path benchmark_results/results.json \
  --jsonl-path benchmark_results/results.jsonl \
  --interactive-path benchmark_results/interactive.json \
  --chart-dir benchmark_charts
```

**Available charts (auto-selected based on data availability):**

| # | Chart | Type | When Generated |
|---|-------|------|----------------|
| 01 | Category Distribution | Comparison (horizontal bar) | Always |
| 02 | Token Composition | Composition (donut) | Full/interactive modes |
| 03 | Duration vs Token Cost | Comparison (grouped column) | Full/interactive modes |
| 04 | Per-Email Duration Histogram | Distribution (histogram) | Always |
| 05a | LLM Latency Consistency | Comparison (line + stats box) | Multi-iteration (>= 2 runs) |
| 05b | LLM Token Variance | Comparison (line + stats box) | Multi-iteration (>= 2 runs) |
| 05c | Per-Email Cost Variance | Comparison (dual-axis + stats) | Multi-iteration (>= 2 runs) |
| 06 | Interactive Turn Breakdown | Comparison (grouped column) | Interactive mode |
| 07 | Interactive Token Heatmap | Relationship (heatmap) | Interactive mode |
| 08 | Category Stability | Composition (stacked bar + annotation) | Multi-iteration (>= 2 runs) |
| 09 | Token vs Duration Scatter | Relationship (scatter + trend) | Always (>= 2 data points) |

**Variance charts (05a, 05b, 05c)** include a **Consistency Report** box showing μ (mean), σ (stdev), and CV% (coefficient of variation). These quantify LLM non-determinism — how much token counts and latency vary when running the *same* benchmark on the *same* emails. Low CV% = predictable cost. High CV% = volatile behavior.

**Category Stability (08)** shows that heuristic classification is deterministic — bars should be identical across runs, contrasting with LLM-based variance shown in charts 05a-c.

**Output:** All charts saved as numbered PNGs in `--chart-dir/` with a `CHARTS.md` index file.

---

## CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--mbox-path` | *(required)* | Path to MBOX file |
| `--mode` | `heuristic` | `heuristic`, `full`, or `interactive` |
| `--model` | `heuristic-only` | Model ID for LLM modes |
| `--base-url` | env or localhost | LLM server URL |
| `--limit` | 100 | Max emails to process |
| `--batch-size` | 20 | Emails per batch (heuristic only) |
| `--iterations` | 1 | Number of benchmark runs |
| `--output-dir` | `benchmark_results` | Output directory |
| `--variance-only` | false | Re-analyze existing JSONL |
| `--jsonl-path` | (auto) | JSONL path for variance-only |
| `--compare` | none | Compare two JSON files |
| `--ground-truth` | none | Ground truth JSON for quality |
| `--cost-per-1m-input` | 0.0 | Cost per 1M input tokens |
| `--cost-per-1m-output` | 0.0 | Cost per 1M output tokens |
| `--visualize` | false | Generate chart PNGs after the run |
| `--chart-dir` | `benchmark_charts` | Directory for chart output |

---

## Output Files

Every benchmark run produces these files in `--output-dir`:

| File | Format | Contents |
|------|--------|----------|
| `results.csv` | CSV | Per-email rows + summary (openclaw-eval compatible) |
| `results.json` | JSON | Full run detail with per-step tokens |
| `results.jsonl` | JSONL | Append-only log for multi-iteration runs |
| `summary.csv` | CSV | Summary spreadsheet (4-column layout) |
| `variance.json` | JSON | Statistical report (multi-iteration only) |
| `comparison.json` | JSON | Heuristic vs full diff |
| `interactive.json` | JSON | Multi-turn session detail |
| `charts/*.png` | PNG | Auto-generated visualizations |
| `charts/CHARTS.md` | Markdown | Chart index with descriptions |

### CSV Column Layout

The `results.csv` matches openclaw-eval column layout with 40+ columns including: `run_id`, `timestamp`, `model`, `provider`, `email_id`, `subject`, `sender`, `gaia_category`, `openclaw_category`, `is_spam`, `is_phishing`, `confident`, `reason`, `duration_per_email_ms`, and cumulative token counts.

---

## Architecture

```
src/gaia/agents/email/bench/
├── runner.py      # Core benchmark engine (heuristic, full, interactive)
├── output.py      # CSV/JSON/JSONL formatters, summary generation
├── compare.py     # Cross-mode comparison (heuristic vs full)
├── variance.py    # Statistical variance analysis
├── cli.py         # CLI entry point (gaia email bench)
└── __init__.py
```

### Data Shapes

- `EmailResult` — single email classification
- `BatchResult` — batch of emails with aggregated metrics
- `RunResult` — complete benchmark run
- `StepResult` — single LLM call with token/duration stats
- `TurnResult` — single turn in interactive session
- `ModeComparison` — heuristic vs full diff report
- `VarianceSummary` — statistical summary across runs

### How token tracking works

1. Each LLM call stores performance stats as a `system` message with `type: "stats"` in the conversation
2. `StepResult` extraction walks the conversation and pulls `input_tokens`, `output_tokens`, `total_tokens`, and `duration` from each stats entry
3. For interactive mode, steps are accumulated across all turns
