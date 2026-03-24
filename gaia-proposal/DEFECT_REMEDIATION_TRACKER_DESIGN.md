# DefectRemediationTracker Design Document

**Document Type:** Technical Design Specification
**Component:** DefectRemediationTracker
**Version:** 1.0.0
**Date:** 2026-03-23
**Author:** Dr. Sarah Kim, Technical Product Strategist & Engineering Lead
**Phase:** PLANNING
**Quality Target:** >= 0.90

---

## 1. Executive Summary

### 1.1 Purpose

The DefectRemediationTracker component provides comprehensive tracking and management of defects throughout the GAIA pipeline's recursive loop iterations. It enables:

- **Status lifecycle management** - Track defects from discovery through verification
- **Audit trail** - Complete history of all status changes with timestamps and reasons
- **Concurrent loop support** - Thread-safe operations for parallel loop iterations
- **Analytics and reporting** - Real-time visibility into defect resolution progress

### 1.2 Problem Statement

The GAIA pipeline currently has a `DefectRouter` that routes defects to appropriate phases, but lacks:

1. **Status tracking** - No way to track if a defect is being fixed, resolved, or verified
2. **Lifecycle management** - Cannot enforce valid status transitions (e.g., OPEN → IN_PROGRESS → RESOLVED → VERIFIED)
3. **Audit trail** - No record of who changed a defect's status and when
4. **Progress visibility** - Cannot query pending defects or generate resolution summaries
5. **Loop isolation** - Cannot track defects separately across concurrent loop iterations

Without remediation tracking:
- Defects may be marked as "fixed" without verification
- No accountability for defect resolution
- Cannot measure mean time to resolution (MTTR)
- Loop-back iterations lose defect context

### 1.3 Solution Overview

DefectRemediationTracker introduces:

1. **DefectStatusChange** - Immutable audit record of each status transition
2. **Status lifecycle enforcement** - Valid transition rules (e.g., cannot verify without resolving first)
3. **Thread-safe operations** - Lock-based concurrency control for parallel loops
4. **Query capabilities** - Filter by phase, status, severity, defect type
5. **Analytics** - Summary statistics and progress tracking

---

## 2. Component Architecture

### 2.1 Class Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      DefectRemediationTracker                    │
├─────────────────────────────────────────────────────────────────┤
│ - _defects: Dict[str, Defect]                                   │
│ - _history: List[DefectStatusChange]                            │
│ - _phase_buckets: Dict[str, Set[str]]                           │
│ - _lock: threading.RLock                                        │
├─────────────────────────────────────────────────────────────────┤
│ + add_defect(defect: Defect, phase: str) → None                 │
│ + start_fix(defect_id: str) → DefectStatusChange                │
│ + mark_resolved(defect_id: str, description: str) → DefectStatusChange │
│ + mark_verified(defect_id: str, notes: str) → DefectStatusChange │
│ + mark_deferred(defect_id: str, reason: str) → DefectStatusChange │
│ + mark_cannot_fix(defect_id: str, reason: str) → DefectStatusChange │
│ + get_pending_defects() → List[Defect]                          │
│ + get_summary() → Dict[str, Any]                                │
│ + get_defect_history(defect_id: Optional[str] = None) → List[DefectStatusChange] │
│ + get_defects_by_phase(phase: str) → List[Defect]               │
│ + get_defects_by_status(status: DefectStatus) → List[Defect]    │
│ + get_defect(defect_id: str) → Optional[Defect]                 │
│ + get_all_defects() → List[Defect]                              │
│ + export_audit_log() → List[Dict[str, Any]]                     │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
                              │
┌─────────────────────────────────────────────────────────────────┐
│                      DefectStatusChange                          │
├─────────────────────────────────────────────────────────────────┤
│ - defect_id: str                                                │
│ - old_status: DefectStatus                                      │
│ - new_status: DefectStatus                                      │
│ - changed_at: datetime                                          │
│ - changed_by: Optional[str]                                     │
│ - description: Optional[str]                                    │
│ - metadata: Dict[str, Any]                                      │
├─────────────────────────────────────────────────────────────────┤
│ + to_dict() → Dict[str, Any]                                    │
│ + to_audit_entry() → Dict[str, Any]                             │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Design Principles

1. **Immutability** - Status change history is append-only (audit trail)
2. **Thread Safety** - All operations are protected by reentrant lock
3. **Lifecycle Enforcement** - Invalid status transitions raise exceptions
4. **Phase Isolation** - Defects are bucketed by phase for concurrent loops
5. **Integration** - Works seamlessly with existing DefectRouter types

---

## 3. Python API Specification

### 3.1 Core Data Structures

```python
"""
GAIA DefectRemediationTracker

Tracks defect status across loop iterations with full audit trail.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timezone
import threading
import copy

from gaia.pipeline.defect_router import Defect, DefectType, DefectSeverity, DefectStatus
from gaia.pipeline.state import PipelineState
from gaia.utils.logging import get_logger


logger = get_logger(__name__)


class DefectStatus(Enum):
    """
    Status of defect in remediation lifecycle.

    Extends the base DefectStatus from defect_router.py with additional states.

    Lifecycle:
        OPEN → IN_PROGRESS → RESOLVED → VERIFIED (success path)
        OPEN → DEFERRED (blocked or low priority)
        OPEN → CANNOT_FIX (fundamental limitation)

    Attributes:
        OPEN: Newly discovered defect, awaiting action
        IN_PROGRESS: Currently being fixed
        RESOLVED: Fix implemented, awaiting verification
        VERIFIED: Fix confirmed by quality check
        DEFERRED: Cannot fix now (with reason)
        CANNOT_FIX: Fundamental limitation preventing fix
    """

    OPEN = auto()
    IN_PROGRESS = auto()
    RESOLVED = auto()
    VERIFIED = auto()
    DEFERRED = auto()
    CANNOT_FIX = auto()

    def is_terminal(self) -> bool:
        """Check if this is a terminal status (no further transitions expected)."""
        return self in {DefectStatus.VERIFIED, DefectStatus.DEFERRED, DefectStatus.CANNOT_FIX}

    def is_active(self) -> bool:
        """Check if defect is actively being worked."""
        return self in {DefectStatus.OPEN, DefectStatus.IN_PROGRESS}


@dataclass
class DefectStatusChange:
    """
    Immutable record of a defect status change.

    Captures the complete context of a status transition for audit purposes.

    Attributes:
        defect_id: Unique defect identifier
        old_status: Previous status value
        new_status: New status value
        changed_at: Timestamp of change
        changed_by: Optional identifier of who/what made the change
        description: Optional description of the change
        metadata: Additional contextual information

    Example:
        >>> change = DefectStatusChange(
        ...     defect_id="defect-001",
        ...     old_status=DefectStatus.OPEN,
        ...     new_status=DefectStatus.IN_PROGRESS,
        ...     description="Starting fix in DEVELOPMENT phase"
        ... )
        >>> print(change.to_dict())
    """

    defect_id: str
    old_status: DefectStatus
    new_status: DefectStatus
    changed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    changed_by: Optional[str] = None
    description: Optional[str] = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate status change."""
        if self.old_status == self.new_status:
            logger.warning(
                f"Status change from {self.old_status} to {self.new_status} is a no-op",
                extra={"defect_id": self.defect_id},
            )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns:
            Dictionary representation of the status change
        """
        return {
            "defect_id": self.defect_id,
            "old_status": self.old_status.name,
            "new_status": self.new_status.name,
            "changed_at": self.changed_at.isoformat(),
            "changed_by": self.changed_by,
            "description": self.description,
            "metadata": self.metadata,
        }

    def to_audit_entry(self) -> Dict[str, Any]:
        """
        Convert to audit log entry format.

        Returns:
            Audit log formatted entry
        """
        return {
            "event_type": "DEFECT_STATUS_CHANGE",
            "defect_id": self.defect_id,
            "timestamp": self.changed_at.isoformat(),
            "actor": self.changed_by,
            "action": f"{self.old_status.name} → {self.new_status.name}",
            "description": self.description,
            "metadata": self.metadata,
        }


class InvalidStatusTransitionError(Exception):
    """
    Raised when an invalid status transition is attempted.

    Attributes:
        defect_id: Defect that had the invalid transition
        current_status: Current status value
        requested_status: Requested new status
        allowed_transitions: List of allowed next statuses
    """

    def __init__(
        self,
        defect_id: str,
        current_status: DefectStatus,
        requested_status: DefectStatus,
        allowed_transitions: List[DefectStatus],
    ):
        self.defect_id = defect_id
        self.current_status = current_status
        self.requested_status = requested_status
        self.allowed_transitions = allowed_transitions

        super().__init__(
            f"Invalid status transition for {defect_id}: "
            f"{current_status.name} → {requested_status.name}. "
            f"Allowed transitions: {[s.name for s in allowed_transitions]}",
            {
                "defect_id": defect_id,
                "current_status": current_status.name,
                "requested_status": requested_status.name,
                "allowed_transitions": [s.name for s in allowed_transitions],
            },
        )
```

### 3.2 DefectRemediationTracker Class

```python
class DefectRemediationTracker:
    """
    Tracks defect status across loop iterations with full audit trail.

    The DefectRemediationTracker manages the complete lifecycle of defects
    from discovery through verification. It enforces valid status transitions,
    maintains an immutable audit trail, and supports concurrent loop execution.

    Status Lifecycle:
        OPEN ──► IN_PROGRESS ──► RESOLVED ──► VERIFIED
          │                              │
          │                              └──► (Quality check confirms fix)
          │
          ├──► DEFERRED (blocked, low priority, or waiting on dependency)
          │
          └──► CANNOT_FIX (fundamental limitation or technical constraint)

    Example:
        >>> tracker = DefectRemediationTracker()
        >>> defect = Defect(
        ...     id="defect-001",
        ...     type=DefectType.MISSING_TESTS,
        ...     severity=DefectSeverity.HIGH,
        ...     description="No unit tests for new module"
        ... )
        >>> tracker.add_defect(defect, phase="QUALITY")
        >>> tracker.start_fix("defect-001")  # OPEN → IN_PROGRESS
        >>> tracker.mark_resolved("defect-001", "Added 15 unit tests")  # IN_PROGRESS → RESOLVED
        >>> tracker.mark_verified("defect-001", "Quality check passed")  # RESOLVED → VERIFIED
        >>> pending = tracker.get_pending_defects()
        >>> summary = tracker.get_summary()
    """

    # Valid status transitions
    ALLOWED_TRANSITIONS: Dict[DefectStatus, List[DefectStatus]] = {
        DefectStatus.OPEN: [
            DefectStatus.IN_PROGRESS,
            DefectStatus.DEFERRED,
            DefectStatus.CANNOT_FIX,
        ],
        DefectStatus.IN_PROGRESS: [
            DefectStatus.RESOLVED,
            DefectStatus.OPEN,  # Can reopen if not ready
            DefectStatus.DEFERRED,
        ],
        DefectStatus.RESOLVED: [
            DefectStatus.VERIFIED,
            DefectStatus.IN_PROGRESS,  # Reopen for more work
            DefectStatus.OPEN,
        ],
        DefectStatus.VERIFIED: [
            DefectStatus.IN_PROGRESS,  # Regression found
        ],
        DefectStatus.DEFERRED: [
            DefectStatus.OPEN,  # Can be reopened
            DefectStatus.IN_PROGRESS,
        ],
        DefectStatus.CANNOT_FIX: [
            DefectStatus.OPEN,  # Can be reopened if workaround found
        ],
    }

    def __init__(self, tracker_id: Optional[str] = None):
        """
        Initialize defect remediation tracker.

        Args:
            tracker_id: Optional unique identifier for this tracker instance
                       (useful for tracking per-loop or per-phase)

        Example:
            >>> tracker = DefectRemediationTracker(tracker_id="loop-001")
            >>> tracker = DefectRemediationTracker(tracker_id="phase-QUALITY")
        """
        self.tracker_id = tracker_id or f"tracker-{datetime.now(timezone.utc).isoformat()}"
        self._defects: Dict[str, Defect] = {}
        self._history: List[DefectStatusChange] = []
        self._phase_buckets: Dict[str, Set[str]] = {}  # phase -> set of defect IDs
        self._lock = threading.RLock()

        logger.info(
            "DefectRemediationTracker initialized",
            extra={"tracker_id": self.tracker_id},
        )

    def add_defect(self, defect: Defect, phase: str) -> None:
        """
        Add a new defect to the tracker.

        The defect must have OPEN status when added. Automatically
        creates a status change record for the audit trail.

        Args:
            defect: Defect to track
            phase: Pipeline phase where defect was detected

        Raises:
            ValueError: If defect status is not OPEN

        Example:
            >>> defect = Defect(id="d1", type=DefectType.MISSING_TESTS, ...)
            >>> tracker.add_defect(defect, phase="QUALITY")
            >>> tracker.add_defect(defect, phase="DEVELOPMENT")  # Duplicate ID ignored
        """
        with self._lock:
            # Check for duplicate
            if defect.id in self._defects:
                logger.warning(
                    f"Defect {defect.id} already exists, ignoring duplicate add",
                    extra={"defect_id": defect.id},
                )
                return

            # Validate initial status
            if defect.status != DefectStatus.OPEN:
                logger.warning(
                    f"Defect {defect.id} added with non-OPEN status: {defect.status.name}. "
                    f"Setting to OPEN.",
                    extra={"defect_id": defect.id, "original_status": defect.status.name},
                )
                # Create a deep copy to avoid modifying the original
                defect = copy.deepcopy(defect)
                defect.status = DefectStatus.OPEN

            # Add defect
            self._defects[defect.id] = defect

            # Add to phase bucket
            if phase not in self._phase_buckets:
                self._phase_buckets[phase] = set()
            self._phase_buckets[phase].add(defect.id)

            # Record initial status change
            change = DefectStatusChange(
                defect_id=defect.id,
                old_status=DefectStatus.OPEN,  # Initial state
                new_status=DefectStatus.OPEN,
                description=f"Defect discovered in {phase} phase",
                metadata={"phase_detected": phase},
            )
            self._history.append(change)

            logger.info(
                f"Added defect: {defect.id} ({defect.type.name}, {defect.severity.name})",
                extra={
                    "defect_id": defect.id,
                    "phase": phase,
                    "severity": defect.severity.name,
                },
            )

    def start_fix(self, defect_id: str, changed_by: Optional[str] = None) -> DefectStatusChange:
        """
        Start working on a defect (OPEN → IN_PROGRESS).

        Args:
            defect_id: ID of defect to start fixing
            changed_by: Optional identifier of who/what is making the change

        Returns:
            DefectStatusChange record

        Raises:
            InvalidStatusTransitionError: If current status doesn't allow transition
            KeyError: If defect not found

        Example:
            >>> tracker.add_defect(defect, "QUALITY")
            >>> change = tracker.start_fix("defect-001", changed_by="senior-developer")
            >>> print(change.description)  # "Starting fix"
        """
        return self._transition_status(
            defect_id=defect_id,
            new_status=DefectStatus.IN_PROGRESS,
            description="Starting fix",
            changed_by=changed_by,
        )

    def mark_resolved(
        self,
        defect_id: str,
        description: str,
        changed_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DefectStatusChange:
        """
        Mark a defect as resolved (IN_PROGRESS → RESOLVED).

        The fix has been implemented but awaits verification by quality check.

        Args:
            defect_id: ID of defect to mark resolved
            description: Description of the fix implemented
            changed_by: Optional identifier of who/what made the change
            metadata: Optional additional metadata about the fix

        Returns:
            DefectStatusChange record

        Raises:
            InvalidStatusTransitionError: If current status doesn't allow transition
            KeyError: If defect not found

        Example:
            >>> tracker.start_fix("defect-001")
            >>> change = tracker.mark_resolved(
            ...     "defect-001",
            ...     description="Added 15 unit tests with 95% coverage",
            ...     changed_by="senior-developer",
            ...     metadata={"tests_added": 15, "coverage": 0.95}
            ... )
        """
        return self._transition_status(
            defect_id=defect_id,
            new_status=DefectStatus.RESOLVED,
            description=description,
            changed_by=changed_by,
            metadata=metadata or {},
        )

    def mark_verified(
        self,
        defect_id: str,
        notes: str,
        changed_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DefectStatusChange:
        """
        Verify a defect fix (RESOLVED → VERIFIED).

        Called after quality check confirms the fix is effective.

        Args:
            defect_id: ID of defect to verify
            notes: Verification notes from quality check
            changed_by: Optional identifier of who/what made the change
            metadata: Optional additional metadata about verification

        Returns:
            DefectStatusChange record

        Raises:
            InvalidStatusTransitionError: If current status doesn't allow transition
            KeyError: If defect not found

        Example:
            >>> tracker.mark_resolved("defect-001", "Fix implemented")
            >>> change = tracker.mark_verified(
            ...     "defect-001",
            ...     notes="Quality check passed - tests run successfully",
            ...     changed_by="quality-reviewer",
            ...     metadata={"quality_score": 0.95}
            ... )
        """
        return self._transition_status(
            defect_id=defect_id,
            new_status=DefectStatus.VERIFIED,
            description=notes,
            changed_by=changed_by,
            metadata=metadata or {},
        )

    def mark_deferred(
        self,
        defect_id: str,
        reason: str,
        changed_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DefectStatusChange:
        """
        Defer a defect (OPEN/IN_PROGRESS → DEFERRED).

        Used when a defect cannot or should not be fixed in the current iteration.

        Args:
            defect_id: ID of defect to defer
            reason: Reason for deferral
            changed_by: Optional identifier of who/what made the change
            metadata: Optional additional metadata

        Returns:
            DefectStatusChange record

        Raises:
            InvalidStatusTransitionError: If current status doesn't allow transition
            KeyError: If defect not found

        Example:
            >>> tracker.mark_deferred(
            ...     "defect-001",
            ...     reason="Low priority, deferring to next sprint",
            ...     changed_by="product-owner",
            ...     metadata={"defer_reason": "low_priority"}
            ... )
        """
        return self._transition_status(
            defect_id=defect_id,
            new_status=DefectStatus.DEFERRED,
            description=reason,
            changed_by=changed_by,
            metadata={**(metadata or {}), "defer_reason": reason},
        )

    def mark_cannot_fix(
        self,
        defect_id: str,
        reason: str,
        changed_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DefectStatusChange:
        """
        Mark a defect as unfixable (OPEN/IN_PROGRESS → CANNOT_FIX).

        Used when a fundamental limitation prevents fixing the defect.

        Args:
            defect_id: ID of defect to mark as unfixable
            reason: Reason why it cannot be fixed
            changed_by: Optional identifier of who/what made the change
            metadata: Optional additional metadata

        Returns:
            DefectStatusChange record

        Raises:
            InvalidStatusTransitionError: If current status doesn't allow transition
            KeyError: If defect not found

        Example:
            >>> tracker.mark_cannot_fix(
            ...     "defect-001",
            ...     reason="Platform limitation - cannot be resolved",
            ...     changed_by="tech-lead",
            ...     metadata={"limitation": "platform"}
            ... )
        """
        return self._transition_status(
            defect_id=defect_id,
            new_status=DefectStatus.CANNOT_FIX,
            description=reason,
            changed_by=changed_by,
            metadata={**(metadata or {}), "cannot_fix_reason": reason},
        )

    def _transition_status(
        self,
        defect_id: str,
        new_status: DefectStatus,
        description: str = "",
        changed_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DefectStatusChange:
        """
        Internal method to transition defect status.

        Args:
            defect_id: ID of defect to transition
            new_status: New status value
            description: Description of the transition
            changed_by: Who/what made the change
            metadata: Additional metadata

        Returns:
            DefectStatusChange record

        Raises:
            InvalidStatusTransitionError: If transition is not allowed
            KeyError: If defect not found
        """
        with self._lock:
            if defect_id not in self._defects:
                raise KeyError(f"Defect not found: {defect_id}")

            defect = self._defects[defect_id]
            old_status = defect.status

            # Validate transition
            allowed = self.ALLOWED_TRANSITIONS.get(old_status, [])
            if new_status not in allowed:
                raise InvalidStatusTransitionError(
                    defect_id=defect_id,
                    current_status=old_status,
                    requested_status=new_status,
                    allowed_transitions=allowed,
                )

            # Update defect status
            defect.status = new_status

            # Record status change
            change = DefectStatusChange(
                defect_id=defect_id,
                old_status=old_status,
                new_status=new_status,
                description=description,
                changed_by=changed_by,
                metadata=metadata or {},
            )
            self._history.append(change)

            logger.info(
                f"Defect {defect_id} status changed: {old_status.name} → {new_status.name}",
                extra={
                    "defect_id": defect_id,
                    "old_status": old_status.name,
                    "new_status": new_status.name,
                    "changed_by": changed_by,
                },
            )

            return change

    def get_pending_defects(self) -> List[Defect]:
        """
        Get all defects that are not in terminal status.

        Returns defects with status: OPEN, IN_PROGRESS, or RESOLVED.

        Returns:
            List of pending defects sorted by severity (CRITICAL first)

        Example:
            >>> pending = tracker.get_pending_defects()
            >>> print(f"{len(pending)} defects need attention")
        """
        with self._lock:
            pending = [
                d for d in self._defects.values()
                if d.status in {DefectStatus.OPEN, DefectStatus.IN_PROGRESS, DefectStatus.RESOLVED}
            ]
            # Sort by severity (CRITICAL=1, HIGH=2, MEDIUM=3, LOW=4)
            pending.sort(key=lambda d: d.severity.value)
            return pending

    def get_summary(self) -> Dict[str, Any]:
        """
        Generate summary statistics for all tracked defects.

        Returns:
            Dictionary with summary statistics including:
            - total: Total number of defects
            - by_status: Count by status
            - by_severity: Count by severity
            - by_type: Count by defect type
            - by_phase: Count by phase detected
            - pending_count: Number not in terminal status
            - verified_count: Number verified as fixed
            - resolution_rate: Percentage resolved/verified

        Example:
            >>> summary = tracker.get_summary()
            >>> print(f"Total: {summary['total']}, Pending: {summary['pending_count']}")
            >>> print(f"Resolution rate: {summary['resolution_rate']:.1%}")
        """
        with self._lock:
            summary = {
                "total": len(self._defects),
                "by_status": {},
                "by_severity": {},
                "by_type": {},
                "by_phase": {},
                "pending_count": 0,
                "verified_count": 0,
                "deferred_count": 0,
                "cannot_fix_count": 0,
                "resolution_rate": 0.0,
            }

            for defect in self._defects.values():
                # Count by status
                status_name = defect.status.name
                summary["by_status"][status_name] = summary["by_status"].get(status_name, 0) + 1

                # Count pending vs terminal
                if defect.status == DefectStatus.VERIFIED:
                    summary["verified_count"] += 1
                elif defect.status == DefectStatus.DEFERRED:
                    summary["deferred_count"] += 1
                elif defect.status == DefectStatus.CANNOT_FIX:
                    summary["cannot_fix_count"] += 1
                else:
                    summary["pending_count"] += 1

                # Count by severity
                severity_name = defect.severity.name
                summary["by_severity"][severity_name] = (
                    summary["by_severity"].get(severity_name, 0) + 1
                )

                # Count by type
                type_name = defect.type.name
                summary["by_type"][type_name] = summary["by_type"].get(type_name, 0) + 1

                # Count by phase (from metadata)
                phase = defect.phase_detected or "UNKNOWN"
                summary["by_phase"][phase] = summary["by_phase"].get(phase, 0) + 1

            # Calculate resolution rate
            resolved_or_verified = (
                summary["verified_count"] + summary["deferred_count"] + summary["cannot_fix_count"]
            )
            if summary["total"] > 0:
                summary["resolution_rate"] = resolved_or_verified / summary["total"]

            return summary

    def get_defect_history(
        self,
        defect_id: Optional[str] = None,
        status_filter: Optional[DefectStatus] = None,
    ) -> List[DefectStatusChange]:
        """
        Get defect status change history.

        Args:
            defect_id: Optional filter for specific defect
            status_filter: Optional filter for specific new status

        Returns:
            List of status changes (chronological order)

        Example:
            >>> all_history = tracker.get_defect_history()
            >>> single_defect = tracker.get_defect_history("defect-001")
            >>> verified_only = tracker.get_defect_history(status_filter=DefectStatus.VERIFIED)
        """
        with self._lock:
            history = self._history.copy()

            if defect_id:
                history = [h for h in history if h.defect_id == defect_id]

            if status_filter:
                history = [h for h in history if h.new_status == status_filter]

            return history

    def get_defects_by_phase(self, phase: str) -> List[Defect]:
        """
        Get all defects detected in a specific phase.

        Args:
            phase: Phase name to filter by

        Returns:
            List of defects from that phase

        Example:
            >>> quality_defects = tracker.get_defects_by_phase("QUALITY")
        """
        with self._lock:
            phase_defect_ids = self._phase_buckets.get(phase, set())
            return [
                self._defects[did] for did in phase_defect_ids if did in self._defects
            ]

    def get_defects_by_status(self, status: DefectStatus) -> List[Defect]:
        """
        Get all defects with a specific status.

        Args:
            status: Status to filter by

        Returns:
            List of defects with that status

        Example:
            >>> open_defects = tracker.get_defects_by_status(DefectStatus.OPEN)
            >>> in_progress = tracker.get_defects_by_status(DefectStatus.IN_PROGRESS)
        """
        with self._lock:
            return [d for d in self._defects.values() if d.status == status]

    def get_defect(self, defect_id: str) -> Optional[Defect]:
        """
        Get a specific defect by ID.

        Args:
            defect_id: Defect ID to retrieve

        Returns:
            Defect or None if not found

        Example:
            >>> defect = tracker.get_defect("defect-001")
            >>> if defect:
            ...     print(f"Status: {defect.status.name}")
        """
        with self._lock:
            return self._defects.get(defect_id)

    def get_all_defects(self) -> List[Defect]:
        """
        Get all tracked defects.

        Returns:
            List of all defects

        Example:
            >>> all_defects = tracker.get_all_defects()
        """
        with self._lock:
            return list(self._defects.values())

    def export_audit_log(self) -> List[Dict[str, Any]]:
        """
        Export complete audit log of all status changes.

        Returns:
            List of audit entries in chronological order

        Example:
            >>> audit_log = tracker.export_audit_log()
            >>> for entry in audit_log:
            ...     print(f"{entry['timestamp']}: {entry['action']}")
        """
        with self._lock:
            return [change.to_audit_entry() for change in self._history]

    def get_analytics(self) -> Dict[str, Any]:
        """
        Generate advanced analytics for defect remediation.

        Returns:
            Dictionary with analytics including:
            - mean_time_to_resolve: Average time from OPEN to RESOLVED
            - mean_time_to_verify: Average time from RESOLVED to VERIFIED
            - defects_by_severity_priority: Defects sorted by severity
            - phase_distribution: Defects per phase
            - status_trend: Status distribution over time

        Example:
            >>> analytics = tracker.get_analytics()
            >>> print(f"MTTR: {analytics['mean_time_to_resolve']:.2f} hours")
        """
        with self._lock:
            analytics = {
                "mean_time_to_resolve": None,
                "mean_time_to_verify": None,
                "defects_by_severity_priority": {},
                "phase_distribution": {},
                "status_trend": {},
            }

            # Calculate mean time to resolve
            resolve_times = []
            verify_times = []

            for defect_id in self._defects:
                defect_history = [h for h in self._history if h.defect_id == defect_id]

                # Find OPEN → IN_PROGRESS → RESOLVED → VERIFIED transitions
                open_time = None
                resolve_time = None
                verified_time = None

                for change in defect_history:
                    if change.new_status == DefectStatus.OPEN and open_time is None:
                        open_time = change.changed_at
                    elif change.new_status == DefectStatus.RESOLVED:
                        resolve_time = change.changed_at
                    elif change.new_status == DefectStatus.VERIFIED:
                        verified_time = change.changed_at

                if open_time and resolve_time:
                    resolve_times.append((resolve_time - open_time).total_seconds() / 3600)

                if resolve_time and verified_time:
                    verify_times.append((verified_time - resolve_time).total_seconds() / 3600)

            if resolve_times:
                analytics["mean_time_to_resolve"] = sum(resolve_times) / len(resolve_times)

            if verify_times:
                analytics["mean_time_to_verify"] = sum(verify_times) / len(verify_times)

            # Severity priority distribution
            for severity in DefectSeverity:
                count = sum(1 for d in self._defects.values() if d.severity == severity)
                if count > 0:
                    analytics["defects_by_severity_priority"][severity.name] = count

            # Phase distribution
            analytics["phase_distribution"] = dict(self._phase_buckets)
            for phase, defect_ids in analytics["phase_distribution"].items():
                analytics["phase_distribution"][phase] = len(defect_ids)

            # Status trend (simplified)
            analytics["status_trend"] = {
                "OPEN": len([d for d in self._defects.values() if d.status == DefectStatus.OPEN]),
                "IN_PROGRESS": len([d for d in self._defects.values() if d.status == DefectStatus.IN_PROGRESS]),
                "RESOLVED": len([d for d in self._defects.values() if d.status == DefectStatus.RESOLVED]),
                "VERIFIED": len([d for d in self._defects.values() if d.status == DefectStatus.VERIFIED]),
                "DEFERRED": len([d for d in self._defects.values() if d.status == DefectStatus.DEFERRED]),
                "CANNOT_FIX": len([d for d in self._defects.values() if d.status == DefectStatus.CANNOT_FIX]),
            }

            return analytics

    def clear(self) -> None:
        """
        Clear all tracked defects and history.

        Use with caution - this removes all audit trail data.

        Example:
            >>> tracker.clear()  # Reset tracker
        """
        with self._lock:
            self._defects.clear()
            self._history.clear()
            self._phase_buckets.clear()
            logger.info("DefectRemediationTracker cleared", extra={"tracker_id": self.tracker_id})
```

---

## 4. Status Lifecycle Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DEFECT STATUS LIFECYCLE                                │
└─────────────────────────────────────────────────────────────────────────────┘

                                    ┌──────────┐
                                    │   OPEN   │
                                    │ (newly   │
                                    │discovered)
                                    └────┬─────┘
                                         │
            ┌────────────────────────────┼────────────────────────────┐
            │                            │                            │
            │ start_fix()                │ mark_deferred()            │ mark_cannot_fix()
            │                            │                            │
            ▼                            ▼                            ▼
    ┌───────────────┐            ┌───────────────┐            ┌───────────────┐
    │ IN_PROGRESS   │            │   DEFERRED    │            │  CANNOT_FIX   │
    │(being fixed)  │◄──────────►│ (blocked/low  │◄──────────►│ (fundamental  │
    └───────┬───────┘   reopen   │  priority)    │   reopen   │  limitation)  │
            │                    └───────────────┘            └───────────────┘
            │
            │ mark_resolved(description)
            │
            ▼
    ┌───────────────┐
    │   RESOLVED    │
    │(fix applied,  │
    │awaiting QA)   │
    └───────┬───────┘
            │
            │ mark_verified(notes)
            │ OR reopen if regression
            │
            ▼
    ┌───────────────┐
    │   VERIFIED    │─────────────────────────────────┐
    │  (confirmed   │                                 │
    │    fixed)     │     regression found            │
    └───────────────┘◄────────────────────────────────┘
                           start_fix()

LEGEND:
─────►  Valid status transition
┄┄┄┄┄┄  Reopen path (requires justification)

TRANSITION RULES:
┌──────────────────┬──────────────────────────────────────────────────────────┐
│ From Status      │ Allowed Transitions                                     │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ OPEN             │ → IN_PROGRESS (developer starts fix)                    │
│                  │ → DEFERRED (blocked or low priority)                    │
│                  │ → CANNOT_FIX (fundamental limitation)                   │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ IN_PROGRESS      │ → RESOLVED (fix implemented)                            │
│                  │ → OPEN (not ready, needs more work)                     │
│                  │ → DEFERRED (blocked while working)                      │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ RESOLVED         │ → VERIFIED (QA confirms fix)                            │
│                  │ → IN_PROGRESS (needs more work)                         │
│                  │ → OPEN (fix inadequate)                                 │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ VERIFIED         │ → IN_PROGRESS (regression discovered)                   │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ DEFERRED         │ → OPEN (unblocked, priority increased)                  │
│                  │ → IN_PROGRESS (actively working on deferred item)       │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ CANNOT_FIX       │ → OPEN (workaround found, can address now)              │
└──────────────────┴──────────────────────────────────────────────────────────┘
```

---

## 5. Integration with PhaseContract and LoopManager

### 5.1 Integration with PhaseContract

The DefectRemediationTracker integrates with PhaseContract to ensure defects flow correctly between phases:

```python
# In PhaseContract, defects are optional inputs for loop-back
planning_contract = PhaseContract(
    phase_name="PLANNING",
).add_optional_input(
    name="defects",
    expected_type=list,
    description="Defects from previous iteration",
    default_value=[],
)

# Integration: DefectRemediationTracker provides the defects list
def get_defects_for_phase(tracker: DefectRemediationTracker, phase: str) -> List[Dict[str, Any]]:
    """
    Extract defects targeted for a specific phase.

    Args:
        tracker: Defect remediation tracker
        phase: Target phase name

    Returns:
        List of defect dictionaries for phase contract
    """
    defects = tracker.get_defects_by_status(DefectStatus.OPEN)
    return [d.to_dict() for d in defects if d.target_phase == phase]
```

### 5.2 Integration with LoopManager

For concurrent loop iterations, each loop can have its own tracker or share a global tracker:

```python
# In LoopManager, integrate with DefectRemediationTracker
class LoopManager:
    def __init__(
        self,
        max_concurrent: int = 10,
        defect_tracker: Optional[DefectRemediationTracker] = None,
    ):
        self._defect_tracker = defect_tracker or DefectRemediationTracker()
        self._loop_trackers: Dict[str, DefectRemediationTracker] = {}  # Per-loop trackers

    async def create_loop(self, config: LoopConfig) -> str:
        """Create loop with dedicated defect tracker."""
        loop_id = await super().create_loop(config)

        # Create per-loop tracker for isolation
        self._loop_trackers[loop_id] = DefectRemediationTracker(
            tracker_id=f"loop-{loop_id}"
        )

        return loop_id

    def get_loop_tracker(self, loop_id: str) -> DefectRemediationTracker:
        """Get defect tracker for specific loop."""
        return self._loop_trackers.get(loop_id, self._defect_tracker)
```

### 5.3 Integration with PipelineEngine

```python
# In PipelineEngine, coordinate defect tracking across phases
class PipelineEngine:
    def __init__(self):
        self._defect_tracker = DefectRemediationTracker(tracker_id="pipeline-main")
        self._contract_registry = PhaseContractRegistry()

    async def _execute_quality_phase(self, state: PipelineState) -> bool:
        """Execute QUALITY phase with defect discovery."""
        # ... quality evaluation ...

        # New defects discovered
        for defect in quality_report.defects:
            self._defect_tracker.add_defect(defect, phase="QUALITY")

        # Update state with defect summary
        state.add_artifact("defect_summary", self._defect_tracker.get_summary())

        return True

    async def _execute_development_phase(self, state: PipelineState) -> bool:
        """Execute DEVELOPMENT phase with defect remediation."""
        # Get pending defects for this phase
        pending = self._defect_tracker.get_pending_defects()

        for defect in pending:
            if defect.target_phase == "DEVELOPMENT" and defect.status == DefectStatus.OPEN:
                # Start fix
                self._defect_tracker.start_fix(defect.id, changed_by="senior-developer")

                # ... implement fix ...

                # Mark resolved
                self._defect_tracker.mark_resolved(
                    defect.id,
                    description="Fix implemented",
                    changed_by="senior-developer",
                )

        return True
```

---

## 6. Analytics and Reporting Capabilities

### 6.1 Real-time Dashboard Data

```python
# Dashboard query functions
def get_dashboard_data(tracker: DefectRemediationTracker) -> Dict[str, Any]:
    """Generate data for defect tracking dashboard."""
    summary = tracker.get_summary()
    analytics = tracker.get_analytics()

    return {
        "overview": {
            "total_defects": summary["total"],
            "pending": summary["pending_count"],
            "resolved": summary["by_status"].get("RESOLVED", 0),
            "verified": summary["verified_count"],
            "resolution_rate": f"{summary['resolution_rate']:.1%}",
        },
        "severity_breakdown": summary["by_severity"],
        "phase_distribution": summary["by_phase"],
        "metrics": {
            "mttr_hours": analytics["mean_time_to_resolve"],
            "mttv_hours": analytics["mean_time_to_verify"],
        },
        "critical_defects": [
            {"id": d.id, "type": d.type.name, "description": d.description}
            for d in tracker.get_defects_by_status(DefectStatus.OPEN)
            if d.severity == DefectSeverity.CRITICAL
        ],
    }
```

### 6.2 Quality Phase Integration

```python
# In QUALITY phase, use tracker data for quality scoring
def calculate_defect_impact_score(tracker: DefectRemediationTracker) -> float:
    """
    Calculate defect impact on quality score.

    Returns:
        Score modifier (0.0 - 1.0) based on defect status

    - 1.0: All defects verified (no impact)
    - 0.7: Some pending defects
    - 0.5: Critical defects pending
    """
    summary = tracker.get_summary()

    if summary["total"] == 0:
        return 1.0  # No defects, no impact

    # Check for critical pending defects
    critical_pending = sum(
        1 for d in tracker.get_pending_defects()
        if d.severity == DefectSeverity.CRITICAL
    )

    if critical_pending > 0:
        return 0.5  # Critical defects significantly reduce score

    # Base score on resolution rate
    return 0.7 + (0.3 * summary["resolution_rate"])
```

### 6.3 Audit Report Generation

```python
def generate_audit_report(
    tracker: DefectRemediationTracker,
    output_path: str,
    format: str = "json",
) -> str:
    """
    Generate comprehensive audit report.

    Args:
        tracker: Defect remediation tracker
        output_path: Path to write report
        format: Output format (json, csv, markdown)

    Returns:
        Path to generated report
    """
    import json

    audit_log = tracker.export_audit_log()
    summary = tracker.get_summary()
    analytics = tracker.get_analytics()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tracker_id": tracker.tracker_id,
        "summary": summary,
        "analytics": analytics,
        "audit_trail": audit_log,
    }

    with open(output_path, "w") as f:
        if format == "json":
            json.dump(report, f, indent=2)
        # Add other formats as needed

    return output_path
```

---

## 7. File Structure

```
gaia/src/gaia/pipeline/
├── defect_router.py              # Existing: Defect, DefectType, DefectSeverity, DefectStatus
├── defect_remediation_tracker.py # New: DefectRemediationTracker implementation
└── __init__.py                   # Export public API

gaia/tests/pipeline/
├── test_defect_remediation_tracker.py  # Unit tests
├── test_defect_router.py               # Existing tests
└── test_integration.py                 # Integration with PhaseContract/LoopManager

gaia/docs/
├── DEFECT_REMEDIATION_TRACKER_DESIGN.md  # This design document
└── defect_lifecycle.md                   # User guide for defect management
```

---

## 8. Testing Strategy

### 8.1 Unit Tests

```python
import pytest
from datetime import datetime, timezone, timedelta
from gaia.pipeline.defect_router import Defect, DefectType, DefectSeverity, DefectStatus
from gaia.pipeline.defect_remediation_tracker import (
    DefectRemediationTracker,
    DefectStatusChange,
    InvalidStatusTransitionError,
)


class TestDefectStatusChange:
    def test_create_status_change(self):
        change = DefectStatusChange(
            defect_id="defect-001",
            old_status=DefectStatus.OPEN,
            new_status=DefectStatus.IN_PROGRESS,
            description="Starting fix",
        )
        assert change.defect_id == "defect-001"
        assert change.old_status == DefectStatus.OPEN
        assert change.new_status == DefectStatus.IN_PROGRESS
        assert change.description == "Starting fix"

    def test_to_dict(self):
        change = DefectStatusChange(
            defect_id="defect-001",
            old_status=DefectStatus.OPEN,
            new_status=DefectStatus.IN_PROGRESS,
        )
        data = change.to_dict()
        assert data["defect_id"] == "defect-001"
        assert data["old_status"] == "OPEN"
        assert data["new_status"] == "IN_PROGRESS"

    def test_to_audit_entry(self):
        change = DefectStatusChange(
            defect_id="defect-001",
            old_status=DefectStatus.OPEN,
            new_status=DefectStatus.IN_PROGRESS,
            changed_by="developer",
        )
        audit = change.to_audit_entry()
        assert audit["event_type"] == "DEFECT_STATUS_CHANGE"
        assert audit["action"] == "OPEN → IN_PROGRESS"


class TestDefectRemediationTracker:
    @pytest.fixture
    def tracker(self):
        return DefectRemediationTracker(tracker_id="test-tracker")

    @pytest.fixture
    def sample_defect(self):
        return Defect(
            id="defect-001",
            type=DefectType.MISSING_TESTS,
            severity=DefectSeverity.HIGH,
            description="No unit tests for module",
            phase_detected="QUALITY",
        )

    def test_add_defect(self, tracker, sample_defect):
        tracker.add_defect(sample_defect, phase="QUALITY")

        retrieved = tracker.get_defect("defect-001")
        assert retrieved is not None
        assert retrieved.status == DefectStatus.OPEN

    def test_add_defect_non_open_status(self, tracker):
        defect = Defect(
            id="defect-002",
            type=DefectType.CODE_STYLE,
            severity=DefectSeverity.LOW,
            status=DefectStatus.RESOLVED,  # Non-OPEN
            description="Test defect",
        )
        tracker.add_defect(defect, phase="DEVELOPMENT")

        # Should be reset to OPEN
        retrieved = tracker.get_defect("defect-002")
        assert retrieved.status == DefectStatus.OPEN

    def test_start_fix(self, tracker, sample_defect):
        tracker.add_defect(sample_defect, phase="QUALITY")
        change = tracker.start_fix("defect-001", changed_by="developer")

        assert change.old_status == DefectStatus.OPEN
        assert change.new_status == DefectStatus.IN_PROGRESS
        assert tracker.get_defect("defect-001").status == DefectStatus.IN_PROGRESS

    def test_mark_resolved(self, tracker, sample_defect):
        tracker.add_defect(sample_defect, phase="QUALITY")
        tracker.start_fix("defect-001")

        change = tracker.mark_resolved(
            "defect-001",
            description="Added 15 tests",
            metadata={"tests_added": 15},
        )

        assert change.new_status == DefectStatus.RESOLVED

    def test_mark_verified(self, tracker, sample_defect):
        tracker.add_defect(sample_defect, phase="QUALITY")
        tracker.start_fix("defect-001")
        tracker.mark_resolved("defect-001", "Fix applied")

        change = tracker.mark_verified("defect-001", "QA passed")

        assert change.new_status == DefectStatus.VERIFIED

    def test_invalid_transition(self, tracker, sample_defect):
        tracker.add_defect(sample_defect, phase="QUALITY")

        # Cannot go directly from OPEN to VERIFIED
        with pytest.raises(InvalidStatusTransitionError) as exc_info:
            tracker.mark_verified("defect-001", "QA passed")

        assert exc_info.value.current_status == DefectStatus.OPEN
        assert exc_info.value.requested_status == DefectStatus.VERIFIED

    def test_defer_defect(self, tracker, sample_defect):
        tracker.add_defect(sample_defect, phase="QUALITY")
        change = tracker.mark_deferred(
            "defect-001",
            reason="Low priority",
            changed_by="product-owner",
        )

        assert change.new_status == DefectStatus.DEFERRED

    def test_cannot_fix(self, tracker, sample_defect):
        tracker.add_defect(sample_defect, phase="QUALITY")
        change = tracker.mark_cannot_fix(
            "defect-001",
            reason="Platform limitation",
        )

        assert change.new_status == DefectStatus.CANNOT_FIX

    def test_get_pending_defects(self, tracker, sample_defect):
        # Add multiple defects
        defect2 = Defect(
            id="defect-002",
            type=DefectType.CODE_STYLE,
            severity=DefectSeverity.LOW,
            description="Style issue",
        )

        tracker.add_defect(sample_defect, phase="QUALITY")
        tracker.add_defect(defect2, phase="DEVELOPMENT")

        # Resolve one
        tracker.start_fix("defect-001")
        tracker.mark_resolved("defect-001", "Fixed")
        tracker.mark_verified("defect-001", "Verified")

        pending = tracker.get_pending_defects()
        assert len(pending) == 1
        assert pending[0].id == "defect-002"

    def test_get_summary(self, tracker, sample_defect):
        tracker.add_defect(sample_defect, phase="QUALITY")

        summary = tracker.get_summary()
        assert summary["total"] == 1
        assert summary["by_status"]["OPEN"] == 1
        assert summary["pending_count"] == 1
        assert summary["resolution_rate"] == 0.0

    def test_get_defect_history(self, tracker, sample_defect):
        tracker.add_defect(sample_defect, phase="QUALITY")
        tracker.start_fix("defect-001")
        tracker.mark_resolved("defect-001", "Fixed")
        tracker.mark_verified("defect-001", "Verified")

        history = tracker.get_defect_history("defect-001")
        assert len(history) == 4  # Initial + 3 transitions

    def test_get_defects_by_phase(self, tracker, sample_defect):
        tracker.add_defect(sample_defect, phase="QUALITY")

        defect2 = Defect(
            id="defect-002",
            type=DefectType.CODE_STYLE,
            severity=DefectSeverity.LOW,
            description="Style issue",
            phase_detected="DEVELOPMENT",
        )
        tracker.add_defect(defect2, phase="DEVELOPMENT")

        quality_defects = tracker.get_defects_by_phase("QUALITY")
        dev_defects = tracker.get_defects_by_phase("DEVELOPMENT")

        assert len(quality_defects) == 1
        assert len(dev_defects) == 1

    def test_get_defects_by_status(self, tracker, sample_defect):
        tracker.add_defect(sample_defect, phase="QUALITY")

        open_defects = tracker.get_defects_by_status(DefectStatus.OPEN)
        assert len(open_defects) == 1

    def test_export_audit_log(self, tracker, sample_defect):
        tracker.add_defect(sample_defect, phase="QUALITY")
        tracker.start_fix("defect-001")

        audit_log = tracker.export_audit_log()
        assert len(audit_log) == 2

        # Check audit entry format
        entry = audit_log[1]
        assert entry["event_type"] == "DEFECT_STATUS_CHANGE"
        assert "OPEN → IN_PROGRESS" in entry["action"]

    def test_thread_safety(self, tracker, sample_defect):
        import threading
        import time

        # Add initial defects
        defects = [
            Defect(
                id=f"defect-{i:03d}",
                type=DefectType.MISSING_TESTS,
                severity=DefectSeverity.MEDIUM,
                description=f"Defect {i}",
            )
            for i in range(100)
        ]

        def add_and_process(defect):
            tracker.add_defect(defect, phase="QUALITY")
            tracker.start_fix(defect.id)
            tracker.mark_resolved(defect.id, f"Fixed {defect.id}")
            tracker.mark_verified(defect.id, f"Verified {defect.id}")

        # Create threads
        threads = []
        for defect in defects:
            t = threading.Thread(target=add_and_process, args=(defect,))
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # Verify all defects are tracked
        assert len(tracker.get_all_defects()) == 100
        assert len(tracker.get_defect_history()) == 400  # 4 transitions per defect


class TestDefectRemediationTrackerAnalytics:
    @pytest.fixture
    def tracker_with_data(self):
        tracker = DefectRemediationTracker(tracker_id="analytics-test")

        # Add defects and progress them
        for i in range(10):
            defect = Defect(
                id=f"defect-{i:03d}",
                type=DefectType.MISSING_TESTS,
                severity=DefectSeverity.HIGH if i < 3 else DefectSeverity.MEDIUM,
                description=f"Defect {i}",
                phase_detected="QUALITY",
            )
            tracker.add_defect(defect, phase="QUALITY")

            # Progress some to verified
            if i < 7:
                tracker.start_fix(f"defect-{i:03d}")
                tracker.mark_resolved(f"defect-{i:03d}", f"Fixed {i}")
                if i < 5:
                    tracker.mark_verified(f"defect-{i:03d}", f"Verified {i}")

        return tracker

    def test_get_analytics(self, tracker_with_data):
        analytics = tracker_with_data.get_analytics()

        assert "mean_time_to_resolve" in analytics
        assert "mean_time_to_verify" in analytics
        assert "defects_by_severity_priority" in analytics
        assert "phase_distribution" in analytics
        assert analytics["phase_distribution"]["QUALITY"] == 10

    def test_analytics_mttr(self, tracker_with_data):
        analytics = tracker_with_data.get_analytics()

        # Should have MTTR for defects that were resolved
        assert analytics["mean_time_to_resolve"] is not None
        assert analytics["mean_time_to_resolve"] >= 0
```

### 8.2 Integration Tests

```python
class TestPhaseContractIntegration:
    def test_defects_in_phase_contract(self):
        """Test that defects flow correctly through phase contracts."""
        from gaia.pipeline.phase_contract import (
            PhaseContractRegistry,
            create_planning_contract,
        )

        registry = PhaseContractRegistry()
        registry.register(create_planning_contract())

        tracker = DefectRemediationTracker()

        # Add defect
        defect = Defect(
            id="defect-001",
            type=DefectType.MISSING_REQUIREMENT,
            severity=DefectSeverity.HIGH,
            description="Missing requirement",
            target_phase="PLANNING",
        )
        tracker.add_defect(defect, phase="QUALITY")

        # PLANNING contract should accept defects
        planning_contract = registry.get("PLANNING")
        assert "defects" in planning_contract.optional_inputs

    def test_loop_manager_integration(self):
        """Test DefectRemediationTracker with LoopManager."""
        from gaia.pipeline.loop_manager import LoopManager, LoopConfig

        manager = LoopManager(max_concurrent=5)
        tracker = DefectRemediationTracker(tracker_id="loop-manager-test")

        # Create loop config
        config = LoopConfig(
            loop_id="loop-001",
            phase_name="DEVELOPMENT",
            agent_sequence=["senior-developer"],
            exit_criteria={"goal": "Fix defects"},
            quality_threshold=0.90,
        )

        # Add defects to tracker
        defect = Defect(
            id="defect-001",
            type=DefectType.MISSING_TESTS,
            severity=DefectSeverity.HIGH,
            description="Missing tests",
            target_phase="DEVELOPMENT",
        )
        tracker.add_defect(defect, phase="QUALITY")

        # Verify defects are tracked
        pending = tracker.get_pending_defects()
        assert len(pending) == 1
```

---

## 9. Success Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| **API Completeness** | 100% | All required methods implemented |
| **Status Transitions** | 100% | All lifecycle transitions covered |
| **Thread Safety** | 100% | All operations protected by lock |
| **Audit Trail** | 100% | All changes recorded immutably |
| **Integration** | 0 breaking changes | Existing tests pass |
| **Test Coverage** | >= 95% | Unit test line coverage |
| **Quality Threshold** | >= 0.90 | QUALITY phase must achieve |
| **Concurrent Loops** | 5+ parallel | Supported without race conditions |

---

## 10. Appendix

### 10.1 Glossary

| Term | Definition |
|------|------------|
| **Defect** | Issue or problem identified during quality evaluation |
| **DefectStatus** | Current state of defect in remediation lifecycle |
| **DefectStatusChange** | Immutable record of status transition |
| **Audit Trail** | Complete history of all status changes |
| **Terminal Status** | Final state (VERIFIED, DEFERRED, CANNOT_FIX) |
| **MTTR** | Mean Time To Resolve (OPEN → RESOLVED) |
| **MTTV** | Mean Time To Verify (RESOLVED → VERIFIED) |

### 10.2 References

- `gaia/src/gaia/pipeline/defect_router.py` - Existing Defect type and routing
- `gaia/src/gaia/pipeline/phase_contract.py` - PhaseContract integration
- `gaia/src/gaia/pipeline/loop_manager.py` - Loop execution context
- `GAIA_META_PIPELINE_PLAN.md` - Meta-pipeline execution plan
- `PHASECONTRACT_DESIGN.md` - Design pattern reference

### 10.3 Open Questions

1. **Persistence** - Should defects be persisted to disk/database for recovery?
2. **User Attribution** - How to identify `changed_by` in automated pipeline?
3. **Notifications** - Should stakeholders be notified of status changes?
4. **SLA Tracking** - Should we track time-based SLAs for defect resolution?

---

*Document Version: 1.0.0*
*Generated: 2026-03-23*
*Status: Ready for Development*
*Quality Target: >= 0.90*
