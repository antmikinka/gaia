# Email Triage Methodology — How Categorization Actually Works

## The Full Data Flow

```
Email arrives (from MBOX / Gmail API)
     │
     ▼
┌──────────────────────────────────────────────────┐
│ triage_inbox_impl()  (read_tools.py:168)         │
│  ┌────────────────────────────────────────────┐  │
│  │ classify_category_heuristic()              │  │
│  │  - Gmail system labels (INBOX, SPAM, etc.) │  │
│  │  - CATEGORY_PROMOTIONS, SOCIAL, UPDATES    │  │
│  │  - Subject keyword matching                │  │
│  │  - Sender pattern matching (noreply, etc.) │  │
│  │  - Phishing keyword pairs                  │  │
│  └──────────────────┬─────────────────────────┘  │
│                     │                             │
│               confident?                          │
│                 /    \                            │
│               Yes      No                         │
│               │        │                          │
│               ▼        ▼                          │
│         Category    LLM re-classification          │
│         locked      (agent planning loop)          │
│         (Python)    (unconstrained categories)     │
└──────────────────────────────────────────────────┘
```

## System Prompt Analysis

The Email Triage Agent system prompt (`src/gaia/agents/email/agent.py:72-108`) contains **no category taxonomy**. At ~324-450 tokens, it covers:

| Section | Tokens | Content |
|---------|--------|---------|
| Role | ~39 | Identity and capabilities |
| Untrusted Input (I1) | ~55 | Prompt injection defense |
| Delimiter Examples | ~68 | Concrete attack examples |
| ACTIONS | ~124 | Tool confirmation levels |
| OUTPUT | ~39 | How to present tool results |

The 4-category taxonomy (`urgent`, `actionable`, `informational`, `low priority`) lives in **two places**:
1. `triage_heuristics.py` — Python constants and rules (invisible to LLM)
2. `triage_inbox` tool docstring (`read_tools.py:340-346`) — visible to LLM only when that tool is called

**Gap**: The system prompt never instructs the agent what to do when `confident=False`. There is no explicit instruction to re-classify those emails, and no shared category vocabulary for the LLM to use.

## Empirical Findings (Real Benchmark Data)

From `results_qwen3.5-35b-a3b-gguf.jsonl` (100 emails, full mode):

| Metric | Value |
|--------|-------|
| Total tokens | 16,728 |
| Duration | 118s |
| Categories found | `informational` (55), `low priority` (45) |
| `confident=True` | **100** (100%) |
| `confident=False` | **0** (0%) |
| `urgent` emails | 0 |
| `actionable` emails | 0 |
| Conversation messages saved | 0 (transient, not persisted) |
| Step results (per-step stats) | 0 (was `show_stats=False`, now fixed) |

**Key finding**: 100% of emails were classified by the heuristic. The LLM was never called for per-email classification. The 16,728 tokens come from the agent's initial planning call (deciding to call `triage_inbox`) and final summary.

## What This Means for Benchmark Interpretation

| Chart | What it appears to measure | What it actually measures |
|-------|--------------------------|--------------------------|
| Chart 1 (Category Distribution) | LLM categorization behavior | Python keyword + label matching |
| Chart 8 (Category Stability) | Deterministic LLM classification | 100% deterministic Python heuristic |
| Charts 5a-5c (LLM Non-Determinism) | LLM variance across identical runs | Wall-clock variance of Python execution + agent overhead |
| Charts 05d, 05e, 13, 14 (TTFT/TPS) | LLM inference speed | LLM speed for the 1-2 calls that DO happen (planning + summary). Now captured after `show_stats=True` fix |

## Is This the Correct Behavior?

**Yes — the heuristic is a deliberate part of the GAIA Email Triage Agent's architecture**, not a benchmark artifact. The agent is designed to avoid wasting LLM calls on obviously-low-priority mail. For a typical Gmail inbox:

- `CATEGORY_PROMOTIONS` / `CATEGORY_SOCIAL` → `low priority` (confident, no LLM)
- `CATEGORY_UPDATES` → `informational` (confident, no LLM)
- `SPAM` → `low priority` + `is_spam=True` (confident, no LLM)
- Automated senders (`noreply@`, `notifications@`) → `informational` (confident, no LLM)
- Promotional subject keywords ("50% off", "newsletter") → `low priority` (confident, no LLM)
- `IMPORTANT` / `STARRED` labels → escalates to LLM (confident=False)
- Everything else → escalates to LLM (confident=False)

**The benchmark measures real agent behavior**, including the heuristic optimization. This is how the agent behaves in production. The limitation is that charts labeled "LLM non-determinism" are mostly measuring Python execution variance, not LLM variance, because the LLM isn't doing per-email categorization on typical inboxes.

## Conversation Not Persisted

The `RunResult` dataclass in `runner.py` does **not** include a `conversation` field. The agent's `process_query()` returns a conversation list, but the runner only reads FROM it to extract:
- `triage_results` (from tool result JSON)
- `step_results` (from system stats messages)

The raw conversation is discarded after extraction. This means detailed per-step LLM behavior (individual tool calls, prompts, responses) cannot be recovered from saved JSONL files — only the aggregated summary data survives.

## Fixes Applied

1. **`show_stats=True`** added to both `EmailAgentConfig` instances in `runner.py` (lines 259, 611). This enables per-step stats capture (TTFT, TPS) in future benchmark runs.

2. **`plot_run_scatter`** (Chart 22) was missing — implemented in `visualize.py:1905`.

3. Existing benchmark data still has zero TTFT/TPS because it was generated before the `show_stats=True` fix. New runs will capture this data.
