"""
GAIA Pipeline Engine

Core pipeline engine components for orchestration and execution.
"""

# Direct imports that don't trigger the full agent dependency chain
from gaia.pipeline.state import (
    PipelineState,
    PipelineContext,
    PipelineSnapshot,
    PipelineStateMachine,
)
from gaia.pipeline.decision_engine import (
    DecisionEngine,
    Decision,
    DecisionType,
)
from gaia.pipeline.defect_router import (
    DefectRouter,
    Defect,
    DefectType,
    DefectSeverity,
    DefectStatus,
    create_defect,
)
from gaia.pipeline.defect_remediation_tracker import (
    DefectRemediationTracker,
    DefectStatusChange,
    DefectStatusTransition,
    InvalidStatusTransitionError,
    DefectStatus as RemediationDefectStatus,
)
from gaia.pipeline.phase_contract import (
    PhaseContract,
    PhaseContractRegistry,
    ContractTerm,
    ContractViolationSeverity,
    InputType,
    ValidationResult,
    ContractViolationError,
    PhaseExecutionError,
    create_default_phase_contracts,
    create_planning_contract,
    create_development_contract,
    create_quality_contract,
    create_decision_contract,
    validate_defect_routing,
)
from gaia.pipeline.audit_logger import (
    AuditLogger,
    AuditEvent,
    AuditEventType,
    IntegrityVerificationError,
)

# Lazy imports for components with complex dependencies
def __getattr__(name):
    """Lazy loading for components with complex dependencies."""
    if name == "PipelineEngine":
        from gaia.pipeline.engine import PipelineEngine
        return PipelineEngine
    elif name == "LoopManager":
        from gaia.pipeline.loop_manager import LoopManager
        return LoopManager
    elif name == "LoopConfig":
        from gaia.pipeline.loop_manager import LoopConfig
        return LoopConfig
    elif name == "LoopState":
        from gaia.pipeline.loop_manager import LoopState
        return LoopState
    elif name == "LoopStatus":
        from gaia.pipeline.loop_manager import LoopStatus
        return LoopStatus
    raise AttributeError(f"module {__name__} has no attribute {name}")


__all__ = [
    # State machine
    "PipelineState",
    "PipelineContext",
    "PipelineSnapshot",
    "PipelineStateMachine",
    # Phase Contract
    "PhaseContract",
    "PhaseContractRegistry",
    "ContractTerm",
    "ContractViolationSeverity",
    "InputType",
    "ValidationResult",
    "ContractViolationError",
    "PhaseExecutionError",
    # Audit Logger
    "AuditLogger",
    "AuditEvent",
    "AuditEventType",
    "IntegrityVerificationError",
    # Contract factories
    "create_default_phase_contracts",
    "create_planning_contract",
    "create_development_contract",
    "create_quality_contract",
    "create_decision_contract",
    # Defect routing and remediation
    "DefectRouter",
    "Defect",
    "DefectType",
    "DefectSeverity",
    "DefectStatus",
    "DefectStatusChange",
    "DefectStatusTransition",
    "RemediationDefectStatus",
    "InvalidStatusTransitionError",
    "create_defect",
    "DefectRemediationTracker",
    # Validation
    "validate_defect_routing",
    # Decision engine
    "DecisionEngine",
    "Decision",
    "DecisionType",
    # Lazy loaded
    "PipelineEngine",
    "LoopManager",
    "LoopConfig",
    "LoopState",
    "LoopStatus",
]
