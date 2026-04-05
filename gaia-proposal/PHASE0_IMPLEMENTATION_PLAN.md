# BAIBEL-GAIA Integration - Phase 0 Implementation Plan

**Status:** READY FOR IMPLEMENTATION
**Priority:** P0 - IMMEDIATE
**Estimated Effort:** 2 weeks
**Target Repository:** `C:/Users/antmi/gaia`
**Branch:** `feature/pipeline-orchestration-v1`

---

## Executive Summary

Following completion of P1, P2, and P3 phases in gaia-proposal (100% production-ready, 401+ tests, 0.965 aggregate quality score), **Phase 0 (Tool Scoping)** is the immediate next step for BAIBEL architectural pattern integration.

### Current Status

| Component | Status | Location |
|-----------|--------|----------|
| **P1-P3 Completion** | COMPLETE | gaia-proposal (feature/gaia-pipeline-implementation) |
| **Code Transfer** | COMPLETE | Main gaia repo (feature/pipeline-orchestration-v1) |
| **BAIBEL Specification** | COMPLETE | `docs/spec/baibel-gaia-integration-master.md` (1192 lines) |
| **Phase 0 Spec** | COMPLETE | `docs/spec/phase0-tool-scoping-integration.md` |
| **Phase 0 Implementation** | **NOT STARTED** | BLOCKED - Ready to implement |

---

## Phase 0 Objective: Tool Scoping

### Problem Statement

**Current State:** Global mutable `_TOOL_REGISTRY` dict shared across all agents.

**Risk:** Tool cross-contamination between agents with different responsibilities. A chat agent could potentially access file system tools, violating security boundaries.

**Target State:** Per-agent tool allowlist with case-sensitive validation.

---

## Implementation Plan (2 Weeks)

### Week 1: Core Implementation

#### Day 1-2: ToolRegistry Class

**File:** `src/gaia/tools/registry.py` (NEW)

```python
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any
from threading import RLock
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolMetadata:
    """Metadata for a registered tool."""
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: callable


class ToolRegistry:
    """
    Thread-safe tool registry with per-agent scoping.

    Replaces global _TOOL_REGISTRY dict with scoped access control.
    """

    _instance: Optional['ToolRegistry'] = None
    _lock = RLock()

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._tools: Dict[str, ToolMetadata] = {}
        self._agent_scopes: Dict[str, 'AgentScope'] = {}
        self._lock = RLock()
        self._initialized = True

    def register_tool(self, name: str, description: str, parameters: Dict, handler: callable) -> None:
        """Register a tool globally."""
        with self._lock:
            if name in self._tools:
                logger.warning(f"Tool '{name}' already registered, overwriting")
            self._tools[name] = ToolMetadata(
                name=name,
                description=description,
                parameters=parameters,
                handler=handler
            )
            logger.info(f"Tool '{name}' registered")

    def create_scope(self, agent_id: str, allowed_tools: List[str]) -> 'AgentScope':
        """Create a scoped view for an agent with tool allowlist."""
        with self._lock:
            if agent_id in self._agent_scopes:
                logger.warning(f"Agent scope for '{agent_id}' already exists, overwriting")

            # Validate all tools exist
            valid_tools = []
            for tool_name in allowed_tools:
                if tool_name not in self._tools:
                    logger.warning(f"Tool '{tool_name}' not found in registry (allowed for agent '{agent_id}')")
                else:
                    valid_tools.append(tool_name)

            scope = AgentScope(self, agent_id, set(valid_tools))
            self._agent_scopes[agent_id] = scope
            logger.info(f"Created scope for agent '{agent_id}' with {len(valid_tools)} tools")
            return scope

    def execute_tool(self, agent_id: str, tool_name: str, arguments: Dict) -> Any:
        """
        Execute a tool on behalf of an agent.

        Validates:
        1. Tool exists in registry
        2. Agent has scope with allowlist
        3. Tool is in agent's allowlist (case-sensitive)
        """
        with self._lock:
            if agent_id not in self._agent_scopes:
                raise RuntimeError(f"No tool scope for agent '{agent_id}'")

            scope = self._agent_scopes[agent_id]
            return scope.execute_tool(tool_name, arguments)

    def get_all_tools(self) -> List[str]:
        """Get all registered tool names."""
        with self._lock:
            return list(self._tools.keys())

    def clear(self) -> None:
        """Clear all tools and scopes (for testing)."""
        with self._lock:
            self._tools.clear()
            self._agent_scopes.clear()


class AgentScope:
    """
    Per-agent scoped tool access with allowlist filtering.

    Provides a view of only the tools this agent is allowed to use.
    """

    def __init__(self, registry: ToolRegistry, agent_id: str, allowed_tools: Set[str]):
        self._registry = registry
        self._agent_id = agent_id
        self._allowed_tools = allowed_tools

    def execute_tool(self, tool_name: str, arguments: Dict) -> Any:
        """Execute tool with allowlist validation."""
        # Case-sensitive matching (security requirement)
        if tool_name not in self._allowed_tools:
            raise PermissionError(
                f"Agent '{self._agent_id}' not authorized to use tool '{tool_name}'. "
                f"Allowed tools: {sorted(self._allowed_tools)}"
            )

        tool = self._registry._tools[tool_name]
        logger.debug(f"Agent '{self._agent_id}' executing tool '{tool_name}'")
        return tool.handler(**arguments)

    def get_available_tools(self) -> List[str]:
        """Get list of tools available to this agent."""
        return sorted(self._allowed_tools)

    def has_tool(self, tool_name: str) -> bool:
        """Check if agent has access to a specific tool."""
        return tool_name in self._allowed_tools


# Backward compatibility shim
class _ToolRegistryAlias(dict):
    """Backward-compatible dict shim for legacy code."""

    def __init__(self, registry: ToolRegistry):
        self._registry = registry
        import warnings
        warnings.warn(
            "Global _TOOL_REGISTRY is deprecated. Use ToolRegistry.create_scope() instead.",
            DeprecationWarning,
            stacklevel=2
        )

    def __getitem__(self, key):
        import warnings
        warnings.warn("Direct dict access deprecated", DeprecationWarning, stacklevel=2)
        return self._registry._tools[key].handler

    def __contains__(self, key):
        return key in self._registry._tools

    def keys(self):
        return self._registry.get_all_tools()


# Global instance (deprecated but maintained for backward compat)
_TOOL_REGISTRY = _ToolRegistryAlias(ToolRegistry())
```

#### Day 3-4: Agent Configuration Update

**File:** `src/gaia/agents/registry.py` (MODIFIED)

Add `allowed_tools` field to agent definitions and integrate with ToolRegistry.

**File:** `config/agents/*.yaml` (MODIFIED - 17 files)

Add `allowed_tools` list to each agent:

```yaml
agent:
  name: senior-developer
  role: Senior Software Engineer
  allowed_tools:
    - read_file
    - write_file
    - execute_python
    - run_tests
    - search_code
```

#### Day 5: Integration with PipelineEngine

**File:** `src/gaia/pipeline/engine.py` (MODIFIED)

```python
from gaia.tools.registry import ToolRegistry

class PipelineEngine:
    def __init__(self):
        self.tool_registry = ToolRegistry()
        # ... rest of init

    async def execute_phase(self, phase: str, state: PipelineState) -> PipelineState:
        agent = self.agent_registry.select_agent(phase)

        # Create scoped tool access for this agent
        scope = self.tool_registry.create_scope(
            agent_id=f"{phase}_{state.execution_id}",
            allowed_tools=agent.allowed_tools
        )

        # Pass scoped tool access to agent
        result = await agent.execute(state.artifacts, tool_scope=scope)
        # ... rest of phase execution
```

### Week 2: Testing & Validation

#### Day 6-8: Security Tests

**File:** `tests/tools/test_tool_scoping.py` (NEW)

```python
import pytest
from gaia.tools.registry import ToolRegistry, AgentScope


class TestToolScopingSecurity:
    """Test tool scoping security guarantees."""

    @pytest.fixture
    def registry(self):
        """Fresh registry for each test."""
        registry = ToolRegistry()
        registry.clear()

        # Register test tools
        registry.register_tool('read_file', 'Read file', {}, lambda **kw: 'read')
        registry.register_tool('write_file', 'Write file', {}, lambda **kw: 'write')
        registry.register_tool('execute_python', 'Execute Python', {}, lambda **kw: 'exec')

        return registry

    def test_agent_cannot_access_unauthorized_tool(self, registry):
        """Agent blocked from tools not in allowlist."""
        scope = registry.create_scope('test-agent', ['read_file'])

        with pytest.raises(PermissionError) as exc_info:
            scope.execute_tool('write_file', {})

        assert 'not authorized' in str(exc_info.value)
        assert 'write_file' in str(exc_info.value)

    def test_case_sensitive_tool_matching(self, registry):
        """Tool name matching is case-sensitive (security requirement)."""
        scope = registry.create_scope('test-agent', ['read_file'])

        # Attempt bypass via case variation
        with pytest.raises(PermissionError):
            scope.execute_tool('READ_FILE', {})

        with pytest.raises(PermissionError):
            scope.execute_tool('Read_File', {})

    def test_multiple_agents_isolated(self, registry):
        """Multiple agents have isolated tool access."""
        agent1_scope = registry.create_scope('agent-1', ['read_file'])
        agent2_scope = registry.create_scope('agent-2', ['write_file'])

        # Agent 1 can read
        assert agent1_scope.has_tool('read_file')
        assert not agent1_scope.has_tool('write_file')

        # Agent 2 can write
        assert agent2_scope.has_tool('write_file')
        assert not agent2_scope.has_tool('read_file')

    def test_agent_with_all_tools(self, registry):
        """Supervisor agent with all tools."""
        scope = registry.create_scope('supervisor', ['read_file', 'write_file', 'execute_python'])

        assert len(scope.get_available_tools()) == 3
        assert scope.has_tool('read_file')
        assert scope.has_tool('write_file')
        assert scope.has_tool('execute_python')
```

#### Day 9-10: Integration Tests

**File:** `tests/integration/test_tool_scoping_integration.py` (NEW)

Test end-to-end tool scoping with real agent definitions.

#### Day 11-12: Backward Compatibility Validation

Ensure existing code using `_TOOL_REGISTRY` dict still works with deprecation warnings.

#### Day 13-14: Documentation & Code Review

Update API documentation, add migration guide.

---

## Success Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| **Tool Isolation** | 100% | Agents cannot access unauthorized tools |
| **Case Sensitivity** | 100% | Case variation bypass attempts blocked |
| **Backward Compatibility** | 100% | Existing code works with deprecation warnings |
| **Test Coverage** | >= 50 tests | Security + integration tests |
| **Quality Score** | >= 0.90 | QualityScorer evaluation |

---

## Risk Mitigation

| Risk | Severity | Mitigation |
|------|----------|------------|
| Breaking existing agents | HIGH | Backward compat shim, deprecation warnings |
| Performance overhead | LOW | RLock is fast, agent scopes are lightweight |
| Tool name typos in YAML | MEDIUM | Validation at agent load time, warning logs |
| Case sensitivity confusion | LOW | Clear error messages, documentation |

---

## Files to Create/Modify

### New Files
- `src/gaia/tools/registry.py` (ToolRegistry + AgentScope)
- `tests/tools/test_tool_scoping.py` (Security tests)
- `tests/tools/__init__.py`

### Modified Files
- `src/gaia/agents/registry.py` (Integrate ToolRegistry)
- `src/gaia/agents/base.py` (Add allowed_tools parameter)
- `src/gaia/agents/configurable.py` (Load allowed_tools from YAML)
- `src/gaia/pipeline/engine.py` (Create scopes per phase)
- `config/agents/*.yaml` (17 files, add allowed_tools list)
- `src/gaia/__init__.py` (Export ToolRegistry)

---

## Git Commits Plan

```bash
# Commit 1: Core ToolRegistry implementation
git add src/gaia/tools/registry.py
git commit -m "feat: Add ToolRegistry with per-agent scoping (Phase 0)"

# Commit 2: Agent integration
git add src/gaia/agents/*.py config/agents/*.yaml
git commit -m "feat: Integrate ToolRegistry with agent system"

# Commit 3: Pipeline integration
git add src/gaia/pipeline/engine.py
git commit -m "feat: Create tool scopes in PipelineEngine"

# Commit 4: Security tests
git add tests/tools/test_tool_scoping.py
git commit -m "test: Add tool scoping security tests (25 tests)"

# Commit 5: Integration tests
git add tests/integration/test_tool_scoping_integration.py
git commit -m "test: Add tool scoping integration tests"
```

---

## Post-Implementation Validation

```bash
# Run all tool scoping tests
pytest tests/tools/test_tool_scoping.py -v
pytest tests/integration/test_tool_scoping_integration.py -v

# Quality check
python -m gaia.quality.validate src/gaia/tools/registry.py

# Verify no regressions
pytest tests/pipeline/ tests/quality/ tests/agents/ -v
```

---

## Next Steps After Phase 0

1. **Phase 1 (8 weeks):** Nexus State Unification
   - ChronicleDigest for token-efficient context
   - Workspace metadata index
   - Agent event logging integration

2. **Phase 2 (6 weeks):** Supervisor Agent + Quality Enhancement
   - LLM-based quality gate agent
   - Mandatory workspace sandboxing

3. **Phase 3 (12 weeks):** Agent-as-Data Refactoring
   - Reduce Agent class from 3000 to <500 lines
   - Service layer decoupling

---

**Prepared By:** Dr. Sarah Kim, Technical Product Strategist
**Date:** 2026-04-05
**Status:** READY FOR IMPLEMENTATION
