# Program Plan: Email Batch Organize String Coercion Fix

## Problem Statement

The 7 batch organize tools declare `message_ids: list[str]` but LLMs emit comma-separated strings (e.g. `"id1,id2,id3"`). Python iterates the string character-by-character in `_run_batch`/`_run_batch_with_prior`, producing 169 KeyErrors. Additionally, the `"total"` field in wrapper responses reports string length instead of ID count.

## Files to Modify

| File | Purpose |
|------|---------|
| `C:\Users\antmi\gaia-main\src\gaia\agents\email\tools\organize_tools.py` | Add `_coerce_ids()` helper + 7 call sites |
| `C:\Users\antmi\gaia-main\tests\unit\agents\test_email_batch_organize.py` | Add coercion tests + total field verification |

## 7 Batch Tool Wrappers (target insertion points)

Located in `OrganizeToolsMixin._register_organize_tools()` (lines 439-704):

1. `mark_read_batch` (line 440) -- uses `_run_batch`
2. `mark_unread_batch` (line 473) -- uses `_run_batch`
3. `add_star_batch` (line 506) -- uses `_run_batch`
4. `remove_star_batch` (line 539) -- uses `_run_batch`
5. `archive_message_batch` (line 572) -- uses `_run_batch_with_prior`
6. `label_message_batch` (line 616) -- uses `_run_batch`
7. `move_to_label_batch` (line 655) -- uses `_run_batch_with_prior`

---

## Phase 1: Create `_coerce_ids()` Helper

**File:** `src/gaia/agents/email/tools/organize_tools.py`
**Location:** Module-level, after imports and before `class OrganizeToolsMixin` (around line 282, after the batch helpers).

```python
def _coerce_ids(message_ids: list[str] | str | None) -> list[str]:
    """Normalize LLM output to list[str].

    Accepts ``list[str]`` (already correct), comma/semicolon-separated
    ``str``, or ``None``/empty (returns ``[]``).  Strips whitespace and
    drops blank tokens from trailing delimiters.
    """
    if message_ids is None:
        return []
    if isinstance(message_ids, list):
        return message_ids
    # String input: split on comma or semicolon, strip, drop empties.
    return [s.strip() for s in re.split(r"[,;]+", message_ids) if s.strip()]
```

**Additional import:** Add `import re` to the existing imports block (line 17 area).

---

## Phase 2: Insert Coercion Call in Each of 7 Batch Tools

**Pattern for all 7 wrappers.** After the existing `if not message_ids:` empty-check and BEFORE `_check_threshold()`, insert:

```python
            message_ids = _coerce_ids(message_ids)
            if not message_ids:
                return _envelope_ok({"total": 0, "succeeded": [], "failed": []})
```

**Rationale for repositioning:** The existing empty-check `if not message_ids:` works for both `[]` and `""` (both falsy), but after coercion we need to re-check in case the string was `",,,"` (produces `[]` after split+filter). Moving the coercion before the empty-check eliminates the need for a second check while keeping the same early-return path.

**Concrete change for each wrapper** (replace the existing first two lines of the try body):

**Before** (example: `mark_read_batch`, lines 442-445):
```python
            if not message_ids:
                return _envelope_ok({"total": 0, "succeeded": [], "failed": []})
            if (err := _check_threshold()) is not None:
                return _envelope_err(err)
```

**After:**
```python
            message_ids = _coerce_ids(message_ids)
            if not message_ids:
                return _envelope_ok({"total": 0, "succeeded": [], "failed": []})
            if (err := _check_threshold()) is not None:
                return _envelope_err(err)
```

This exact 1-line addition (`message_ids = _coerce_ids(message_ids)`) applies to all 7 wrappers. The empty-check and threshold-check remain unchanged in position and logic.

---

## Phase 3: Add Tests

**File:** `tests/unit/agents/test_email_batch_organize.py`

### 3a. New test class: `TestStringCoercion`

**Import update:** Add `_coerce_ids` to the existing import from `organize_tools` (line 36-38):
```python
from gaia.agents.email.tools.organize_tools import (
    _run_batch,
    _run_batch_with_prior,
    _coerce_ids,
)
```

**Tests to add:**

| # | Test Name | Input | Expected | Defect Covered |
|---|-----------|-------|----------|----------------|
| 1 | `test_comma_separated_string` | `"id1,id2,id3"` | `["id1", "id2", "id3"]` | Primary bug |
| 2 | `test_whitespace_around_ids` | `" id1 , id2 , id3 "` | `["id1", "id2", "id3"]` | Whitespace handling |
| 3 | `test_trailing_comma` | `"id1,id2,"` | `["id1", "id2"]` | Trailing delimiter |
| 4 | `test_empty_string` | `""` | `[]` | Empty string edge case |
| 5 | `test_list_passthrough` | `["id1", "id2"]` | `["id1", "id2"]` | Regression: list unchanged |
| 6 | `test_none_input` | `None` | `[]` | None handling |
| 7 | `test_single_id_string` | `"id1"` | `["id1"]` | Single item (no delimiter) |
| 8 | `test_semicolon_separated` | `"id1;id2;id3"` | `["id1", "id2", "id3"]` | Semicolon delimiter |
| 9 | `test_mixed_delimiters` | `"id1,id2;id3"` | `["id1", "id2", "id3"]` | Mixed comma+semicolon |

### 3b. Integration test: String coercion through wrapper

Add one test per wrapper tool (parametrized over `_BATCH_TOOLS`) to verify:
- A comma-separated string produces `total == 3` (not `len("id1,id2,id3") == 11`)
- The `succeeded` list contains the correct 3 message_ids
- DB rows are written with correct message_ids

```python
class TestStringCoercionIntegration:
    @pytest.mark.parametrize("tool_name", _BATCH_TOOLS)
    def test_comma_string_produces_correct_total(
        self, email_agent, fake_gmail, tool_name
    ):
        """String input like 'id1,id2,id3' must yield total=3, not 11."""
        msg_ids = list(fake_gmail._messages.keys())[:3]
        csv_ids = ",".join(msg_ids)
        fn = _get_tool(tool_name)
        if tool_name in ("label_message_batch", "move_to_label_batch"):
            new_label = fake_gmail.create_label(name=f"sc-{tool_name}")
            result = _parse(fn(message_ids=csv_ids, label_id=new_label["id"]))
        else:
            result = _parse(fn(message_ids=csv_ids))

        assert result["ok"] is True
        data = result["data"]
        assert data["total"] == 3  # NOT len("id1,id2,id3") == 11
        assert len(data["succeeded"]) == 3
        succeeded_ids = {s["message_id"] for s in data["succeeded"]}
        assert succeeded_ids == set(msg_ids)
```

### 3c. Update existing `TestBatchEmptyInput`

Add one test for empty string input (currently only tests `[]`):
```python
def test_empty_string_returns_zero_total(self, email_agent, tool_name):
    fn = _get_tool(tool_name)
    if tool_name in ("label_message_batch", "move_to_label_batch"):
        result = _parse(fn(message_ids="", label_id="Label_1"))
    else:
        result = _parse(fn(message_ids=""))
    assert result["ok"] is True
    assert result["data"]["total"] == 0
```

---

## Phase 4: Verify

1. Run lint: `python util/lint.py --all --fix` on both modified files
2. Run tests: `python -m pytest tests/unit/agents/test_email_batch_organize.py -xvs`
3. Verify all existing tests pass (no regressions)
4. Verify new coercion tests pass
5. Confirm total lines of change: ~10 (helper + import) + 7 (call sites) + ~50 (tests) = ~67 lines total

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **R1:** Coercion changes `message_ids` identity (rebinds local variable) | LOW -- `message_ids` is a local parameter, rebinding is safe | Unit tests verify list passthrough returns same content |
| **R2:** `_coerce_ids` called after empty-check in original plan | MEDIUM -- `total` field still wrong | Plan positions coercion BEFORE empty-check, so both empty-check and total see the coerced list |
| **R3:** Existing tests pass `list[str]` and could break | LOW -- `_coerce_ids` is a passthrough for lists | Regression test (#5) covers this; existing tests unchanged |
| **R4:** LLM emits unexpected delimiter formats | LOW -- regex handles comma, semicolon, mixed, whitespace | Test #9 covers mixed delimiters; can extend regex if new patterns emerge |
| **R5:** Threshold counter uses `message_ids` before coercion | MEDIUM -- if threshold logic ever inspects `message_ids` content | Currently threshold only checks counter state, not `message_ids` content. Coercion before threshold-check is safe. |

---

## Total Estimated Lines Changed

| Change | Lines |
|--------|-------|
| `_coerce_ids()` helper | ~10 |
| `import re` addition | 1 |
| 7 call-site insertions (1 line each) | 7 |
| Coercion unit tests (9 tests) | ~30 |
| Integration test (7 parametrized) | ~20 |
| Empty string test (7 parametrized) | ~10 |
| **Total** | **~78** |
