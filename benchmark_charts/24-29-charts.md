# Benchmark Report: Extended Analysis (Charts 24-29)

GAIA Email Benchmark — Extended Visualization Suite. All six charts are implemented in `visualize.py`; those marked "Requires data" need specific benchmark runs to render.

| Chart | Status | Data Required |
|-------|--------|---------------|
| [24 - Planning Steps Heatmap](#chart-24-estimated-llm-planning-steps-by-model--email-limit) | Implemented | Multi-model runs with varying email limits |
| [25 - Token Efficiency](#chart-25-tokens-per-email-by-model-input--output--total) | Implemented | Multi-model runs |
| [26 - Latency vs Heuristic](#chart-26-duration-vs-heuristic-confidenttrue) | Implemented | Multi-model runs |
| [27 - Interactive LLM Activity](#chart-27-projected-llm-calls-per-turn-interactive-session) | Implemented | Interactive mode session data |
| [28 - Model Performance Radar](#chart-28-model-performance-radar-normalized-0-100) | Implemented | ≥ 2 models with complete run data |
| [29 - Steps Scaling Heatmap](#chart-29-total-llm-calls-scaling-planning--summary--tools) | Implemented | Multi-model runs with varying email limits |

---

## Chart 24: Estimated LLM Planning Steps by Model & Email Limit

![Planning Steps Heatmap](24_planning_steps_heatmap.png)

**Status:** Implemented — requires multi-model runs with varying email limits in `results.jsonl`

### Problem Statement

Without this chart, there is no way to see how many LLM planning invocations each model requires at different email volumes, or whether planning cost scales linearly with inbox size. A user cannot determine if a model is relying on the heuristic fast-path or burning through LLM calls for every email.

### Claim Statement

Models that stay blue (≤2 planning steps) even at high email limits are successfully routing most emails through the heuristic fast-path. Models that shift from blue to red as email limits increase are failing to scale — each additional batch of emails triggers disproportionate LLM planning, revealing a fundamental classification inefficiency rather than a throughput issue.

### Description

Diverging heatmap (`RdYlBu_r`) showing estimated planning steps (`total_tokens / 2800`) by model and email limit. Blue (≤2 steps) = heuristic fast-path dominates. Yellow (3-5) = moderate LLM escalation. Red (≥6) = heavy LLM planning overhead. Each cell displays the rounded mean step count.

---

## Chart 25: Tokens per Email by Model (Input / Output / Total)

![Token Efficiency](25_token_efficiency.png)

**Status:** Implemented — requires multi-model runs in `results.jsonl`

### Problem Statement

Without this chart, there is no way to decompose token consumption into input vs. output components per model, making it impossible to tell whether high token usage comes from sending too much context (large input) or from verbose LLM reasoning (large output). A user also cannot verify the claimed inverse relationship between heuristic confidence and token cost.

### Claim Statement

A model with a high heuristic percentage ("H: XX%") but still high total tokens indicates the heuristic is catching many emails but the escalated ones are extremely expensive — a concentrated cost pattern. Conversely, a model with low heuristic percentage and low output tokens suggests the LLM is making quick classification decisions even without heuristic help. Wide error bars reveal that token usage is non-deterministic, making cost prediction unreliable for that model.

### Description

Grouped bar chart with error bars (±1σ) and heuristic % overlay. Three bars per model: Input (blue), Output (orange), Total (GAIA orange). "H: XX%" label above each group shows the percentage of emails classified by the heuristic fast-path. Lower bars = more token-efficient classification.

---

## Chart 26: Duration vs Heuristic % (confident=true)

![Latency vs Heuristic Scatter](26_latency_heuristic_scatter.png)

**Status:** Implemented — requires multi-model runs in `results.jsonl`

### Problem Statement

Without this chart, there is no empirical evidence linking heuristic classification rate to end-to-end benchmark duration. A user cannot determine whether faster runs are fast because the heuristic caught more emails, or because the underlying model inference is simply faster — two very different optimization targets.

### Claim Statement

A strong negative correlation (high R²) confirms that heuristic rate is the dominant driver of benchmark speed — improving heuristic coverage is the single most effective optimization. A weak correlation (low R²) reveals that duration is driven by other factors like model load time or network latency, meaning heuristic improvements alone will not meaningfully reduce benchmark runtime. Points in the top-left quadrant represent the Pareto-optimal combination: fast execution with high heuristic utilization.

### Description

Scatter plot with linear regression trend line. X-axis: duration (seconds). Y-axis: heuristic % — (confident emails / total emails) × 100. Point size scaled by email count. R² annotation in top-left quadrant. One color per model.

---

## Chart 27: Projected LLM Calls per Turn (Interactive Session)

![Interactive LLM Activity](27_interactive_llm_activity.png)

**Status:** Implemented — requires interactive mode session data (`interactive.json`). Single model sufficient.

### Problem Statement

Without this chart, there is no visibility into how LLM computational effort distributes across multi-turn conversational sessions. A user cannot tell whether later turns become more efficient as context accumulates, or whether each turn independently consumes the same number of planning and tool calls — a critical distinction for evaluating the interactive mode's scalability to long conversations.

### Claim Statement

A decreasing trend in total LLM calls across turns indicates the agent is learning from accumulated context and requiring fewer planning invocations as the session progresses — good interactive design. A flat or increasing trend indicates each turn is stateless or context-overloaded, requiring full re-planning regardless of prior conversation history. Turns dominated by tool calls (orange-heavy) versus planning calls (blue-heavy) reveal whether the session is action-oriented (managing emails) or reasoning-oriented (classifying and deciding).

### Description

Stacked bar chart showing per-turn LLM call counts. Blue segment = Planning calls (reasoning, classification, decision-making). Orange segment = Tool calls (tool-augmented steps). X-axis: conversation turn number. Total call count annotated above each bar.

---

## Chart 28: Model Performance Radar (Normalized 0-100)

![Model Performance Radar](28_model_performance_radar.png)

**Status:** Implemented — requires ≥ 2 models with complete run data in `results.jsonl`

### Problem Statement

Without this chart, comparing models requires examining six separate metrics across different units (milliseconds, token counts, percentages), making it impossible to form a holistic view of which model performs best overall or where trade-offs exist. A user cannot quickly identify whether a model excels in one dimension at the expense of others, or whether it provides balanced performance.

### Claim Statement

A model with a large, symmetric polygon is the best all-around performer — consistently efficient across speed, token economy, and classification quality. A model with a spiky, asymmetric polygon has a clear specialization (e.g., fast but token-expensive, or token-efficient but slow to escalate) and should be selected only when that specific dimension is prioritized. The radar chart makes it immediately visible whether "bigger models are always better" is true in this benchmark, or whether smaller models achieve comparable normalized scores on specific axes.

### Description

6-axis radar/spider chart (polar plot) with normalized 0-100 scoring. Axes: Duration, Tokens, Steps (lower-is-better); Heuristic % (higher-is-better); CV% (token variation, lower-is-better); Escalation % (lower-is-better). One semi-transparent polygon per model. Larger polygon area = better overall performance. Spiky polygons indicate trade-offs; symmetric polygons indicate balanced performance.

---

## Chart 29: Total LLM Calls Scaling (Planning + Summary + Tools)

![Steps Scaling Heatmap](29_steps_scaling_heatmap.png)

**Status:** Implemented — requires multi-model runs with varying email limits in `results.jsonl`

### Problem Statement

Without this chart, there is no way to assess whether total LLM call volume (including the fixed +2 overhead for summary and final classification) grows predictably with email volume, or whether some models exhibit super-linear scaling where doubling the email count more than doubles the LLM invocations. Chart 24 shows planning steps alone; this chart captures the full operational cost including summary generation.

### Claim Statement

Models that maintain yellow-to-green cells across increasing email limits exhibit predictable, linear scaling — each additional email adds a roughly constant number of LLM calls. Models that transition to purple at higher limits show super-linear scaling, meaning the system complexity grows faster than the input size — a red flag for production deployment at scale. Purple cells at low email limits (e.g., 10-20 emails) indicate fundamental inefficiency: the model is invoking excessive LLM steps even for trivial workloads, independent of scaling behavior.

### Description

Sequential heatmap (`viridis`) showing estimated total LLM calls (`(total_tokens / 2800) + 2`) by model and email limit. Yellow (1-5 calls) = minimal LLM involvement. Green (6-15) = moderate multi-step processing. Purple (16+) = extensive LLM planning and tool usage. White circles mark cells with actual measured data points. Formula annotation in bottom-left corner.
