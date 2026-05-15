# Planning Document: Email Benchmark Chart Enhancements (Refined)

**Author:** Dr. Sarah Kim, Technical Product Strategist & Engineering Lead
**Date:** 2026-05-14
**Status:** Draft -- awaiting user review
**Branch:** `feat/email-bench-chart-enhancements`

---

## Part 1: Run ID in Chart Filenames

### Problem Statement

Currently all chart PNGs use fixed names (e.g., `01_category_distribution.png`). When a user runs the benchmark multiple times, each run overwrites the previous charts. There is no way to correlate a chart file with the specific benchmark run that produced it.

The run ID format is: `run-interactive-20260514-133017-Qwen3.5-4B-GGUF-a3b2c1` (timestamp + model + 6-char hex suffix). The suffix `a3b2c1` is the compact unique identifier suitable for filenames.

### Option A: Append run suffix to each filename

**Mechanism:** Modify `_save_chart()` to accept an optional `run_id_suffix` parameter. Filename becomes `01_category_distribution_a3b2c1.png`.

**Pros:**
- Every chart file is self-identifying; no directory navigation needed
- Works naturally with the existing `_last_run.json` mechanism (read `run_id` from that JSON)
- No structural change to `output_dir` -- single flat directory
- Diff in `generate_charts()` callers is minimal (one new kwarg threading through)
- Existing CI/CD scripts that glob `*.png` continue to work

**Cons:**
- Filenames become longer
- Chart index (`CHARTS.md`) needs updating to reference suffixed names (see Gap 2 resolution below)
- Multi-run charts (11-14, 17-18, 22, 24-26, 28-29) already encode their identity through model labels in the chart itself -- no suffix needed
- Framework comparison charts (15, 16, 19-21) similarly do not need suffixes

**Recommendation:** Apply suffix only to single-run charts (1-4, 9, 10) and interactive charts (6, 7, 27). Multi-model comparison charts already aggregate across runs so the suffix is redundant.

---

### Option B: Keep fixed names, use `_last_run.json` for lookup

**Mechanism:** No filename changes. The existing `_last_run.json` file (already written by `report_generator.py` at line 408) maps the latest run's data to the fixed filenames. Users look up the run ID from `_last_run.json`.

**Pros:**
- Zero changes to `_save_chart()` or filename logic
- Clean filenames remain short and predictable
- `_last_run.json` already exists and contains `run_id` field

**Cons:**
- No self-identification in the chart file itself -- must always pair chart with `_last_run.json`
- Historical charts are destroyed on every new run (overwritten)
- User cannot look at a chart file in isolation and know which run produced it
- Makes before/after comparisons impossible without manual file renaming

**Recommendation:** Not recommended as a standalone solution. Acceptable only if combined with Option C (subdirectories) or if the user's workflow is strictly "only care about latest run."

---

### Option C: Subdirectory per run

**Mechanism:** Each benchmark run creates its own `charts/<run-suffix>/` subdirectory. All charts for that run land there with fixed names.

**Pros:**
- Complete isolation between runs -- no overwriting
- Fixed, short filenames within each subdirectory
- Easy to diff two runs directory-to-directory
- Clean for archiving or sharing a specific run's results

**Cons:**
- Breaks existing `generate_charts()` contract (it receives a single `output_dir`)
- Report generator (`report_generator.py` line 408-421) passes a single `chart_dir` -- would need refactoring
- `CHARTS.md` index would need per-run generation
- Multi-model charts (which span runs) become ambiguous -- which subdirectory do they go in?
- Significant structural change with downstream impact on CLI and report workflows

**Recommendation:** Too invasive for the current scope. Better suited as a future "run archive" feature once the other enhancements are stable.

---

### Recommended Approach: Option A (suffix on single-run charts)

- Modify `_save_chart()` signature: `def _save_chart(fig, output_dir, name, dpi=150, *, run_id_suffix=None) -> Path`
- When `run_id_suffix` is provided, save as `{name}_{suffix}.png`; otherwise `{name}.png` (backward compatible)
- In `generate_charts()`, extract `run_id_suffix` from the single-run JSON (see Gap 5 resolution for extraction method)
- Pass suffix to all single-run chart calls; do not pass for multi-model or framework comparison charts
- Update `CHARTS.md` generation to reference suffixed filenames (see Gap 2 resolution)

---

## Part 1a: Gap Resolutions

### Gap 1: Annotations on Existing Charts (NEW SECTION)

**Issue:** The original plan only proposed new charts (#30, #31, #32) but did not consider adding batch-tool annotations to existing charts where they would be immediately visible and complementary.

**Resolution: Two targeted annotations on existing charts**

#### 1a. Chart 6 (Interactive Turn Breakdown) -- Add "batch tool used" markers

Chart 6 (`plot_interactive_turns` at visualize.py:718) already shows per-turn duration and tokens as grouped columns with dual Y-axes. Adding a third visual dimension would clutter the existing layout. Instead, use **bottom-axis annotation markers**:

- **Approach:** Add colored triangle markers (`v` shape) below each turn label on the X-axis. Green triangle = batch tool used in that turn, grey triangle = serial tools only.
- **Data source:** `turns[].tools_called` -- check for any tool name containing `_batch` (e.g., `mark_read_batch`, `archive_message_batch`) vs individual action tools.
- **Implementation:** After the existing `ax1.set_xticklabels(turn_labels)` call (line 791), add a second x-axis at y=-0.05 in axes coordinates with marker annotations. One-line matplotlib: `ax1.text(x_pos, -0.12, "BATCH" if is_batch else "", transform=ax1.get_xaxis_transform(), ha="center", fontsize=7, fontweight="bold", color="#38A169" if is_batch else "#A0AEC0")`.
- **No new chart number needed** -- enhancement to existing Chart 6.

#### 1b. Chart 29 (Steps Scaling Heatmap) -- Add "execution mode" annotation

Chart 29 (`plot_steps_scaling_heatmap` at visualize.py:2725) is a Model x Email Limit matrix of estimated LLM calls. The current cells show `est_calls = (total_tokens / 2800) + 2`. To make the batch vs serial distinction visible:

- **Approach:** Add a single annotation row below the heatmap (outside the `imshow` grid) showing "execution mode" for each model: "serial" or "batch". This is a text-only row, not part of the color-coded matrix.
- **Data source & algorithm:** The `mode` field on runs distinguishes "full"/"heuristic"/"interactive" -- NOT serial vs batch. Serial vs batch is determined by which tools the agent actually called. Two code paths feed data into Chart 29:

  1. **Full-mode runs (JSONL/JSON via `output.py`):** These serialize `step_results` as a list where each step has a `tool_name` field. Batch tool names all end with `_batch` suffix (`mark_read_batch`, `archive_message_batch`, `add_star_batch`, etc., defined in `tools/organize_tools.py`).
  2. **Interactive runs:** These serialize turns under the `"turns"` key (NOT `"turn_results"`), each turn having a `tools_called` list.

  Concrete detection algorithm:
  ```python
  def _detect_execution_mode(run: dict[str, Any]) -> str:
      """Classify a run as 'batch', 'serial', or 'mixed'.

      Checks actual tool names in serialized step_results (full mode)
      or tools_called (interactive mode). Does NOT use the 'mode' field
      which only distinguishes full/heuristic/interactive.
      """
      # Full mode: check step_results[].tool_name
      steps = run.get("step_results", [])
      if steps:
          tool_names = {s.get("tool_name", "") for s in steps if s.get("tool_name")}
          has_batch = any(t.endswith("_batch") for t in tool_names)
          has_serial = any(t and not t.endswith("_batch") for t in tool_names)
          if has_batch and not has_serial:
              return "batch"
          if has_serial and not has_batch:
              return "serial"
          if has_batch and has_serial:
              return "mixed"

      # Interactive mode: check turns[].tools_called
      turns = run.get("turns", [])
      if turns:
          all_tools = set()
          for t in turns:
              all_tools.update(t.get("tools_called", []))
          has_batch = any(t.endswith("_batch") for t in all_tools)
          has_serial = any(t and not t.endswith("_batch") for t in all_tools)
          if has_batch and not has_serial:
              return "batch"
          if has_serial and not has_batch:
              return "serial"
          if has_batch and has_serial:
              return "mixed"

      return "unknown"
  ```

- **Implementation:** After the heatmap rendering loop (line 2793), add `ax.text()` calls in a new row at y=-0.08 for each column. Use red text for "serial", green for "batch", orange for "mixed". Only annotate cells where the mode can be determined.
- **No new chart number needed** -- enhancement to existing Chart 29.

**Why annotate existing charts instead of only creating new ones:**
- Chart 6 and Chart 29 are already generated for every interactive/multi-model run -- annotations appear automatically without the user needing to run a separate comparison command.
- New charts (#30, #31, #32) answer aggregate/before-after questions; annotations answer "was batch used here?" at the granular per-turn/per-model level.
- Complementary, not redundant. Annotations provide context; new charts provide analysis.

---

### Gap 2: CHARTS.md Index with Suffixed Names (NEW SECTION)

**Issue:** The original plan's mitigation ("Use pattern matching e.g. `01_category_distribution_*.png` in markdown links") is incorrect. Markdown image syntax `![alt](glob-pattern.png)` does NOT expand globs -- it looks for a literal filename containing the asterisk character.

**Resolution: Per-run CHARTS.md generated from actual file list**

Since `generate_charts()` builds the `charts_index` list in-memory as it creates each chart (lines 2836-3198), the exact filenames are known at write time. The fix is straightforward:

- **No glob patterns in CHARTS.md.** The index is written at lines 3190-3198 using the actual `fname` from the `charts_index` list, which already contains the suffixed filenames.
- **Per-run generation:** Each `generate_charts()` invocation writes CHARTS.md at the end, overwriting the previous one. This means CHARTS.md always reflects the most recent run's files. This is the correct behavior because:
  - CHARTS.md lives in the same `output_dir` as the chart PNGs
  - When a user browses to the charts directory, CHARTS.md points to files that exist in that same directory
  - If a user wants to preserve a historical index, they should archive the entire output directory (charts + CHARTS.md) together
- **No symlinks needed:** Symlinks add cross-platform complexity (Windows symlink requires admin privileges). The per-run overwrite approach is simpler and sufficient for the "latest run" use case.

**Impact on original plan:** The risk mitigation row in the original plan ("Use pattern matching... in markdown links") is deleted. CHARTS.md already uses actual filenames from the `charts_index` list -- the suffixed names are naturally included. No additional complexity.

---

### Gap 3: Call Chain Integration for Chart 30 (NEW SECTION)

**Issue:** Chart 30 needs `before_run` and `after_run` parameters, but the current call chain is:

```
CLI (cli.py) → generate_reports() (report_generator.py:429) → _generate_charts() (report_generator.py:389) → generate_charts() (visualize.py:2814)
```

None of these functions currently accept `before_path`/`after_path` or `before_run`/`after_run` parameters.

**Resolution: Two-path approach -- immediate and future**

#### Path A (Immediate): Add parameters through the existing call chain

Thread optional `before_run` and `after_run` parameters through each layer:

1. **`visualize.py:generate_charts()`** -- Add parameters:
   ```python
   def generate_charts(
       ...
       *,
       before_run: dict[str, Any] | None = None,
       after_run: dict[str, Any] | None = None,
       ...
   )
   ```
   When both are provided, call `plot_feature_impact(before_run, after_run, output_dir)`.

2. **`report_generator.py:_generate_charts()`** (line 389) -- Add and forward parameters:
   ```python
   def _generate_charts(
       runs, clawflow_run, chart_dir, jsonl_path=None, last_gaia_json=None,
       *,
       before_run: dict | None = None,
       after_run: dict | None = None,
   ):
       ...
       generate_charts(..., before_run=before_run, after_run=after_run)
   ```

3. **`report_generator.py:generate_reports()`** (line 429) -- Add parameters:
   ```python
   def generate_reports(
       input_dir, output_dir=None, generate_charts=False, chart_dir=None,
       skip_cold_start=False, ground_truth=None,
       cost_per_1m_input=0.0, cost_per_1m_output=0.0,
       *,
       before_path: str | None = None,
       after_path: str | None = None,
   ):
   ```
   Load the JSON files if paths are provided, then pass to `_generate_charts()`.

4. **`report_generator.py:build_parser()`** (line 30) -- Add CLI flags:
   ```python
   parser.add_argument("--before", type=str, default=None,
                       help="Path to 'before' benchmark JSON for feature impact comparison.")
   parser.add_argument("--after", type=str, default=None,
                       help="Path to 'after' benchmark JSON for feature impact comparison.")
   ```

5. **`cli.py:_build_report_args()`** (line 387) -- Thread the args:
   ```python
   if args.before:
       rpt_args.extend(["--before", args.before])
   if args.after:
       rpt_args.extend(["--after", args.after])
   ```

6. **`cli.py:build_parser()`** (report subcommand, line 189) -- Add parser args:
   ```python
   rpt_parser.add_argument("--before", type=str, default=None,
                           help="Path to 'before' benchmark JSON.")
   rpt_parser.add_argument("--after", type=str, default=None,
                           help="Path to 'after' benchmark JSON.")
   ```

**Data loading:** In `generate_reports()`, use `_load_json(Path(before_path))` and `_load_json(Path(after_path))` from `visualize.py` (already available as a module import). The loaded dicts are plain JSON dicts matching the run shape -- no need to deserialize into `RunResult` dataclass instances.

#### Path B (Future): Separate `gaia email compare` subcommand

If before/after comparison becomes a frequently-used workflow, promote it to its own subcommand:

```
gaia email compare --before benchmark_results/before.json --after benchmark_results/after.json --charts
```

This would have its own entry point in `cli.py`, its own argument parser, and a dedicated comparison report generator. The `plot_feature_impact()` function would be shared between the report subcommand and the compare subcommand.

**Recommendation:** Implement Path A now. It requires 5 file changes across 3 modules but each change is a small parameter addition. Path B can be considered if user demand for comparison workflows grows.

---

### Gap 4: total_steps Schema Change (NEW SECTION)

**Issue:** Chart 30 and Chart 32 both need a `total_steps` value. Currently `RunResult` (data_shapes.py:111) does not have this field. Two options:

#### Option A: Computed property (no schema change)

**Mechanism:** In the chart generation code, compute `total_steps = len(run.get("step_results", []))` for full mode, or `sum(len(t.get("step_results", [])) for t in run.get("turns", []))` for interactive mode.

**Pros:**
- No schema migration required
- Works with all existing data (any historical run with step_results)
- Single source of truth: step count is derived from the actual step list, not a stored number

**Cons:**
- Every chart function that needs step count must implement the same computation logic
- Interactive mode requires iterating through `turns` which may not always be present
- Slightly less efficient (recomputes on each chart render)

#### Option B: Persisted field with default

**Mechanism:** Add `total_steps: int = 0` to the `RunResult` dataclass (data_shapes.py:111). Update the runner to populate it at write time.

**Pros:**
- Fast lookup in chart code (single dict key access)
- Self-documenting: `total_steps` is clearly a first-class metric
- Easier to query/aggregate in variance analysis and statistical tests

**Cons:**
- Requires a default value (`= 0`) so older serialized runs without this field don't break on deserialization
- Runner code must be updated to populate the field (runner.py:201, runner.py:219, runner.py:234, runner.py:511, runner.py:842)
- Risk of inconsistency if the stored value diverges from actual step list length

**Recommendation: Option A (computed property) for now, with Option B as a follow-up.**

Rationale:
- The current codebase serializes `RunResult` as plain JSON dicts (via `asdict()` from dataclasses), not via strict schema validation. Adding a field to the dataclass does NOT retroactively add it to existing JSON files -- older files will simply lack the key.
- A computed property via a helper function `def _count_steps(run: dict) -> int` in `visualize.py` handles both old data (steps from step_results list) and new data (direct field lookup if present) with a fallback chain:
  ```python
  def _count_steps(run: dict[str, Any]) -> int:
      """Return total LLM step count, preferring stored field over computed.

      Handles three serialization variants:
      1. Full-mode JSON/JSONL (output.py): has "step_results" list
      2. Interactive benchmark JSON (bench_runner.py): has "turns" key (NOT "turn_results")
      3. Future: may have persisted "total_steps" field
      """
      stored = run.get("total_steps")
      if isinstance(stored, int) and stored >= 0:
          return stored
      # Fallback 1: compute from step_results (full mode)
      direct = run.get("step_results", [])
      if direct:
          return len(direct)
      # Fallback 2: compute from turns (interactive mode)
      # NOTE: serialized key is "turns", NOT "turn_results" (the RunResult
      # dataclass field is turn_results but bench_runner.py serializes as "turns")
      turns = run.get("turns", [])
      return sum(len(t.get("step_results", [])) for t in turns)
  ```
- This approach is backward-compatible with ALL existing data, works immediately, and leaves the door open to persisting `total_steps` in the schema later (the helper function will prefer the stored value when present).

---

### Gap 5: Run ID Suffix Extraction (NEW SECTION)

**Issue:** The original plan's "extract last 6 chars of `run_id`" is fragile. The run ID format is constructed in `runner.py` at lines 163, 374, and 695:

```python
run_id = f"run-{mode}-{timestamp}-{model_id.replace('/', '-')}-{uuid.uuid4().hex[:6]}"
```

Using `run_id[-6:]` assumes the suffix is always the last 6 characters. This is correct today but would silently break if:
- The model name format changes to include a trailing hyphen
- An additional segment is appended to the run ID format
- The UUID prefix length changes from `[:6]` to something else

**Resolution: Parse from known position using rsplit**

Since the run ID uses hyphens as delimiters and the suffix is always the last segment:

```python
def _extract_run_suffix(run_id: str) -> str:
    """Extract the 6-char run suffix from a run_id string.

    Handles formats like:
      run-full-20260514-133017-Qwen3.5-4B-GGUF-a3b2c1
      run-interactive-20260514-133017-Qwen3-5-Coder-4B-GGUF-f4e2d1

    Returns the last hyphen-delimited segment.
    """
    return run_id.rsplit("-", 1)[-1]
```

**Why `rsplit("-", 1)` over `run_id[-6:]`:**
- Model names like `Qwen3-5-Coder-4B-GGUF` contain hyphens, making `split()` unreliable
- `rsplit("-", 1)` splits only on the LAST hyphen, correctly isolating the suffix regardless of how many hyphens appear earlier
- If the suffix length ever changes (e.g., to 8 chars), `rsplit` still works without code changes
- If the run ID format adds a new trailing segment, only the delimiter position changes -- `rsplit` adapts automatically

**Alternative: Store suffix at generation time**

The cleanest long-term solution is to store the UUID suffix as a separate field in the serialized JSON:

```python
# In runner.py, alongside run_id:
run_suffix = uuid.uuid4().hex[:6]
run_id = f"run-{mode}-{timestamp}-{model_id.replace('/', '-')}-{run_suffix}"
# ...
run_result = RunResult(
    run_id=run_id,
    run_suffix=run_suffix,  # new field, stored alongside run_id
    ...
)
```

Then `generate_charts()` reads `run.get("run_suffix")` directly with no parsing. This is the most robust approach but requires adding `run_suffix: str = ""` to the `RunResult` dataclass.

**Recommendation:** Use `rsplit("-", 1)[-1]` immediately (no schema change needed). Add `run_suffix` field as a future enhancement when other schema changes (like `total_steps`) are being made.

---

## Part 2: Analytical Comparison Charts

### Current Chart Inventory

| Range | Scope | Count |
|-------|-------|-------|
| 1-4 | Single-run (category, token, duration, per-email) | 4 |
| 5a/b/c | Multi-run variance trends | 3 |
| 6-7 | Interactive mode (turns, heatmap) + annotations (Gap 1) | 2+ |
| 8 | Category stability (multi-run) | 1 |
| 9-10 | Single-run (scatter, step performance) | 2 |
| 11-14 | Multi-model comparison (duration, tokens, TTFT, TPS) | 4 |
| 15-16 | GAIA vs ClawFlow framework comparison | 2 |
| 17-18 | Per-model variance, cold-start | 2 |
| 19-21 | Model x Architecture comparison | 3 |
| 22 | Run-level scatter (multi-model) | 1 |
| 23 | Heuristic vs LLM escalation | 1 |
| 24-26 | Planning heatmap, token efficiency, latency/scatter | 3 |
| 27-29 | Interactive LLM activity, radar, steps scaling + annotations (Gap 1) | 3+ |

**Total:** 29 chart functions, plus 2 annotation enhancements on existing charts (Chart 6 and Chart 29, per Gap 1 resolution).

---

### Proposal 1: Before/After Feature Impact Chart

**Chart Number:** 30 (always generated when two compatible runs are available)

**Name:** `30_feature_impact_comparison.png`

**What it shows:** Side-by-side comparison of two runs representing "before" and "after" a feature change. Specifically designed for the batch tools optimization case (serial 13-step execution vs batch 2-step execution). Displays:
- Duration (seconds) -- grouped columns for before/after
- Total tokens -- grouped columns for before/after
- LLM steps/calls -- grouped columns for before/after (uses `_count_steps()` helper from Gap 4 resolution)
- Percentage improvement annotations on each metric group (e.g., "95% reduction")

**Data source:**
- Two `RunResult` dicts passed via `before_run: dict | None`, `after_run: dict | None` parameters (see Gap 3 resolution for call chain)
- Fields used: `total_duration_ms`, `total_tokens`, `total_input_tokens`, `total_output_tokens`, `total_reasoning_tokens`, `total_emails`
- Steps via `_count_steps()` helper (Gap 4)
- For interactive mode: also use `turns[].duration_ms`, `turns[].total_tokens`, `turns[].step_results` for per-turn breakdown

**Chart type:** Grouped column chart with 3 metric groups (Duration, Tokens, Steps), each with "Before" and "After" bars. Improvement percentage annotations as text above each group. Color scheme: red/orange for "Before" (problematic), green/teal for "After" (optimized).

**Pros:**
- Directly addresses the documented ISSUE-serial-tool-execution.md findings (13 -> 2 steps, 488s -> 30s, 12K -> 1.2K tokens)
- Produces a single, compelling visual for PR descriptions, release notes, and blog posts
- Reusable for any before/after comparison (not just batch tools)
- Fits naturally into the existing `generate_charts()` pipeline (see Gap 3, Path A)

**Cons:**
- Requires the user to provide two separate benchmark JSON files (before and after)
- Only meaningful when comparing the same model and same email dataset
- If the two runs differ in model or email count, the comparison is misleading (needs validation)

**When generated:** Only when both `before_run` and `after_run` parameters are provided to `generate_charts()`. CLI flags: `gaia email report --charts --before <path> --after <path>`.

**Implementation surface:**
- New function: `plot_feature_impact(before: dict, after: dict, output_dir: Path) -> Path | None`
- New `generate_charts()` parameters (see Gap 3, Path A)
- Guard: validate same `model` and `total_emails` before rendering; warn otherwise

---

### Proposal 2: Per-Turn Tool Efficiency Waterfall

**Chart Number:** 31 (interactive mode only)

**Name:** `31_tool_efficiency_waterfall.png`

**What it shows:** For interactive mode runs, a waterfall chart showing how each conversation turn contributes to total duration and total tokens, with visual distinction between "planning" turns (high token, low tool impact) and "execution" turns (tool-heavy). Specifically highlights turns where batch tools were used vs serial tool calls, showing the delta in duration and steps.

**Data source:**
- Interactive run JSON (already loaded as `interactive_path`)
- Fields used: `turns[].turn_number`, `turns[].prompt`, `turns[].duration_ms`, `turns[].total_tokens`, `turns[].tools_called`, `turns[].step_results`, `turns[].emails_affected`
- Derived: classify each turn as "planning" (no tool calls or `triage_inbox` only) vs "execution" (action tools: `mark_read`, `archive`, `add_star`, `delete`, `move`) vs "batch" (batch tools used)

**Chart type:** Waterfall (cascade) chart. X-axis = turn number. Y-axis = cumulative duration (seconds). Each bar = duration of that turn, color-coded by turn type. Annotations on each bar showing: number of tool calls, emails affected. A secondary Y-axis or inset showing tokens per turn as a line overlay.

**Pros:**
- Makes the serial-vs-batch tool execution problem immediately visible in the interactive chart set
- Complements existing Chart 6 (Interactive Turn Breakdown) by adding efficiency context
- Shows the value of batch tools at the per-turn level, not just aggregate
- Useful for identifying which specific prompts trigger pathological serial behavior

**Cons:**
- Waterfall charts are more complex to implement in matplotlib than bar/line charts
- Only useful in interactive mode (not heuristic or full batch mode)
- Requires parsing `tools_called` to classify turn types, which may be noisy if tool names change
- Overlaps partially with existing Chart 6 -- mitigated by Gap 1 annotations which provide a lighter-weight alternative for the "was batch used?" question

**When generated:** Interactive mode only, alongside existing Charts 6, 7, and 27. Only when `interactive_path` contains `turns` with `tools_called` data.

**Implementation surface:**
- New function: `plot_tool_efficiency_waterfall(interactive: dict, output_dir: Path) -> Path | None`
- Added to the interactive mode block in `generate_charts()`
- Requires `_classify_turn()` helper function

---

### Proposal 3: Steps-to-Emails Scaling Curve

**Chart Number:** 32 (multi-model, always when >= 2 runs available)

**Name:** `32_steps_scaling_curve.png`

**What it shows:** Line chart showing how LLM steps scale as email count increases. Each line = one model. X-axis = number of emails. Y-axis = LLM steps required. The chart reveals the scaling behavior difference between serial (linear O(n) growth) and batch (flat O(1) growth) tool execution.

**Data source:**
- Multiple run JSONs or JSONL iterations
- Fields used: `total_emails`, `total_steps` via `_count_steps()` helper (Gap 4 resolution)
- For multi-model runs: `model` field to group by model
- Ground truth ISSUE data provides the anchor points (9 emails = 13 steps serial, 9 emails = 2 steps batch)

**Chart type:** Multi-line chart with markers. Each model gets a colored line. Two lines per model if both serial and batch data are available (dashed = serial, solid = batch). Annotations at key points (e.g., "9 emails, 13 steps" on the serial line). Ideal/reference lines: horizontal line at 2 steps (ideal batch behavior) and diagonal line at 1x slope (ideal 1-step-per-email).

**Pros:**
- Shows scalability implications, not just point-in-time comparison
- Answers the question "what happens at 50 emails? 100 emails?" -- critical for evaluating feature impact at scale
- Complements existing Chart 29 (Steps Scaling Heatmap) which is a model x email-limit matrix; this is a line chart showing the actual measured data
- Useful for release notes and documentation ("batch tools reduce scaling from O(n) to O(1)")

**Cons:**
- Requires multiple runs with different email counts to be meaningful (single data point per model is not a curve)
- May overlap with existing Chart 29 (which already covers steps scaling as a heatmap)
- Needs careful design to avoid confusing the measured data with the extrapolated ideal lines
- If the user only has one email count (e.g., always 10 emails), the chart reduces to a point plot

**When generated:** Multi-model runs with >= 2 distinct email counts. If only one email count is available, fall back to a grouped bar chart variant showing steps per model at that count.

**Implementation surface:**
- New function: `plot_steps_scaling_curve(runs: list[dict], output_dir: Path) -> Path | None`
- Added to the multi-model block in `generate_charts()`
- Requires grouping runs by `(model, total_emails)` and computing median steps per group

---

## Summary: Recommended Priority Order

| Priority | Enhancement | Effort | Value | When |
|----------|-------------|--------|-------|------|
| **P0** | Run ID suffix on single-run charts (Gap 5: rsplit extraction) | Low | High | Always |
| **P0b** | CHARTS.md per-run generation (Gap 2: no globs) | Low | Medium | Always |
| **P1** | Chart 30: Feature impact comparison (Gap 3: threaded params) | Medium | High | Multi-experiment |
| **P1b** | Chart 6 + Chart 29 annotations (Gap 1) | Low | Medium | Always (when applicable) |
| **P2** | Chart 32: Steps scaling curve (Gap 4: computed steps) | Medium | Medium | Multi-model |
| **P3** | Chart 31: Tool efficiency waterfall | High | Medium | Interactive only |
| **Future** | `run_suffix` field in RunResult + `total_steps` persisted | Low | Low | When schema evolves |

### Rationale for Priority Ordering

1. **P0 (Run ID suffix)** is foundational -- without it, any chart enhancement risks being lost on the next run. It's a small change with high reliability impact.

2. **P0b (CHARTS.md fix)** is trivially small but prevents a subtle bug (markdown globs don't work). Must be done alongside P0.

3. **P1 (Feature impact comparison)** directly addresses the documented ISSUE-serial-tool-execution.md case and produces the most stakeholder-visible output. It's the chart that answers "how much better did we make it?"

4. **P1b (Annotations)** are low-effort additions to existing charts that provide immediate value without new chart numbers. They complement the new charts by answering "was batch used here?" at the granular level.

5. **P2 (Steps scaling curve)** answers the scalability question that naturally follows from P1. It's important but requires more diverse data to be meaningful.

6. **P3 (Tool efficiency waterfall)** is the most complex to implement (waterfall in matplotlib) and overlaps with existing Chart 6. It's valuable but not essential, especially now that Chart 6 has batch annotations (Gap 1).

---

## Implementation Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `_save_chart()` signature change breaks callers | Low | Medium | Default `run_id_suffix=None`, backward compatible |
| Before/after runs have different models or email counts | Medium | High | Add validation in `plot_feature_impact()`; warn and skip if mismatched |
| Waterfall chart implementation is fragile in matplotlib | Medium | Medium | Use grouped stacked bars as fallback if matplotlib waterfall is unreliable |
| Scaling curve has insufficient data points | Medium | Low | Fall back to grouped bar chart when only one email count is available |
| CHARTS.md overwritten on each run (data loss) | Low | Low | By design -- CHARTS.md is a per-run index. Users who need historical indices should archive the output directory |
| `rsplit` fails on malformed run_id | Low | Medium | Add fallback: `run_id[-6:]` if `rsplit` produces an empty string or single segment |
| `_count_steps()` helper diverges from persisted value | Low | Low | When `total_steps` is eventually persisted (future), the helper prefers the stored value |

---

## Open Questions for User Review

1. **Run ID suffix scope:** Should the suffix apply to ALL charts, or only single-run charts (recommended)? Multi-model charts already aggregate across runs so the suffix is redundant.

2. **Before/after input mechanism:** Should the user provide two separate JSON files (`--before` / `--after` via the report subcommand, recommended), or should the system auto-detect the two most recent runs in the input directory?

3. **Chart 32 data requirements:** Does the user have runs with varying email counts to populate the scaling curve, or should we rely on synthetic projection from ISSUE document anchor points?

4. **Backward compatibility:** Should there be a config option to disable the run ID suffix and revert to the current fixed-name behavior?

5. **Future subcommand:** Should `gaia email compare` be planned as a separate subcommand from the start, or should comparison remain part of the `report` subcommand (recommended: start with report, promote later if demand warrants)?

---

## Files That Would Be Modified

| File | Change |
|------|--------|
| `src/gaia/agents/email/bench/visualize.py` | Modify `_save_chart()` (run_id_suffix param), add `_extract_run_suffix()`, add `_count_steps()` helper (Gap 4), add `_detect_execution_mode()` helper (Gap 1), add `plot_feature_impact()`, `plot_tool_efficiency_waterfall()`, `plot_steps_scaling_curve()`, update `generate_charts()` signature, enhance `plot_interactive_turns()` with batch annotations, enhance `plot_steps_scaling_heatmap()` with execution mode row |
| `src/gaia/agents/email/bench/report_generator.py` | Add `--before` / `--after` CLI args, add `before_path`/`after_path` params to `generate_reports()` and `_generate_charts()`, load and pass before/after JSON dicts |
| `src/gaia/agents/email/bench/cli.py` | Add `--before` / `--after` flags to report subcommand parser, thread through `_build_report_args()` |
| `src/gaia/agents/email/bench/data_shapes.py` | No changes required in this phase. Future: add `total_steps: int = 0` and `run_suffix: str = ""` to `RunResult` |
| `src/gaia/agents/email/bench/runner.py` | No changes required in this phase. Future: populate `total_steps` and `run_suffix` fields at serialization time |

---

*End of planning document. Awaiting user feedback on options and priorities.*

---

## Resolution Status

### Issue 1: Chart 29 Annotation Underspecification -- RESOLVED

**Root cause:** The original plan said to "infer from step count ratio" but the `mode` field distinguishes "full"/"heuristic"/"interactive", not serial vs batch. No algorithm was specified.

**Resolution:** Defined a concrete detection algorithm (`_detect_execution_mode()`) that inspects actual tool names in serialized data:
- For full-mode runs: checks `step_results[].tool_name` for `_batch` suffix
- For interactive runs: checks `turns[].tools_called` for `_batch` suffix
- Returns "batch", "serial", "mixed", or "unknown"

**Verification:** Confirmed tool names in `src/gaia/agents/email/tools/organize_tools.py` -- all batch tools end with `_batch` (`mark_read_batch`, `archive_message_batch`, `add_star_batch`, `remove_star_batch`, `label_message_batch`, `move_to_label_batch`). Confirmed full-mode runs serialize `step_results` with `tool_name` (output.py:330-344). Confirmed interactive runs serialize under `"turns"` key with `tools_called` list (bench_runner.py:126, runner.py:849).

### Issue 2: `_count_steps` Helper Key Mismatch -- RESOLVED

**Root cause:** The proposed `_count_steps()` used `run.get("turn_results", [])` but both `runner.py` and `bench_runner.py` serialize interactive turns under the key `"turns"` (not `"turn_results"`). The `RunResult` dataclass field is `turn_results` but the JSON serialization key is `"turns"`.

**Resolution:** Corrected the fallback chain to use `run.get("turns", [])` instead of `run.get("turn_results", [])`. Verified this matches existing code in visualize.py which already correctly uses `interactive.get("turns", [])` (lines 723, 814, 2535). The `_count_steps()` helper now handles all three serialization variants: persisted `total_steps`, full-mode `step_results`, and interactive `turns`.
