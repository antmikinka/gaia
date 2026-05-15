# Benchmark Visualization Charts — Extended Suite (Charts 24-29)

This document describes 6 new visualization charts (Charts 24-29) for the GAIA Email Benchmark
visualization suite. All charts are implemented in the generation script; charts marked "Requires data"
need specific benchmark runs (multi-model or interactive mode) to populate. Each chart includes full
specs, legends, and interpretation guidance.

## Status

| Chart | Status | Requires |
|-------|--------|----------|
| 24 - Planning Steps Heatmap | Implemented | Multi-model runs with varying email limits |
| 25 - Token Efficiency Bars | Implemented | Multi-model runs |
| 26 - Latency vs Heuristic Scatter | Implemented | Multi-model runs |
| 27 - Interactive LLM Activity | Implemented | Interactive mode session data (`interactive.json`) |
| 28 - Model Performance Radar | Implemented | ≥ 2 models with complete run data |
| 29 - Steps Scaling Heatmap | Implemented | Multi-model runs with varying email limits |

## Data Requirements

- **`results.jsonl`**: Standard benchmark results with multi-model runs. Required for Charts 24, 25, 26, 28, 29.
- **`interactive.json`**: Interactive mode session data from conversational email benchmark runs. Required for Chart 27.
- **Multi-model runs**: Charts 24, 25, 26, 28, 29 require at least 2 different models to show comparative data.
- **Varying email limits**: Charts 24 and 29 require runs with different `total_emails` values to show scaling behavior.
- **Chart 28 (Radar)**: Requires ≥ 2 runs per model for CV% (coefficient of variation) calculation. With a single run per model, CV% axis will show 0.

---

For Charts 1-23, see [CHARTS.md](CHARTS.md).

---

## Chart 24: Estimated LLM Planning Steps by Model & Email Limit

**Type:** Heatmap (diverging colormap)
**Data Source:** `results.jsonl` — requires multi-model runs with varying email limits
**File:** `24_planning_steps_heatmap.png`

### Problem Statement

Without this chart, there is no way to see how many LLM planning invocations each model requires at different email volumes, or whether planning cost scales linearly with inbox size. A user cannot determine if a model is relying on the heuristic fast-path or burning through LLM calls for every email.

### Claim Statement

Models that stay blue (≤2 planning steps) even at high email limits are successfully routing most emails through the heuristic fast-path. Models that shift from blue to red as email limits increase are failing to scale — each additional batch of emails triggers disproportionate LLM planning, revealing a fundamental classification inefficiency rather than a throughput issue.

### Axes
- **X-Axis:** Model names (sorted alphabetically, truncated to 25 chars)
- **Y-Axis:** Email Limit (total_emails from runs, sorted ascending)
- **Cell Value:** Estimated planning steps = `total_tokens / 2800`

### Colormap
`RdYlBu_r` (diverging, reversed)

| Color | Range | Interpretation |
|-------|-------|----------------|
| Blue | ≤ 2 steps | Minimal LLM planning; heuristic fast-path dominates |
| Yellow | 3-5 steps | Moderate planning; some emails escalated to LLM |
| Red | ≥ 6 steps | Heavy LLM planning overhead |

### Annotations
- Each cell displays the rounded mean `step_results` count (integer) across runs for that model/email limit combination
- Color key at bottom-left: "Blue = Low (≤2)  Yellow = Med (3-5)  Red = High (≥6)"

### Legend
**Formula:** `est_planning_steps = total_tokens / 2800`

The divisor 2800 approximates the average token cost of a single planning LLM call
(observed median across benchmark runs).

### Interpretation
Lower values (blue) indicate more efficient classification via heuristic fast-path.
Higher values (red) indicate greater reliance on LLM planning, increasing latency and cost.
Compare across email limits to observe scaling behavior — efficient models stay blue even at high limits.

---

## Chart 25: Tokens per Email by Model (Input / Output / Total)

**Type:** Grouped bar chart with error bars + heuristic % overlay
**Data Source:** `results.jsonl` — multi-model runs
**File:** `25_token_efficiency.png`

### Problem Statement

Without this chart, there is no way to decompose token consumption into input vs. output components per model, making it impossible to tell whether high token usage comes from sending too much context (large input) or from verbose LLM reasoning (large output). A user also cannot verify the claimed inverse relationship between heuristic confidence and token cost.

### Claim Statement

A model with a high heuristic percentage ("H: XX%") but still high total tokens indicates the heuristic is catching many emails but the escalated ones are extremely expensive — a concentrated cost pattern. Conversely, a model with low heuristic percentage and low output tokens suggests the LLM is making quick classification decisions even without heuristic help. Wide error bars reveal that token usage is non-deterministic, making cost prediction unreliable for that model.

### Axes
- **X-Axis:** Model names (truncated to 20 chars)
- **Y-Axis:** Tokens per Email (mean across runs)

### Groups (3 bars per model)

| Bar | Color | Description |
|-----|-------|-------------|
| Input | Blue (#3182CE) | Mean input tokens per email |
| Output | Orange (#DD6B20) | Mean output tokens per email |
| Total | GAIA Orange (#ED6C02) | Mean total tokens per email |

### Error Bars
±1 standard deviation across runs, 4px caps.

### Heuristic % Overlay
Text label **"H: XX%"** displayed above each model's bar group.
Represents the percentage of emails where the heuristic classifier was confident (`confident=True`).
Higher H% = fewer LLM escalations = lower token usage expected.

### Legend
- "Input tokens/email" — prompt tokens for planning/classification
- "Output tokens/email" — tokens generated by LLM (reasoning + classification)
- "Total tokens/email" — sum of input + output + reasoning tokens
- "H: XX%" — heuristic confidence rate

### Interpretation
Lower bars = more token-efficient classification.
Large input bars suggest verbose prompts or large email content being sent.
Large output bars suggest verbose LLM reasoning or multi-step tool chains.
Compare H% with token usage: models with high heuristic % should have lower total tokens.
Wide error bars indicate non-deterministic token consumption across runs.

---

## Chart 26: Duration vs Heuristic % (confident=true)

**Type:** Scatter plot with trend line and R² annotation
**Data Source:** `results.jsonl` — multi-model runs
**File:** `26_latency_heuristic_scatter.png`

### Problem Statement

Without this chart, there is no empirical evidence linking heuristic classification rate to end-to-end benchmark duration. A user cannot determine whether faster runs are fast because the heuristic caught more emails, or because the underlying model inference is simply faster — two very different optimization targets.

### Claim Statement

A strong negative correlation (high R²) confirms that heuristic rate is the dominant driver of benchmark speed — improving heuristic coverage is the single most effective optimization. A weak correlation (low R²) reveals that duration is driven by other factors like model load time or network latency, meaning heuristic improvements alone will not meaningfully reduce benchmark runtime. Points in the top-left quadrant represent the Pareto-optimal combination: fast execution with high heuristic utilization.

### Axes
- **X-Axis:** Duration (seconds) — total benchmark run time
- **Y-Axis:** Heuristic % — (confident emails / total emails) × 100

### Encoding
- **Color:** One distinct color per model
- **Point Size:** Scaled by total_emails processed (larger = more emails)
- **Edge:** White border (0.5px) for point separation

### Trend Line
Linear regression across all data points. Black dashed line with R² annotation in top-left.

### Interpretation
- **Top-left quadrant:** Fast runs with high heuristic rates — ideal
- **Bottom-right quadrant:** Slow runs with low heuristic rates — heavy LLM involvement
- **Negative correlation:** Higher heuristic rates correlate with faster execution
- **R² near 1.0:** Strong linear relationship between duration and heuristic rate
- **R² near 0.0:** Duration driven by other factors (model load, network latency)

---

## Chart 27: Projected LLM Calls per Turn (Interactive Session)

**Type:** Stacked bar chart with baseline reference
**Data Source:** `interactive.json` — interactive mode session data
**File:** `27_interactive_llm_activity.png` (with run ID suffix when applicable, e.g., `27_interactive_llm_activity_59c3c6.png`)

### Problem Statement

Without this chart, there is no visibility into how LLM computational effort distributes across multi-turn conversational sessions. A user cannot tell whether later turns become more efficient as context accumulates, or whether each turn independently consumes the same number of planning and tool calls -- a critical distinction for evaluating the interactive mode's scalability to long conversations.

### Claim Statement

A decreasing trend in total LLM calls across turns indicates the agent is learning from accumulated context and requiring fewer planning invocations as the session progresses -- good interactive design. A flat or increasing trend indicates each turn is stateless or context-overloaded, requiring full re-planning regardless of prior conversation history. Turns dominated by tool calls (orange-heavy) versus planning calls (blue-heavy) reveal whether the session is action-oriented (managing emails) or reasoning-oriented (classifying and deciding).

### Axes
- **X-Axis:** Conversation Turn (Turn 1 through Turn N)
- **Y-Axis:** LLM Calls (count of planning + tool invocations)

### Stacks

| Stack | Color | Description |
|-------|-------|-------------|
| Planning | Blue (#3182CE) | LLM calls for reasoning, classification, decision-making |
| Tool | Orange (#DD6B20) | LLM calls triggered by tool execution |

### Legend
- "Planning calls" — direct LLM invocations for turn processing
- "Tool calls" — LLM invocations from tool-augmented steps

### Interpretation
- Tall bars = complex turns requiring multiple LLM invocations
- Planning-dominant (blue-heavy): more reasoning/classification work
- Tool-dominant (orange-heavy): more tool-based actions (email operations)
- Trend across turns: should show decreasing calls as agent gains context

---

## Chart 28: Model Performance Radar (Normalized 0-100)

**Type:** 6-axis radar/spider chart (polar plot)
**Data Source:** `results.jsonl` — requires ≥ 2 models with complete run data
**File:** `28_model_performance_radar.png`

### Problem Statement

Without this chart, comparing models requires examining six separate metrics across different units (milliseconds, token counts, percentages), making it impossible to form a holistic view of which model performs best overall or where trade-offs exist. A user cannot quickly identify whether a model excels in one dimension at the expense of others, or whether it provides balanced performance.

### Claim Statement

A model with a large, symmetric polygon is the best all-around performer -- consistently efficient across speed, token economy, and classification quality. A model with a spiky, asymmetric polygon has a clear specialization (e.g., fast but token-expensive, or token-efficient but slow to escalate) and should be selected only when that specific dimension is prioritized. The radar chart makes it immediately visible whether "bigger models are always better" is true in this benchmark, or whether smaller models achieve comparable normalized scores on specific axes.

### Axes (6 dimensions, arranged at equal angular intervals on polar plot, starting from top)

| Axis | Direction | Description |
|------|-----------|-------------|
| Duration | Lower = Better | Total run time (ms) |
| Tokens | Lower = Better | Total token consumption |
| Steps | Lower = Better | Number of LLM step invocations |
| Heuristic % | Higher = Better | % of emails classified by heuristic |
| CV% | Lower = Better | Coefficient of variation in total token consumption (requires ≥ 2 runs per model; shows 0 for single-run) |
| Escalation % | Lower = Better | % of emails escalated to LLM |

### Normalization
Each axis normalized 0-100 based on min/max across all models:
- **Lower-is-better:** score = 100 × (1 - normalized_value)
- **Higher-is-better:** score = 100 × normalized_value

### Visual Encoding
- One polygon per model with semi-transparent fill (alpha=0.15)
- Opaque line border (linewidth=2) with circular markers
- Larger polygon area = better overall performance

### Legend
Model name with color coding. Legend labels include key metrics (duration, tokens).

### Interpretation
- **Larger polygons** = better overall models
- **Spiky polygons** = trade-offs (strong in some areas, weak in others)
- **Symmetric polygons** = balanced performance across all dimensions
- Compare shapes to identify model specializations

---

## Chart 29: Total LLM Calls Scaling (Planning + Summary + Tools)

**Type:** Heatmap (sequential colormap) with data point overlay
**Data Source:** `results.jsonl` — multi-model runs with varying email limits
**File:** `29_steps_scaling_heatmap.png`

### Problem Statement

Without this chart, there is no way to assess whether total LLM call volume (including the fixed +2 overhead for summary and final classification) grows predictably with email volume, or whether some models exhibit super-linear scaling where doubling the email count more than doubles the LLM invocations. Chart 24 shows planning steps alone; this chart captures the full operational cost including summary generation.

### Claim Statement

Models that maintain yellow-to-green cells across increasing email limits exhibit predictable, linear scaling -- each additional email adds a roughly constant number of LLM calls. Models that transition to purple at higher limits show super-linear scaling, meaning the system complexity grows faster than the input size -- a red flag for production deployment at scale. Purple cells at low email limits (e.g., 10-20 emails) indicate fundamental inefficiency: the model is invoking excessive LLM steps even for trivial workloads, independent of scaling behavior.

### Axes
- **X-Axis:** Model names (truncated to 18 chars with param size, 25 chars without; param size in parentheses when available)
- **Y-Axis:** Email Limit (total_emails from runs, sorted ascending)
- **Cell Value:** Estimated total LLM calls = `(total_tokens / 2800) + 2`

### Colormap
`viridis` (sequential)

| Color | Interpretation |
|-------|----------------|
| Yellow | Low total calls (1-5) — minimal LLM involvement |
| Green | Medium total calls (6-15) — moderate multi-step processing |
| Purple | High total calls (16+) — extensive LLM planning and tool usage |

### Overlay
- White circles mark cells with actual measured data points
- Formula annotation in bottom-left corner

### Legend
**Formula:** `est_total_calls = (total_tokens / 2800) + 2`
- `total_tokens / 2800` estimates planning step calls
- `+ 2` accounts for summary generation and final classification steps

### Interpretation
- **Compare with Chart 24:** This chart includes the fixed +2 overhead
- **Vertical progression:** Shows how LLM calls scale with email volume
  - Linear scaling = predictable behavior
  - Super-linear = complexity increases disproportionately
- **Horizontal comparison:** Smaller models should use equal or fewer calls than larger models
- **Purple cells at low limits:** Indicate fundamental inefficiency, not just scaling
