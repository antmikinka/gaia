# Quick Reference: Email Benchmark Smart Mode

## Running Benchmarks

### Interactive Smart Mode (recommended for production cost estimation)

```bash
gaia email bench --mode interactive --smart --limit 100 --model <model_id>
```

### Interactive Smart with Force LLM (tests LLM classification quality)

```bash
gaia email bench --mode interactive --smart --force-llm --limit 100
```

### Interactive Non-Smart (tests full agent planning loop)

```bash
gaia email bench --mode interactive --limit 10
```

### Full Mode (single-turn, all emails through LLM)

```bash
gaia email bench --mode full --limit 100
```

### Batched Mode (batch LLM calls for non-confident emails)

```bash
gaia email bench --mode batched --batched --batch-size 10 --limit 100
```

### With mbox path

```bash
gaia email bench --mode interactive --smart --mbox-path /path/to/inbox.mbox --limit 50
```

### With JSONL path (no mbox required)

```bash
gaia email bench --mode interactive --smart --jsonl-path /path/to/emails.jsonl --limit 50
```

---

## Verifying You Are on the Fixed Path

### 1. Check the per-turn output

The fixed path shows a smart-mode breakdown:

```
  Smart-Mode Breakdown
  Heuristic (confident): 7 emails
  LLM (non-confident): 3 emails
  Heuristic savings:     ~150 tokens (7 LLM calls avoided)
```

If you see LLM planning steps with no heuristic breakdown, you are on the old path.

### 2. Check token counts

- Fixed path: heuristic-only turns show `total_tokens: 0` or very low counts.
- Old path: every turn shows 50K-200K tokens.

### 3. Verify the code path

```bash
grep -n "process_interactive_smart_triage" src/gaia/agents/email/bench/runner.py
```

You should see calls to `process_interactive_smart_triage` when `enable_smart_mode=True`.

### 4. Check git log

```bash
git log --oneline --grep="smart" -- src/gaia/agents/email/
```

You should see commits adding `process_interactive_smart_triage` and fixing the dispatch logic.

---

## Common Issues

### Token counts are all 0

This is correct when all emails are heuristic-confident. No LLM was invoked. Check the "Heuristic savings" section of the output for estimated tokens avoided.

### Smart mode not triggering

- Ensure both `--mode interactive` AND `--smart` flags are present.
- The first-turn prompt must contain a triage verb: "triage", "categorize", or "classify".
- "Show me my inbox" is a summary request, not a triage request -- it will use `process_query()`.

### Token counts still high (>100K at limit 100)

- You may be on the old code path. Verify the dispatch fix is present.
- Check if `--force-llm` is set -- this bypasses the heuristic and sends all emails through the LLM.
- Non-confident email composition may be high. Check the heuristic rate in the summary.

### Charts show pre-fix and post-fix data mixed

Do not mix pre-fix and post-fix results in the same chart. The measurement instrument changed. Re-run old benchmarks with the new code or label them clearly.

---

## Where to Find Documentation

| Document | Path |
|----------|------|
| PR1 Description | `benchmark_charts/PR1-DESCRIPTION.md` |
| PR2 Description | `benchmark_charts/PR2-DESCRIPTION.md` |
| Changelog | `benchmark_charts/CHANGELOG-INTERACTIVE-SMART-FIX.md` |
| Migration Guide | `benchmark_charts/MIGRATION-interactive-smart.md` |
| Benchmark Methodology | `benchmark_charts/METHODOLOGY-SMART-INTERACTIVE.md` |
| Unified Implementation Driver | `docs/plans/interactive-smart-bench-unified-driver.md` |
| PR2 Test Plan | `docs/plans/pr2-email-bench-test-plan.md` |
| Batched Mode Usage | `benchmark_charts/USAGE-batched-mode.md` |
| Batched Triage Plan | `benchmark_charts/PLAN-batched-email-triage.md` |

---

## Test Execution

```bash
# PR1 unit tests
python -m pytest tests/unit/agents/test_email_agent_interactive_smart_triage.py -xvs

# PR2 unit tests (context compaction + gate logging + TurnResult)
python -m pytest tests/unit/agents/test_email_bench_pr2_features.py -xvs

# PR1 gap-fix tests
python -m pytest tests/unit/agents/test_email_bench_runner_gaps.py -xvs

# Integration tests (full smart path + dual-path + regression)
python -m pytest tests/integration/test_email_bench_smart_integration.py -xvs
python -m pytest tests/integration/test_email_bench_dual_path_integration.py -xvs
python -m pytest tests/integration/test_email_bench_regression.py -xvs

# Performance tests
python -m pytest tests/performance/test_email_bench_performance.py -xvs --slow
```
