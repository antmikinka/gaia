# Charts 24-29 — Implementation Audit & Fixes

**Date:** 2026-05-19
**Branch:** `feat/email-bench-visualizations`

---

## Pipeline

`planning-analysis-v2` → `enhanced-senior-developer` → `quality-reviewer`

## Verdict

All 7 chart functions are **implemented and spec-compliant**. Two issues were identified and fixed:

---

## Fixes Applied

### Fix 1 (Bug): Chart 24 — Cell Annotation Mismatch

**File:** `src/gaia/agents/email/bench/visualize.py`
**Line:** ~2356

**Problem:** Cell text displayed `steps` (actual `step_results` count) while cell color encoded `val` (`total_tokens / 2800` estimated). These are two different values, creating a contradiction where a blue cell (supposedly "low <=2 steps") could display "8".

**Fix:** Changed annotation from `f"{steps}"` to `f"{val:.0f}"` so the displayed number matches the color encoding used by the heatmap and color key.

### Fix 2 (Cleanup): Chart 27 — Redundant Dead Code

**File:** `src/gaia/agents/email/bench/visualize.py`
**Line:** ~2610

**Problem:** `tool_name not in ("", "planning", "think")` — the `""` check is unreachable because the preceding `tool_name and` short-circuits empty strings.

**Fix:** Removed `""` from the tuple: `tool_name not in ("planning", "think")`.

---

## Issues Investigated and Dismissed

| # | Issue | Verdict |
|---|-------|---------|
| 1 | Chart 24 color/text mismatch | **Fixed** |
| 2 | Chart 27b multi-run bar overlap | Dismissed — batched mode is documented as single-model, single-run |
| 3 | Chart 25 label overlap at small scales | Dismissed — theoretical only, no observed failure |
| 4 | Chart 27b missing single-model guard | Dismissed — single-model timeline is a legitimate use case |
| 5 | Chart 27 dead `""` check | **Fixed** |
| 6 | Chart 28 CV% all-50 for single-run models | Dismissed — documented in README spec ("shows 0 for single-run") |
| 7 | Hardcoded colors vs `COLORS` dict | Deferred — style cleanup, no functional impact |
| 8 | Chart 28 `tight_layout()` clipping polar labels | Dismissed — `pad=20` on title provides sufficient clearance |

---

## Chart Status After Fixes

| Chart | Function | Status |
|-------|----------|--------|
| 24 — Planning Steps Heatmap | `plot_planning_steps_heatmap` | Fixed |
| 25 — Token Efficiency Bars | `plot_token_efficiency` | Clean |
| 26 — Latency vs Heuristic Scatter | `plot_latency_heuristic_scatter` | Clean |
| 27 — Interactive LLM Activity | `plot_interactive_llm_activity` | Fixed |
| 27b — Batch Processing Timeline | `plot_batched_llm_activity` | Clean |
| 28 — Model Performance Radar | `plot_model_performance_radar` | Clean |
| 29 — Steps Scaling Heatmap | `plot_steps_scaling_heatmap` | Clean |
