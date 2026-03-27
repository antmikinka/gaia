"""
GAIA Pipeline Engine

Main pipeline orchestrator that coordinates all components.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Union
from pathlib import Path

from gaia.pipeline.state import (
    PipelineState,
    PipelineContext,
    PipelineSnapshot,
    PipelineStateMachine,
)
from gaia.pipeline.loop_manager import LoopManager, LoopConfig
from gaia.pipeline.decision_engine import DecisionEngine, DecisionType
from gaia.pipeline.routing_engine import RoutingEngine, RoutingDecision
from gaia.quality.scorer import QualityScorer
from gaia.agents.registry import AgentRegistry
from gaia.hooks.base import HookContext
from gaia.hooks.registry import HookRegistry, HookExecutor
from gaia.hooks.production.validation_hooks import (
    PreActionValidationHook,
    PostActionValidationHook,
)
from gaia.hooks.production.context_hooks import (
    ContextInjectionHook,
    OutputProcessingHook,
)
from gaia.hooks.production.quality_hooks import (
    QualityGateHook,
    DefectExtractionHook,
    PipelineNotificationHook,
    ChronicleHarvestHook,
)
from gaia.pipeline.recursive_template import (
    RecursivePipelineTemplate,
    PhaseConfig,
    AgentCategory,
)
from gaia.pipeline.template_loader import TemplateLoader, TemplateValidationError
from gaia.utils.logging import get_logger, setup_logging
from gaia.utils.id_generator import generate_loop_id
from gaia.exceptions import (
    PipelineNotInitializedError,
    PipelineAlreadyRunningError,
    InvalidQualityThresholdError,
)


logger = get_logger(__name__)


# Pipeline phases
class PipelinePhase:
    """Pipeline phase constants."""

    PLANNING = "PLANNING"
    DEVELOPMENT = "DEVELOPMENT"
    QUALITY = "QUALITY"
    DECISION = "DECISION"

    ALL = [PLANNING, DEVELOPMENT, QUALITY, DECISION]


@dataclass
class PipelineConfig:
    """
    Pipeline configuration.

    Attributes:
        template_name: Name of template to use
        template_file: Path to template YAML file
        template: Loaded RecursivePipelineTemplate
        quality_threshold: Required quality score (0-1)
        max_iterations: Maximum loop iterations
        concurrent_loops: Number of concurrent loops
        agents_dir: Directory for agent definitions
        enable_hooks: Whether to enable hooks
        hooks: List of hooks to register
    """

    template_name: Optional[str] = None
    template_file: Optional[Union[str, Path]] = None
    template: Optional[RecursivePipelineTemplate] = None
    quality_threshold: float = 0.90
    max_iterations: int = 10
    concurrent_loops: int = 5
    agents_dir: Optional[str] = None
    enable_hooks: bool = True
    hooks: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.template:
            # Use template's quality threshold if not explicitly set
            if self.quality_threshold == 0.90 and self.template.quality_threshold != 0.90:
                self.quality_threshold = self.template.quality_threshold
            # Use template's max iterations if not explicitly set
            if self.max_iterations == 10 and self.template.max_iterations != 10:
                self.max_iterations = self.template.max_iterations
        elif not 0 <= self.quality_threshold <= 1:
            raise InvalidQualityThresholdError(self.quality_threshold)
        if self.max_iterations < 0:
            raise ValueError("max_iterations must be non-negative")
        if self.concurrent_loops < 1:
            raise ValueError("concurrent_loops must be at least 1")


class PipelineEngine:
    """
    Main pipeline orchestrator.

    The PipelineEngine coordinates all pipeline components:
    - State machine for lifecycle management
    - Loop manager for concurrent execution
    - Decision engine for progression logic
    - Quality scorer for evaluation
    - Agent registry for agent selection
    - Hook executor for event handling
    - Template loader for dynamic phase configuration

    Example:
        >>> engine = PipelineEngine()
        >>> context = PipelineContext(
        ...     pipeline_id="test-001",
        ...     user_goal="Build a REST API"
        ... )
        >>> config = PipelineConfig(template_name="standard")
        >>> await engine.initialize(context, config)
        >>> result = await engine.start()
        >>> print(f"Pipeline completed with state: {result.state}")
    """

    def __init__(
        self,
        agents_dir: Optional[str] = None,
        template_dir: Optional[str] = None,
        enable_logging: bool = True,
        log_level: int = 20,  # INFO
    ):
        """
        Initialize pipeline engine.

        Args:
            agents_dir: Directory for agent definitions
            template_dir: Directory for template YAML files
            enable_logging: Whether to setup logging
            log_level: Logging level
        """
        if enable_logging:
            setup_logging(level=log_level)

        self._agents_dir = agents_dir
        self._template_dir = template_dir
        self._initialized = False
        self._running = False

        # Components (initialized in initialize())
        self._state_machine: Optional[PipelineStateMachine] = None
        self._loop_manager: Optional[LoopManager] = None
        self._decision_engine: Optional[DecisionEngine] = None
        self._routing_engine: Optional[RoutingEngine] = None
        self._quality_scorer: Optional[QualityScorer] = None
        self._agent_registry: Optional[AgentRegistry] = None
        self._hook_registry: Optional[HookRegistry] = None
        self._hook_executor: Optional[HookExecutor] = None
        self._template_loader: Optional[TemplateLoader] = None

        # State
        self._context: Optional[PipelineContext] = None
        self._config: Optional[PipelineConfig] = None
        self._current_template: Optional[RecursivePipelineTemplate] = None
        self._completion_event: Optional[asyncio.Event] = None

        logger.info("PipelineEngine created")

    async def initialize(
        self,
        context: PipelineContext,
        config: Optional[Union[Dict[str, Any], PipelineConfig]] = None,
    ) -> None:
        """
        Initialize pipeline with context and configuration.

        Args:
            context: Pipeline context
            config: Configuration dictionary or PipelineConfig instance

        Raises:
            PipelineAlreadyRunningError: If pipeline is already initialized
        """
        if self._initialized:
            raise PipelineAlreadyRunningError("Pipeline already initialized")

        logger.info(
            f"Initializing pipeline {context.pipeline_id}",
            extra={"pipeline_id": context.pipeline_id},
        )

        # Convert dict to PipelineConfig if needed
        if isinstance(config, dict):
            self._config = PipelineConfig(**config)
        elif isinstance(config, PipelineConfig):
            self._config = config
        else:
            self._config = PipelineConfig()

        self._context = context

        # Initialize template loader and load template if specified
        self._template_loader = TemplateLoader(
            template_dir=self._template_dir
        )

        if self._config.template_name or self._config.template_file:
            try:
                if self._config.template_file:
                    self._current_template = self._template_loader.load_template(
                        self._config.template_name or "standard",
                        self._config.template_file,
                    )
                else:
                    self._current_template = self._template_loader.load_template(
                        self._config.template_name or "standard",
                    )

                logger.info(
                    f"Loaded template: {self._current_template.name}",
                    extra={"template_name": self._current_template.name},
                )
            except Exception as e:
                logger.warning(f"Failed to load template: {e}. Using default configuration.")
                self._current_template = None
        else:
            self._current_template = None

        # Initialize state machine
        self._state_machine = PipelineStateMachine(context)

        # Initialize loop manager
        concurrent_loops = self._config.concurrent_loops
        self._loop_manager = LoopManager(
            max_concurrent=concurrent_loops,
            agent_registry=self._agent_registry,
        )

        # Initialize decision engine
        self._decision_engine = DecisionEngine({
            "quality_threshold": self._config.quality_threshold,
            "max_iterations": self._config.max_iterations,
        })

        # Initialize routing engine (for defect-based routing)
        self._routing_engine = RoutingEngine(agent_registry=self._agent_registry)

        # Initialize quality scorer
        self._quality_scorer = QualityScorer()

        # Initialize agent registry
        agents_dir = self._config.agents_dir or self._agents_dir
        self._agent_registry = AgentRegistry(agents_dir=agents_dir)
        await self._agent_registry.initialize()

        # Update routing engine with initialized registry
        if self._routing_engine:
            self._routing_engine.set_agent_registry(self._agent_registry)

        # Validate template against agent registry if loaded
        if self._current_template and self._agent_registry:
            validation_errors = self._template_loader.validate_template(
                self._current_template,
                self._agent_registry,
            )
            if validation_errors:
                raise TemplateValidationError(
                    f"Template validation failed with {len(validation_errors)} error(s): "
                    f"{'; '.join(validation_errors)}"
                )

        # Initialize hook system
        if self._config.enable_hooks:
            self._hook_registry = HookRegistry()
            self._hook_executor = HookExecutor(self._hook_registry)
            self._register_default_hooks()

        # Transition to READY state
        self._state_machine.transition(
            PipelineState.READY,
            "Initialization complete",
        )

        self._initialized = True
        self._completion_event = asyncio.Event()

        logger.info(
            f"Pipeline {context.pipeline_id} initialized",
            extra={
                "pipeline_id": context.pipeline_id,
                "template": self._current_template.name if self._current_template else "default",
            },
        )

    def _register_default_hooks(self) -> None:
        """Register default production hooks."""
        if not self._hook_registry:
            return

        hooks = [
            PreActionValidationHook(),
            PostActionValidationHook(),
            ContextInjectionHook(),
            OutputProcessingHook(),
            QualityGateHook(),
            DefectExtractionHook(),
            PipelineNotificationHook(),
            ChronicleHarvestHook(),
        ]

        for hook in hooks:
            self._hook_registry.register(hook)

        logger.info(f"Registered {len(hooks)} default hooks")

    async def start(self) -> PipelineSnapshot:
        """
        Start pipeline execution.

        Returns:
            Current pipeline snapshot

        Raises:
            PipelineNotInitializedError: If not initialized
            PipelineAlreadyRunningError: If already running
        """
        if not self._initialized:
            raise PipelineNotInitializedError()

        if self._running:
            raise PipelineAlreadyRunningError()

        logger.info(
            f"Starting pipeline {self._context.pipeline_id}",
            extra={"pipeline_id": self._context.pipeline_id},
        )

        self._running = True

        # Transition to RUNNING
        self._state_machine.transition(PipelineState.RUNNING, "Pipeline started")

        # Execute pipeline phases
        try:
            await self._execute_pipeline()
        except Exception as e:
            logger.exception(f"Pipeline error: {e}")
            self._state_machine.transition(
                PipelineState.FAILED,
                f"Pipeline error: {e}",
            )
            self._running = False
            self._completion_event.set()

        return self._state_machine.snapshot

    async def _execute_pipeline(self) -> None:
        """Execute all pipeline phases."""
        phases = [
            PipelinePhase.PLANNING,
            PipelinePhase.DEVELOPMENT,
            PipelinePhase.QUALITY,
            PipelinePhase.DECISION,
        ]

        for phase in phases:
            if not self._running:
                break

            phase_complete = await self._execute_phase(phase)

            if not phase_complete:
                logger.warning(f"Phase {phase} did not complete successfully")
                break

        # Pipeline complete
        self._state_machine.transition(
            PipelineState.COMPLETED,
            "Pipeline execution complete",
        )
        self._running = False
        self._completion_event.set()

    async def _execute_phase(self, phase_name: str) -> bool:
        """
        Execute a single phase.

        Args:
            phase_name: Phase to execute

        Returns:
            True if phase completed successfully
        """
        logger.info(f"Executing phase: {phase_name}")

        self._state_machine.set_phase(phase_name)

        # Execute phase enter hooks
        if self._hook_executor:
            context = HookContext(
                event="PHASE_ENTER",
                pipeline_id=self._context.pipeline_id,
                phase=phase_name,
                state=self._get_state_dict(),
            )
            result = await self._hook_executor.execute_hooks("PHASE_ENTER", context)
            if result.halt_pipeline:
                return False

        # Execute phase based on type
        success = True
        if phase_name == PipelinePhase.PLANNING:
            success = await self._execute_planning()
        elif phase_name == PipelinePhase.DEVELOPMENT:
            success = await self._execute_development()
        elif phase_name == PipelinePhase.QUALITY:
            success = await self._execute_quality()
        elif phase_name == PipelinePhase.DECISION:
            success = await self._execute_decision()

        # Execute phase exit hooks
        if self._hook_executor:
            context = HookContext(
                event="PHASE_EXIT",
                pipeline_id=self._context.pipeline_id,
                phase=phase_name,
                state=self._get_state_dict(),
                data={"success": success},
            )
            result = await self._hook_executor.execute_hooks("PHASE_EXIT", context)
            if result.halt_pipeline:
                return False

        return success

    async def _execute_planning(self) -> bool:
        """
        Execute planning phase using template configuration.

        If a template is loaded, uses the agent IDs from the template.
        Otherwise falls back to dynamic agent selection.
        """
        logger.info("Executing PLANNING phase")

        # Get agents from template if available
        template_agents = self._get_agents_for_phase(PipelinePhase.PLANNING)

        if template_agents:
            # Validate agents exist in registry
            valid_agents = []
            for agent_id in template_agents:
                if self._agent_registry.get_agent(agent_id):
                    valid_agents.append(agent_id)
                    logger.info(f"Using template agent: {agent_id}")
                else:
                    logger.warning(f"Template agent not found: {agent_id}")

            agent_sequence = valid_agents if valid_agents else template_agents
        else:
            # Fall back to dynamic selection
            agent_id = self._agent_registry.select_agent(
                task_description=self._context.user_goal,
                current_phase=PipelinePhase.PLANNING,
                state=self._get_state_dict(),
            )
            agent_sequence = [agent_id] if agent_id else []

        if agent_sequence:
            self._state_machine.add_artifact("planning_agent", agent_sequence[0])

        # Get output artifact name from template
        output_artifact = self._get_output_artifact_name(PipelinePhase.PLANNING)

        # Create planning loop
        loop_config = LoopConfig(
            loop_id=generate_loop_id(self._context.pipeline_id),
            phase_name=PipelinePhase.PLANNING,
            agent_sequence=agent_sequence,
            exit_criteria={
                "quality_threshold": self._context.quality_threshold,
                "output_artifact": output_artifact,
            },
            quality_threshold=self._context.quality_threshold,
            max_iterations=self._context.max_iterations,
        )
        await self._loop_manager.create_loop(loop_config)
        await self._loop_manager.start_loop(loop_config.loop_id)

        # Wait for loop completion
        await asyncio.sleep(0.1)  # In production, would wait properly

        self._state_machine.increment_iteration()
        return True

    async def _execute_development(self) -> bool:
        """
        Execute development phase using template configuration.

        If a template is loaded, uses the agent IDs from the template.
        Otherwise falls back to dynamic agent selection.
        """
        logger.info("Executing DEVELOPMENT phase")

        # Get agents from template if available
        template_agents = self._get_agents_for_phase(PipelinePhase.DEVELOPMENT)

        if template_agents:
            # Validate agents exist in registry
            valid_agents = []
            for agent_id in template_agents:
                if self._agent_registry.get_agent(agent_id):
                    valid_agents.append(agent_id)
                    logger.info(f"Using template agent: {agent_id}")
                else:
                    logger.warning(f"Template agent not found: {agent_id}")

            agent_sequence = valid_agents if valid_agents else template_agents
        else:
            # Fall back to dynamic selection
            agent_id = self._agent_registry.select_agent(
                task_description=self._context.user_goal,
                current_phase=PipelinePhase.DEVELOPMENT,
                state=self._get_state_dict(),
                required_capabilities=["full-stack-development"],
            )
            agent_sequence = [agent_id] if agent_id else []

        # Get output artifact name from template
        output_artifact = self._get_output_artifact_name(PipelinePhase.DEVELOPMENT)

        # Create development loop
        loop_config = LoopConfig(
            loop_id=generate_loop_id(self._context.pipeline_id),
            phase_name=PipelinePhase.DEVELOPMENT,
            agent_sequence=agent_sequence,
            exit_criteria={
                "quality_threshold": self._context.quality_threshold,
                "output_artifact": output_artifact,
            },
            quality_threshold=self._context.quality_threshold,
            max_iterations=self._context.max_iterations,
        )
        await self._loop_manager.create_loop(loop_config)
        await self._loop_manager.start_loop(loop_config.loop_id)

        await asyncio.sleep(0.1)

        self._state_machine.increment_iteration()
        return True

    async def _execute_quality(self) -> bool:
        """
        Execute quality phase using template configuration.

        Uses template quality weights if available.
        """
        logger.info("Executing QUALITY phase")

        # Get artifacts to evaluate
        artifacts = self._state_machine.snapshot.artifacts

        # Get quality weights from template if available
        quality_weights = {}
        if self._current_template:
            quality_weights = self._current_template.quality_weights or {}

        # Evaluate quality
        quality_report = await self._quality_scorer.evaluate(
            artifact=artifacts,
            context={
                "requirements": [self._context.user_goal],
                "template": self._current_template.name if self._current_template else "default",
                "quality_weights": quality_weights,
            },
        )

        # Store quality score
        quality_score = quality_report.overall_score / 100
        self._state_machine.set_quality_score(quality_score)

        # Store with template-defined artifact name
        output_artifact = self._get_output_artifact_name(PipelinePhase.QUALITY)
        self._state_machine.add_artifact(output_artifact, quality_report.to_dict())

        logger.info(
            f"Quality evaluation complete: {quality_score:.2f}",
            extra={"quality_score": quality_score},
        )

        return True

    async def _execute_decision(self) -> bool:
        """
        Execute decision phase using template configuration.

        Uses template quality threshold for decision evaluation.
        Integrates routing engine for defect-based routing decisions.
        """
        logger.info("Executing DECISION phase")

        quality_score = self._state_machine.snapshot.quality_score or 0.0
        iteration = self._state_machine.snapshot.iteration_count

        # Use template quality threshold if available
        quality_threshold = self._context.quality_threshold
        if self._current_template:
            quality_threshold = self._current_template.quality_threshold

        # Get defects from snapshot
        defects = self._state_machine.snapshot.defects

        # Route defects using routing engine if available
        routing_decisions = []
        if self._routing_engine and defects:
            context = {
                "current_phase": PipelinePhase.DECISION,
                "iteration": iteration,
                "quality_score": quality_score,
            }
            for defect in defects:
                try:
                    decision = self._routing_engine.route_defect(defect, context)
                    routing_decisions.append(decision)
                    # Update defect with routing information
                    defect["target_phase"] = decision.target_phase
                    defect["target_agent"] = decision.target_agent
                    defect["routing"] = decision.to_dict()
                except Exception as e:
                    logger.warning(f"Failed to route defect: {e}")

        # Make decision
        decision = self._decision_engine.evaluate(
            phase_name=PipelinePhase.DECISION,
            quality_score=quality_score,
            quality_threshold=quality_threshold,
            defects=defects,
            iteration=iteration,
            max_iterations=self._context.max_iterations,
            is_final_phase=True,
        )

        # Prepare decision metadata with routing information
        decision_metadata = {
            "quality_score": quality_score,
            "quality_threshold": quality_threshold,
            "iteration": iteration,
            "routing_decisions_count": len(routing_decisions),
            "routing_decisions": [rd.to_dict() for rd in routing_decisions],
        }

        # Add routing decisions to decision metadata
        if routing_decisions:
            decision.metadata["routing"] = {
                "decisions": [rd.to_dict() for rd in routing_decisions],
                "phases": list(set(rd.target_phase for rd in routing_decisions)),
            }

        self._state_machine.add_artifact("decision", decision.to_dict())

        logger.info(
            f"Decision: {decision.decision_type.name}",
            extra={
                "decision_type": decision.decision_type.name,
                "quality_threshold": quality_threshold,
                "routing_decisions": len(routing_decisions),
            },
        )

        # Handle decision
        if decision.decision_type == DecisionType.FAIL:
            self._state_machine.set_error(decision.reason)
            return False

        # Handle loop back with routing information
        if decision.decision_type == DecisionType.LOOP_BACK:
            # Store routing decisions for loop manager to use
            if routing_decisions:
                self._state_machine.add_artifact(
                    "routing_decisions",
                    [rd.to_dict() for rd in routing_decisions],
                )
                logger.info(
                    f"Loop back with {len(routing_decisions)} routed defects",
                    extra={"routing_count": len(routing_decisions)},
                )

        return True

    def _get_state_dict(self) -> Dict[str, Any]:
        """Get current state as dictionary."""
        snapshot = self._state_machine.snapshot
        return {
            "pipeline_id": self._context.pipeline_id,
            "user_goal": self._context.user_goal,
            "current_phase": snapshot.current_phase,
            "quality_score": snapshot.quality_score,
            "iteration_count": snapshot.iteration_count,
            "defects": snapshot.defects,
            "artifacts": snapshot.artifacts,
            "max_iterations": self._context.max_iterations,
        }

    def _get_phase_config(self, phase_name: str) -> Optional[PhaseConfig]:
        """
        Get phase configuration from template.

        Args:
            phase_name: Name of phase to get config for

        Returns:
            PhaseConfig if template has this phase, None otherwise
        """
        if not self._current_template:
            return None

        return self._current_template.get_phase(phase_name)

    def _get_agents_for_phase(self, phase_name: str) -> List[str]:
        """
        Get list of agent IDs for a phase from template.

        Args:
            phase_name: Name of phase

        Returns:
            List of agent IDs configured for this phase
        """
        # First try template phase config
        phase_config = self._get_phase_config(phase_name)
        if phase_config and phase_config.agents:
            return list(phase_config.agents)

        # Fall back to category-based lookup
        if self._current_template:
            for category, agents in self._current_template.agent_categories.items():
                if category.lower() == phase_name.lower():
                    return list(agents)

        return []

    def _get_output_artifact_name(self, phase_name: str) -> str:
        """
        Get output artifact name for a phase from template.

        Args:
            phase_name: Name of phase

        Returns:
            Artifact name for phase output
        """
        phase_config = self._get_phase_config(phase_name)
        if phase_config and phase_config.exit_criteria.get("artifact"):
            return phase_config.exit_criteria["artifact"]

        # Default artifact names
        default_artifacts = {
            PipelinePhase.PLANNING: "technical_plan",
            PipelinePhase.DEVELOPMENT: "implementation",
            PipelinePhase.QUALITY: "quality_report",
            PipelinePhase.DECISION: "decision",
        }
        return default_artifacts.get(phase_name, f"{phase_name.lower()}_output")

    async def pause(self, reason: str) -> PipelineSnapshot:
        """Pause pipeline execution."""
        if not self._initialized:
            raise PipelineNotInitializedError()

        self._state_machine.transition(PipelineState.PAUSED, reason)
        logger.info(f"Pipeline paused: {reason}")
        return self._state_machine.snapshot

    async def resume(self) -> PipelineSnapshot:
        """Resume paused pipeline."""
        if not self._initialized:
            raise PipelineNotInitializedError()

        if self._state_machine.current_state != PipelineState.PAUSED:
            raise PipelineNotInitializedError("Pipeline is not paused")

        self._state_machine.transition(PipelineState.RUNNING, "Pipeline resumed")
        self._running = True
        logger.info("Pipeline resumed")
        return self._state_machine.snapshot

    async def cancel(self) -> PipelineSnapshot:
        """Cancel pipeline execution."""
        if not self._initialized:
            raise PipelineNotInitializedError()

        self._running = False
        self._state_machine.transition(PipelineState.CANCELLED, "Pipeline cancelled")

        # Cancel all loops
        for loop_id in list(self._loop_manager.get_all_loops().keys()):
            await self._loop_manager.cancel_loop(loop_id)

        self._completion_event.set()
        logger.info("Pipeline cancelled")
        return self._state_machine.snapshot

    async def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for pipeline to complete.

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            True if completed, False if timeout
        """
        if not self._completion_event:
            return False

        try:
            await asyncio.wait_for(
                self._completion_event.wait(),
                timeout=timeout,
            )
            return True
        except asyncio.TimeoutError:
            return False

    def get_snapshot(self) -> PipelineSnapshot:
        """Get current pipeline state snapshot."""
        if not self._initialized:
            raise PipelineNotInitializedError()
        return self._state_machine.snapshot

    def get_chronicle(self) -> List[Dict[str, Any]]:
        """Get pipeline chronicle (event log)."""
        if not self._initialized:
            raise PipelineNotInitializedError()
        return self._state_machine.chronicle

    def get_loop_manager(self) -> LoopManager:
        """Get loop manager instance."""
        if not self._loop_manager:
            raise PipelineNotInitializedError()
        return self._loop_manager

    def shutdown(self) -> None:
        """Shutdown pipeline and cleanup resources."""
        logger.info("Shutting down PipelineEngine")

        if self._loop_manager:
            self._loop_manager.shutdown(wait=False)

        if self._agent_registry:
            self._agent_registry.shutdown()

        self._initialized = False
        self._running = False
