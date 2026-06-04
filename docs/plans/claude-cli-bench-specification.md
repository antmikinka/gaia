# Claude CLI Email Benchmark Runner -- Technical Specification

## Overview

A standalone benchmark runner that classifies 1000 stratified emails using the Claude CLI (`claude --bare`) with embedded SKILL.md classification rules. Produces GAIA-compatible JSONL output that feeds directly into the existing visualization, cost analysis, comparison, and report pipelines.

---

## 1. Required Fix: Add `"claude-cli"` to COLORS

**File**: `src/gaia/agents/email/bench/visualize.py`
**Location**: Line 54, inside the `COLORS` dict
**Change**: Add one entry after the `"clawflow"` line:

```python
COLORS = {
    ...
    "clawflow": "#3182CE",  # Blue
    "claude-cli": "#8B5CF6",  # Purple -- Anthropic Claude CLI benchmark
}
```

This enables all chart functions that look up framework colors by name (e.g., `_plot_per_model_bars`, `plot_framework_category_comparison`) to render Claude CLI bars in purple alongside GAIA (orange) and ClawFlow (blue).

---

## 2. File 1: `claude_cli_bench.py` -- Main Orchestrator

**Path**: `src/gaia/agents/email/bench/claude_cli_bench.py`
**Size**: ~250 lines

### 2.1 Imports

```python
from __future__ import annotations

import json
import subprocess
import time
import signal
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gaia.agents.email.bench.data_shapes import (
    BatchResult,
    EmailResult,
    RunResult,
    StepResult,
)
from gaia.agents.email.bench.claude_prompt import build_classification_prompt
from gaia.agents.email.bench.claude_result_adapter import (
    parse_claude_output,
    build_run_result,
)
```

### 2.2 CLI Invocation Template

```python
def _invoke_claude_cli(
    prompt: str,
    *,
    model: str = "sonnet",
    max_budget_usd: float = 1.0,
    timeout_secs: int = 60,
) -> tuple[str, dict, float]:
    """Run claude --bare with the given prompt.

    Returns:
        (raw_stdout, parsed_json_stats, duration_secs)

    The claude CLI emits a JSON stats block at the end of --bare output.
    This function captures stdout, extracts the JSON block, and returns
    both the classification text and the token/cost metadata.

    CLI command:
        claude --bare -p "<prompt>" \
            --output-format json \
            --dangerously-skip-permissions \
            --no-session-persistence \
            --max-budget-usd 1 \
            --model sonnet
    """
    cmd = [
        "claude",
        "--bare",
        "-p", prompt,
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--max-budget-usd", str(max_budget_usd),
        "--model", model,
    ]

    start = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_secs,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start
        raise TimeoutError(
            f"claude CLI timed out after {duration:.1f}s on email"
        ) from exc

    duration = time.monotonic() - start

    # Parse the JSON output. With --output-format json, the entire
    # stdout is a JSON object containing both the response and usage stats.
    parsed = json.loads(result.stdout)
    return result.stdout, parsed, duration
```

### 2.3 Checkpoint Format

**File name**: `checkpoint_claude_cli_<run_slug>.json`
**Location**: Same directory as output JSONL

```python
@dataclass
class Checkpoint:
    """Resume state for the Claude CLI benchmark runner."""
    run_id: str
    timestamp: str
    model: str
    jsonl_input_path: str
    jsonl_output_path: str
    next_email_index: int        # 0-based index into the input JSONL
    email_results_so_far: list   # List of EmailResult dicts (already serialized)
    total_input_tokens: int      # Cumulative across completed emails
    total_output_tokens: int
    total_reasoning_tokens: int
    total_duration_ms: int
    is_cold_start_done: bool     # True once the first (uncached) email completed
    partial_batch: list          # EmailResult dicts not yet flushed (for Ctrl+C)
```

**Serialization**:
```python
def save_checkpoint(cp: dict, path: Path) -> None:
    """Write checkpoint atomically (write to .tmp, then rename)."""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cp, f, indent=2, ensure_ascii=False)
    tmp.replace(path)

def load_checkpoint(path: Path) -> dict | None:
    """Load checkpoint if it exists, else None."""
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None
```

### 2.4 Main Function Signature

```python
def run_claude_cli_benchmark(
    jsonl_path: str,
    *,
    model: str = "sonnet",
    limit: int = 1000,
    output_dir: str = "benchmark_results",
    checkpoint_interval: int = 25,
    resume: bool = True,
    fail_fast: bool = False,
    email_timeout_secs: int = 60,
    skip_cold_start: bool = False,
) -> RunResult:
    """Run the Claude CLI email classification benchmark.

    Args:
        jsonl_path: Path to stratified_1000.jsonl (or any email JSONL).
        model: Claude model alias (default "sonnet").
        limit: Max emails to process (0 = all).
        output_dir: Directory for results JSONL and checkpoints.
        checkpoint_interval: Save checkpoint every N emails (default 25).
        resume: If True, look for existing checkpoint and continue.
        fail_fast: Abort on first email classification failure.
        email_timeout_secs: Per-email subprocess timeout.
        skip_cold_start: If True, do NOT mark first email as cold start.

    Returns:
        RunResult compatible with the existing bench pipeline.
    """
```

### 2.5 Processing Loop (Pseudocode)

```
1. Generate run_id, timestamp
2. Determine checkpoint path: output_dir / "checkpoint_claude_cli_<slug>.json"
3. If resume and checkpoint exists:
     Load checkpoint -> restore next_email_index, email_results_so_far, token totals
   Else:
     next_email_index = 0, email_results_so_far = [], token totals = 0, is_cold_start_done = False
4. Open input JSONL, skip to next_email_index
5. For each email (index from next_email_index to limit):
     a. Build prompt via build_classification_prompt(email)
     b. is_cold = (not is_cold_start_done) and (not skip_cold_start)
     c. Invoke claude CLI, capture (raw, stats, duration)
     d. Parse result via parse_claude_output(raw, stats)
     e. Build EmailResult from parsed data + email metadata
     f. Append to email_results_so_far, update token totals
     g. If is_cold: is_cold_start_done = True
     h. If (index + 1) % checkpoint_interval == 0:
          Save checkpoint with current state
6. Build single BatchResult (batch_number=1, batch_size=total, total_batches=1)
7. Build RunResult via build_run_result(...)
8. Serialize to JSONL via save_jsonl(run, output_path)
9. Delete checkpoint file (run completed)
10. Return RunResult
```

### 2.6 KeyboardInterrupt Handling

```python
def _signal_handler(signum, frame):
    """Handle Ctrl+C: flush partial results and save checkpoint."""
    # Called from the main loop's try/except KeyboardInterrupt block
    # 1. Flush any partial_batch into email_results_so_far
    # 2. Save checkpoint with next_email_index = current_index + 1
    # 3. Print: "Interrupted at email N/M. Checkpoint saved. Resume with --resume"
    # 4. sys.exit(1) -- results up to this point are preserved
```

### 2.7 JSONL Output Shape

One line per run (not per email). The JSONL line is a `RunResult` serialized via `_run_result_to_dict` from `output.py`:

```json
{
  "run_id": "claude-cli-20260604-143022-sonnet-a1b2c3",
  "timestamp": "2026-06-04T14:30:22.000000+00:00",
  "model": "claude-sonnet-4-6",
  "source_framework": "claude-cli",
  "provider": "anthropic",
  "mbox_path": "",
  "jsonl_path": "data/stratified_1000.jsonl",
  "data_source": "jsonl",
  "mode": "claude-cli",
  "total_emails": 1000,
  "total_duration_ms": 8400000,
  "total_input_tokens": 4567890,
  "total_output_tokens": 234567,
  "total_reasoning_tokens": 0,
  "total_tokens": 4802457,
  "avg_time_to_first_token_ms": 0.0,
  "avg_tokens_per_second": 0.0,
  "is_cold_start": false,
  "category_counts": {"urgent": 45, "actionable": 230, "informational": 580, "low priority": 145},
  "status": "completed",
  "error": "",
  "heuristic_only_count": 0,
  "llm_processed_count": 1000,
  "batch_results": [{
    "batch_number": 1,
    "batch_size": 1000,
    "total_batches": 1,
    "email_results": [... 1000 EmailResult objects ...],
    "duration_ms": 8400000,
    "total_input_tokens": 4567890,
    "total_output_tokens": 234567,
    "total_reasoning_tokens": 0,
    "total_tokens": 4802457,
    "avg_time_to_first_token_ms": 0.0,
    "avg_tokens_per_second": 0.0,
    "categories": ["urgent", "actionable", "informational", "low priority"],
    "status": "ok",
    "error": ""
  }],
  "step_results": []
}
```

Each `EmailResult` within `batch_results[0].email_results`:

```json
{
  "email_id": "email_0001",
  "subject": "Your Amazon order has shipped",
  "sender": "shipping@amazon.com",
  "label_ids": ["INBOX"],
  "category": "informational",
  "is_spam": false,
  "is_phishing": false,
  "confident": true,
  "reason": "Order confirmation with tracking number, no action required",
  "llm_summary": "",
  "duration_ms": 6200,
  "input_tokens": 4523,
  "output_tokens": 218,
  "reasoning_tokens": 0,
  "total_tokens": 4741,
  "time_to_first_token_ms": 0.0,
  "tokens_per_second": 0.0,
  "status": "ok",
  "error": ""
}
```

---

## 3. File 2: `claude_prompt.py` -- Prompt Builder

**Path**: `src/gaia/agents/email/bench/claude_prompt.py`
**Size**: ~80 lines

### 3.1 Prompt Template

```python
CLASSIFICATION_PROMPT_TEMPLATE = """You are an email triage classifier. Classify the following email into exactly ONE category.

CATEGORIES (choose exactly one):
- urgent: Requires immediate attention today (deadline, crisis, escalation from senior leadership).
- actionable: Requires a response or action within the next few days (meeting invite with RSVP, question requiring answer, task assignment).
- informational: Useful to know but requires no action (FYI, newsletter with interesting content, status update, order confirmation).
- low priority: Can be safely ignored or archived (promotions, marketing, social notifications, bulk mail).

RULES:
1. Check for phishing FIRST. If the email shows signs of phishing (suspicious sender domain, urgent financial request, mismatched URLs, grammar/spelling errors typical of scams), set is_phishing=true and classify as "urgent".
2. Sender reputation matters: emails from known internal colleagues are more likely actionable; unknown external senders are more likely informational or low priority.
3. Subject line + body text together determine category. Do not classify based on subject alone.
4. If the email contains a specific request with a deadline or time sensitivity, it is "urgent" or "actionable".
5. Marketing, promotional content, and automated notifications are "low priority".
6. Meeting invitations that require RSVP are "actionable".
7. Order confirmations, shipping notifications, and receipts are "informational".
8. When uncertain between two categories, choose the one that would cause LESS harm if misclassified (prefer actionable over informational).

Respond with ONLY a JSON object (no markdown, no code blocks, no explanation outside the JSON):
{{
  "category": "<one of: urgent, actionable, informational, low priority>",
  "is_phishing": <true or false>,
  "confident": <true or false>,
  "reason": "<one sentence explaining the classification>"
}}

EMAIL TO CLASSIFY:
---
From: {sender}
Subject: {subject}
Date: {date}

{body_text}
---"""
```

### 3.2 Function Signature

```python
def build_classification_prompt(email: dict) -> str:
    """Build the classification prompt from an email dict.

    Args:
        email: Dict with keys: sender, subject, body_text, date (from JSONL input).

    Returns:
        Formatted prompt string ready for claude --bare -p.

    Notes:
        - Full body_text is included (not truncated) for phishing signal detection.
        - No JSON schema wrapper in the prompt; the JSON output shape is enforced
          by the instruction text + claude CLI --output-format json.
    """
    sender = email.get("sender", "unknown")
    subject = email.get("subject", "(no subject)")
    body = email.get("body_text", "")
    date = email.get("date", "unknown")

    return CLASSIFICATION_PROMPT_TEMPLATE.format(
        sender=sender,
        subject=subject,
        date=date,
        body_text=body,
    )
```

---

## 4. File 3: `claude_result_adapter.py` -- Result Parser

**Path**: `src/gaia/agents/email/bench/claude_result_adapter.py`
**Size**: ~120 lines

### 4.1 Parse Claude CLI JSON Output

The `claude --bare --output-format json` response shape:

```json
{
  "type": "result",
  "content": [
    {
      "type": "text",
      "text": "{\"category\": \"informational\", \"is_phishing\": false, \"confident\": true, \"reason\": \"...\"}"
    }
  ],
  "usage": {
    "input_tokens": 6,
    "cache_creation_input_tokens": 4541,
    "cache_read_input_tokens": 0,
    "output_tokens": 267
  },
  "cost_usd": 0.0351
}
```

### 4.2 Functions

```python
def parse_claude_output(raw_stdout: str, parsed_json: dict) -> dict:
    """Extract classification result and metadata from claude CLI output.

    Args:
        raw_stdout: Raw stdout from claude --bare (may contain extra text).
        parsed_json: The JSON-parsed stdout (from json.loads).

    Returns:
        Dict with: category, is_phishing, confident, reason,
                   input_tokens, cache_creation, cache_read, output_tokens,
                   cost_usd, duration_ms

    Handles:
        - Text wrapped in markdown code blocks (strip ```json ... ```)
        - Nested content array (extract first text block)
        - Malformed JSON in the text field (graceful error)
    """
    # Extract the text content from the response.
    content = parsed_json.get("content", [])
    text = ""
    for block in content:
        if block.get("type") == "text":
            text = block["text"]
            break

    # Strip markdown code blocks if present.
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]  # remove opening ```json
    if text.endswith("```"):
        text = text.rsplit("\n", 1)[0]  # remove closing ```
    text = text.strip()

    classification = json.loads(text)

    usage = parsed_json.get("usage", {})
    return {
        "category": classification.get("category", "informational"),
        "is_phishing": classification.get("is_phishing", False),
        "confident": classification.get("confident", True),
        "reason": classification.get("reason", ""),
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "cache_creation": usage.get("cache_creation_input_tokens", 0) or 0,
        "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "cost_usd": parsed_json.get("cost_usd", 0.0) or 0.0,
    }


def build_email_result(
    email: dict,
    classification: dict,
    duration_secs: float,
) -> EmailResult:
    """Build an EmailResult from an email dict and classification result.

    Args:
        email: Input email dict (id, sender, subject, etc.)
        classification: Output from parse_claude_output()
        duration_secs: Wall-clock seconds for this classification.

    Returns:
        EmailResult dataclass instance.
    """
    total_tokens = (
        classification["input_tokens"]
        + classification["cache_creation"]
        + classification["cache_read"]
        + classification["output_tokens"]
    )

    return EmailResult(
        email_id=email.get("id", "unknown"),
        subject=email.get("subject", ""),
        sender=email.get("sender", ""),
        label_ids=email.get("label_ids", []),
        category=classification["category"],
        is_spam=False,
        is_phishing=classification["is_phishing"],
        confident=classification["confident"],
        reason=classification["reason"],
        duration_ms=int(duration_secs * 1000),
        input_tokens=classification["input_tokens"] + classification["cache_creation"] + classification["cache_read"],
        output_tokens=classification["output_tokens"],
        reasoning_tokens=0,
        total_tokens=total_tokens,
        status="ok",
        error="",
    )


def build_run_result(
    email_results: list[EmailResult],
    *,
    run_id: str,
    timestamp: str,
    model: str,
    jsonl_path: str,
    total_duration_ms: int,
    is_cold_start: bool = False,
) -> RunResult:
    """Build a RunResult from all email results.

    Computes aggregate token counts, category counts, and wraps
    everything in a single BatchResult (batch_number=1).

    Args:
        email_results: All EmailResult instances from the run.
        run_id: Unique run identifier.
        timestamp: ISO-8601 timestamp.
        model: Model string (e.g., "claude-sonnet-4-6").
        jsonl_path: Path to the input JSONL file.
        total_duration_ms: Wall-clock milliseconds for the full run.
        is_cold_start: Whether this run includes the cold-start email.

    Returns:
        RunResult dataclass instance compatible with the bench pipeline.
    """
    total_input = sum(e.input_tokens for e in email_results)
    total_output = sum(e.output_tokens for e in email_results)
    total_reasoning = sum(e.reasoning_tokens for e in email_results)
    total_tokens = sum(e.total_tokens for e in email_results)

    category_counts: dict[str, int] = {}
    for e in email_results:
        cat = e.category
        category_counts[cat] = category_counts.get(cat, 0) + 1

    batch = BatchResult(
        batch_number=1,
        batch_size=len(email_results),
        total_batches=1,
        email_results=email_results,
        duration_ms=total_duration_ms,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_reasoning_tokens=total_reasoning,
        total_tokens=total_tokens,
        categories=list(category_counts.keys()),
        status="ok",
    )

    run = RunResult(
        run_id=run_id,
        timestamp=timestamp,
        model=model,
        provider="anthropic",
        jsonl_path=jsonl_path,
        data_source="jsonl",
        mode="claude-cli",
        batch_results=[batch],
        step_results=[],
        total_emails=len(email_results),
        total_duration_ms=total_duration_ms,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_reasoning_tokens=total_reasoning,
        total_tokens=total_tokens,
        category_counts=category_counts,
        is_cold_start=is_cold_start,
        source_framework="claude-cli",
        status="completed",
    )

    return run
```

---

## 5. CLI Integration

### 5.1 New Subcommand

Add to `cli.py` build_parser():

```python
# Subcommand: claude-cli
cc_parser = subparsers.add_parser(
    "claude-cli",
    help="Run Claude CLI email classification benchmark. Outputs claude_cli_results.jsonl.",
)
cc_parser.add_argument(
    "--jsonl-path",
    type=str,
    required=True,
    help="Path to email JSONL file (e.g., stratified_1000.jsonl).",
)
cc_parser.add_argument(
    "--model",
    type=str,
    default="sonnet",
    help="Claude model alias (default: sonnet).",
)
cc_parser.add_argument(
    "--limit",
    type=int,
    default=0,
    help="Max emails to process (0 = all). Default 0.",
)
cc_parser.add_argument(
    "--output-dir",
    type=str,
    default="benchmark_results",
    help="Directory for results. Default 'benchmark_results'.",
)
cc_parser.add_argument(
    "--checkpoint-interval",
    type=int,
    default=25,
    help="Save checkpoint every N emails. Default 25.",
)
cc_parser.add_argument(
    "--no-resume",
    action="store_true",
    help="Ignore existing checkpoint and start fresh.",
)
cc_parser.add_argument(
    "--fail-fast",
    action="store_true",
    help="Abort on first email classification failure.",
)
cc_parser.add_argument(
    "--timeout",
    type=int,
    default=60,
    help="Per-email subprocess timeout in seconds. Default 60.",
)
cc_parser.add_argument(
    "--skip-cold-start",
    action="store_true",
    help="Do not mark first email as cold start.",
)
```

### 5.2 CLI Handler

```python
elif args.bench_action == "claude-cli":
    from gaia.agents.email.bench.claude_cli_bench import run_claude_cli_benchmark
    from gaia.agents.email.bench.output import save_jsonl, print_summary
    from gaia.agents.email.bench.visualize import _extract_run_suffix

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    limit = args.limit or None  # 0 means no limit

    result = run_claude_cli_benchmark(
        jsonl_path=args.jsonl_path,
        model=args.model,
        limit=limit if limit else 0,
        output_dir=args.output_dir,
        checkpoint_interval=args.checkpoint_interval,
        resume=not args.no_resume,
        fail_fast=args.fail_fast,
        email_timeout_secs=args.timeout,
        skip_cold_start=args.skip_cold_start,
    )

    slug = _extract_run_suffix(result.run_id) if result.run_id else "claude-cli"
    jsonl_path = output_dir / f"claude_cli_results_{slug}.jsonl"
    save_jsonl(result, jsonl_path)
    print_summary(result)
    print(f"\n  Results saved to: {jsonl_path}")
    return 0
```

### 5.3 Usage Examples

```bash
# Full 1000-email benchmark with default settings
gaia email claude-cli --jsonl-path data/stratified_1000.jsonl

# Quick test with 10 emails
gaia email claude-cli --jsonl-path data/stratified_1000.jsonl --limit 10

# Resume after Ctrl+C interruption
gaia email claude-cli --jsonl-path data/stratified_1000.jsonl

# Fresh run (ignore checkpoint)
gaia email claude-cli --jsonl-path data/stratified_1000.jsonl --no-resume

# Generate reports + charts including Claude CLI results
gaia email report --input-dir benchmark_results --charts
```

---

## 6. Data Flow

```
stratified_1000.jsonl
    |
    v
load_emails(jsonl_path)           [read each line as dict]
    |
    v
build_classification_prompt(email) [format prompt template]
    |
    v
subprocess: claude --bare -p "..."  [invoke CLI, capture stdout]
    |
    v
parse_claude_output(raw, parsed)   [extract classification + usage]
    |
    v
build_email_result(email, parsed)  [create EmailResult]
    |
    v
[accumulate 25 emails] -> save_checkpoint()  [periodic checkpoint]
    |
    v
build_run_result(all_results)      [create RunResult + BatchResult]
    |
    v
save_jsonl(run, output_path)       [append to results JSONL]
    |
    v
[existing pipeline]
    +-> 0_planning_insights.py     [charts]
    +-> analyze_cost.py            [cost analysis]
    +-> compare.py                 [framework comparison]
    +-> report_generator.py        [full report]
```

---

## 7. Compatibility Requirements

### 7.1 With `analyze_cost.py`

Add pricing entry for Claude Sonnet:

**File**: `src/gaia/agents/email/bench/analyze_cost.py`
**Location**: `_PRICING_PER_1M` dict (line 27-37)

```python
_PRICING_PER_1M: dict[str, tuple[float, float]] = {
    ...
    "claude-sonnet-4-6": (3.0, 15.0),          # already present
    "claude-sonnet-4-20250514": (3.0, 15.0),   # add dated variant
    "sonnet": (3.0, 15.0),                      # add short alias
}
```

The `_lookup_pricing` function uses prefix matching, so `"claude-sonnet"` entries will match any model string starting with that prefix.

### 7.2 With `visualize.py` COLORS

Add `"claude-cli": "#8B5CF6"` to COLORS dict (see Section 1).

### 7.3 With `output.py` serialization

The `RunResult` uses `source_framework="claude-cli"` which:
- `_run_result_to_dict` reads it via `getattr(run, "source_framework", "gaia")`
- `_run_to_csv_rows` includes it in the CSV `source_framework` column
- `save_jsonl` serializes it via `_run_result_to_dict`

### 7.4 With `compare.py` framework comparison

The `compare.py` module compares GAIA vs ClawFlow. To extend for Claude CLI:

- The `_email_categories_from_run` function works on any run dict with `batch_results[].email_results[]` shape (compatible).
- `FrameworkComparison` uses framework-agnostic field names (`gaia_*` vs `clawflow_*`); a three-way comparison would need a new dataclass or the existing one extended with `claude_*` fields.

For the initial scope, Claude CLI results appear in the same `results.jsonl` (or separate `claude_cli_results.jsonl`) and are consumed by the report generator alongside existing framework results. Charts render them via the COLORS lookup.

### 7.5 With `report_generator.py`

The report generator loads all `*.jsonl` files from the input directory. The Claude CLI JSONL output follows the same `RunResult` shape, so it will be:
- Included in model comparison charts
- Included in category distribution charts
- Included in cost analysis (if pricing is configured)

---

## 8. Checkpoint File Format (Complete)

```json
{
  "run_id": "claude-cli-20260604-143022-sonnet-a1b2c3",
  "timestamp": "2026-06-04T14:30:22.000000+00:00",
  "model": "claude-sonnet-4-6",
  "jsonl_input_path": "data/stratified_1000.jsonl",
  "jsonl_output_path": "benchmark_results/claude_cli_results_a1b2c3.jsonl",
  "next_email_index": 175,
  "email_results_so_far": [
    {"email_id": "email_0001", "subject": "...", "category": "informational", ...},
    ... 174 more EmailResult dicts ...
  ],
  "total_input_tokens": 789456,
  "total_output_tokens": 42130,
  "total_reasoning_tokens": 0,
  "total_duration_ms": 1470000,
  "is_cold_start_done": true,
  "partial_batch": []
}
```

---

## 9. Error Handling Matrix

| Scenario | Behavior |
|----------|----------|
| `claude` CLI not in PATH | Fail immediately with actionable error: "claude CLI not found. Install with `npm install -g @anthropic-ai/claude-code`" |
| Subprocess timeout (60s) | Log error for that email, mark EmailResult status="error", continue (unless --fail-fast) |
| Non-JSON response from Claude | Parse error: log warning, set category="informational", confident=False, status="parse_error" |
| KeyboardInterrupt (Ctrl+C) | Save checkpoint, print resume instructions, exit with code 1 |
| Checkpoint file corrupted | Ignore checkpoint, start fresh, print warning |
| Email JSONL malformed line | Skip line, log warning, continue |
| First email fails (cold start) | Retry once, if still fails: abort with error (cold start is critical) |

---

## 10. Expected Performance (Based on Live Test Data)

| Metric | Cold (1st email) | Warm (2nd-1000th) | 1000-email total |
|--------|-----------------|-------------------|------------------|
| Duration | ~8s | ~6s | ~6,008s (~100 min) |
| Input tokens | 4,547 (6 + 4,541 cache_creation) | 4,526 (6 + 216 + 4,310 cache_read) | ~4,524,000 |
| Output tokens | 267 | ~218 | ~218,000 |
| Cost | $0.035 | $0.009 | ~$9.03 |
| cache_creation | 4,541 | 216 | 4,541 + (999 * 216) |
| cache_read | 0 | 4,310 | 999 * 4,310 |

Note: The `--no-session-persistence` flag means each invocation is independent. Prompt caching works at the API level (Anthropic's prompt cache), not the CLI session level. The warm-cache benefit comes from the system prompt + classification rules being cached by the API across calls.

---

## 11. File Summary

| File | Path | Lines | Purpose |
|------|------|-------|---------|
| `claude_cli_bench.py` | `src/gaia/agents/email/bench/claude_cli_bench.py` | ~250 | Main orchestrator: CLI invocation, loop, checkpoint, signal handling |
| `claude_prompt.py` | `src/gaia/agents/email/bench/claude_prompt.py` | ~80 | Prompt template builder from SKILL.md rules |
| `claude_result_adapter.py` | `src/gaia/agents/email/bench/claude_result_adapter.py` | ~120 | Parse CLI output, build EmailResult/RunResult |
| **Existing fixes** | | | |
| `visualize.py` COLORS | Line 54 | +1 line | Add `"claude-cli": "#8B5CF6"` |
| `analyze_cost.py` pricing | Line 27-37 | +2 lines | Add sonnet pricing entries |
| `cli.py` subcommand | After line 204 | ~40 lines | Add `claude-cli` subcommand parser + handler |
