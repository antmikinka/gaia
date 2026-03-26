# GAIA Complete System Architecture

## Executive Summary

This document provides a comprehensive understanding of the GAIA (Generalized Agent Intelligence Architecture) pipeline system, including:
1. Tool injection mechanism
2. Multi-agent orchestration
3. Inter-agent communication
4. Production readiness status
5. Implementation roadmap

---

## Part 1: Tool Injection Mechanism

### 1.1 The Problem

In a multi-agent system where agents are configured via YAML files, we must ensure:
- Each agent can ONLY use tools specified in its YAML configuration
- The LLM must know which tools are available (via system prompt)
- Tool execution must be validated against the allowlist
- Production security requires strict tool isolation

### 1.2 Complete Flow: YAML → System Prompt → Tool Execution

```
┌─────────────────────────────────────────────────────────────────┐
│ STEP 1: YAML Configuration (config/agents/senior-developer.yaml)│
└─────────────────────────────────────────────────────────────────┘
  agent:
    id: senior-developer
    tools: [file_read, file_write, bash_execute, git_operations]
    capabilities: [full-stack-development, api-design]

                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 2: AgentRegistry._load_agent()                             │
└─────────────────────────────────────────────────────────────────┘
  - Parses YAML file
  - Creates AgentDefinition(tools=[...])
  - Stores in self._agents[agent_id]

                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 3: PipelineEngine._execute_phase()                         │
└─────────────────────────────────────────────────────────────────┘
  - Calls registry.select_agent(task, phase, state)
  - Gets agent_id: "senior-developer"

                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 4: LoopManager._execute_agent()                            │
└─────────────────────────────────────────────────────────────────┘
  - Gets AgentDefinition from registry
  - Creates ConfigurableAgent(definition=agent_def)
  - Calls agent.initialize()

                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 5: ConfigurableAgent.initialize()                          │
└─────────────────────────────────────────────────────────────────┘
  - _register_tools_from_yaml() → loads tool modules
  - rebuild_system_prompt() → injects tools into prompt

                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 6: rebuild_system_prompt()                                 │
└─────────────────────────────────────────────────────────────────┘
  1. Get base prompt: _get_system_prompt()
  2. Get tools: _format_tools_for_prompt()
     → FILTERS to YAML allowlist ONLY
  3. Append: "==== AVAILABLE TOOLS ====\n-tool1...\n-tool2..."
  4. Append: "==== RESPONSE FORMAT ====\n{tool, tool_args}"

                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 7: Agent Execution - LLM receives prompt                   │
└─────────────────────────────────────────────────────────────────┘
  System Prompt:
  "You are Senior Developer...
   ==== AVAILABLE TOOLS ====
   - file_read(path: str): Read a file
   - file_write(path: str, content: str): Write to file
   - bash_execute(command: str): Run shell command

   ==== RESPONSE FORMAT ====
   Respond with JSON: {tool: 'tool_name', tool_args: {...}}"

   User: "Create a new Python module"

   LLM Response: {"tool": "file_write", "tool_args": {...}}

                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 8: ConfigurableAgent._execute_tool()                       │
└─────────────────────────────────────────────────────────────────┘
  1. VALIDATE: Is "file_write" in definition.tools?
     → YES: Proceed
     → NO: Return error {"status": "error", "security_violation": true}
  2. Call super()._execute_tool()
  3. Return result

                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 9: Result returned to LoopManager                          │
└─────────────────────────────────────────────────────────────────┘
  {
    "success": true,
    "artifact": "...",
    "agent_id": "senior-developer"
  }
```

### 1.3 Security Guarantees

| Guarantee | Implementation |
|-----------|----------------|
| Prompt Isolation | `_format_tools_for_prompt()` filters by allowlist |
| Execution Validation | `_execute_tool()` checks `tool ∈ definition.tools` |
| MCP Resolution | `_resolve_tool_name()` only resolves within allowlist |
| Audit Logging | Security violations logged with full context |

---

## Part 2: Multi-Agent Orchestration

### 2.1 Architecture Pattern: Centralized Orchestration

```
┌────────────────────────────────────────────────────────────────┐
│                     PipelineEngine                              │
│                  (Central Orchestrator)                         │
└────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ PLANNING      │    │ DEVELOPMENT   │    │ QUALITY       │
│ Phase         │    │ Phase         │    │ Phase         │
│               │    │               │    │               │
│ select_agent()│    │ select_agent()│    │ QualityScorer │
│ create_loop() │    │ create_loop() │    │ evaluate()    │
│               │    │               │    │               │
└───────┬───────┘    └───────┬───────┘    └───────┬───────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ DECISION Phase │
                    │                │
                    │ DecisionEngine │
                    │ - Evaluate     │
                    │ - Decide       │
                    └────────────────┘
```

### 2.2 Phase Execution Flow

| Phase | Agent Selection | Agent Execution | Output |
|-------|-----------------|-----------------|--------|
| PLANNING | `select_agent(keywords=["plan", "architect"], phases=["PLANNING"])` | `ConfigurableAgent.execute({goal, phase, artifacts})` | Plan document → state |
| DEVELOPMENT | `select_agent(capabilities=["full-stack-development"], phases=["DEVELOPMENT"])` | `ConfigurableAgent.execute({goal, phase, artifacts, defects})` | Code artifacts → state |
| QUALITY | N/A (uses QualityScorer) | `QualityScorer.evaluate({artifacts, template})` | Score + defects → state |
| DECISION | N/A (uses DecisionEngine) | `DecisionEngine.decide({score, threshold, iteration})` | Decision (CONTINUE/LOOP_BACK/etc.) |

### 2.3 Inter-Agent Communication: Shared State Pattern

Agents do NOT communicate directly. All communication flows through `PipelineState`:

```
┌──────────────────────────────────────────────────────────────────┐
│ PipelineState (Shared State Layer)                               │
│                                                                  │
│  artifacts: {                                                     │
│    "planning": {...},                                            │
│    "development": {...},                                         │
│    "quality_report": {...}                                       │
│  }                                                               │
│                                                                  │
│  defects: [                                                       │
│    {"type": "missing_tests", "phase": "DEVELOPMENT", ...},       │
│    {"type": "security_issue", "phase": "QUALITY", ...}           │
│  ]                                                               │
│                                                                  │
│  quality_score: 0.85                                             │
│  iteration: 3                                                    │
│  current_phase: "DECISION"                                       │
└──────────────────────────────────────────────────────────────────┘
                              ▲
                              │
                              │ All agents read/write here
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
  Planning Agent       Development Agent      Quality Agent
  - Reads: user_goal   - Reads: planning    - Reads: all artifacts
  - Writes: plan         artifacts            - Writes: score, defects
```

### 2.4 Loop-Back Mechanism

```
DECISION Phase evaluates:
  if quality_score >= threshold:
    → CONTINUE to next phase
  else:
    → LOOP_BACK to previous phase WITH DEFECTS

LoopManager._execute_loop():
  for iteration in range(max_iterations):
    for agent_id in agent_sequence:
      context = {
        "goal": user_goal,
        "phase": current_phase,
        "defects": loop_state.defects,  # ← Accumulated defects
        "artifacts": loop_state.artifacts,
      }
      result = agent.execute(context)

    quality = evaluate_quality(result)
    if quality >= threshold:
      break  # Exit loop - success
    # Otherwise, continue to next iteration with defects
```

---

## Part 3: Production Readiness Assessment

### 3.1 Component Status

| Component | Status | Completeness | Notes |
|-----------|--------|--------------|-------|
| **Tool Injection** | | | |
| ConfigurableAgent | ✅ | 100% | Tool isolation, allowlist validation |
| YAML Loading | ✅ | 100% | AgentRegistry._load_agent() |
| Prompt Filtering | ✅ | 100% | _format_tools_for_prompt() |
| Execution Validation | ✅ | 100% | _execute_tool() with security checks |
| **Orchestration** | | | |
| PipelineEngine | ✅ | 100% | Phase orchestration complete |
| LoopManager | ✅ | 95% | Agent execution complete, defect routing TODO |
| AgentRegistry | ✅ | 100% | Capability-based routing |
| PipelineState | ✅ | 100% | Thread-safe state machine |
| **Quality System** | | | |
| QualityScorer | ✅ | 100% | 27 validators across 6 dimensions |
| DecisionEngine | ✅ | 100% | 5 decision types |
| **Missing Components** | | | |
| DefectRouter | ⏳ TODO | 0% | Route defects to appropriate phases |
| PhaseContract | ⏳ TODO | 0% | Explicit input/output contracts |
| DefectRemediationTracker | ⏳ TODO | 0% | Track defect fix progress |

### 3.2 Overall Assessment: 70% Production-Ready

**Strengths:**
- ✅ Tool injection with security isolation
- ✅ Agent orchestration and phase management
- ✅ Quality scoring and decision engine
- ✅ Hook system for extensibility
- ✅ State machine with thread safety

**Gaps to Close:**
- ⏳ Defect routing not implemented
- ⏳ Phase handoff contracts not explicit
- ⏳ Defect remediation tracking missing

---

## Part 4: Recursive Iterative Implementation Strategy

### 4.1 The Pipeline Builds Itself

The GAIA pipeline can use ITS OWN mechanism to implement missing features:

```
Iteration N: Implement DefectRouter
────────────────────────────────────
PLANNING:
  Agent: planning-analysis-strategist
  Task: "Design DefectRouter component"
  Output: Design document with routing rules

DEVELOPMENT:
  Agent: senior-developer
  Task: "Implement DefectRouter class"
  Output: defect_router.py

QUALITY:
  Validators: Code quality, tests, security
  Score: 0.82 (below 0.90 threshold)

DECISION:
  Decision: LOOP_BACK to DEVELOPMENT
  Defects: ["missing_unit_tests", "incomplete_error_handling"]

Iteration N+1: Fix Defects
────────────────────────────────────
DEVELOPMENT (loop back):
  Agent: senior-developer (with defects context)
  Task: "Address defects: missing tests, error handling"
  Output: Updated defect_router.py + tests

QUALITY:
  Score: 0.94 (above threshold)

DECISION:
  Decision: CONTINUE to next feature
```

### 4.2 Feature Implementation Priority

| Priority | Feature | Description | Estimated Iterations |
|----------|---------|-------------|---------------------|
| 1 | DefectRouter | Route defects to appropriate phases | 2-3 |
| 2 | PhaseContract | Define explicit phase I/O contracts | 2 |
| 3 | DefectRemediationTracker | Track defect status | 2 |
| 4 | ToolInjectionEnforcer | Ensure ConfigurableAgent always used | 1 |
| 5 | AuditLogger | Comprehensive execution logging | 2 |

### 4.3 Quality Thresholds by Phase

| Phase | Quality Dimensions | Threshold |
|-------|-------------------|-----------|
| PLANNING | Requirements completeness, feasibility | 0.85 |
| DEVELOPMENT | Code quality, security, tests | 0.90 |
| QUALITY | Validator coverage, accuracy | 0.95 |
| DECISION | Logic correctness, edge cases | 0.90 |

---

## Part 5: Implementation Checklist

### Immediate (Before Next Sprint)
- [ ] Implement DefectRouter
- [ ] Add defect status tracking (OPEN, IN_PROGRESS, RESOLVED, VERIFIED)
- [ ] Update LoopManager to route defects to phase context

### Short-Term (This Sprint)
- [ ] Define PhaseContract for each phase
- [ ] Implement PhaseHandoff validator
- [ ] Add comprehensive audit logging

### Medium-Term (Next Sprint)
- [ ] Implement DefectRemediationTracker
- [ ] Add defect analytics dashboard
- [ ] Performance optimization for concurrent loops

---

## Appendix: Key Code References

### ConfigurableAgent - Tool Isolation
```python
# File: gaia/agents/configurable.py

def _format_tools_for_prompt(self) -> str:
    """Filter to YAML allowlist ONLY - PRODUCTION SECURITY"""
    allowed_tools = set(self.definition.tools or [])
    tool_descriptions = []

    for name, tool_info in _TOOL_REGISTRY.items():
        if name not in allowed_tools:
            continue  # Skip unauthorized tools
        # ... format description

    return "\n".join(tool_descriptions)

def _execute_tool(self, tool_name: str, tool_args: Dict) -> Any:
    """Validate tool against allowlist - PRODUCTION SECURITY"""
    allowed_tools = set(self.definition.tools or [])

    if tool_name not in allowed_tools:
        return {
            "status": "error",
            "error": f"Tool '{tool_name}' not authorized",
            "security_violation": True,
        }

    return super()._execute_tool(tool_name, tool_args)
```

### LoopManager - Agent Execution
```python
# File: gaia/pipeline/loop_manager.py

def _execute_agent(self, agent_id: str, loop_state: LoopState) -> Dict:
    """Execute agent with proper tool injection"""
    # Get agent definition from registry
    agent_def = self._agent_registry.get_agent(agent_id)

    # Create configurable agent
    agent = ConfigurableAgent(definition=agent_def)

    # Initialize (registers tools, builds prompt)
    await agent.initialize()

    # Prepare context with defects
    context = {
        "goal": "...",
        "phase": "...",
        "defects": loop_state.defects,
        "artifacts": loop_state.artifacts,
    }

    # Execute
    result = await agent.execute(context)
    return result
```

---

*Document generated: 2026-03-23*
*GAIA Pipeline Version: 1.0.0*
