"""
GAIA Core Pipeline Engine

A quality-gated multi-agent orchestration system.
"""

__version__ = "0.1.0"
__author__ = "GAIA Team"

from gaia.pipeline.state import (
    PipelineState,
    PipelineContext,
    PipelineSnapshot,
    PipelineStateMachine,
)
from gaia.pipeline.engine import PipelineEngine
from gaia.quality.scorer import QualityScorer
from gaia.agents.registry import AgentRegistry
from gaia.hooks.registry import HookRegistry

__all__ = [
    "PipelineState",
    "PipelineContext",
    "PipelineSnapshot",
    "PipelineStateMachine",
    "PipelineEngine",
    "QualityScorer",
    "AgentRegistry",
    "HookRegistry",
]
