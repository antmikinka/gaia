# SMART Interactive Benchmark Analysis — Charts

**Generated from:** `smart_benchmark_analysis.json`  
**Purpose:** Professional analysis of `--mode interactive --smart` behavior

---

## Chart 01: Heuristic vs LLM Coverage in SMART Mode

![Heuristic vs LLM Split](smart_charts/01_heuristic_vs_llm_split.png)

**Core Problem Statement**  
In normal full mode the heuristic catches 95–100% of emails. In SMART mode on the stratified dataset, it only catches ~2 emails per run.

**Core Claim**  
The current SMART implementation escalates 90–96% of emails to the LLM, largely defeating the purpose of the heuristic pre-filter on balanced datasets.

**Description**  
Grouped bar chart showing the percentage of emails handled by the heuristic vs sent to the LLM across models.

---

## Chart 02: Token Consumption Scaling

![Token Scaling](smart_charts/02_token_scaling.png)

**Core Problem Statement**  
Token usage grows very aggressively with email limit in SMART mode.

**Core Claim**  
At limit 100, some runs exceed 1.9 million tokens. The dominant cost comes from repeated `get_message` calls rather than final classification.

**Description**  
Line chart showing total token consumption as email limit increases.

---

## Chart 03: Duration Comparison (Limit = 100)

![Duration Comparison](smart_charts/03_duration_comparison.png)

**Core Problem Statement**  
Larger models show significantly higher latency in SMART interactive mode.

**Core Claim**  
The 4B and 9B models take 3–4× longer than the 0.8B model at limit 100, with no clear quality gain in the current results.

**Description**  
Bar chart comparing average duration across models at the highest tested limit.

---

## Chart 04: Final Category Distribution

![Category Distribution](smart_charts/04_category_distribution.png)

**Core Problem Statement**  
Despite 90–96% of emails going through the LLM, almost no `urgent` or `actionable` emails appear in the final output.

**Core Claim**  
The LLM in SMART mode is heavily defaulting to `informational`, or the final summarization step is collapsing categories.

**Description**  
Grouped bar chart of final category counts by model.

---

## Chart 05: Tokens per Email (Efficiency)

![Tokens per Email](smart_charts/05_tokens_per_email.png)

**Core Problem Statement**  
Token cost per email varies significantly across models and limits.

**Core Claim**  
Smaller models can sometimes be more token-efficient in SMART mode than larger ones on this workload.

**Description**  
Box plot showing tokens consumed per email across models.

---

## Chart 06: SMART Mode Success Rate by Model

![Success Rate](smart_charts/06_success_rate.png)

**Core Problem Statement**  
The 35B model had a 0% success rate in the collected runs.

**Core Claim**  
Most 35B failures were caused by `--smart` not being recognized (argparse errors), indicating the flag was not available in the installed GAIA version during testing.

**Description**  
Bar chart showing percentage of successfully completed runs per model.

---

**Summary**

| Chart | Key Finding | Implication |
|-------|-------------|-------------|
| 01    | Heuristic coverage collapsed to ~2 emails | SMART mode is behaving close to force-LLM on this dataset |
| 02    | Token usage scales very poorly | Main cost driver = repeated `get_message` calls |
| 03    | Larger models are much slower | Latency penalty without clear quality benefit |
| 04    | Almost no urgent/actionable in output | Quality of LLM classification needs investigation |
| 05    | Token efficiency varies widely | Smaller models can be competitive |
| 06    | 35B had 0% success | `--smart` flag was likely not installed/available |

> **Note:** These charts are based on the current implementation of `--smart` in interactive mode. The behavior may evolve as the feature matures.



## Chart 07: Estimated Token Source Breakdown (Proxy Analysis)

![Token Sources](smart_charts/07_token_sources_breakdown.png)

**Core Problem Statement**  
It is currently difficult to know exactly where the massive token consumption in SMART mode is coming from.

**Core Claim**  
The majority of tokens in SMART interactive mode are **not** coming from the final LLM classification. They are dominated by:
1. Repeated `get_message` calls (sending full email bodies into context)
2. Planning + multi-turn reasoning overhead

**Description**  
Stacked bar chart using proxy estimation from available log data:
- **Red**: Estimated tokens from `get_message` calls (body transmission)
- **Orange**: Estimated planning + multi-turn reasoning tokens
- **Blue**: Remaining tokens attributed to actual LLM classification work

**Key Insight**  
`get_message` calls appear to be the single largest token consumer in the current SMART implementation. This explains why token counts scale so aggressively with limit.