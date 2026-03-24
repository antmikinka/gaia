# PhaseContract Design Document

**Document Type:** Technical Design Specification
**Component:** PhaseContract
**Version:** 1.0.0
**Date:** 2026-03-23
**Author:** Dr. Sarah Kim, Technical Product Strategist & Engineering Lead

---

## 1. Executive Summary

### 1.1 Purpose

The PhaseContract component defines explicit input/output contracts between pipeline phases, ensuring that each phase receives the required artifacts before execution and produces the expected outputs upon completion. This enables:

- **Type-safe phase handoffs** with explicit contracts
- **Automated validation** of phase prerequisites
- **Clear accountability** for phase responsibilities
- **Recursive loop-back support** with defect accumulation

### 1.2 Problem Statement

Without explicit contracts:
- Phases may execute with missing prerequisites
- Defect routing lacks formal input validation
- Quality evaluation cannot verify artifact completeness
- Loop-back iterations may lose context between phases

### 1.3 Solution Overview

PhaseContract introduces a declarative contract system where each phase declares:
1. **Required inputs** - Must exist before phase execution
2. **Optional inputs** - Enhance phase output if present
3. **Expected outputs** - Must produce by phase completion
4. **Quality criteria** - Thresholds for acceptable output quality
5. **Validators** - Custom validation functions for contract enforcement

---

## 2. Component Architecture

### 2.1 Class Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         PhaseContract                            │
├─────────────────────────────────────────────────────────────────┤
│ - phase_name: str                                               │
│ - required_inputs: Dict[str, Type]                              │
│ - optional_inputs: Dict[str, Type]                              │
│ - expected_outputs: Dict[str, Type]                             │
│ - quality_criteria: Dict[str, float]                            │
│ - validators: List[Callable[[PipelineState], ValidationResult]] │
├─────────────────────────────────────────────────────────────────┤
│ + validate_inputs(state: PipelineState) -> ValidationResult     │
│ + validate_outputs(state: PipelineState) -> ValidationResult    │
│ + validate_quality(state: PipelineState) -> ValidationResult    │
│ + get_missing_inputs(state: PipelineState) -> List[str]         │
│ + get_produced_outputs(state: PipelineState) -> List[str]       │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
                              │
┌─────────────────────────────────────────────────────────────────┐
│                     PhaseContractRegistry                        │
├─────────────────────────────────────────────────────────────────┤
│ - contracts: Dict[str, PhaseContract]                           │
├─────────────────────────────────────────────────────────────────┤
│ + register(contract: PhaseContract) -> None                     │
│ + get(phase_name: str) -> PhaseContract                         │
│ + validate_phase_transition(from_phase: str, to_phase: str,     │
│                             state: PipelineState) -> bool        │
│ + get_all_contracts() -> Dict[str, PhaseContract]               │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Design Principles

1. **Explicit Contracts** - All phase inputs/outputs are explicitly declared
2. **Fail Fast** - Validate inputs before phase execution
3. **Type Safety** - Use Python type hints for artifact validation
4. **Composability** - Validators can be composed and extended
5. **Traceability** - Track which artifacts satisfy which contract terms

---

## 3. Python API Specification

### 3.1 Core Data Structures

```python
"""
GAIA PhaseContract

Defines explicit input/output contracts between pipeline phases.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Any, Optional, Callable, Type, TypeVar, Generic
from datetime import datetime
import inspect

from gaia.pipeline.state import PipelineState, PipelineSnapshot
from gaia.exceptions import ContractViolationError, PhaseExecutionError


T = TypeVar('T')


class ContractViolationSeverity(Enum):
    """Severity levels for contract violations."""

    WARNING = auto()      # Non-blocking, log only
    ERROR = auto()        # Should block, but can be overridden
    CRITICAL = auto()     # Must block, cannot proceed


class InputType(Enum):
    """Classification of input types."""

    REQUIRED = auto()     # Must exist before phase execution
    OPTIONAL = auto()     # Nice to have, enhances output
    CONDITIONAL = auto()  # Required based on conditions


@dataclass
class ContractTerm(Generic[T]):
    """
    Single term in a phase contract.

    Attributes:
        name: Term identifier (e.g., "user_goal", "planning_artifacts")
        expected_type: Expected Python type for the artifact
        description: Human-readable description of the term
        input_type: Whether this is required, optional, or conditional
        default_value: Default value if optional and not provided
        validator: Optional custom validator function
    """

    name: str
    expected_type: Type[T]
    description: str
    input_type: InputType = InputType.REQUIRED
    default_value: Optional[T] = None
    validator: Optional[Callable[[T], bool]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self, value: Any) -> tuple[bool, Optional[str]]:
        """
        Validate a value against this contract term.

        Args:
            value: Value to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Type check
        if not isinstance(value, self.expected_type):
            return False, f"Expected {self.expected_type.__name__}, got {type(value).__name__}"

        # Custom validator
        if self.validator and not self.validator(value):
            return False, f"Custom validation failed for {self.name}"

        return True, None


@dataclass
class ValidationResult:
    """
    Result of contract validation.

    Attributes:
        is_valid: Whether validation passed
        violations: List of contract violations found
        warnings: List of warnings (non-blocking issues)
        validated_at: When validation occurred
        validator_name: Name of validator that produced this result
    """

    is_valid: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    validated_at: datetime = field(default_factory=datetime.utcnow)
    validator_name: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "is_valid": self.is_valid,
            "violations": self.violations,
            "warnings": self.warnings,
            "validated_at": self.validated_at.isoformat(),
            "validator_name": self.validator_name,
            "details": self.details,
        }

    @classmethod
    def success(cls, details: Optional[Dict[str, Any]] = None) -> "ValidationResult":
        """Create a successful validation result."""
        return cls(is_valid=True, details=details or {})

    @classmethod
    def failure(
        cls,
        violations: List[str],
        warnings: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> "ValidationResult":
        """Create a failed validation result."""
        return cls(
            is_valid=False,
            violations=violations,
            warnings=warnings or [],
            details=details or {},
        )


@dataclass
class PhaseContract:
    """
    Contract defining phase input/output requirements.

    The PhaseContract ensures that each pipeline phase has explicit
    requirements for what inputs it needs and what outputs it produces.

    Attributes:
        phase_name: Name of the phase this contract applies to
        required_inputs: Inputs that must exist before execution
        optional_inputs: Inputs that enhance output if present
        expected_outputs: Outputs that must be produced
        quality_criteria: Quality thresholds for outputs
        validators: Custom validation functions
    """

    phase_name: str
    required_inputs: Dict[str, ContractTerm] = field(default_factory=dict)
    optional_inputs: Dict[str, ContractTerm] = field(default_factory=dict)
    expected_outputs: Dict[str, ContractTerm] = field(default_factory=dict)
    quality_criteria: Dict[str, float] = field(default_factory=dict)
    validators: List[Callable[[PipelineState], ValidationResult]] = field(
        default_factory=list
    )
    description: str = ""
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate_inputs(self, state: PipelineState) -> ValidationResult:
        """
        Validate that all required inputs are present.

        Args:
            state: Current pipeline state

        Returns:
            ValidationResult with any violations found
        """
        violations = []
        warnings = []
        snapshot = state.snapshot

        # Validate required inputs
        for name, term in self.required_inputs.items():
            value = snapshot.artifacts.get(name)
            if value is None:
                # Check if it's in context_injected
                value = snapshot.context_injected.get(name)

            if value is None and term.default_value is None:
                violations.append(f"Missing required input: {name}")
            elif value is not None:
                # Validate the value
                is_valid, error = term.validate(value)
                if not is_valid:
                    violations.append(f"Invalid input '{name}': {error}")

        # Validate optional inputs (warn if type mismatch)
        for name, term in self.optional_inputs.items():
            value = snapshot.artifacts.get(name)
            if value is not None:
                is_valid, error = term.validate(value)
                if not is_valid:
                    warnings.append(f"Optional input '{name}' has unexpected type: {error}")

        # Run custom validators
        for validator in self.validators:
            try:
                result = validator(state)
                if not result.is_valid:
                    violations.extend(result.violations)
                    warnings.extend(result.warnings)
            except Exception as e:
                violations.append(f"Validator error: {str(e)}")

        return ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            warnings=warnings,
            validator_name=f"{self.phase_name}_input_validator",
        )

    def validate_outputs(self, state: PipelineState) -> ValidationResult:
        """
        Validate that all expected outputs were produced.

        Args:
            state: Current pipeline state

        Returns:
            ValidationResult with any missing outputs
        """
        violations = []
        snapshot = state.snapshot

        for name, term in self.expected_outputs.items():
            value = snapshot.artifacts.get(name)
            if value is None:
                violations.append(f"Missing expected output: {name}")
            elif not isinstance(value, term.expected_type):
                violations.append(
                    f"Output '{name}' has wrong type: "
                    f"expected {term.expected_type.__name__}, "
                    f"got {type(value).__name__}"
                )

        return ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            validator_name=f"{self.phase_name}_output_validator",
        )

    def validate_quality(self, state: PipelineState) -> ValidationResult:
        """
        Validate that quality criteria are met.

        Args:
            state: Current pipeline state

        Returns:
            ValidationResult with quality assessment
        """
        violations = []
        snapshot = state.snapshot

        for criteria_name, threshold in self.quality_criteria.items():
            # Get the quality score
            if criteria_name == "overall_quality":
                score = snapshot.quality_score
                if score is None:
                    violations.append("Quality score not available")
                elif score < threshold:
                    violations.append(
                        f"Quality score {score:.2f} below threshold {threshold:.2f}"
                    )
            else:
                # Check for other quality metrics in artifacts
                quality_report = snapshot.artifacts.get("quality_report", {})
                if isinstance(quality_report, dict):
                    score = quality_report.get(criteria_name)
                    if score is not None and score < threshold:
                        violations.append(
                            f"{criteria_name} score {score:.2f} below threshold {threshold:.2f}"
                        )

        return ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            validator_name=f"{self.phase_name}_quality_validator",
        )

    def get_missing_inputs(self, state: PipelineState) -> List[str]:
        """
        Get list of missing required inputs.

        Args:
            state: Current pipeline state

        Returns:
            List of missing input names
        """
        missing = []
        snapshot = state.snapshot

        for name, term in self.required_inputs.items():
            value = snapshot.artifacts.get(name)
            if value is None:
                value = snapshot.context_injected.get(name)
            if value is None and term.default_value is None:
                missing.append(name)

        return missing

    def get_produced_outputs(self, state: PipelineState) -> List[str]:
        """
        Get list of expected outputs that have been produced.

        Args:
            state: Current pipeline state

        Returns:
            List of output names that exist
        """
        produced = []
        snapshot = state.snapshot

        for name in self.expected_outputs:
            if name in snapshot.artifacts:
                produced.append(name)

        return produced

    def add_required_input(
        self,
        name: str,
        expected_type: Type,
        description: str,
        validator: Optional[Callable] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "PhaseContract":
        """Fluent method to add required input."""
        self.required_inputs[name] = ContractTerm(
            name=name,
            expected_type=expected_type,
            description=description,
            input_type=InputType.REQUIRED,
            validator=validator,
            metadata=metadata or {},
        )
        return self

    def add_optional_input(
        self,
        name: str,
        expected_type: Type,
        description: str,
        default_value: Any = None,
        validator: Optional[Callable] = None,
    ) -> "PhaseContract":
        """Fluent method to add optional input."""
        self.optional_inputs[name] = ContractTerm(
            name=name,
            expected_type=expected_type,
            description=description,
            input_type=InputType.OPTIONAL,
            default_value=default_value,
            validator=validator,
        )
        return self

    def add_expected_output(
        self,
        name: str,
        expected_type: Type,
        description: str,
        quality_threshold: float = 0.0,
    ) -> "PhaseContract":
        """Fluent method to add expected output."""
        self.expected_outputs[name] = ContractTerm(
            name=name,
            expected_type=expected_type,
            description=description,
            input_type=InputType.REQUIRED,  # Outputs are required
        )
        if quality_threshold > 0:
            self.quality_criteria[name] = quality_threshold
        return self

    def with_quality_criteria(
        self,
        criteria_name: str,
        threshold: float,
    ) -> "PhaseContract":
        """Fluent method to add quality criteria."""
        if not 0 <= threshold <= 1:
            raise ValueError("Quality threshold must be between 0 and 1")
        self.quality_criteria[criteria_name] = threshold
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert contract to dictionary for serialization."""
        return {
            "phase_name": self.phase_name,
            "description": self.description,
            "version": self.version,
            "required_inputs": {
                name: {
                    "type": term.expected_type.__name__,
                    "description": term.description,
                    "input_type": term.input_type.name,
                }
                for name, term in self.required_inputs.items()
            },
            "optional_inputs": {
                name: {
                    "type": term.expected_type.__name__,
                    "description": term.description,
                    "default_value": term.default_value,
                }
                for name, term in self.optional_inputs.items()
            },
            "expected_outputs": {
                name: {
                    "type": term.expected_type.__name__,
                    "description": term.description,
                }
                for name, term in self.expected_outputs.items()
            },
            "quality_criteria": self.quality_criteria,
            "metadata": self.metadata,
        }
```

### 3.2 Phase Contract Registry

```python
class PhaseContractRegistry:
    """
    Registry for managing phase contracts.

    The registry stores contracts for all phases and provides
    validation services for phase transitions.

    Example:
        >>> registry = PhaseContractRegistry()
        >>> registry.register_default_contracts()
        >>> contract = registry.get("PLANNING")
        >>> result = contract.validate_inputs(state)
        >>> if not result.is_valid:
        ...     print(f"Validation failed: {result.violations}")
    """

    def __init__(self):
        """Initialize the contract registry."""
        self._contracts: Dict[str, PhaseContract] = {}

    def register(self, contract: PhaseContract) -> None:
        """
        Register a phase contract.

        Args:
            contract: Contract to register
        """
        self._contracts[contract.phase_name] = contract

    def get(self, phase_name: str) -> PhaseContract:
        """
        Get contract for a phase.

        Args:
            phase_name: Name of the phase

        Returns:
            PhaseContract for the phase

        Raises:
            KeyError: If contract not found
        """
        if phase_name not in self._contracts:
            raise KeyError(f"No contract registered for phase: {phase_name}")
        return self._contracts[phase_name]

    def get_or_none(self, phase_name: str) -> Optional[PhaseContract]:
        """Get contract or return None if not found."""
        return self._contracts.get(phase_name)

    def validate_phase_transition(
        self,
        from_phase: str,
        to_phase: str,
        state: PipelineState,
    ) -> ValidationResult:
        """
        Validate that a phase transition is valid.

        This checks that:
        1. The source phase has produced all expected outputs
        2. The target phase has all required inputs available

        Args:
            from_phase: Source phase name
            to_phase: Target phase name
            state: Current pipeline state

        Returns:
            ValidationResult with transition validation
        """
        violations = []

        # Validate source phase outputs
        if from_phase in self._contracts:
            source_contract = self._contracts[from_phase]
            output_result = source_contract.validate_outputs(state)
            if not output_result.is_valid:
                violations.extend([
                    f"Phase '{from_phase}' has not produced required outputs: {v}"
                    for v in output_result.violations
                ])

        # Validate target phase inputs
        if to_phase in self._contracts:
            target_contract = self._contracts[to_phase]
            input_result = target_contract.validate_inputs(state)
            if not input_result.is_valid:
                violations.extend([
                    f"Phase '{to_phase}' is missing required inputs: {v}"
                    for v in input_result.violations
                ])

        return ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            validator_name="phase_transition_validator",
        )

    def get_all_contracts(self) -> Dict[str, PhaseContract]:
        """Get all registered contracts."""
        return dict(self._contracts)

    def register_default_contracts(self) -> None:
        """Register default contracts for all pipeline phases."""
        # These are created using the contract factory functions below
        for contract in create_default_phase_contracts():
            self.register(contract)


def create_default_phase_contracts() -> List[PhaseContract]:
    """
    Create default phase contracts for the GAIA pipeline.

    Returns:
        List of PhaseContract instances for all phases
    """
    return [
        create_planning_contract(),
        create_development_contract(),
        create_quality_contract(),
        create_decision_contract(),
    ]


def create_planning_contract() -> PhaseContract:
    """
    Create contract for PLANNING phase.

    PLANNING: inputs={user_goal, context} -> outputs={plan, tasks, complexity}
    """
    return PhaseContract(
        phase_name="PLANNING",
        description="Requirements analysis and planning phase",
    ).add_required_input(
        name="user_goal",
        expected_type=str,
        description="User's goal or requirement statement",
    ).add_required_input(
        name="context",
        expected_type=dict,
        description="Additional context for planning",
    ).add_optional_input(
        name="previous_plan",
        expected_type=dict,
        description="Plan from previous iteration (for loop-back)",
        default_value={},
    ).add_optional_input(
        name="defects",
        expected_type=list,
        description="Defects from previous iteration",
        default_value=[],
    ).add_expected_output(
        name="planning_artifacts",
        expected_type=dict,
        description="Planning deliverables including plan, tasks, and analysis",
    ).add_expected_output(
        name="task_breakdown",
        expected_type=list,
        description="List of tasks derived from requirements",
    ).add_expected_output(
        name="complexity_analysis",
        expected_type=dict,
        description="Complexity assessment and estimates",
    ).with_quality_criteria(
        criteria_name="overall_quality",
        threshold=0.85,
    )


def create_development_contract() -> PhaseContract:
    """
    Create contract for DEVELOPMENT phase.

    DEVELOPMENT: inputs={plan, goal, defects} -> outputs={code, tests, docs}
    """
    return PhaseContract(
        phase_name="DEVELOPMENT",
        description="Implementation and development phase",
    ).add_required_input(
        name="planning_artifacts",
        expected_type=dict,
        description="Planning output with tasks and requirements",
    ).add_required_input(
        name="user_goal",
        expected_type=str,
        description="Original user goal being implemented",
    ).add_optional_input(
        name="defects",
        expected_type=list,
        description="Defects to address from previous iteration",
        default_value=[],
    ).add_optional_input(
        name="existing_code",
        expected_type=str,
        description="Existing code to modify or extend",
        default_value="",
    ).add_expected_output(
        name="code_artifacts",
        expected_type=dict,
        description="Generated code files and modules",
    ).add_expected_output(
        name="test_artifacts",
        expected_type=dict,
        description="Test files and test coverage data",
    ).add_expected_output(
        name="documentation",
        expected_type=dict,
        description="Documentation artifacts",
    ).with_quality_criteria(
        criteria_name="overall_quality",
        threshold=0.90,
    )


def create_quality_contract() -> PhaseContract:
    """
    Create contract for QUALITY phase.

    QUALITY: inputs={all_artifacts} -> outputs={report, defects, score}
    """
    return PhaseContract(
        phase_name="QUALITY",
        description="Quality evaluation and assessment phase",
    ).add_required_input(
        name="planning_artifacts",
        expected_type=dict,
        description="Planning output for requirements validation",
    ).add_required_input(
        name="code_artifacts",
        expected_type=dict,
        description="Code to evaluate",
    ).add_required_input(
        name="quality_template",
        expected_type=str,
        description="Quality template name (STANDARD, RAPID, etc.)",
    ).add_optional_input(
        name="test_artifacts",
        expected_type=dict,
        description="Test results for evaluation",
        default_value={},
    ).add_optional_input(
        name="documentation",
        expected_type=dict,
        description="Documentation to evaluate",
        default_value={},
    ).add_expected_output(
        name="quality_report",
        expected_type=dict,
        description="Comprehensive quality evaluation report",
    ).add_expected_output(
        name="defects",
        expected_type=list,
        description="List of defects identified",
    ).add_expected_output(
        name="quality_score",
        expected_type=float,
        description="Overall quality score (0-1)",
    ).with_quality_criteria(
        criteria_name="overall_quality",
        threshold=0.90,  # Must achieve 90% quality
    ).add_validator(
        lambda state: _validate_quality_completeness(state),
    )


def create_decision_contract() -> PhaseContract:
    """
    Create contract for DECISION phase.

    DECISION: inputs={score, threshold, defects} -> outputs={decision, target_phase}
    """
    return PhaseContract(
        phase_name="DECISION",
        description="Decision-making and pipeline progression phase",
    ).add_required_input(
        name="quality_report",
        expected_type=dict,
        description="Quality evaluation report",
    ).add_required_input(
        name="defects",
        expected_type=list,
        description="Defects from quality evaluation",
    ).add_required_input(
        name="iteration_count",
        expected_type=int,
        description="Current iteration number",
    ).add_optional_input(
        name="max_iterations",
        expected_type=int,
        description="Maximum allowed iterations",
        default_value=10,
    ).add_expected_output(
        name="decision",
        expected_type=dict,
        description="Decision output (type, reason, target_phase)",
    ).add_validator(
        lambda state: _validate_decision_context(state),
    )


def _validate_quality_completeness(state: PipelineState) -> ValidationResult:
    """
    Validate that quality phase has all required artifacts.

    Args:
        state: Current pipeline state

    Returns:
        ValidationResult
    """
    violations = []
    snapshot = state.snapshot

    # Check that we have something to evaluate
    if "code_artifacts" not in snapshot.artifacts:
        violations.append("No code artifacts to evaluate")

    if "planning_artifacts" not in snapshot.artifacts:
        violations.append("No planning artifacts for requirements validation")

    return ValidationResult(
        is_valid=len(violations) == 0,
        violations=violations,
        validator_name="quality_completeness_validator",
    )


def _validate_decision_context(state: PipelineState) -> ValidationResult:
    """
    Validate that decision phase has proper context.

    Args:
        state: Current pipeline state

    Returns:
        ValidationResult
    """
    violations = []
    snapshot = state.snapshot

    # Need quality score
    if snapshot.quality_score is None:
        violations.append("Quality score not available for decision")

    return ValidationResult(
        is_valid=len(violations) == 0,
        violations=violations,
        validator_name="decision_context_validator",
    )
```

### 3.3 Integration with PipelineEngine

```python
# Integration point in PipelineEngine._execute_phase()

async def _execute_phase(self, phase_name: str) -> bool:
    """Execute a single phase with contract validation."""
    logger.info(f"Executing phase: {phase_name}")

    # Get contract for this phase
    contract = self._contract_registry.get(phase_name)

    # Validate inputs BEFORE phase execution
    input_validation = contract.validate_inputs(self._state_machine)
    if not input_validation.is_valid:
        logger.error(
            f"Phase {phase_name} contract violation: {input_validation.violations}",
            extra={"phase": phase_name, "violations": input_validation.violations},
        )
        # Record contract violation
        self._state_machine.add_chronicle_entry(
            event="CONTRACT_VIOLATION",
            data={
                "phase": phase_name,
                "type": "input_validation_failed",
                "violations": input_validation.violations,
            },
        )
        # Decide whether to proceed or fail based on severity
        if self._config.get("strict_contract_enforcement", True):
            self._state_machine.set_error(
                f"Phase {phase_name} missing required inputs: {input_validation.violations}"
            )
            return False

    # Set phase and execute
    self._state_machine.set_phase(phase_name)

    # ... execute phase logic ...

    # Validate outputs AFTER phase execution
    output_validation = contract.validate_outputs(self._state_machine)
    if not output_validation.is_valid:
        logger.error(
            f"Phase {phase_name} failed to produce outputs: {output_validation.violations}",
            extra={"phase": phase_name, "violations": output_validation.violations},
        )
        self._state_machine.add_chronicle_entry(
            event="CONTRACT_VIOLATION",
            data={
                "phase": phase_name,
                "type": "output_validation_failed",
                "violations": output_validation.violations,
            },
        )

    return output_validation.is_valid
```

---

## 4. Phase Contract Definitions

### 4.1 PLANNING Phase Contract

| Category | Name | Type | Description |
|----------|------|------|-------------|
| **Required Inputs** | `user_goal` | `str` | User's goal or requirement statement |
| | `context` | `dict` | Additional context for planning |
| **Optional Inputs** | `previous_plan` | `dict` | Plan from previous iteration |
| | `defects` | `list` | Defects to address |
| **Expected Outputs** | `planning_artifacts` | `dict` | Planning deliverables |
| | `task_breakdown` | `list` | Tasks derived from requirements |
| | `complexity_analysis` | `dict` | Complexity assessment |
| **Quality Criteria** | `overall_quality` | `>= 0.85` | Minimum quality threshold |

### 4.2 DEVELOPMENT Phase Contract

| Category | Name | Type | Description |
|----------|------|------|-------------|
| **Required Inputs** | `planning_artifacts` | `dict` | Planning output with tasks |
| | `user_goal` | `str` | Original user goal |
| **Optional Inputs** | `defects` | `list` | Defects to address |
| | `existing_code` | `str` | Code to modify |
| **Expected Outputs** | `code_artifacts` | `dict` | Generated code |
| | `test_artifacts` | `dict` | Test files |
| | `documentation` | `dict` | Documentation |
| **Quality Criteria** | `overall_quality` | `>= 0.90` | Minimum quality threshold |

### 4.3 QUALITY Phase Contract

| Category | Name | Type | Description |
|----------|------|------|-------------|
| **Required Inputs** | `planning_artifacts` | `dict` | Planning for requirements |
| | `code_artifacts` | `dict` | Code to evaluate |
| | `quality_template` | `str` | Quality template name |
| **Optional Inputs** | `test_artifacts` | `dict` | Test results |
| | `documentation` | `dict` | Documentation |
| **Expected Outputs** | `quality_report` | `dict` | Quality report |
| | `defects` | `list` | Identified defects |
| | `quality_score` | `float` | Quality score (0-1) |
| **Quality Criteria** | `overall_quality` | `>= 0.90` | Must achieve 90% |

### 4.4 DECISION Phase Contract

| Category | Name | Type | Description |
|----------|------|------|-------------|
| **Required Inputs** | `quality_report` | `dict` | Quality evaluation |
| | `defects` | `list` | Defects from quality |
| | `iteration_count` | `int` | Current iteration |
| **Optional Inputs** | `max_iterations` | `int` | Maximum iterations |
| **Expected Outputs** | `decision` | `dict` | Decision output |
| **Quality Criteria** | `correct_decision` | `>= 0.95` | Decision accuracy |

---

## 5. Validation Rules and Error Handling

### 5.1 Validation Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Phase Execution Flow                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. PRE-EXECUTION: Validate Inputs                                │
│    - Check required inputs exist                                 │
│    - Validate input types                                        │
│    - Run custom validators                                       │
│    - FAIL: ContractViolationError (block execution)              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. EXECUTION: Run Phase Logic                                    │
│    - Execute agents                                              │
│    - Generate artifacts                                          │
│    - Record chronicle entries                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. POST-EXECUTION: Validate Outputs                              │
│    - Check expected outputs produced                             │
│    - Validate output types                                       │
│    - Validate quality criteria                                   │
│    - FAIL: Record violation, notify DecisionEngine               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. TRANSITION: Validate Phase Handoff                            │
│    - Source outputs → Target inputs                              │
│    - Update PipelineState                                        │
│    - Log transition in chronicle                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Error Handling Strategy

```python
class ContractViolationError(Exception):
    """Raised when a phase contract is violated."""

    def __init__(
        self,
        message: str,
        phase: str,
        violations: List[str],
        severity: ContractViolationSeverity,
    ):
        super().__init__(message)
        self.phase = phase
        self.violations = violations
        self.severity = severity
        self.timestamp = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "error": "ContractViolationError",
            "phase": self.phase,
            "violations": self.violations,
            "severity": self.severity.name,
            "timestamp": self.timestamp.isoformat(),
            "message": str(self),
        }


class PhaseExecutionError(Exception):
    """Raised when phase execution fails."""

    def __init__(
        self,
        message: str,
        phase: str,
        cause: Optional[Exception] = None,
        missing_outputs: Optional[List[str]] = None,
    ):
        super().__init__(message)
        self.phase = phase
        self.cause = cause
        self.missing_outputs = missing_outputs or []


# Error handling in PipelineEngine
async def _execute_phase_with_contract(self, phase_name: str) -> bool:
    """Execute phase with contract validation and error handling."""
    contract = self._contract_registry.get(phase_name)

    try:
        # Pre-execution validation
        input_result = contract.validate_inputs(self._state_machine)
        if not input_result.is_valid:
            raise ContractViolationError(
                message=f"Phase {phase_name} missing required inputs",
                phase=phase_name,
                violations=input_result.violations,
                severity=ContractViolationSeverity.CRITICAL,
            )

        # Execute phase
        success = await self._execute_phase_logic(phase_name)

        if not success:
            raise PhaseExecutionError(
                message=f"Phase {phase_name} execution failed",
                phase=phase_name,
            )

        # Post-execution validation
        output_result = contract.validate_outputs(self._state_machine)
        if not output_result.is_valid:
            raise ContractViolationError(
                message=f"Phase {phase_name} failed to produce outputs",
                phase=phase_name,
                violations=output_result.violations,
                severity=ContractViolationSeverity.ERROR,
            )

        # Quality validation
        quality_result = contract.validate_quality(self._state_machine)
        if not quality_result.is_valid:
            # Log but don't fail - DecisionEngine handles quality decisions
            logger.warning(
                f"Phase {phase_name} quality below threshold: {quality_result.violations}",
                extra={"phase": phase_name, "quality_violations": quality_result.violations},
            )
            self._state_machine.add_chronicle_entry(
                event="QUALITY_THRESHOLD_NOT_MET",
                data={
                    "phase": phase_name,
                    "violations": quality_result.violations,
                },
            )

        return True

    except ContractViolationError as e:
        logger.error(
            f"Contract violation in {phase_name}: {e.violations}",
            extra={"phase": phase_name, "error": e.to_dict()},
        )
        self._state_machine.add_chronicle_entry(
            event="CONTRACT_VIOLATION",
            data=e.to_dict(),
        )
        if e.severity == ContractViolationSeverity.CRITICAL:
            return False
        # For ERROR severity, check config
        if self._config.get("strict_contract_enforcement", True):
            return False

    except PhaseExecutionError as e:
        logger.error(
            f"Phase execution error in {phase_name}: {e}",
            extra={"phase": phase_name, "missing_outputs": e.missing_outputs},
        )
        self._state_machine.set_error(str(e))
        return False

    except Exception as e:
        logger.exception(f"Unexpected error in {phase_name}: {e}")
        self._state_machine.set_error(f"Unexpected error: {str(e)}")
        return False
```

---

## 6. Integration Points

### 6.1 Integration with PipelineState

The PhaseContract works closely with `PipelineState` to validate artifacts:

```python
# The contract reads from PipelineSnapshot
snapshot = state.snapshot

# Check artifacts dictionary
value = snapshot.artifacts.get("planning_artifacts")

# Check context_injected for loop-back data
value = snapshot.context_injected.get("defects")

# Check quality score
score = snapshot.quality_score
```

### 6.2 Integration with LoopManager

For recursive loop-back, the PhaseContract preserves context:

```python
# In LoopManager._execute_agent()
context = {
    "goal": loop_state.config.exit_criteria.get("goal"),
    "phase": loop_state.config.phase_name,
    "defects": loop_state.defects,  # Accumulated defects
    "artifacts": loop_state.artifacts,  # Previous outputs
    "iteration": loop_state.iteration,
}

# Contract validates these are available for the target phase
contract = registry.get(loop_state.config.phase_name)
input_validation = contract.validate_inputs(state)
```

### 6.3 Integration with DefectRouter

The DefectRouter uses contract information:

```python
# In DefectRouter.route_defect()
def route_defect(self, defect: Defect) -> str:
    # Check which phase produced the artifact with the defect
    phase_detected = defect.phase_detected

    # Get target phase from routing rules
    target_phase = super().route_defect(defect)

    # Validate target phase can accept this defect
    contract = self._contract_registry.get(target_phase)
    if "defects" not in contract.optional_inputs:
        # Defect cannot be routed here, use default
        return "DEVELOPMENT"

    return target_phase
```

### 6.4 Integration with DecisionEngine

The DecisionEngine validates contract outputs:

```python
# In DecisionEngine.evaluate()
def evaluate(self, phase_name: str, ...) -> Decision:
    # Get contract for current phase
    contract = self._contract_registry.get(phase_name)

    # Validate quality criteria from contract
    quality_result = contract.validate_quality(state)

    # Make decision based on contract thresholds
    if quality_result.is_valid and quality_score >= threshold:
        return Decision.continue_decision(...)
    else:
        return Decision.loop_back_decision(
            target_phase="PLANNING",
            defects=defects,
            ...
        )
```

---

## 7. File Structure

```
gaia/src/gaia/pipeline/
├── phase_contract.py          # Core PhaseContract implementation
├── contract_registry.py       # PhaseContractRegistry
├── contract_validators.py     # Built-in validators
└── contracts/
    ├── __init__.py
    ├── planning.py            # PLANNING phase contract
    ├── development.py         # DEVELOPMENT phase contract
    ├── quality.py             # QUALITY phase contract
    └── decision.py            # DECISION phase contract

gaia/tests/pipeline/
├── test_phase_contract.py     # PhaseContract tests
├── test_contract_registry.py  # Registry tests
└── test_integration.py        # Integration tests
```

---

## 8. Usage Examples

### 8.1 Creating a Custom Phase Contract

```python
from gaia.pipeline.phase_contract import PhaseContract, ContractTerm, InputType

# Create a custom review phase contract
review_contract = PhaseContract(
    phase_name="REVIEW",
    description="Human review phase",
).add_required_input(
    name="code_artifacts",
    expected_type=dict,
    description="Code to review",
).add_required_input(
    name="quality_report",
    expected_type=dict,
    description="Quality evaluation report",
).add_optional_input(
    name="reviewer_notes",
    expected_type=str,
    description="Notes from human reviewer",
    default_value="",
).add_expected_output(
    name="review_decision",
    expected_type=dict,
    description="Review decision (approve/reject/changes_requested)",
).add_expected_output(
    name="review_feedback",
    expected_type=list,
    description="Feedback items for development",
).with_quality_criteria(
    criteria_name="review_approval",
    threshold=1.0,  # Must be approved
)

# Register with registry
registry = PhaseContractRegistry()
registry.register(review_contract)
```

### 8.2 Validating Phase Execution

```python
from gaia.pipeline.phase_contract import PhaseContractRegistry
from gaia.pipeline.state import PipelineContext, PipelineStateMachine

# Initialize
context = PipelineContext(
    pipeline_id="test-001",
    user_goal="Build REST API",
)
state_machine = PipelineStateMachine(context)
registry = PhaseContractRegistry()
registry.register_default_contracts()

# Add required artifacts
state_machine.add_artifact("user_goal", "Build REST API")
state_machine.add_artifact("context", {"language": "python"})

# Validate PLANNING phase inputs
planning_contract = registry.get("PLANNING")
input_result = planning_contract.validate_inputs(state_machine)

if not input_result.is_valid:
    print(f"Cannot execute PLANNING: {input_result.violations}")
else:
    print("PLANNING phase can proceed")

# After PLANNING execution, validate outputs
state_machine.add_artifact("planning_artifacts", {...})
state_machine.add_artifact("task_breakdown", [...])
state_machine.add_artifact("complexity_analysis", {...})

output_result = planning_contract.validate_outputs(state_machine)
if not output_result.is_valid:
    print(f"PLANNING incomplete: {output_result.violations}")
```

### 8.3 Loop-Back with Defects

```python
# In loop-back scenario, defects flow back to PLANNING
state_machine.add_artifact("defects", [
    {"type": "missing_tests", "severity": "high"},
    {"type": "incomplete_docs", "severity": "medium"},
])

# PLANNING contract accepts defects as optional input
planning_contract = registry.get("PLANNING")
input_result = planning_contract.validate_inputs(state_machine)

# Should pass - defects are optional but now present
print(f"Input validation: {input_result.is_valid}")  # True
print(f"Missing inputs: {planning_contract.get_missing_inputs(state_machine)}")  # []
```

---

## 9. Testing Strategy

### 9.1 Unit Tests

```python
import pytest
from gaia.pipeline.phase_contract import (
    PhaseContract,
    ContractTerm,
    InputType,
    PhaseContractRegistry,
)
from gaia.pipeline.state import PipelineContext, PipelineStateMachine


class TestPhaseContract:
    def test_create_contract(self):
        contract = PhaseContract(phase_name="TEST")
        assert contract.phase_name == "TEST"

    def test_validate_missing_input(self, sample_state):
        contract = PhaseContract(phase_name="TEST").add_required_input(
            name="required_field",
            expected_type=str,
            description="A required field",
        )
        result = contract.validate_inputs(sample_state)
        assert not result.is_valid
        assert "Missing required input: required_field" in result.violations

    def test_validate_present_input(self, sample_state_with_data):
        contract = PhaseContract(phase_name="TEST").add_required_input(
            name="user_goal",
            expected_type=str,
            description="User goal",
        )
        result = contract.validate_inputs(sample_state_with_data)
        assert result.is_valid

    def test_validate_type_mismatch(self, sample_state_wrong_type):
        contract = PhaseContract(phase_name="TEST").add_required_input(
            name="user_goal",
            expected_type=str,
            description="User goal",
        )
        result = contract.validate_inputs(sample_state_wrong_type)
        assert not result.is_valid
        assert "wrong type" in result.violations[0]


class TestPhaseContractRegistry:
    def test_register_and_get(self):
        registry = PhaseContractRegistry()
        contract = PhaseContract(phase_name="TEST")
        registry.register(contract)

        retrieved = registry.get("TEST")
        assert retrieved is contract

    def test_validate_transition(self, sample_state):
        registry = PhaseContractRegistry()
        registry.register_default_contracts()

        # Add required artifacts for PLANNING -> DEVELOPMENT
        sample_state.add_artifact("user_goal", "Test")
        sample_state.add_artifact("context", {})
        sample_state.add_artifact("planning_artifacts", {})
        sample_state.add_artifact("task_breakdown", [])
        sample_state.add_artifact("complexity_analysis", {})

        result = registry.validate_phase_transition(
            "PLANNING",
            "DEVELOPMENT",
            sample_state,
        )
        assert result.is_valid
```

### 9.2 Integration Tests

```python
class TestPhaseContractIntegration:
    @pytest.mark.asyncio
    async def test_full_pipeline_with_contracts(self):
        """Test complete pipeline with contract validation."""
        engine = PipelineEngine()
        context = PipelineContext(
            pipeline_id="integration-test-001",
            user_goal="Build calculator",
            quality_threshold=0.90,
        )
        config = {"strict_contract_enforcement": True}

        await engine.initialize(context, config)
        result = await engine.start()

        # Verify contracts were validated
        chronicle = engine.get_chronicle()
        contract_validations = [
            e for e in chronicle if "CONTRACT" in e.get("event", "")
        ]
        assert len(contract_validations) > 0

        # Verify pipeline completed
        assert result.state == PipelineState.COMPLETED
```

---

## 10. Success Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Contract Coverage | 100% | All 4 phases have contracts |
| Input Validation | < 100ms | Time to validate inputs |
| Output Validation | < 100ms | Time to validate outputs |
| Error Detection | 100% | All missing inputs detected |
| Integration | 0 breaking changes | Existing tests pass |
| Quality Threshold | >= 0.90 | QUALITY phase must achieve |

---

## 11. Appendix

### 11.1 Glossary

| Term | Definition |
|------|------------|
| **Contract** | Formal agreement of phase I/O requirements |
| **ContractTerm** | Single input/output specification |
| **ValidationResult** | Outcome of contract validation |
| **ContractViolation** | Failure to meet contract terms |
| **PhaseContractRegistry** | Central contract management |

### 11.2 References

- GAIA_META_PIPELINE_PLAN.md - Meta-pipeline execution plan
- GAIA_COMPLETE_ARCHITECTURE.md - System architecture
- gaia/src/gaia/pipeline/state.py - PipelineState implementation
- gaia/src/gaia/pipeline/loop_manager.py - Loop execution
- gaia/src/gaia/pipeline/decision_engine.py - Decision logic

---

*Document Version: 1.0.0*
*Generated: 2026-03-23*
*Status: Ready for Development*
