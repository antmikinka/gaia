# Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
# SPDX-License-Identifier: MIT
"""
Data shapes for the GAIA Email Triage benchmark runner.

These dataclasses are in a separate module to avoid circular imports
between ``runner.py`` and ``trace_extractor.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StepResult:
    """Single step in the agent loop with its token/duration cost."""

    step_number: int
    action: str  # "llm_call", "planning", "final_answer"
    tool_name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0  # tokens in <thinking> blocks (estimated)
    total_tokens: int = 0
    duration_ms: int = 0
    time_to_first_token_ms: float = 0.0  # TTFT: time from prompt send to first token
    tokens_per_second: float = 0.0  # TPS: inference throughput
    status: str = "ok"


@dataclass
class TurnResult:
    """Single turn in an interactive benchmark session."""

    turn_number: int
    prompt: str
    step_results: list[StepResult] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    emails_affected: list[str] = field(default_factory=list)
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    time_to_first_token_ms: float = 0.0
    tokens_per_second: float = 0.0
    final_answer: str = ""
    status: str = "ok"
    error: str = ""
    # PR2: Smart-mode per-turn fields.
    heuristic_email_count: int = 0
    llm_email_count: int = 0
    context_compacted: bool = False
    gate_decisions: list[dict] = field(default_factory=list)


@dataclass
class EmailResult:
    """Result of classifying a single email."""

    email_id: str
    subject: str
    sender: str
    label_ids: list[str] = field(default_factory=list)
    category: str = ""
    is_spam: bool = False
    is_phishing: bool = False
    confident: bool = False
    reason: str = ""
    llm_summary: str = ""
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    time_to_first_token_ms: float = 0.0
    tokens_per_second: float = 0.0
    status: str = "ok"
    error: str = ""


@dataclass
class SessionState:
    """Tracks email actions across an interactive session."""

    archived: set = field(default_factory=set)
    starred: set = field(default_factory=set)
    drafted: set = field(default_factory=set)
    sent: set = field(default_factory=set)
    marked_read: set = field(default_factory=set)
    deleted: set = field(default_factory=set)
    triaged_emails: dict = field(default_factory=dict)  # id -> category
    # Smart-mode partitions (id -> category).
    heuristic_triaged: dict = field(default_factory=dict)
    llm_triaged: dict = field(default_factory=dict)
    # Force-LLM bypass set (id -> reason). Populated by "reclassify" command
    # in interactive sessions. Reserved for future wiring into triage_inbox_impl.
    force_llm_ids: dict = field(default_factory=dict)
    # Cost-tracking counters for smart mode.
    llm_calls_saved: int = 0
    heuristic_token_estimate: int = 0


@dataclass
class BatchResult:
    """Result of processing one batch of emails."""

    batch_number: int
    batch_size: int
    total_batches: int
    email_results: list[EmailResult] = field(default_factory=list)
    duration_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_tokens: int = 0
    avg_time_to_first_token_ms: float = 0.0
    avg_tokens_per_second: float = 0.0
    categories: list[str] = field(default_factory=list)
    status: str = "ok"
    error: str = ""


@dataclass
class RunResult:
    """Result of a complete benchmark run."""

    run_id: str
    timestamp: str
    model: str
    provider: str
    mbox_path: str = ""
    jsonl_path: str = ""
    data_source: str = "mbox"  # "mbox" | "jsonl"
    mode: str = ""  # "heuristic" | "full" | "batched" | "smart"
    batch_results: list[BatchResult] = field(default_factory=list)
    step_results: list[StepResult] = field(default_factory=list)
    total_emails: int = 0
    total_duration_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_tokens: int = 0
    avg_time_to_first_token_ms: float = 0.0
    avg_tokens_per_second: float = 0.0
    category_counts: dict[str, int] = field(default_factory=dict)
    status: str = "ok"
    error: str = ""
    # Multi-model / cross-framework extensions.
    is_cold_start: bool = False
    source_framework: str = "gaia"
    estimated_steps: int = 0
    heuristic_only_count: int = 0
    llm_processed_count: int = 0
