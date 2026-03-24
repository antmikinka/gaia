# AuditLogger Design Document

**Document Type:** Technical Design Specification
**Component:** AuditLogger
**Version:** 1.0.0
**Date:** 2026-03-23
**Author:** Dr. Sarah Kim, Technical Product Strategist & Engineering Lead
**Phase:** PLANNING
**Quality Target:** >= 0.90

---

## 1. Executive Summary

### 1.1 Purpose

The AuditLogger component provides a tamper-proof audit trail of all GAIA pipeline execution events. It implements a cryptographic hash chain mechanism that detects any attempt to modify or tamper with the audit log, ensuring the integrity and immutability of the pipeline's execution history.

### 1.2 Problem Statement

Without tamper-proof audit logging:

1. **No accountability** - Cannot prove what actions were taken during pipeline execution
2. **No tamper detection** - Audit logs could be modified without detection
3. **No compliance** - Cannot meet regulatory requirements for audit trails
4. **No forensic analysis** - Cannot reconstruct execution history for debugging
5. **No loop isolation** - Cannot separate audit trails for concurrent loop iterations

### 1.3 Solution Overview

AuditLogger introduces:

1. **Hash Chain Integrity** - Each event contains hash of previous event, creating cryptographic chain
2. **Immutable Events** - Events cannot be modified after creation (frozen dataclass)
3. **Thread-Safe Operations** - All operations protected by reentrant lock
4. **Loop-Based Isolation** - Events bucketed by loop_id for concurrent execution
5. **Multiple Export Formats** - JSON and CSV export for reporting and compliance
6. **Flexible Querying** - Filter by event type, loop, phase, time range, payload content

---

## 2. Component Architecture

### 2.1 Class Diagram

```
+-----------------------------------------------------------------+
|                         AuditLogger                               |
+-----------------------------------------------------------------+
| - _events: List[AuditEvent]                                     |
| - _event_index: Dict[str, AuditEvent]                           |
| - _loop_buckets: Dict[str, List[str]]                           |
| - _lock: threading.RLock                                        |
| - _genesis_hash: str                                            |
+-----------------------------------------------------------------+
| + log(event_type: AuditEventType, **kwargs) -> AuditEvent        |
| + verify_integrity() -> bool                                     |
| + get_events(filters: Optional[Dict]) -> List[AuditEvent]        |
| + export_log(format: str) -> str                                 |
| + get_event(event_id: str) -> Optional[AuditEvent]               |
| + get_events_by_type(event_type: AuditEventType) -> List[AuditEvent] |
| + get_events_by_loop(loop_id: str) -> List[AuditEvent]           |
| + get_events_in_range(start: datetime, end: datetime) -> List[AuditEvent] |
| + get_chain_summary() -> Dict[str, Any]                          |
| + get_integrity_report() -> Dict[str, Any]                       |
| + clear() -> None                                                |
+-----------------------------------------------------------------+
                              ^
                              |
                              |
+-----------------------------------------------------------------+
|                          AuditEvent                               |
+-----------------------------------------------------------------+
| - event_id: str                                                 |
| - event_type: AuditEventType                                    |
| - timestamp: datetime                                           |
| - previous_hash: str                                            |
| - current_hash: str                                             |
| - loop_id: Optional[str]                                        |
| - phase: Optional[str]                                          |
| - agent_id: Optional[str]                                       |
| - payload: Dict[str, Any]                                       |
| - metadata: Dict[str, Any]                                      |
| - sequence_number: int                                          |
+-----------------------------------------------------------------+
| + compute_hash() -> str                                          |
| + to_dict() -> Dict[str, Any]                                    |
| + to_json() -> str                                               |
| + verify_hash() -> bool                                          |
+-----------------------------------------------------------------+
```

### 2.2 Design Principles

1. **Immutability** - Events cannot be modified after creation
2. **Hash Chain Integrity** - Each event cryptographically linked to previous
3. **Thread Safety** - All operations protected by reentrant lock
4. **Loop Isolation** - Events bucketed by loop_id for concurrent execution
5. **Tamper Evidence** - Any modification breaks hash chain verification
6. **Complete Context** - Full pipeline context captured in each event

---

## 3. Python API Specification

### 3.1 Core Data Structures

```python
"""
GAIA AuditLogger

Provides tamper-proof audit trail of pipeline execution with hash chain integrity.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timezone
import threading
import hashlib
import json
import csv
import io

from gaia.pipeline.state import PipelineState
from gaia.utils.logging import get_logger


logger = get_logger(__name__)


class AuditEventType(Enum):
    """
    Enumeration of all auditable pipeline events.

    Categories:
        - Pipeline lifecycle (START, COMPLETE)
        - Phase transitions (ENTER, EXIT)
        - Agent operations (SELECTED, EXECUTED)
        - Quality operations (EVALUATED)
        - Decision operations (MADE)
        - Defect operations (DISCOVERED, REMEDIATED)
        - Loop operations (LOOP_BACK)
        - Tool operations (EXECUTED)
    """

    # Pipeline Lifecycle
    PIPELINE_START = auto()
    PIPELINE_COMPLETE = auto()

    # Phase Transitions
    PHASE_ENTER = auto()
    PHASE_EXIT = auto()

    # Agent Operations
    AGENT_SELECTED = auto()
    AGENT_EXECUTED = auto()

    # Quality Operations
    QUALITY_EVALUATED = auto()

    # Decision Operations
    DECISION_MADE = auto()

    # Defect Operations
    DEFECT_DISCOVERED = auto()
    DEFECT_REMEDIATED = auto()

    # Loop Operations
    LOOP_BACK = auto()

    # Tool Operations
    TOOL_EXECUTED = auto()

    def category(self) -> str:
        """Get category of this event type."""
        name = self.name
        if "PIPELINE" in name:
            return "lifecycle"
        elif "PHASE" in name:
            return "phase_transition"
        elif "AGENT" in name:
            return "agent_operation"
        elif "QUALITY" in name:
            return "quality"
        elif "DECISION" in name:
            return "decision"
        elif "DEFECT" in name:
            return "defect"
        elif "LOOP" in name:
            return "loop"
        elif "TOOL" in name:
            return "tool"
        return "unknown"


@dataclass(frozen=True)
class AuditEvent:
    """
    Immutable audit event with hash chain integrity.

    Each event contains:
    - Unique event ID (UUID)
    - Event type classification
    - Timestamp of occurrence
    - Hash of previous event (chain linkage)
    - Computed hash of current event
    - Context (loop_id, phase, agent_id)
    - Payload (event-specific data)
    - Sequence number (global ordering)
    """

    event_id: str
    event_type: AuditEventType
    timestamp: datetime
    previous_hash: str
    sequence_number: int
    current_hash: str = field(default="", init=False)
    loop_id: Optional[str] = None
    phase: Optional[str] = None
    agent_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Compute hash after initialization."""
        if not self.current_hash:
            object.__setattr__(self, 'current_hash', self.compute_hash())

    def compute_hash(self) -> str:
        """Compute cryptographic hash of this event."""
        hash_data = {
            "event_id": self.event_id,
            "event_type": self.event_type.name,
            "timestamp": self.timestamp.isoformat(),
            "previous_hash": self.previous_hash,
            "sequence_number": self.sequence_number,
            "loop_id": self.loop_id,
            "phase": self.phase,
            "agent_id": self.agent_id,
            "payload": json.dumps(self.payload, sort_keys=True),
            "metadata": json.dumps(self.metadata, sort_keys=True),
        }
        canonical = json.dumps(hash_data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def verify_hash(self) -> bool:
        """Verify that the stored hash matches computed hash."""
        return self.current_hash == self.compute_hash()

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.name,
            "timestamp": self.timestamp.isoformat(),
            "previous_hash": self.previous_hash,
            "current_hash": self.current_hash,
            "sequence_number": self.sequence_number,
            "loop_id": self.loop_id,
            "phase": self.phase,
            "agent_id": self.agent_id,
            "payload": self.payload,
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class IntegrityVerificationError(Exception):
    """Raised when hash chain integrity verification fails."""

    def __init__(
        self,
        failed_event_id: str,
        failure_type: str,
        expected_hash: Optional[str] = None,
        actual_hash: Optional[str] = None,
        message: Optional[str] = None,
    ):
        self.failed_event_id = failed_event_id
        self.failure_type = failure_type
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash

        if message is None:
            message = self._generate_message()

        super().__init__(message)

    def _generate_message(self) -> str:
        if self.failure_type == "HASH_MISMATCH":
            return (
                f"Hash mismatch for event {self.failed_event_id}: "
                f"expected {self.expected_hash}, got {self.actual_hash}"
            )
        elif self.failure_type == "BROKEN_CHAIN":
            return (
                f"Broken hash chain at event {self.failed_event_id}: "
                f"previous hash does not match"
            )
        elif self.failure_type == "MISSING_EVENT":
            return f"Missing event in chain: {self.failed_event_id}"
        else:
            return f"Integrity verification failed at {self.failed_event_id}: {self.failure_type}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": "IntegrityVerificationError",
            "failed_event_id": self.failed_event_id,
            "failure_type": self.failure_type,
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
            "message": str(self),
        }
```

### 3.2 AuditLogger Class

```python
class AuditLogger:
    """
    Tamper-proof audit logger with hash chain integrity.

    Features:
        - Hash chain integrity verification
        - Thread-safe concurrent access
        - Loop-based event isolation
        - Multiple export formats (JSON, CSV)
        - Flexible querying and filtering
    """

    GENESIS_HASH = "0" * 64  # 64 hex characters for SHA-256

    def __init__(
        self,
        logger_id: Optional[str] = None,
        genesis_hash: Optional[str] = None,
    ):
        """
        Initialize audit logger.

        Args:
            logger_id: Unique identifier for this logger instance
            genesis_hash: Optional custom genesis hash (default: 64 zeros)
        """
        self.logger_id = logger_id or f"audit-{datetime.now(timezone.utc).isoformat()}"
        self._events: List[AuditEvent] = []
        self._event_index: Dict[str, AuditEvent] = {}
        self._loop_buckets: Dict[str, List[str]] = {}
        self._sequence_counter = 0
        self._lock = threading.RLock()
        self._genesis_hash = genesis_hash or self.GENESIS_HASH
        self._initialized_at = datetime.now(timezone.utc)

        logger.info(
            "AuditLogger initialized",
            extra={"logger_id": self.logger_id, "genesis_hash": self._genesis_hash[:16] + "..."},
        )

    def log(
        self,
        event_type: AuditEventType,
        loop_id: Optional[str] = None,
        phase: Optional[str] = None,
        agent_id: Optional[str] = None,
        **kwargs,
    ) -> AuditEvent:
        """
        Log a new audit event.

        Args:
            event_type: Type of event being logged
            loop_id: Optional loop iteration identifier
            phase: Optional pipeline phase name
            agent_id: Optional agent identifier
            **kwargs: Additional payload data

        Returns:
            The created AuditEvent
        """
        with self._lock:
            previous_hash = self._get_latest_hash()
            self._sequence_counter += 1

            event = AuditEvent(
                event_id=self._generate_event_id(),
                event_type=event_type,
                timestamp=datetime.now(timezone.utc),
                previous_hash=previous_hash,
                sequence_number=self._sequence_counter,
                loop_id=loop_id,
                phase=phase,
                agent_id=agent_id,
                payload=kwargs,
            )

            self._events.append(event)
            self._event_index[event.event_id] = event

            if loop_id:
                if loop_id not in self._loop_buckets:
                    self._loop_buckets[loop_id] = []
                self._loop_buckets[loop_id].append(event.event_id)

            logger.debug(
                f"Logged event: {event.event_type.name}",
                extra={
                    "event_id": event.event_id,
                    "event_type": event.event_type.name,
                    "sequence": event.sequence_number,
                    "loop_id": loop_id,
                    "phase": phase,
                },
            )

            return event

    def verify_integrity(self) -> bool:
        """
        Verify the integrity of the entire hash chain.

        Returns:
            True if chain is intact, False if tampering detected

        Raises:
            IntegrityVerificationError: Details about first failure found
        """
        with self._lock:
            if not self._events:
                return True

            previous_hash = self._genesis_hash

            for event in self._events:
                # Verify event hash
                if not event.verify_hash():
                    raise IntegrityVerificationError(
                        failed_event_id=event.event_id,
                        failure_type="HASH_MISMATCH",
                        expected_hash=event.current_hash,
                        actual_hash=event.compute_hash(),
                    )

                # Verify chain linkage
                if event.previous_hash != previous_hash:
                    raise IntegrityVerificationError(
                        failed_event_id=event.event_id,
                        failure_type="BROKEN_CHAIN",
                        expected_hash=previous_hash,
                        actual_hash=event.previous_hash,
                    )

                previous_hash = event.current_hash

            return True

    def get_events(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[AuditEvent]:
        """
        Query events with optional filters.

        Args:
            filters: Dictionary of filter criteria
            limit: Maximum number of events to return
            offset: Number of events to skip

        Returns:
            List of matching AuditEvents (chronological order)
        """
        with self._lock:
            events = self._events.copy()

            if filters:
                if "event_type" in filters:
                    events = [e for e in events if e.event_type == filters["event_type"]]

                if "event_types" in filters:
                    events = [e for e in events if e.event_type in filters["event_types"]]

                if "loop_id" in filters:
                    events = [e for e in events if e.loop_id == filters["loop_id"]]

                if "phase" in filters:
                    events = [e for e in events if e.phase == filters["phase"]]

                if "agent_id" in filters:
                    events = [e for e in events if e.agent_id == filters["agent_id"]]

                if "start_time" in filters:
                    events = [e for e in events if e.timestamp >= filters["start_time"]]

                if "end_time" in filters:
                    events = [e for e in events if e.timestamp <= filters["end_time"]]

                if "category" in filters:
                    events = [e for e in events if e.event_type.category() == filters["category"]]

                if "payload_contains" in filters:
                    key, value = filters["payload_contains"]
                    events = [
                        e for e in events
                        if key in e.payload and e.payload[key] == value
                    ]

            events = events[offset:]
            if limit:
                events = events[:limit]

            return events

    def export_log(self, format: str = "json", indent: Optional[int] = 2) -> str:
        """
        Export complete audit log to string.

        Args:
            format: Export format ("json" or "csv")
            indent: JSON indentation (None for compact)

        Returns:
            Formatted string of audit log
        """
        with self._lock:
            if format == "json":
                return self._export_json(indent)
            elif format == "csv":
                return self._export_csv()
            else:
                raise ValueError(f"Unsupported export format: {format}")

    def _export_json(self, indent: Optional[int]) -> str:
        """Export to JSON format."""
        export_data = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "logger_id": self.logger_id,
            "genesis_hash": self._genesis_hash,
            "total_events": len(self._events),
            "integrity_verified": True,
            "events": [event.to_dict() for event in self._events],
        }

        try:
            self.verify_integrity()
            export_data["integrity_verified"] = True
        except IntegrityVerificationError:
            export_data["integrity_verified"] = False
            export_data["integrity_warning"] = "Chain verification failed - possible tampering"

        return json.dumps(export_data, indent=indent)

    def _export_csv(self) -> str:
        """Export to CSV format."""
        output = io.StringIO()

        fieldnames = [
            "sequence_number",
            "event_id",
            "event_type",
            "timestamp",
            "loop_id",
            "phase",
            "agent_id",
            "payload_summary",
            "current_hash",
        ]

        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for event in self._events:
            writer.writerow({
                "sequence_number": event.sequence_number,
                "event_id": event.event_id,
                "event_type": event.event_type.name,
                "timestamp": event.timestamp.isoformat(),
                "loop_id": event.loop_id or "",
                "phase": event.phase or "",
                "agent_id": event.agent_id or "",
                "payload_summary": json.dumps(event.payload),
                "current_hash": event.current_hash[:16] + "...",
            })

        return output.getvalue()

    def get_event(self, event_id: str) -> Optional[AuditEvent]:
        """Get specific event by ID."""
        with self._lock:
            return self._event_index.get(event_id)

    def get_events_by_type(self, event_type: AuditEventType) -> List[AuditEvent]:
        """Get all events of a specific type."""
        with self._lock:
            return [e for e in self._events if e.event_type == event_type]

    def get_events_by_loop(self, loop_id: str) -> List[AuditEvent]:
        """Get all events for a specific loop iteration."""
        with self._lock:
            event_ids = self._loop_buckets.get(loop_id, [])
            return [self._event_index[eid] for eid in event_ids if eid in self._event_index]

    def get_events_in_range(
        self,
        start: datetime,
        end: datetime,
    ) -> List[AuditEvent]:
        """Get events within a time range."""
        with self._lock:
            return [
                e for e in self._events
                if start <= e.timestamp <= end
            ]

    def get_chain_summary(self) -> Dict[str, Any]:
        """Get summary of the audit chain."""
        with self._lock:
            by_type = {}
            for event in self._events:
                type_name = event.event_type.name
                by_type[type_name] = by_type.get(type_name, 0) + 1

            by_category = {}
            for event in self._events:
                category = event.event_type.category()
                by_category[category] = by_category.get(category, 0) + 1

            first_timestamp = self._events[0].timestamp if self._events else None
            last_timestamp = self._events[-1].timestamp if self._events else None

            return {
                "logger_id": self.logger_id,
                "total_events": len(self._events),
                "by_type": by_type,
                "by_category": by_category,
                "first_event": first_timestamp.isoformat() if first_timestamp else None,
                "last_event": last_timestamp.isoformat() if last_timestamp else None,
                "genesis_hash": self._genesis_hash,
                "latest_hash": self._get_latest_hash(),
                "loop_count": len(self._loop_buckets),
            }

    def get_integrity_report(self) -> Dict[str, Any]:
        """Generate detailed integrity verification report."""
        with self._lock:
            report = {
                "is_valid": True,
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "total_events": len(self._events),
                "genesis_hash": self._genesis_hash,
                "latest_hash": self._get_latest_hash(),
                "failure_details": None,
            }

            try:
                self.verify_integrity()
            except IntegrityVerificationError as e:
                report["is_valid"] = False
                report["failure_details"] = e.to_dict()

            return report

    def clear(self) -> None:
        """Clear all events and reset logger."""
        with self._lock:
            self._events.clear()
            self._event_index.clear()
            self._loop_buckets.clear()
            self._sequence_counter = 0
            logger.warning("AuditLogger cleared", extra={"logger_id": self.logger_id})

    def _get_latest_hash(self) -> str:
        """Get hash of the most recent event (or genesis hash if empty)."""
        if self._events:
            return self._events[-1].current_hash
        return self._genesis_hash

    def _generate_event_id(self) -> str:
        """Generate unique event ID."""
        import uuid
        return f"evt-{uuid.uuid4().hex[:12]}"
```

---

## 4. Hash Chain Integrity Mechanism

### 4.1 Chain Structure

```
    GENESIS HASH (64 zeros)
           |
           v
    +----------------------------------------------+
    | EVENT 1: PIPELINE_START                      |
    | previous_hash: 0000000000000000...           |
    | current_hash:  sha256(event1_data + prev)    |
    +----------------------------------------------+
           |
           | current_hash becomes next previous_hash
           v
    +----------------------------------------------+
    | EVENT 2: PHASE_ENTER                         |
    | previous_hash: [EVENT 1 current_hash]        |
    | current_hash:  sha256(event2_data + prev)    |
    +----------------------------------------------+
           |
           v
    +----------------------------------------------+
    | EVENT 3: AGENT_SELECTED                      |
    | previous_hash: [EVENT 2 current_hash]        |
    | current_hash:  sha256(event3_data + prev)    |
    +----------------------------------------------+
           |
           v
           ... (chain continues)

TAMPERING DETECTION:
If EVENT 2 is modified:
- Recomputed hash != stored hash -> HASH_MISMATCH
- EVENT 3.previous_hash != EVENT 2.current_hash -> BROKEN_CHAIN
- All subsequent events also fail verification
```

### 4.2 Hash Computation

```python
def compute_event_hash(event_data: Dict[str, Any]) -> str:
    """Compute SHA-256 hash of event data."""
    canonical = json.dumps(event_data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
```

### 4.3 Integrity Verification Algorithm

```python
def verify_chain_integrity(events: List[AuditEvent], genesis_hash: str) -> bool:
    """
    Verify hash chain integrity.

    Algorithm:
    1. Start with genesis hash
    2. For each event in sequence order:
       a. Verify event.current_hash == compute_hash(event)
       b. Verify event.previous_hash == previous_event.current_hash
    3. If all checks pass, chain is intact
    """
    previous_hash = genesis_hash

    for event in events:
        if event.current_hash != event.compute_hash():
            return False, "HASH_MISMATCH"

        if event.previous_hash != previous_hash:
            return False, "BROKEN_CHAIN"

        previous_hash = event.current_hash

    return True, "VALID"
```

---

## 5. Event Type Definitions

### 5.1 Complete Event Type Catalog

| Event Type | Category | Description | Required Payload Fields |
|------------|----------|-------------|------------------------|
| PIPELINE_START | lifecycle | Pipeline execution initiated | pipeline_id, user_goal, config |
| PIPELINE_COMPLETE | lifecycle | Pipeline execution finished | final_state, quality_score, total_iterations |
| PHASE_ENTER | phase_transition | Entering a pipeline phase | phase_name, inputs_available |
| PHASE_EXIT | phase_transition | Exiting a pipeline phase | phase_name, outputs_produced, duration_ms |
| AGENT_SELECTED | agent_operation | Agent selected for task | agent_id, capabilities, selection_reason |
| AGENT_EXECUTED | agent_operation | Agent completed execution | agent_id, execution_time_ms, artifacts_produced |
| QUALITY_EVALUATED | quality | Quality assessment performed | quality_score, validators_run, defects_found |
| DECISION_MADE | decision | Decision engine made determination | decision_type, target_phase, reasoning |
| DEFECT_DISCOVERED | defect | Defect identified during quality | defect_id, defect_type, severity, phase_detected |
| DEFECT_REMEDIATED | defect | Defect fix verified | defect_id, remediation_description, verification_notes |
| LOOP_BACK | loop | Loop-back iteration triggered | target_phase, loop_id, defects_count, reason |
| TOOL_EXECUTED | tool | Tool or command executed | tool_name, command, exit_code, duration_ms |

---

## 6. Integration Points

### 6.1 Integration with LoopManager

```python
class LoopManager:
    def __init__(self, max_concurrent: int = 10):
        self._main_logger = AuditLogger(logger_id="pipeline-main")
        self._loop_loggers: Dict[str, AuditLogger] = {}

    async def create_loop(self, config: LoopConfig) -> str:
        """Create loop with dedicated audit logger."""
        loop_id = await super().create_loop(config)

        self._loop_loggers[loop_id] = AuditLogger(
            logger_id=f"loop-{loop_id}"
        )

        self._main_logger.log(
            event_type=AuditEventType.LOOP_BACK,
            loop_id=loop_id,
            target_phase=config.phase_name,
            defects_count=len(config.defects or []),
        )

        return loop_id

    def get_loop_logger(self, loop_id: str) -> AuditLogger:
        """Get audit logger for specific loop."""
        return self._loop_loggers.get(loop_id, self._main_logger)
```

### 6.2 Integration with PipelineState

```python
class PipelineState:
    def __init__(self, context: PipelineContext):
        self._audit_logger = AuditLogger(logger_id=context.pipeline_id)
        self._context = context

    def enter_phase(self, phase_name: str) -> None:
        """Log phase entry."""
        self._audit_logger.log(
            event_type=AuditEventType.PHASE_ENTER,
            phase=phase_name,
            inputs_available=list(self.snapshot.artifacts.keys()),
        )

    def exit_phase(self, phase_name: str, outputs: List[str]) -> None:
        """Log phase exit."""
        self._audit_logger.log(
            event_type=AuditEventType.PHASE_EXIT,
            phase=phase_name,
            outputs_produced=outputs,
        )

    def record_quality_evaluation(self, report: QualityReport) -> None:
        """Log quality evaluation."""
        self._audit_logger.log(
            event_type=AuditEventType.QUALITY_EVALUATED,
            phase="QUALITY",
            quality_score=report.overall_score,
            validators_run=report.validators_run,
            defects_found=len(report.defects),
        )

    def get_audit_logger(self) -> AuditLogger:
        """Get the audit logger for this state."""
        return self._audit_logger
```

### 6.3 Integration with PipelineEngine

```python
class PipelineEngine:
    def __init__(self):
        self._audit_logger = AuditLogger(logger_id="pipeline-engine")

    async def start(self) -> PipelineResult:
        """Start pipeline execution with audit logging."""
        self._audit_logger.log(
            event_type=AuditEventType.PIPELINE_START,
            pipeline_id=self._context.pipeline_id,
            user_goal=self._context.user_goal,
            config=self._config,
        )

        try:
            for phase_name in PHASE_ORDER:
                await self._execute_phase(phase_name)

            self._audit_logger.log(
                event_type=AuditEventType.PIPELINE_COMPLETE,
                final_state=self._state_machine.state.value,
                quality_score=self._state_machine.snapshot.quality_score,
                total_iterations=self._iteration_count,
            )

            return PipelineResult(
                state=PipelineState.COMPLETED,
                quality_score=self._state_machine.snapshot.quality_score,
            )
        except Exception as e:
            self._audit_logger.log(
                event_type=AuditEventType.PIPELINE_COMPLETE,
                final_state="FAILED",
                error=str(e),
            )
            raise
```

---

## 7. Export and Query Capabilities

### 7.1 Query Examples

```python
# Query all events in a specific loop
loop_events = logger.get_events(filters={"loop_id": "loop-002"})

# Query all quality-related events
quality_events = logger.get_events(filters={"category": "quality"})

# Query events by type
phase_exits = logger.get_events_by_type(AuditEventType.PHASE_EXIT)

# Query events in time range
from datetime import timedelta
recent_events = logger.get_events_in_range(
    start=datetime.now() - timedelta(hours=1),
    end=datetime.now()
)

# Query events with specific payload content
high_severity = logger.get_events(filters={
    "payload_contains": ("severity", "CRITICAL")
})
```

### 7.2 Export Formats

```python
# JSON export
json_export = logger.export_log(format="json")

# CSV export
csv_export = logger.export_log(format="csv")

# Write to file
with open("audit_log.json", "w") as f:
    f.write(logger.export_log(format="json", indent=2))
```

---

## 8. File Structure

```
gaia/src/gaia/pipeline/
+-- audit_logger.py              # Core AuditLogger implementation
+-- audit_event.py               # AuditEvent and AuditEventType definitions
+-- exceptions.py                # IntegrityVerificationError
+-- __init__.py                  # Export public API

gaia/tests/pipeline/
+-- test_audit_logger.py         # AuditLogger unit tests
+-- test_audit_event.py          # AuditEvent tests
+-- test_hash_chain.py           # Hash chain integrity tests
+-- test_integration.py          # Integration tests
```

---

## 9. Testing Strategy

### 9.1 Unit Tests

```python
import pytest
from datetime import datetime, timezone
from gaia.pipeline.audit_logger import (
    AuditLogger,
    AuditEvent,
    AuditEventType,
    IntegrityVerificationError,
)


class TestAuditEvent:
    def test_create_event(self):
        event = AuditEvent(
            event_id="evt-001",
            event_type=AuditEventType.PHASE_ENTER,
            timestamp=datetime.now(timezone.utc),
            previous_hash="0" * 64,
            sequence_number=1,
            phase="PLANNING",
        )
        assert event.event_id == "evt-001"
        assert event.phase == "PLANNING"

    def test_compute_hash(self):
        event = AuditEvent(
            event_id="evt-001",
            event_type=AuditEventType.PHASE_ENTER,
            timestamp=datetime.now(timezone.utc),
            previous_hash="0" * 64,
            sequence_number=1,
        )
        hash1 = event.compute_hash()
        hash2 = event.compute_hash()
        assert hash1 == hash2  # Deterministic

    def test_verify_hash(self):
        event = AuditEvent(
            event_id="evt-001",
            event_type=AuditEventType.PHASE_ENTER,
            timestamp=datetime.now(timezone.utc),
            previous_hash="0" * 64,
            sequence_number=1,
        )
        assert event.verify_hash() is True


class TestAuditLogger:
    @pytest.fixture
    def logger(self):
        return AuditLogger(logger_id="test-logger")

    def test_log_event(self, logger):
        event = logger.log(
            event_type=AuditEventType.PIPELINE_START,
            pipeline_id="pipe-001",
        )
        assert event.event_type == AuditEventType.PIPELINE_START
        assert event.sequence_number == 1

    def test_hash_chain(self, logger):
        event1 = logger.log(AuditEventType.PIPELINE_START)
        event2 = logger.log(AuditEventType.PHASE_ENTER, phase="PLANNING")
        event3 = logger.log(AuditEventType.AGENT_SELECTED)

        assert event2.previous_hash == event1.current_hash
        assert event3.previous_hash == event2.current_hash

    def test_verify_integrity(self, logger):
        logger.log(AuditEventType.PIPELINE_START)
        logger.log(AuditEventType.PHASE_ENTER, phase="PLANNING")
        logger.log(AuditEventType.AGENT_SELECTED)

        assert logger.verify_integrity() is True

    def test_tampering_detection(self, logger):
        logger.log(AuditEventType.PIPELINE_START)
        logger.log(AuditEventType.PHASE_ENTER, phase="PLANNING")
        logger.log(AuditEventType.AGENT_SELECTED)

        # Tamper with event
        tampered_event = logger._events[1]
        object.__setattr__(tampered_event, 'payload', {"tampered": True})

        with pytest.raises(IntegrityVerificationError):
            logger.verify_integrity()

    def test_thread_safety(self):
        import threading
        logger = AuditLogger()

        def log_events():
            for i in range(100):
                logger.log(AuditEventType.TOOL_EXECUTED, tool_name=f"tool-{i}")

        threads = [threading.Thread(target=log_events) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(logger.get_events()) == 1000
        assert logger.verify_integrity() is True
```

---

## 10. Success Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| API Completeness | 100% | All required methods implemented |
| Hash Chain Integrity | 100% | Tampering always detected |
| Thread Safety | 100% | All operations protected by lock |
| Event Coverage | All 12 types | All event types defined and tested |
| Export Formats | JSON + CSV | Both formats working |
| Integration | 0 breaking changes | Existing tests pass |
| Test Coverage | >= 95% | Unit test line coverage |
| Quality Threshold | >= 0.90 | QUALITY phase must achieve |
| Concurrent Loops | 10+ parallel | Supported without race conditions |

---

## 11. Appendix

### 11.1 Glossary

| Term | Definition |
|------|------------|
| AuditEvent | Immutable record of a pipeline event |
| Hash Chain | Cryptographic linkage of events via hashes |
| Genesis Hash | Hash of the "zero" event (64 zeros) |
| Integrity Verification | Process of validating hash chain |
| Tamper Evidence | Ability to detect modification attempts |
| Loop Bucket | Events grouped by loop_id for isolation |

### 11.2 References

- `gaia/src/gaia/pipeline/loop_manager.py` - Loop execution context
- `gaia/src/gaia/pipeline/state.py` - PipelineState implementation
- `PHASECONTRACT_DESIGN.md` - Design pattern reference
- `DEFECT_REMEDIATION_TRACKER_DESIGN.md` - Integration reference

---

*Document Version: 1.0.0*
*Generated: 2026-03-23*
*Status: Ready for Development*
*Quality Target: >= 0.90*
