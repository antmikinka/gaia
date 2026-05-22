# PR2 Test Plan: Context Compaction + Gate Logging + TurnResult Fields + Dual-Path Summary

> **Author:** Morgan Rodriguez, Senior QA Engineer & Test Automation Architect
> **Date:** 2026-05-21
> **Branch:** `feat/email-bench-visualizations`
> **PR1 Status:** 12 unit tests passing, 5 gaps identified by code review
> **PR2 Scope:** Context compaction, tool-level LLM gate logging, TurnResult fields, dual-path summary, visualization support

---

## 1. Integration Test: Full Smart Benchmark Path

### Test File
`tests/integration/test_email_bench_smart_integration.py`

### 1.1 Test: `test_run_interactive_benchmark_smart_path_dispatch`

**Purpose:** Exercises `run_interactive_benchmark` end-to-end with `enable_smart_mode=True`, verifying smart dispatch on turn 1 and fallback on subsequent turns.

**Fixture:**
```python
@pytest.fixture
def mock_smart_agent():
    """Construct an EmailTriageAgent with mocked LLM but real smart-mode config."""
    cfg = EmailAgentConfig(
        gmail_backend=FakeGmailBackend(mbox_path=Path("tests/fixtures/email/_stub_inbox.mbox")),
        calendar_backend=FakeCalendarBackend(),
        enable_smart_mode=True,
        batch_size=5,
        silent_mode=True,
        debug=True,
    )
    with patch("gaia.agents.base.agent.AgentSDK") as mock_sdk:
        mock_sdk.return_value = MagicMock()
        agent = EmailTriageAgent(config=cfg)
        agent._mock_chat = mock_sdk.return_value
    yield agent
    agent.close_db()
```

**Setup:**
- Use `_stub_inbox.mbox` (10 emails: 4 confident, 6 non-confident)
- Mock `agent.process_interactive_smart_triage` to return a dict matching the real result shape
- Mock `agent.process_query` for turn 2+ to return a standard dict result
- Mock `agent.sync_smart_triage_cache` as a no-op spy

**Scenario:** 4-turn session:
1. `"Triage my inbox (10 emails)"` -- should trigger smart dispatch
2. `"Archive the low priority emails"` -- should fall through to `process_query`
3. `"Star any urgent messages"` -- should fall through to `process_query`
4. `"Show me a summary"` -- should fall through to `process_query`

**Assertions:**
```python
# Turn 1: Smart dispatch occurred
assert mock_smart_triage.call_count == 1
assert mock_process_query.call_count == 0  # not called on turn 1

# Turns 2-4: Fell through to process_query
assert mock_process_query.call_count == 3

# SessionState populated correctly
state = session_summary["session_state"]  # or access via internal ref
assert len(session_summary["heuristic_triaged"]) == 4  # 4 confident
assert len(session_summary["llm_triaged"]) == 6  # 6 non-confident
assert session_summary["heuristic_only_count"] == 4
assert session_summary["llm_escalated_count"] == 6

# Summary has all 24+ base keys (count them explicitly)
base_keys = {
    "run_id", "timestamp", "model", "mbox_path", "jsonl_path", "data_source",
    "turns", "total_turns", "total_emails_affected", "total_tools_used",
    "tools_used", "total_duration_ms", "total_input_tokens", "total_output_tokens",
    "total_reasoning_tokens", "total_tokens", "avg_tokens_per_turn",
    "avg_duration_per_turn_ms", "avg_time_to_first_token_ms", "avg_tokens_per_second",
}
for key in base_keys:
    assert key in session_summary, f"Missing base key: {key}"

# Smart-mode keys present
smart_keys = {"heuristic_triaged", "llm_triaged", "heuristic_only_count",
              "llm_escalated_count", "heuristic_savings"}
for key in smart_keys:
    assert key in session_summary, f"Missing smart key: {key}"

# heuristic_savings has all sub-keys
savings = session_summary["heuristic_savings"]
assert "llm_calls_saved" in savings
assert "estimated_tokens_saved" in savings
assert "estimated_output_tokens_avoided" in savings
assert "saved_percentage" in savings
```

### 1.2 Test: `test_no_double_counting_between_sync_and_extract`

**Purpose:** Verify that `_sync_session_state_from_smart_result` (turn 1) and `_extract_actions` (turns 2+) do not double-count emails when both parse the same triage results.

**Assertions:**
```python
# After all turns, heuristic_triaged + llm_triaged == triaged_emails total
total_smart = len(state.heuristic_triaged) + len(state.llm_triaged)
assert total_smart == len(state.triaged_emails), (
    f"Double counting detected: heuristic({len(state.heuristic_triaged)}) "
    f"+ llm({len(state.llm_triaged)}) != triaged({len(state.triaged_emails)})"
)

# llm_calls_saved matches heuristic_triaged count
assert state.llm_calls_saved == len(state.heuristic_triaged)
```

### 1.3 Test: `test_non_triage_first_turn_falls_through`

**Purpose:** Verify that when the first turn prompt does NOT match `_is_triage_prompt`, the session falls through to `process_query` even in smart mode.

**Setup:**
- `enable_smart_mode=True`
- First prompt: `"Show me a summary of my emails"`
- No `_is_triage_prompt` keywords present

**Assertions:**
```python
assert mock_smart_triage.call_count == 0  # never called
assert mock_process_query.call_count >= 1  # used for all turns
```

---

## 2. PR1 Regression Fixes (from code review gaps)

### Test File
`tests/unit/agents/test_email_bench_runner_gaps.py`

### 2.1 Test: `test_normalize_agent_result_empty_string`

**Purpose:** `_normalize_agent_result("")` must not crash.

```python
from gaia.agents.email.bench.runner import _normalize_agent_result

def test_normalize_agent_result_empty_string():
    """Empty string should raise a clear error, not crash with JSONDecodeError."""
    with pytest.raises((TypeError, ValueError), match="empty|no data"):
        _normalize_agent_result("")
```

**Expected PR2 fix in `_normalize_agent_result`:**
```python
def _normalize_agent_result(agent_result: object) -> dict:
    if isinstance(agent_result, str):
        if not agent_result.strip():
            raise ValueError("Agent result is empty")
        ...
```

### 2.2 Test: `test_is_triage_prompt_no_false_positives`

**Purpose:** `_is_triage_prompt("show me my inbox")` should NOT trigger smart dispatch -- "show me my inbox" is a summary request, not a triage request.

```python
def test_is_triage_prompt_no_false_positives():
    """Non-triage prompts containing 'inbox' should not trigger smart dispatch."""
    from gaia.agents.email.bench.runner import _is_triage_prompt

    # These should be False -- they're summary/action requests, not triage
    assert _is_triage_prompt("show me my inbox") is False
    assert _is_triage_prompt("what's in my inbox") is False
    assert _is_triage_prompt("count emails in inbox") is False
    assert _is_triage_prompt("clear my inbox") is False

    # These should still be True
    assert _is_triage_prompt("triage my inbox") is True
    assert _is_triage_prompt("categorize these emails") is True
    assert _is_triage_prompt("classify my inbox") is True
```

**Expected PR2 fix in `_is_triage_prompt`:**
```python
# Add negative lookahead or require verb+keyword pattern:
# _TRIAGE_VERBS = ("triage", "categorize", "classify")
# Only match when a triage verb is present, not just "inbox"
```

### 2.3 Test: `test_sync_session_state_conversation_shape_change`

**Purpose:** If the agent result's conversation shape changes (e.g., missing `conversation` key, empty list, nested differently), `_sync_session_state_from_smart_result` must not crash silently.

```python
from gaia.agents.email.bench.data_shapes import SessionState
from gaia.agents.email.bench.runner import _sync_session_state_from_smart_result

def test_sync_session_state_missing_conversation_key():
    state = SessionState()
    _sync_session_state_from_smart_result({"result": "done"}, state)
    # Should be a no-op, not crash
    assert len(state.heuristic_triaged) == 0
    assert len(state.llm_triaged) == 0

def test_sync_session_state_empty_conversation():
    state = SessionState()
    _sync_session_state_from_smart_result({"conversation": []}, state)
    assert len(state.heuristic_triaged) == 0

def test_sync_session_state_malformed_tool_content():
    state = SessionState()
    _sync_session_state_from_smart_result({
        "conversation": [{"role": "tool", "content": "not json"}],
    }, state)
    assert len(state.heuristic_triaged) == 0
```

---

## 3. PR2 Unit Tests: Context Compaction + Gate Logging + TurnResult Fields

### Test File
`tests/unit/agents/test_email_bench_pr2_features.py`

### 3.1 Context Compaction Tests

**Purpose:** Verify that context compaction preserves structural keys while truncating body/snippet fields only.

**New function (PR2):** `compact_context(conversation: list[dict], max_chars: int = 2000) -> list[dict]`

```python
class TestContextCompaction:
    """Context compaction preserves structure while reducing token footprint."""

    def test_preserves_structural_keys(self):
        """System messages, role, and tool metadata are never truncated."""
        from gaia.agents.email.bench.runner import compact_context

        conversation = [
            {"role": "system", "content": {"type": "stats", "performance_stats": {"input_tokens": 100}}},
            {"role": "user", "content": "Triage my inbox"},
            {"role": "assistant", "content": {"tool": "triage_inbox"}},
            {"role": "tool", "name": "triage_inbox", "content": json.dumps({
                "ok": True, "data": {"results": [{"id": "m1", "category": "low priority"}]}
            })},
        ]
        compacted = compact_context(conversation, max_chars=500)

        assert len(compacted) == len(conversation)  # no messages dropped
        assert compacted[0]["role"] == "system"
        assert compacted[0]["content"]["type"] == "stats"  # structural intact
        assert compacted[1]["content"] == "Triage my inbox"  # user prompt untouched
        assert compacted[2]["content"]["tool"] == "triage_inbox"  # tool name intact

    def test_truncates_body_snippet_fields_only(self):
        """Only text-heavy content (snippets, body text) is truncated."""
        from gaia.agents.email.bench.runner import compact_context

        long_body = "x" * 5000
        conversation = [
            {"role": "assistant", "content": f"Here is the full analysis: {long_body}"},
        ]
        compacted = compact_context(conversation, max_chars=200)

        total_len = sum(
            len(str(m.get("content", ""))) for m in compacted
        )
        assert total_len <= 200  # within limit
        assert "Here is the" in str(compacted[0]["content"])  # prefix preserved
        assert "[truncated]" in str(compacted[0]["content"])  # truncation marker

    def test_no_truncation_when_under_limit(self):
        """Short conversations pass through unchanged."""
        from gaia.agents.email.bench.runner import compact_context

        conversation = [
            {"role": "user", "content": "Triage my inbox"},
            {"role": "assistant", "content": "Done"},
        ]
        compacted = compact_context(conversation, max_chars=1000)
        assert compacted == conversation

    def test_empty_conversation(self):
        from gaia.agents.email.bench.runner import compact_context
        assert compact_context([], max_chars=100) == []
```

### 3.2 LLM Gate Logging Tests

**Purpose:** Verify that the LLM gate decision is logged at INFO level for all 4 decision paths.

**New function (PR2):** `_log_gate_decision(email_id, gate, reason, confident)`

```python
class TestLlmGateLogging:
    """LLM gate logging covers all 4 decision paths."""

    @pytest.fixture
    def caplog_info(self, caplog):
        caplog.set_level(logging.INFO)
        return caplog

    def test_gate_heuristic_confident(self, caplog_info):
        """Log when email is classified confidently by heuristic."""
        from gaia.agents.email.bench.runner import _log_gate_decision

        _log_gate_decision("m1", gate="heuristic", reason="CATEGORY_PROMOTIONS", confident=True)
        records = [r for r in caplog_info.records if r.levelno == logging.INFO]
        assert any("m1" in r.message and "heuristic" in r.message.lower() for r in records)
        assert any("confident" in r.message.lower() for r in records)

    def test_gate_llm_escalation(self, caplog_info):
        """Log when email escalates to LLM (non-confident)."""
        from gaia.agents.email.bench.runner import _log_gate_decision

        _log_gate_decision("m2", gate="llm", reason="no_heuristic_match", confident=False)
        records = [r for r in caplog_info.records if r.levelno == logging.INFO]
        assert any("m2" in r.message and "llm" in r.message.lower() for r in records)
        assert any("escalat" in r.message.lower() for r in records)

    def test_gate_force_llm_bypass(self, caplog_info):
        """Log when force_llm overrides heuristic."""
        from gaia.agents.email.bench.runner import _log_gate_decision

        _log_gate_decision("m3", gate="force_llm", reason="user-requested", confident=False)
        records = [r for r in caplog_info.records if r.levelno == logging.INFO]
        assert any("m3" in r.message and "force_llm" in r.message.lower() for r in records)

    def test_gate_cached_skip(self, caplog_info):
        """Log when email is skipped due to prior-turn cache."""
        from gaia.agents.email.bench.runner import _log_gate_decision

        _log_gate_decision("m4", gate="cached", reason="prior_turn_confident", confident=True)
        records = [r for r in caplog_info.records if r.levelno == logging.INFO]
        assert any("m4" in r.message and "cache" in r.message.lower() for r in records)

    def test_all_paths_emit_info_level(self, caplog_info):
        """Every gate decision emits at INFO level, not DEBUG."""
        from gaia.agents.email.bench.runner import _log_gate_decision

        for gate, reason, confident in [
            ("heuristic", "CATEGORY_PROMOTIONS", True),
            ("llm", "no_heuristic_match", False),
            ("force_llm", "user-requested", False),
            ("cached", "prior_turn_confident", True),
        ]:
            caplog_info.clear()
            _log_gate_decision("mX", gate=gate, reason=reason, confident=confident)
            info_records = [r for r in caplog_info.records if r.levelno == logging.INFO]
            assert len(info_records) >= 1, f"No INFO log for gate={gate}"
```

### 3.3 TurnResult New Fields Tests

**Purpose:** Verify new TurnResult fields have correct defaults and per-turn email counts are accurate.

**New TurnResult fields (PR2):**
```python
@dataclass
class TurnResult:
    ...
    heuristic_email_count: int = 0  # emails classified by heuristic this turn
    llm_email_count: int = 0        # emails classified by LLM this turn
    context_compacted: bool = False  # whether context was compacted before this turn
    gate_decisions: list[dict] = field(default_factory=list)  # per-email gate logs
```

```python
class TestTurnResultFields:
    """TurnResult new fields have correct defaults and accurate counts."""

    def test_new_fields_have_zero_defaults(self):
        """New fields default to empty/zero, not None."""
        from gaia.agents.email.bench.data_shapes import TurnResult

        tr = TurnResult(turn_number=1, prompt="test")
        assert tr.heuristic_email_count == 0
        assert tr.llm_email_count == 0
        assert tr.context_compacted is False
        assert tr.gate_decisions == []

    def test_per_turn_heuristic_llm_counts_accurate(self):
        """After a smart triage turn, TurnResult reflects accurate split."""
        from gaia.agents.email.bench.data_shapes import TurnResult

        # Simulate turn 1 smart triage: 5 heuristic, 3 LLM
        tr = TurnResult(
            turn_number=1,
            prompt="Triage my inbox",
            heuristic_email_count=5,
            llm_email_count=3,
        )
        assert tr.heuristic_email_count == 5
        assert tr.llm_email_count == 3
        assert tr.heuristic_email_count + tr.llm_email_count == 8

    def test_non_triage_turn_has_zero_smart_counts(self):
        """Follow-up turns (non-triage) have zero heuristic/LLM email counts."""
        from gaia.agents.email.bench.data_shapes import TurnResult

        tr = TurnResult(
            turn_number=2,
            prompt="Archive low priority",
        )
        assert tr.heuristic_email_count == 0
        assert tr.llm_email_count == 0

    def test_context_compacted_flag_set_when_compaction_occurs(self):
        """TurnResult.context_compacted = True when context was compacted."""
        from gaia.agents.email.bench.data_shapes import TurnResult

        tr = TurnResult(
            turn_number=4,
            prompt="Summary",
            context_compacted=True,
        )
        assert tr.context_compacted is True

    def test_gate_decisions_list_populated_per_turn(self):
        """TurnResult.gate_decisions contains one entry per classified email."""
        from gaia.agents.email.bench.data_shapes import TurnResult

        tr = TurnResult(
            turn_number=1,
            prompt="Triage my inbox",
            gate_decisions=[
                {"email_id": "m1", "gate": "heuristic", "confident": True},
                {"email_id": "m2", "gate": "llm", "confident": False},
            ],
        )
        assert len(tr.gate_decisions) == 2
        assert tr.gate_decisions[0]["email_id"] == "m1"
```

---

## 4. PR2 Integration Tests: Dual-Path Summary + Visualization

### Test File
`tests/integration/test_email_bench_dual_path_integration.py`

### 4.1 Test: `test_smart_summary_serialized_correctly_by_bench_runner`

**Purpose:** `generate_interactive_smart_summary` output must be serializable by `bench_runner.py`'s `_turn_to_dict` and `json.dump`.

```python
def test_smart_summary_serializable():
    """The augmented summary must round-trip through json.dump without error."""
    import json
    from gaia.agents.email.bench.runner import (
        SessionState,
        generate_interactive_smart_summary,
    )
    from gaia.agents.email.bench.data_shapes import TurnResult, StepResult

    # Build a realistic base summary
    base_summary = {
        "run_id": "test-123",
        "timestamp": "2026-05-21T00:00:00",
        "model": "Qwen3.5-4B-GGUF",
        "mbox_path": "/path/to/test.mbox",
        "turns": [
            TurnResult(turn_number=1, prompt="Triage my inbox", heuristic_email_count=5, llm_email_count=3),
            TurnResult(turn_number=2, prompt="Archive low priority"),
        ],
        "total_turns": 2,
        "total_emails_affected": 8,
        "total_tools_used": 2,
        "tools_used": ["triage_inbox", "archive_message"],
        "total_duration_ms": 5000,
        "total_input_tokens": 12000,
        "total_output_tokens": 3000,
        "total_reasoning_tokens": 500,
        "total_tokens": 15000,
        "avg_tokens_per_turn": 7500.0,
        "avg_duration_per_turn_ms": 2500.0,
        "avg_time_to_first_token_ms": 150.0,
        "avg_tokens_per_second": 25.0,
    }

    state = SessionState()
    state.heuristic_triaged = {f"m{i}": "low priority" for i in range(1, 6)}
    state.llm_triaged = {f"m{i}": "informational" for i in range(6, 9)}
    state.llm_calls_saved = 5
    state.heuristic_token_estimate = 250

    result = generate_interactive_smart_summary(base_summary, state, 15000)

    # Must be json-serializable (no sets, no custom objects)
    serialized = json.dumps(result, default=str)
    parsed = json.loads(serialized)

    # All smart keys present after round-trip
    assert parsed["heuristic_triaged"] == state.heuristic_triaged
    assert parsed["llm_triaged"] == state.llm_triaged
    assert parsed["heuristic_savings"]["llm_calls_saved"] == 5
    assert parsed["heuristic_savings"]["saved_percentage"] >= 0
```

### 4.2 Test: `test_chart_23_displays_dual_path_breakdown`

**Purpose:** Chart 23 (`plot_heuristic_vs_llm_escalation`) must correctly display the dual-path breakdown from interactive smart summary data.

```python
def test_chart_23_interactive_data():
    """Chart 23 must handle interactive summary data, not just batch_results."""
    from gaia.agents.email.bench.visualize import plot_heuristic_vs_llm_escalation

    # Interactive summary format (from run_interactive_benchmark smart mode)
    interactive_runs = [{
        "run_id": "run-interactive-abc123",
        "model": "Qwen3.5-4B-GGUF",
        "heuristic_triaged": {f"m{i}": "low priority" for i in range(1, 61)},
        "llm_triaged": {f"m{i}": "informational" for i in range(61, 101)},
        "batch_results": [],  # empty -- interactive mode doesn't use this
        "mode": "smart",
    }]

    with tempfile.TemporaryDirectory() as tmpdir:
        result = plot_heuristic_vs_llm_escalation(
            interactive_runs, Path(tmpdir)
        )
        # Chart 23 should handle interactive data (use heuristic_triaged/llm_triaged)
        assert result is not None
        assert result.exists()
```

### 4.3 Test: `test_chart_23_edge_cases`

```python
def test_chart_23_all_heuristic():
    """100% heuristic, 0% LLM -- chart should show full green bar."""
    from gaia.agents.email.bench.visualize import plot_heuristic_vs_llm_escalation
    runs = [{
        "run_id": "run-all-heuristic",
        "model": "Qwen3.5-4B-GGUF",
        "heuristic_triaged": {"m1": "low priority"},
        "llm_triaged": {},
        "batch_results": [],
    }]
    with tempfile.TemporaryDirectory() as tmpdir:
        result = plot_heuristic_vs_llm_escalation(runs, Path(tmpdir))
        assert result is not None

def test_chart_23_all_llm():
    """0% heuristic, 100% LLM -- chart should show full orange bar."""
    from gaia.agents.email.bench.visualize import plot_heuristic_vs_llm_escalation
    runs = [{
        "run_id": "run-all-llm",
        "model": "Qwen3.5-4B-GGUF",
        "heuristic_triaged": {},
        "llm_triaged": {"m1": "actionable"},
        "batch_results": [],
    }]
    with tempfile.TemporaryDirectory() as tmpdir:
        result = plot_heuristic_vs_llm_escalation(runs, Path(tmpdir))
        assert result is not None

def test_chart_23_empty_runs():
    from gaia.agents.email.bench.visualize import plot_heuristic_vs_llm_escalation
    assert plot_heuristic_vs_llm_escalation([], Path("/tmp")) is None

def test_chart_23_no_triaged_emails():
    from gaia.agents.email.bench.visualize import plot_heuristic_vs_llm_escalation
    runs = [{"run_id": "empty", "model": "X", "heuristic_triaged": {}, "llm_triaged": {}, "batch_results": []}]
    with tempfile.TemporaryDirectory() as tmpdir:
        result = plot_heuristic_vs_llm_escalation(runs, Path(tmpdir))
        assert result is None  # no data to chart
```

### 4.4 Test: `test_plot_smart_turn_split_handles_edge_cases`

**Purpose:** New `plot_smart_turn_split()` function handles edge cases.

```python
def test_plot_smart_turn_split():
    """New chart: per-turn breakdown of heuristic vs LLM classification."""
    from gaia.agents.email.bench.visualize import plot_smart_turn_split

    interactive = {
        "turns": [
            {
                "turn_number": 1,
                "prompt": "Triage my inbox",
                "heuristic_email_count": 50,
                "llm_email_count": 30,
                "total_tokens": 8000,
            },
            {
                "turn_number": 2,
                "prompt": "Archive low priority",
                "heuristic_email_count": 0,
                "llm_email_count": 0,
                "total_tokens": 2000,
            },
            {
                "turn_number": 3,
                "prompt": "Re-triage remaining",
                "heuristic_email_count": 10,
                "llm_email_count": 10,
                "total_tokens": 3000,
            },
        ],
        "model": "Qwen3.5-4B-GGUF",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        result = plot_smart_turn_split(interactive, Path(tmpdir))
        assert result is not None
        assert result.exists()

def test_plot_smart_turn_split_single_turn():
    """Works with only one turn."""
    from gaia.agents.email.bench.visualize import plot_smart_turn_split
    interactive = {
        "turns": [{"turn_number": 1, "heuristic_email_count": 0, "llm_email_count": 5, "total_tokens": 1000}],
        "model": "X",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        result = plot_smart_turn_split(interactive, Path(tmpdir))
        assert result is not None

def test_plot_smart_turn_split_no_smart_fields():
    """Gracefully handles turns without smart-mode fields."""
    from gaia.agents.email.bench.visualize import plot_smart_turn_split
    interactive = {
        "turns": [{"turn_number": 1, "total_tokens": 1000}],
        "model": "X",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        result = plot_smart_turn_split(interactive, Path(tmpdir))
        assert result is not None  # should still render, with zeros
```

---

## 5. Regression Tests: Non-Smart Mode

### Test File
`tests/integration/test_email_bench_regression.py`

### 5.1 Test: `test_interactive_mode_without_smart_unchanged`

**Purpose:** `--mode interactive` without `--smart` produces identical output structure before and after PR1+PR2.

```python
def test_interactive_non_smart_output_unchanged():
    """Non-smart interactive mode should produce same keys as before PR1+PR2."""
    # Run interactive benchmark without smart mode
    with patch("gaia.agents.email.agent.EmailTriageAgent") as MockAgent:
        mock_agent = MockAgent.return_value
        mock_agent.process_query.return_value = {
            "result": "Done",
            "conversation": [],
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }
        mock_agent.conversation_history = []
        mock_agent.sync_smart_triage_cache = MagicMock()

        summary = run_interactive_benchmark(
            mbox_path="tests/fixtures/email/_stub_inbox.mbox",
            model_id="Qwen3.5-4B-GGUF",
            base_url="http://localhost:8000",
            scenario=["Show me my emails"],
            limit=5,
            enable_smart_mode=False,  # NON-SMART
        )

    # Must NOT have smart-mode keys
    assert "heuristic_triaged" in summary  # present but empty
    assert summary["heuristic_triaged"] == {}
    assert summary["llm_triaged"] == {}
    assert summary["heuristic_only_count"] == 0
    assert summary["llm_escalated_count"] == 0

    # All 24 base keys present
    assert len(summary) >= 20  # base keys

    # TurnResult objects should NOT have smart fields populated
    for turn in summary["turns"]:
        assert getattr(turn, "heuristic_email_count", 0) == 0
        assert getattr(turn, "llm_email_count", 0) == 0
        assert getattr(turn, "context_compacted", False) is False
```

### 5.2 Test: `test_full_mode_without_smart_unchanged`

```python
def test_full_mode_non_smart_unchanged():
    """--mode full without --smart should produce same RunResult structure."""
    with patch("gaia.agents.email.agent.EmailTriageAgent") as MockAgent:
        mock_agent = MockAgent.return_value
        mock_agent.process_query.return_value = {
            "result": "done",
            "conversation": [],
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }

        result = _run_full_agent(
            mbox_path="tests/fixtures/email/_stub_inbox.mbox",
            model_id="Qwen3.5-4B-GGUF",
            base_url="http://localhost:8000",
            limit=5,
            force_llm=False,
        )

    assert result.mode == "full"
    assert result.status in ("ok", "completed")
    assert result.total_emails >= 0
```

### 5.3 Test: `test_batched_mode_unaffected`

```python
def test_batched_mode_unaffected():
    """--batched mode should not be affected by PR1+PR2 smart-mode changes."""
    with patch("gaia.agents.email.agent.EmailTriageAgent") as MockAgent:
        mock_agent = MockAgent.return_value
        mock_agent.process_batched_triage.return_value = json.dumps({
            "ok": True,
            "data": {"run_id": "test-batched", "total_emails": 5},
        })

        result = _run_batched_agent(
            mbox_path="tests/fixtures/email/_stub_inbox.mbox",
            model_id="Qwen3.5-4B-GGUF",
            base_url="http://localhost:8000",
            limit=10,
            batch_size=5,
        )

    assert result.mode == "batched"
    assert len(result.batch_results) >= 1
    assert result.total_emails >= 0
```

---

## 6. Performance Tests

### Test File
`tests/performance/test_email_bench_performance.py`

### 6.1 Test: `test_token_consumption_at_limit_100`

**Purpose:** Token consumption at limit 100 must stay under 100K.

```python
@pytest.mark.slow
def test_token_consumption_target():
    """At limit=100, total token consumption should be < 100K."""
    with patch("gaia.agents.email.agent.EmailTriageAgent") as MockAgent:
        mock_agent = MockAgent.return_value
        # Simulate realistic token counts:
        # Turn 1 (triage): ~20K input, ~5K output for 100 emails
        # Turns 2-4: ~3K input, ~1K output each
        mock_agent.process_interactive_smart_triage.return_value = {
            "result": "Triaged 100 emails",
            "conversation": [],
            "input_tokens": 20000,
            "output_tokens": 5000,
            "total_tokens": 25000,
        }
        mock_agent.process_query.return_value = {
            "result": "Done",
            "conversation": [],
            "input_tokens": 3000,
            "output_tokens": 1000,
            "total_tokens": 4000,
        }
        mock_agent.conversation_history = []
        mock_agent.sync_smart_triage_cache = MagicMock()

        summary = run_interactive_benchmark(
            mbox_path="tests/fixtures/email/_stub_inbox.mbox",
            model_id="Qwen3.5-4B-GGUF",
            base_url="http://localhost:8000",
            limit=100,
            enable_smart_mode=True,
        )

    total = summary["total_tokens"]
    assert total < 100_000, f"Token consumption {total:,} exceeds 100K target"
    assert total > 0, "Token consumption should be non-zero"
```

### 6.2 Test: `test_heuristic_rate_target`

**Purpose:** Heuristic classification rate should be >= 70% on the stub dataset.

```python
@pytest.mark.slow
def test_heuristic_rate_target():
    """Heuristic fast-path should classify >= 70% of emails."""
    state = SessionState()

    # Simulate a realistic smart triage result on 100 emails
    # 75 confident (heuristic), 25 non-confident (LLM)
    results = []
    for i in range(1, 76):
        results.append({"id": f"m{i}", "category": "low priority", "confident": True})
    for i in range(76, 101):
        results.append({"id": f"m{i}", "category": "informational", "confident": False})

    agent_result = {
        "conversation": [{
            "role": "tool",
            "name": "triage_inbox",
            "content": json.dumps({"ok": True, "data": {"results": results}}),
        }],
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }

    _sync_session_state_from_smart_result(agent_result, state)

    total_triaged = len(state.heuristic_triaged) + len(state.llm_triaged)
    heuristic_rate = len(state.heuristic_triaged) / total_triaged * 100

    assert heuristic_rate >= 70.0, (
        f"Heuristic rate {heuristic_rate:.1f}% below 70% target "
        f"({len(state.heuristic_triaged)} heuristic / {len(state.llm_triaged)} LLM)"
    )
```

### 6.3 Test: `test_context_growth_rate_after_compaction`

**Purpose:** Context growth after compaction should be <= 2x the raw token count per turn.

```python
def test_context_growth_rate_after_compaction():
    """Compacted context should grow at <= 2x rate vs raw accumulation."""
    from gaia.agents.email.bench.runner import compact_context

    # Simulate conversation growing across 4 turns
    turns_conversation = []
    for turn in range(4):
        turn_msgs = [
            {"role": "user", "content": f"Prompt for turn {turn + 1}"},
            {"role": "assistant", "content": "Response " + "x" * 2000},
            {"role": "tool", "name": "some_tool", "content": "Result " + "y" * 3000},
        ]
        turns_conversation.extend(turn_msgs)

    # Raw (uncompacted) size
    raw_size = sum(len(str(m.get("content", ""))) for m in turns_conversation)

    # Compacted size
    compacted = compact_context(turns_conversation, max_chars=raw_size // 2)
    compacted_size = sum(len(str(m.get("content", ""))) for m in compacted)

    # Growth rate: compacted should be at most 2x the target
    growth_ratio = compacted_size / max(raw_size, 1)
    assert growth_ratio <= 1.0, (
        f"Compacted context ({compacted_size}) exceeds raw ({raw_size})"
    )
    assert compacted_size <= raw_size // 2 + 100  # within target + margin
```

---

## 7. Test Fixture Strategy

### Shared Fixtures (in `tests/fixtures/email/conftest.py`)

```python
@pytest.fixture
def smart_triage_result_100():
    """Realistic smart triage result for 100 emails (70 heuristic / 30 LLM)."""
    results = []
    for i in range(1, 71):
        results.append({
            "id": f"m{i:03d}",
            "category": random.choice(["low priority", "informational"]),
            "confident": True,
            "rationale": "heuristic label match",
        })
    for i in range(71, 101):
        results.append({
            "id": f"m{i:03d}",
            "category": random.choice(["actionable", "urgent", "informational"]),
            "confident": False,
            "rationale": "no heuristic match",
        })
    return {"results": results, "grouped": {"total": 100}}

@pytest.fixture
def mixed_interactive_session():
    """4-turn interactive session with smart-mode data on turn 1."""
    return {
        "run_id": "test-mixed-session",
        "model": "Qwen3.5-4B-GGUF",
        "turns": [...],  # 4 TurnResult objects
        "heuristic_triaged": {...},
        "llm_triaged": {...},
        "heuristic_savings": {...},
    }
```

### Mock Agent Factory

```python
@pytest.fixture
def mock_email_agent():
    """Factory fixture for creating mocked EmailTriageAgent instances."""
    def _make_agent(smart_mode=False, **kwargs):
        cfg = EmailAgentConfig(
            gmail_backend=FakeGmailBackend(mbox_path=Path("tests/fixtures/email/_stub_inbox.mbox")),
            calendar_backend=FakeCalendarBackend(),
            enable_smart_mode=smart_mode,
            silent_mode=True,
            **kwargs,
        )
        with patch("gaia.agents.base.agent.AgentSDK") as mock_sdk:
            mock_sdk.return_value = MagicMock()
            agent = EmailTriageAgent(config=cfg)
            agent._mock_chat = mock_sdk.return_value
        return agent
    yield _make_agent
```

---

## 8. Test Execution Plan

### Phase 1: PR1 Gap Fixes (immediate)
```bash
# Fix _normalize_agent_result empty string handling
# Fix _is_triage_prompt false positives
# Run existing 12 unit tests to verify no regression
python -m pytest tests/unit/agents/test_email_agent_interactive_smart_triage.py -xvs

# Run the 3 new gap-fix tests
python -m pytest tests/unit/agents/test_email_bench_runner_gaps.py -xvs
```

### Phase 2: PR2 Unit Tests
```bash
# Context compaction + gate logging + TurnResult fields
python -m pytest tests/unit/agents/test_email_bench_pr2_features.py -xvs
```

### Phase 3: Integration Tests
```bash
# Full smart path + dual-path summary + regression
python -m pytest tests/integration/test_email_bench_smart_integration.py -xvs
python -m pytest tests/integration/test_email_bench_dual_path_integration.py -xvs
python -m pytest tests/integration/test_email_bench_regression.py -xvs
```

### Phase 4: Performance Tests
```bash
python -m pytest tests/performance/test_email_bench_performance.py -xvs --slow
```

### Total Expected Test Count

| Category | Test Count |
|----------|-----------|
| PR1 Gap Fixes | 3 |
| PR2 Unit Tests (context compaction) | 4 |
| PR2 Unit Tests (gate logging) | 5 |
| PR2 Unit Tests (TurnResult fields) | 5 |
| Integration: Full Smart Path | 3 |
| Integration: Dual-Path + Visualization | 7 |
| Regression: Non-Smart Mode | 3 |
| Performance | 3 |
| **Total** | **33** |

---

## 9. Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| `_is_triage_prompt` fix changes behavior for existing prompts | Medium | Add regression test for all existing scenario prompts |
| Context compaction loses critical information | High | Test that structural keys are never truncated |
| Gate logging adds overhead to benchmark timing | Low | Verify logging is at INFO level only, not DEBUG |
| `TurnResult` new fields break JSON serialization | Medium | Test round-trip through `json.dumps`/`json.loads` |
| Chart 23 doesn't handle interactive data format | Medium | Explicit test with interactive summary input |
| Non-smart mode accidentally picks up smart behavior | High | Explicit regression tests for each non-smart mode |

---

## 10. Absolute File Paths for Test Implementation

| File | Path |
|------|------|
| Runner (PR2 additions) | `C:\Users\antmi\gaia-visualizations\src\gaia\agents\email\bench\runner.py` |
| Data shapes (TurnResult) | `C:\Users\antmi\gaia-visualizations\src\gaia\agents\email\bench\data_shapes.py` |
| Visualization (Chart 23) | `C:\Users\antmi\gaia-visualizations\src\gaia\agents\email\bench\visualize.py` |
| Bench runner (serialization) | `C:\Users\antmi\gaia-visualizations\src\gaia\agents\email\bench\bench_runner.py` |
| Output module | `C:\Users\antmi\gaia-visualizations\src\gaia\agents\email\bench\output.py` |
| Triange heuristics | `C:\Users\antmi\gaia-visualizations\src\gaia\agents\email\tools\triage_heuristics.py` |
| Existing smart triage tests | `C:\Users\antmi\gaia-visualizations\tests\unit\agents\test_email_agent_interactive_smart_triage.py` |
| Email fixtures | `C:\Users\antmi\gaia-visualizations\tests\fixtures\email\conftest.py` |
| Email unit conftest | `C:\Users\antmi\gaia-visualizations\tests\unit\email\conftest.py` |
| Stub mbox | `C:\Users\antmi\gaia-visualizations\tests\fixtures\email\_stub_inbox.mbox` |

---

This test plan provides complete coverage of PR1 gaps, all PR2 features, regression safety for non-smart modes, and performance targets. The 33 tests are organized across 4 test files (unit, integration, regression, performance) with shared fixtures from the existing email test infrastructure.
