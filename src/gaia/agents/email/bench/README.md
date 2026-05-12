# GAIA Email Triage Benchmark

Benchmark harness for the GAIA Email Triage Agent. Measures classification accuracy, token consumption, wall-clock latency, and agent behavior across three modes: **heuristic** (no LLM), **full** (single LLM turn), and **interactive** (multi-turn session).

The benchmark follows the Unix philosophy of small, composable tools: one command runs the benchmark, another runs ClawFlow, and a third reads both outputs to produce all analysis, reports, and charts.

## Quick Reference

| Command | Purpose | Primary output |
|---------|---------|----------------|
| `gaia email bench` | Run GAIA benchmarks (heuristic / full / interactive) | `results.jsonl` |
| `gaia email clawflow` | Run ClawFlow benchmarks on the same MBOX | `clawflow_results.json` |
| `gaia email report` | Read both results, produce analysis + charts | `report.csv`, `variance.json`, `quality.json`, `statistical_tests.json`, `framework_comparison.json`, `charts/` |

| Mode | LLM? | What it measures | Speed |
|------|------|------------------|-------|
| `heuristic` | No | Rule-based classification speed & accuracy | < 1s |
| `full` | Yes | End-to-end triage + summarization tokens | ~30-60s |
| `interactive` | Yes | Multi-turn session: triage -> organize -> summarize | ~90-180s |

---

## 1. Heuristic Mode (Fast, No LLM)

Classifies emails using only Gmail labels and header heuristics. No LLM involved -- zero tokens consumed. Ideal for baseline accuracy and large MBOX files.

```bash
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode heuristic \
  --limit 100
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
gaia email bench --mbox-path "path/to/your.mbox" --mode full --model "Qwen3.5-4B-GGUF" --limit 10
```

**What it measures:**
- Everything from heuristic mode, PLUS:
- Total input/output tokens for the LLM round-trip
- Per-step token breakdown (planning call + summary call)
- Wall-clock time including LLM inference

**Per-step output example:**
```
  Per-Step Token Breakdown:
  ----------------------------------------------------------------------
  Step    Action        Input    Output     Total      Time
    1     llm_call        2500       150      2650       8.2s
    2     llm_call        2400       127      2527       5.1s
  ----------------------------------------------------------------------
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
gaia email bench --mbox-path "path/to/your.mbox" --mode interactive --model "Qwen3.5-4B-GGUF" --limit 10
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
  Interactive Benchmark -- Summary
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

## 4. Multi-Model Benchmark

Run multiple LLM models sequentially against the same MBOX file, measuring comparative performance without model-eviction churn from concurrent runs.

```bash
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode full \
  --models "Qwen3.5-4B-GGUF" \
  --models "Qwen3.5-14B-GGUF" \
  --models "claude-sonnet-4-6" \
  --experiments-per-model 3
```

**Key flags:**

| Flag | Description |
|------|-------------|
| `--models` | Model IDs to benchmark (can specify multiple times) |
| `--experiments-per-model` | Runs per model (default 1). Alias: `--iterations-per-model` (deprecated) |
| `--model-batch-sizes` | Per-model batch sizes, e.g. `"model1:10,model2:20"` |
| `--skip-cold-start` | Exclude the first (cold-start) experiment from variance reports |
| `--fail-fast` | Abort on first failure instead of continuing to next model |

**Backwards compatibility:** `--experiments` (alias `--iterations`) works for single-model runs. When `--models` is not provided, `--experiments N` maps to `--experiments-per-model N`.

**Cold-start tagging:** The first experiment of each model is tagged `is_cold_start: true`. Use `--skip-cold-start` to exclude these from variance analysis, avoiding first-run TTFT contamination from model loading.

**Output:** All runs are appended to a single `results.jsonl` for unified cross-model variance analysis. When multiple models are present, `variance_by_model.json` contains per-model variance reports.

**Serial execution guarantee:** At most one model runs at a time, preventing Lemonade Server model eviction races. Runs execute in the order specified on the command line.

---

## 5. ClawFlow Benchmark

Run [ClawFlow](https://github.com/openclaw-eval) CLI on the same MBOX to produce framework-comparable results. This replaces the old `--clawflow` flag on `gaia email bench`.

```bash
gaia email clawflow \
  --mbox-path "path/to/your.mbox" \
  --workflow inbox-zero-helper \
  --timeout 3600
```

**Key flags:**

| Flag | Description |
|------|-------------|
| `--mbox-path` | *(required)* Path to MBOX file |
| `--workflow` | ClawFlow workflow name (default `inbox-zero-helper`) |
| `--timeout` | Max seconds to wait for ClawFlow (default 3600) |
| `--clawflow-path` | Explicit path to clawflow script or binary |
| `--model` | Model ID for ClawFlow (if applicable) |

**How it works:**

1. ClawFlow CLI is invoked as a subprocess
2. ClawFlow's JSON output is parsed and mapped to GAIA's `RunResult` schema
3. Results are saved to `clawflow_results.json`

**Invocation:** ClawFlow is invoked via `python clawflow_cli.py --workflow <name> --model <model> --json --quiet`. The adapter probes for the script at the default location (`openclaw-eval/scripts/agentic-framework-test/gaia_agents/clawflow_cli.py`) or an explicit `--clawflow-path`.

**Category mapping:** ClawFlow categories are normalized to GAIA taxonomy:

| ClawFlow | GAIA |
|----------|------|
| `URGENT` | `urgent` |
| `NEEDS_RESPONSE` | `actionable` |
| `FYI` | `informational` |
| `PROMOTIONAL` | `low priority` |

**Output:** `clawflow_results.json` -- raw ClawFlow output mapped to GAIA schema.

---

## 6. Report Generation

The `gaia email report` command reads benchmark results from `gaia email bench` and `gaia email clawflow`, computes analysis, and produces all report files and charts. This replaces the old `--variance-only`, `--visualize`, and `--compare` flags.

```bash
gaia email report --input-dir benchmark_results
```

**What it reads:**
- `results.jsonl` (from `gaia email bench`)
- `clawflow_results.json` (from `gaia email clawflow`, if present)

**What it produces:**

| File | Contents |
|------|----------|
| `report.csv` | Per-email rows with all metrics |
| `variance.json` | Statistical variance report (mean, stdev, min, max, CV%) |
| `quality.json` | Ground truth accuracy scores |
| `statistical_tests.json` | Mann-Whitney U, Cliff's delta, bootstrap CI |
| `framework_comparison.json` | GAIA vs ClawFlow side-by-side metrics |
| `charts/` | PNG charts + `CHARTS.md` index |

### Variance Analysis

When multiple experiments exist in `results.jsonl`, the report computes variance statistics automatically.

**Variance report example:**
```
  Variance Summary (across all runs):
  ----------------------------------------------------------------------
  total_duration_s              : mu=     42.00  sigma=        1.20  min=   40.20  max=   43.80  CV=  2.9%
  total_input_tokens            : mu=     2500.0  sigma=        0.0  min= 2500.0  max= 2500.0  CV=  0.0%
  total_output_tokens           : mu=      150.0  sigma=        5.2  min=  142.0  max=  158.0  CV=  3.5%
  total_tokens                  : mu=     2650.0  sigma=        5.2  min= 2642.0  max= 2658.0  CV=  0.2%
  total_emails                  : mu=       10.0  sigma=        0.0  min=   10.0  max=   10.0  CV=  0.0%
  avg_duration_per_email_s      : mu=      4.20  sigma=        0.12  min=    4.02  max=    4.38  CV=  2.9%
  avg_input_tokens_per_email    : mu=      250.0  sigma=        0.0  min=  250.0  max=  250.0  CV=  0.0%
  avg_output_tokens_per_email   : mu=       15.0  sigma=        0.5  min=   14.2  max=   15.8  CV=  3.5%
  avg_total_tokens_per_email    : mu=      265.0  sigma=        0.5  min=  264.2  max=  265.8  CV=  0.2%
  ```

### Mode Comparison

Compare heuristic vs full mode (or any two result sets):

```bash
# Step 1: Run heuristic baseline
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode heuristic \
  --limit 10

# Step 2: Run full mode
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode full \
  --model "Qwen3.5-4B-GGUF" \
  --limit 10

# Step 3: Generate comparison report
gaia email report \
  --compare heuristic full \
  --input-dir benchmark_results
```

**Comparison output:**
```
======================================================================
  GAIA Email Triage Benchmark -- Mode Comparison
======================================================================
  MBOX:    path/to/your.mbox
  Emails:  10 (heuristic) vs 10 (full)

  ----------------------------------------------------------------------
  Totals:
                              heuristic          full       delta
  ----------------------------------------------------------------------
    Duration (ms)                    31         41907      +41876
    Duration (s)                   0.0          41.9        +41.9
    Input tokens                      0          2500       +2500
    Output tokens                     0           150        +150
    Total tokens                      0          2650       +2650

  ----------------------------------------------------------------------
  Per-Email Averages:
                              heuristic          full
  ----------------------------------------------------------------------
    Time per email (ms)               3.1        4190.7
    Time per email (s)              0.003         4.191
    Input tokens/email                0.0         250.0
    Output tokens/email               0.0          15.0
    Total tokens/email                0.0         265.0

  ----------------------------------------------------------------------
  Full Mode Efficiency:
  ----------------------------------------------------------------------
    ms per token:        15.8
    tokens per second:   63.2
    Time overhead vs heuristic:  135243% slower

  ----------------------------------------------------------------------
  Category Distribution:
                      heuristic          full       delta
  ----------------------------------------------------------------------
    informational                7             7         +0
    low priority                 3             3         +0

  ----------------------------------------------------------------------
  Per-Email Classification Agreement:
    Same category:      10/10 (100%)
    Different category: 0/10 (0%)
======================================================================
```

### Framework Comparison (GAIA vs ClawFlow)

When both `results.jsonl` and `clawflow_results.json` are present in the input directory, the report automatically produces a framework comparison:

```bash
# Step 1: Run GAIA benchmark
gaia email bench --mbox-path "path/to/your.mbox" --mode full --model "Qwen3.5-4B-GGUF" --limit 10

# Step 2: Run ClawFlow benchmark
gaia email clawflow --mbox-path "path/to/your.mbox" --workflow inbox-zero-helper

# Step 3: Generate unified report with framework comparison
gaia email report --input-dir benchmark_comparison
```

**Output file:** `framework_comparison.json` with detailed side-by-side metrics.

---

## 7. Quality Scoring

Provide a ground truth JSON to measure classification accuracy.

```bash
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode full \
  --model "Qwen3.5-4B-GGUF" \
  --limit 10 \
  --ground-truth "path/to/ground_truth.json"
```

**Ground truth format:**
```json
{
  "377bc3bc44e6a005": {"category": "informational"},
  "60f9d4ef6bf62b7f": {"category": "low priority"}
}
```

**Quality score:** Fraction of emails classified correctly (0.0--1.0). Computed by `gaia email report` and saved to `quality.json`.

---

## 8. Cost Estimation

For paid API models, estimate the cost of running the benchmark.

```bash
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode full \
  --model "claude-sonnet-4-6" \
  --limit 100 \
  --cost-per-1m-input 3.0 \
  --cost-per-1m-output 15.0
```

Cost appears in `report.csv` as `Cost Per Turn` and `Total Cost`.

---

## 9. Charts (Visualizations)

Generate static PNG charts from benchmark output for reports, dashboards, and presentations. Uses matplotlib with the Agg backend (no display required).

```bash
# Run benchmarks first
gaia email bench --mbox-path "path/to/your.mbox" --mode full --model "Qwen3.5-4B-GGUF" --limit 10 --experiments 5

# Then generate charts from the results
gaia email report --input-dir benchmark_results --charts
```

**Available charts (auto-selected based on data availability):**

| # | Chart | Type | When Generated |
|---|-------|------|----------------|
| 01 | Category Distribution | Comparison (horizontal bar) | Always |
| 02 | Token Composition | Composition (donut) | Full/interactive modes |
| 03 | Duration vs Token Cost | Comparison (grouped column) | Full/interactive modes |
| 04 | Per-Email Duration Histogram | Distribution (histogram) | Always |
| 05a | LLM Latency Consistency | Comparison (line + stats box) | Multi-experiment (>= 2 runs) |
| 05b | LLM Token Variance | Comparison (line + stats box) | Multi-experiment (>= 2 runs) |
| 05c | Per-Email Cost Variance | Comparison (dual-axis + stats) | Multi-experiment (>= 2 runs) |
| 05d | TTFT Consistency | Comparison (line + stats box) | Multi-experiment (>= 2 runs) |
| 05e | TPS Consistency | Comparison (line + stats box) | Multi-experiment (>= 2 runs) |
| 06 | Interactive Turn Breakdown | Comparison (grouped column) | Interactive mode |
| 07 | Interactive Token Heatmap | Relationship (heatmap) | Interactive mode |
| 08 | Category Stability | Composition (stacked bar + annotation) | Multi-experiment (>= 2 runs) |
| 09 | Token vs Duration Scatter | Relationship (scatter + trend) | Always (>= 2 data points) |
| 10 | Per-Step TTFT & TPS | Comparison (dual-axis line) | Full/interactive modes |

**Variance charts (05a, 05b, 05c, 05d, 05e)** include a **Consistency Report** box showing mu (mean), sigma (stdev), and CV% (coefficient of variation). These quantify LLM non-determinism -- how much token counts and latency vary when running the *same* benchmark on the *same* emails. Low CV% = predictable cost. High CV% = volatile behavior. All duration/latency values are in seconds.

**Category Stability (08)** shows that heuristic classification is deterministic -- bars should be identical across runs, contrasting with LLM-based variance shown in charts 05a-c.

**Output:** All charts saved as numbered PNGs in `charts/` with a `CHARTS.md` index file.

### Extended Charts (Charts 11-21)

Multi-model and ClawFlow runs unlock additional charts for cross-framework comparison.

| # | Chart | Type | When Generated |
|---|-------|------|----------------|
| 11 | Model Duration Comparison | Grouped column | Multi-model (>= 2 models) |
| 12 | Model Token Cost | Stacked column | Multi-model (>= 2 models) |
| 13 | TTFT Comparison | Horizontal bar | Multi-model (>= 2 models) |
| 14 | TPS Comparison | Horizontal bar | Multi-model (>= 2 models) |
| 15 | Framework Category Comparison | Side-by-side stacked bars | ClawFlow + GAIA data |
| 16 | Architecture Radar | Radar/spider chart | ClawFlow + GAIA data |
| 17 | Per-Model Variance Trend | Multi-line | Multi-model (>= 3 experiments) |
| 18 | Cold-Start Impact | Scatter with annotation | Multi-model with cold-start data |
| 19 | Model x Architecture Duration | Grouped column | ClawFlow + GAIA data (>= 1 model) |
| 20 | Model x Architecture Token Cost | Grouped stacked column | ClawFlow + GAIA data (>= 1 model) |
| 21 | Architecture Performance Dashboard | 4-panel faceted | ClawFlow + GAIA data (>= 1 model) |

**Architecture Radar (Chart 16)** plots GAIA and ClawFlow across six dimensions: Duration, Tokens, TTFT, TPS, Classification Accuracy, and Category Coverage -- normalized to 0-100 scale for visual comparison.

**Cold-Start Impact (Chart 18)** visualizes the first-experiment TTFT contamination effect, showing how model loading time inflates latency on the first run versus warm subsequent runs.

**Model x Architecture charts (19-21)** display performance metrics across models and frameworks in a unified view. All charts use consistent architecture colors:
- **GAIA**: `#ED6C02` (AMD orange)
- **ClawFlow**: `#3182CE` (blue)

**Architecture Performance Dashboard (Chart 21)** is a 4-panel faceted chart showing TTFT, throughput (TPS), total duration, and token cost -- all grouped by model and colored by architecture for at-a-glance comparison.

---

## 10. Statistical Tests

When multiple models are benchmarked with sufficient experiments (>= 2 per model), the report automatically runs non-parametric statistical tests to determine if performance differences are significant.

**Tests performed:**

| Test | Metric | Purpose |
|------|--------|---------|
| Mann-Whitney U | `total_duration_ms` | Tests if two models' latency distributions differ |
| Cliff's delta | `total_duration_ms` | Effect size: magnitude of difference between models |
| Bootstrap 95% CI | `total_duration_ms` | Confidence interval for mean difference |

**Interpreting results:**
- **p < 0.05**: Statistically significant difference (reject null hypothesis)
- **|Cliff's delta| > 0.147**: Small effect; **> 0.33**: medium; **> 0.474**: large
- **Bootstrap CI excludes 0**: Confirms the direction of difference

```bash
gaia email bench \
  --mbox-path "path/to/your.mbox" \
  --mode full \
  --models "model-a" --models "model-b" \
  --experiments-per-model 5

gaia email report --input-dir benchmark_results
```

**Console output:**
```
  model-a vs model-b:
    Mann-Whitney U = 2.0000, p = 0.0159
    Cliff's delta  = 0.7200
    Bootstrap 95% CI for mean diff = [-12450.3, -3210.1]
```

Results are saved to `statistical_tests.json` for programmatic access.

---

## 11. Output Files

The three subcommands produce distinct outputs:

### `gaia email bench`

| File | Format | When |
|------|--------|------|
| `results.jsonl` | JSONL | Every run (append-only log, all models, all experiments) |
| `results.json` | JSON | Single-run detail (when `--experiments-per-model 1`) |
| `interactive.json` | JSON | Interactive mode only |

### `gaia email clawflow`

| File | Format | When |
|------|--------|------|
| `clawflow_results.json` | JSON | Every run |

### `gaia email report`

| File | Format | When |
|------|--------|------|
| `report.csv` | CSV | Every report (per-email rows) |
| `variance.json` | JSON | Multi-experiment (>= 2 runs) |
| `variance_by_model.json` | JSON | Multi-model (>= 2 models) |
| `quality.json` | JSON | Ground truth provided |
| `statistical_tests.json` | JSON | Multi-model with >= 2 experiments each |
| `comparison.json` | JSON | `--compare` mode |
| `framework_comparison.json` | JSON | ClawFlow + GAIA data present |
| `charts/*.png` | PNG | `--charts` flag |
| `charts/CHARTS.md` | Markdown | Chart index (when charts generated) |

### CSV Column Layout

The `report.csv` matches openclaw-eval column layout with 40+ columns including: `run_id`, `timestamp`, `model`, `provider`, `email_id`, `subject`, `sender`, `gaia_category`, `openclaw_category`, `is_spam`, `is_phishing`, `confident`, `reason`, `duration_per_email_ms`, and cumulative token counts.

---

## 12. CLI Reference

### `gaia email bench` -- Run GAIA Benchmarks

| Flag | Default | Description |
|------|---------|-------------|
| `--mbox-path` | *(required)* | Path to MBOX file |
| `--mode` | `heuristic` | `heuristic`, `full`, or `interactive` |
| `--model` | `heuristic-only` | Model ID for LLM modes |
| `--base-url` | env or localhost | LLM server URL |
| `--limit` | 100 | Max total emails from MBOX (0=no limit). Independent of `--batch-size` |
| `--batch-size` | 20 | Emails per batch (each batch = one LLM prompt) |
| `--experiments` | 1 | Experiments per model (alias `--iterations`, deprecated) |
| `--models` | *(none)* | Model IDs to benchmark (multiple `--models` flags) |
| `--experiments-per-model` | 1 | Experiments per model (alias `--iterations-per-model`, deprecated) |
| `--model-batch-sizes` | *(none)* | `model:batch_size` pairs, e.g. `"m1:10,m2:20"` |
| `--skip-cold-start` | false | Exclude first (cold-start) experiment from reports |
| `--fail-fast` | false | Abort on first model failure |
| `--ground-truth` | none | Ground truth JSON for quality scoring |
| `--cost-per-1m-input` | 0.0 | Cost per 1M input tokens |
| `--cost-per-1m-output` | 0.0 | Cost per 1M output tokens |
| `--steps` | false | Print per-step token breakdown |

**Deprecated flags** (moved to `gaia email report`):
- `--variance-only` -- use `gaia email report --input-dir <dir>` instead
- `--visualize` -- use `gaia email report --charts --input-dir <dir>` instead
- `--compare` -- use `gaia email report --compare <a> <b> --input-dir <dir>` instead
- `--clawflow`, `--clawflow-timeout`, `--clawflow-workflow`, `--clawflow-path` -- use `gaia email clawflow` instead

### `gaia email clawflow` -- Run ClawFlow Benchmarks

| Flag | Default | Description |
|------|---------|-------------|
| `--mbox-path` | *(required)* | Path to MBOX file |
| `--workflow` | `inbox-zero-helper` | ClawFlow workflow name |
| `--timeout` | 3600 | Max seconds to wait for ClawFlow |
| `--clawflow-path` | *(auto)* | Explicit path to clawflow script/binary |
| `--model` | *(auto)* | Model ID for ClawFlow |

### `gaia email report` -- Generate Reports and Charts

| Flag | Default | Description |
|------|---------|-------------|
| `--input-dir` | `benchmark_results` | Directory containing benchmark output files |
| `--charts` | false | Generate chart PNGs in `charts/` subdirectory |
| `--compare` | none | Compare two result sets, e.g. `--compare heuristic full` |
| `--ground-truth` | none | Ground truth JSON for quality scoring |
| `--cost-per-1m-input` | 0.0 | Cost per 1M input tokens |
| `--cost-per-1m-output` | 0.0 | Cost per 1M output tokens |

---

## Architecture

The email benchmark follows the Unix philosophy: three focused commands, each doing one job well, composed via shared output files.

```
gaia email bench       ---->  results.jsonl / interactive.json
gaia email clawflow    ---->  clawflow_results.json
                               |
gaia email report  <----  reads both, produces:
                               report.csv
                               variance.json
                               quality.json
                               statistical_tests.json
                               framework_comparison.json
                               charts/
```

This design separates concerns cleanly:
- **Runner** (`bench`) -- executes benchmarks, collects raw metrics
- **Data** (`clawflow`) -- runs external framework, maps to unified schema
- **Report generator** (`report`) -- reads all data, computes analysis, produces charts

Benefits:
- Each command can run independently and be re-run without re-executing benchmarks
- Results are inspectable between steps for debugging
- New analysis methods can be added to `report` without touching the runner
- CI pipelines can parallelize bench and clawflow, then combine in report

### Source Layout

```
src/gaia/agents/email/bench/
├── runner.py           # Core benchmark engine (heuristic, full, interactive)
├── output.py           # CSV/JSON/JSONL formatters, summary generation
├── compare.py          # Cross-mode comparison (heuristic vs full, framework)
├── variance.py         # Statistical variance + tests (Mann-Whitney U, Cliff's delta, bootstrap CI)
├── visualize.py        # Chart generation (21 charts, matplotlib Agg backend)
├── clawflow_adapter.py # ClawFlow CLI probe, invoke, parse -> GAIA RunResult
├── cli.py              # CLI entry point (gaia email {bench|clawflow|report})
└── __init__.py
```

### Data Shapes

- `EmailResult` -- single email classification
- `BatchResult` -- batch of emails with aggregated metrics
- `RunResult` -- complete benchmark run (GAIA or ClawFlow, unified schema)
- `StepResult` -- single LLM call with token/duration stats
- `TurnResult` -- single turn in interactive session
- `ModeComparison` -- heuristic vs full diff report
- `VarianceSummary` -- statistical summary across runs
- `ClawflowRun` -- ClawFlow BenchmarkRun mapped to GAIA `RunResult` shape

### Statistical Tests

- **Mann-Whitney U** -- non-parametric test for distribution difference (normal approximation)
- **Cliff's delta** -- effect size estimator (small > 0.147, medium > 0.33, large > 0.474)
- **Bootstrap 95% CI** -- confidence interval for mean difference (1000 resamples)

### How token tracking works

1. Each LLM call stores performance stats as a `system` message with `type: "stats"` in the conversation
2. `StepResult` extraction walks the conversation and pulls `input_tokens`, `output_tokens`, `total_tokens`, and `duration` from each stats entry
3. For interactive mode, steps are accumulated across all turns
