# Issue: `--trace` and `--stats` Flags Broken for `gaia email` — And What We Can Do About It

**Observed:** 2026-05-13
**Affected command:** `gaia email` (non-bench invocations)
**Files:**
- `src/gaia/cli.py` — `handle_email_command()` at line 3939
- `src/gaia/agents/email/cli.py` — `main()` at line 27, `_one_shot()` at line 78
- `src/gaia/agents/email/config.py` — `EmailAgentConfig`
- `src/gaia/agents/base/agent.py` — `process_query()` at line 1834, `_process_query_impl()` at line 1872, trace output at line 3490

**Classification:** **CLI WIRING BUG — parent-parser flags parsed but never passed through**

---

## Scope

The `gaia email` command inherits `--trace` and `--stats` from the global parent parser (`cli.py:948`, `cli.py:964`). Both flags are parsed successfully at the CLI level, but the values are **silently discarded** — they never reach the agent.

This means:
- `gaia email --trace -q "Triage my inbox"` — `--trace` is parsed, then ignored
- `gaia email --stats -q "Triage my inbox"` — `--stats` is parsed, then ignored

The flags work for `gaia chat`, `gaia code`, and other agents because their CLI handlers pass the values through. The email CLI handler does not.

---

## Root Cause: Two Wiring Gaps

### Gap 1: `handle_email_command()` never extracts or passes `args.trace`

At `src/gaia/cli.py` lines 4069-4085, the email dispatch to `src/gaia/agents/email/cli.py` normalizes a small subset of args:

```python
# Normalize args the agent CLI expects.
if not hasattr(args, "verbose"):
    args.verbose = False
if not hasattr(args, "debug"):
    args.debug = False
if not hasattr(args, "model"):
    args.model = None
if not hasattr(args, "query"):
    args.query = None
if not hasattr(args, "interactive"):
    args.interactive = False

result = asyncio.run(email_main(args))
```

`args.trace` and `args.show_stats` exist on the `args` namespace (inherited from the parent parser), but are **never normalized or passed through**. They sit unused in the args object.

### Gap 2: `email/cli.py` never reads `args.trace` or `args.show_stats`

At `src/gaia/agents/email/cli.py` lines 27-44, the email CLI constructs `EmailAgentConfig` with only three fields:

```python
config = EmailAgentConfig(
    debug=bool(getattr(args, "debug", False) or getattr(args, "verbose", False)),
    streaming=False,
    silent_mode=False,
)
```

`show_stats` is not set — it defaults to `False` in `EmailAgentConfig.__init__()`.

At lines 78-87, `_one_shot()` calls `process_query` without `trace`:

```python
result = await agent.process_query(query)
```

`process_query()` at `agent.py:1834` accepts `trace: bool = False` and `filename: str = None`, but neither is passed. The same for `_interactive()` at line 90 — `process_query()` is called without `trace`.

---

## What `--trace` Collects (When Wired)

If `trace=True` reaches `process_query()`, the following JSON is written to a file (by `_write_json_to_file()` at line 3490):

```json
{
  "status": "success | failed | incomplete",
  "result": "final text answer",
  "system_prompt": "...",
  "conversation": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."},
    {"role": "tool", "content": "{\"ok\": true, \"data\": {...}}"},
    ...
  ],
  "steps_taken": 12,
  "duration": 487.3,
  "input_tokens": 14520,
  "output_tokens": 2847,
  "total_tokens": 17367,
  "error_count": 0,
  "error_history": [],
  "output_file": "gaia_trace_20260513_140339.json"
}
```

**What's included:**
- Full conversation history (every LLM turn, every tool call, every result)
- Total wall-clock duration
- Aggregated input/output/total token counts (summed from per-step `performance_stats` entries)
- Error count and history
- System prompt text

**What's NOT included:**
- Per-step token breakdown (the per-step data is in the conversation as system messages, but not extracted into a structured array)
- Reasoning tokens (not tracked separately in the result dict)
- Time-to-first-token per LLM call (per-step, available in conversation system messages but not extracted)
- Per-email classification results (this is specific to the email agent's triage output)

### How to get the trace data NOW (without the wiring fix)

The trace is also written to the agent's internal state. After `process_query()` returns, the full result dict is available in `agent.last_result`. If you can intercept the result in the CLI handler, you could write it yourself:

```python
# In handle_email_command(), after email_main() returns:
import json
with open(f"gaia_trace_{time.time()}.json", "w") as f:
    json.dump(agent.last_result, f, indent=2)
```

Alternatively, the agent's console output already shows per-step info on screen — it just isn't captured to a file.

---

## What `--stats` Collects (When Wired)

When `show_stats=True` is passed to `Agent.__init__()`, after each `process_query()` call the `AgentConsole.display_stats()` method renders a Rich table:

```
 Performance Statistics
┌──────────────────────┬──────────┐
│ Duration             │ 487.3s   │
│ Steps Taken          │ 12       │
│ Time to First Token  │ 12.4s    │
│ Tokens per Second    │ 35.6     │
│ Input Tokens         │ 14,520   │
│ Output Tokens        │ 2,847    │
│ Total Tokens         │ 17,367   │
└──────────────────────┴──────────┘
```

This is a console-only output — it does NOT write to a file. It displays the same aggregated metrics as the trace but formatted as a table for human reading.

---

## What `--verbose` / `--debug` Collect (Already Wired)

These ARE properly wired and produce structured log lines to stderr:

**`--verbose` (INFO level):**
```
[2026-05-13 14:03:39] | INFO | gaia.agents.email.log_tool_call | verbose.py:139 | tool_call name=mark_read
[2026-05-13 14:03:39] | INFO | gaia.agents.email.log_tool_call | verbose.py:170 | tool_result name=mark_read ok=True latency=16ms
```

**`--debug` (DEBUG level):** Adds full prompt text and LLM response to logs. Sensitive payloads in logs.

These produce structured lines but are **not machine-parseable as a single JSON document**. They're interleaved with other log lines and require post-processing to extract metrics.

---

## CLI Metrics vs Benchmark Metrics — Full Comparison

| Metric | CLI `--trace` (if wired) | CLI `--stats` (if wired) | CLI `--verbose` (already works) | Benchmark Harness |
|--------|-------------------------|-------------------------|-------------------------------|-------------------|
| Total duration | YES (seconds) | YES (formatted) | NO (scattered log lines) | YES (ms, per-email + total) |
| Steps taken | YES (count) | YES | Partially (log lines) | YES (per-step detail) |
| Input tokens | YES (total) | YES | NO | YES (per-step, per-email, total) |
| Output tokens | YES (total) | YES | NO | YES (per-step, per-email, total) |
| Total tokens | YES | YES | NO | YES |
| Reasoning tokens | NO | NO | NO | YES (estimated from `<thinking>` blocks) |
| TTFT | NO (per-step only in conversation) | YES (per-call) | NO | YES (per-step, per-batch, avg) |
| Tokens/Second | NO | YES | NO | YES (per-step, per-batch, avg) |
| Per-email category | NO (buried in conversation text) | NO | NO | YES (`EmailResult` per email) |
| Per-email duration | NO | NO | NO | YES |
| Spam/phishing flags | NO | NO | NO | YES |
| Confidence flags | NO | NO | NO | YES |
| Category distribution | NO | NO | NO | YES |
| LLM escalation % | NO | NO | NO | YES |
| Cost estimation | NO | NO | NO | YES |
| Quality score | NO | NO | NO | YES (requires ground truth) |
| Cross-run variance | NO | NO | NO | YES |
| Statistical tests | NO | NO | NO | YES (Mann-Whitney U, Cliff's delta) |
| Category stability | NO | NO | NO | YES |
| Full conversation | YES (raw) | NO | NO | Partially (not saved) |
| System prompt | YES | NO | NO | NO |
| Error history | YES | NO | NO | YES |
| Per-step token breakdown | NO (in conversation as system messages) | NO | NO | YES |

---

## Assessment: Can `gaia email` CLI Replace the Benchmark Architecture?

### No — fundamentally different scope

The CLI operates on **one query at a time** against **live Gmail**. The benchmark operates on **batch processing of N emails** from an **MBOX file** across **multiple repeated runs** with **statistical analysis**.

The CLI cannot produce:
- Per-email classification results (the triage results are in the conversation text but not structured)
- Cross-run variance (the CLI runs one query, not N experiments)
- Statistical significance tests (no multi-run data to test)
- Quality scoring against ground truth (no ground truth comparison)
- Category distribution metrics (no structured per-email output)

### Yes — for basic single-run token/duration analysis

If `--trace` and `--stats` were wired, `gaia email` could produce:
- Total duration, input/output/total tokens, steps taken
- Full conversation history (which contains per-step data, just not extracted)
- Error history

This would be sufficient for:
- Quick sanity checks: "how many tokens did this query cost?"
- Debugging a specific query: "what did the model say at each step?"
- Manual comparison of two models on the same query

### The real gap: no structured per-email output from the CLI

The benchmark's key advantage is that it intercepts the `EmailResult` objects — one per email — and extracts structured fields: category, spam, phishing, confident, duration_ms, tokens, etc. The CLI's `process_query()` returns a single result dict with the final answer text, not per-email results.

To get per-email data from the CLI, you would need to either:
1. Parse the conversation text to extract triage results (fragile)
2. Add a structured per-email output to the agent's result dict (modifies `agent.py`)
3. Use the benchmark harness (already does this)

---

## Required Fix

Wire `--trace` and `--stats` through `handle_email_command()` and `email/cli.py`.

### Changes needed (2 files, ~10 lines total)

**File 1: `src/gaia/cli.py`** — `handle_email_command()` at line 4073:
```python
# Add to the normalization block:
if not hasattr(args, "trace"):
    args.trace = False
if not hasattr(args, "show_stats"):
    args.show_stats = False
```

**File 2: `src/gaia/agents/email/cli.py`** — `main()` at line 38 and `_one_shot()`/`_interactive()`:
```python
# In main(), pass show_stats to config:
config = EmailAgentConfig(
    debug=bool(getattr(args, "debug", False) or getattr(args, "verbose", False)),
    streaming=False,
    silent_mode=False,
    show_stats=bool(getattr(args, "show_stats", False)),
)

# In _one_shot() and _interactive(), pass trace to process_query:
result = await agent.process_query(query, trace=getattr(args, "trace", False))
```

**NOTE:** This fix has been analyzed but NOT implemented. The `agent.py` base class cannot be modified, but these two files (CLI wiring) are separate from the base agent and are within scope for fixing.

---

## Architecture Opportunity: Unified Trace-Based Benchmarking

### The Critical Discovery

**The benchmark runner already works by consuming the same `process_query()` result dict that `--trace` writes.**

In `bench/runner.py` lines 323-396:

```python
# The benchmark calls process_query() and gets the standard result dict.
# Then it walks the conversation to extract structured metrics.
conversation = agent_result.get("conversation", [])
for msg in conversation:
    if role == "system" and isinstance(msg.get("content"), dict):
        stats = content["performance_stats"]
        step_results.append(StepResult(...))  # Extract per-step stats
    if role == "tool":
        triage_results = data["results"]      # Extract per-email triage
```

The `--trace` JSON file contains the EXACT same `conversation` array with the EXACT same system messages and tool results. The benchmark doesn't get special data — it just post-processes the same raw data that `--trace` writes to disk.

**This means: the trace JSON already contains all the raw data needed for benchmarking.** The per-email categories, per-step tokens, TTFT, reasoning tokens — it's all there, just buried in the conversation array rather than extracted into structured objects.

### What If We Unified the Two Paths?

Instead of maintaining two separate code paths (CLI for interactive use + benchmark runner for evaluation), what if we made `--trace` the single execution format and built a post-processor that works on ANY trace JSON?

```
Before (two paths):
  gaia email -q "..."              → agent returns result dict → print answer
  bench_runner.py → agent          → result dict → extract metrics → JSONL → report

After (unified path):
  gaia email -q "..." --trace      → writes trace JSON → [post-processor] → structured data → JSONL → report
  gaia email bench --mbox ... --trace → writes trace JSON → [post-processor] → structured data → JSONL → report

Same execution path. Same output format. Same post-processing.
```

### How It Would Work

**Step 1: Wire `--trace` for `gaia email`** (as described above, ~10 lines in 2 files)

**Step 2: Build a trace post-processor** that reads any trace JSON and extracts:
- Per-step stats (from system messages with `performance_stats`)
- Per-email triage results (from `triage_inbox` tool result)
- Reasoning tokens (from `<thinking>` blocks in assistant messages)
- Category distribution (from triage results)
- LLM escalation rate (from triage results' `used_llm` field)
- TTFT, tokens/second (from per-step stats)

This post-processor is essentially the extraction code that already exists in `runner.py` lines 323-430, but refactored into a reusable module that accepts a trace JSON file path as input.

**Step 3: Unified CLI with `--bench` flag**

Add `--bench` to `gaia email` that:
1. Runs the agent with `--trace` (optionally with MBOX backend for reproducibility)
2. Calls the post-processor on the trace JSON
3. Appends structured results to a JSONL file
4. Optionally runs report generation

**Step 4: Report generation reads the JSONL** (already works with current `gaia email report`)

### What Changes vs Current Architecture

| Component | Current | Unified | Status |
|-----------|---------|---------|--------|
| `bench_runner.py` | Creates agent, wraps execution, extracts metrics | Calls CLI with `--trace`, post-processes JSON | Simplified — no wrapper logic |
| `runner.py` (`_run_full_agent`) | Direct `process_query()` call with metric extraction | Same, but output is trace JSON | Unified format |
| `cli.py` (`handle_email_command`) | Doesn't wire `--trace`/`--stats` | Wires both flags | Bug fix |
| `email/cli.py` | Doesn't pass `trace` to `process_query` | Passes `trace`, handles `--bench` | Enhanced |
| `report_generator.py` | Reads JSONL | Reads JSONL (unchanged) | No change needed |
| `variance.py` | Reads JSONL | Reads JSONL (unchanged) | No change needed |
| `visualize.py` | Reads JSONL | Reads JSONL (unchanged) | No change needed |
| New: `trace_extractor.py` | N/A | Post-processes trace JSON → structured | New module |

### What DOESN'T Need to Change

- `agent.py` — no modifications needed
- `report_generator.py`, `variance.py`, `visualize.py` — already consume JSONL, would continue to do so
- The agent's internal logic — just richer output capture

### Benefits

1. **One code path:** CLI and benchmark run the same agent code, produce the same format
2. **Debuggable:** Every benchmark run has a full trace JSON you can inspect
3. **Simpler maintenance:** No wrapper functions to keep in sync with agent internals
4. **Live Gmail benchmarking:** Could benchmark against real Gmail (with `--trace`), not just MBOX
5. **Post-hoc analysis:** The trace JSON is a permanent record you can re-analyze with new tools later

### Risks

1. **Trace file size:** Full conversation JSON can be large (50-200KB per run for long conversations). But this is acceptable for benchmarking where you run maybe 10-30 experiments.
2. **Post-processor coupling:** The post-processor needs to understand the conversation structure (system messages, tool results, triage format). If the agent's conversation format changes, the post-processor breaks. But this is the same coupling the current benchmark runner already has.

---

## Related Issues

- **ISSUE-parallel-tool-calls.md** — Parallel tool call retry prompt bug (in `agent.py`, cannot fix)
- **ISSUE-mutation-tool-repetition-loop.md** — Repetition loop on mutation tools (in `agent.py`, cannot fix)
- This issue is different: it's a CLI wiring bug, NOT a base agent bug. The fix touches only `cli.py` and `email/cli.py`, not `agent.py`.
