// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT
//
// Orchestrator Engine for the GAIA C++ pipeline orchestration system.
// Ported from Python: src/gaia/orchestration/engine.py
//
// Phase 2: Synchronous sequential dispatch loop.
// Phase 3: Parallel execution, hooks, git worktrees, supervisor.

#pragma once

#include <functional>
#include <optional>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "gaia/orchestrator_types.h"

namespace gaia {

// ---------------------------------------------------------------------------
// Constants (mirrors Python engine.py defaults)
// ---------------------------------------------------------------------------

inline constexpr const char* ORCHESTRATOR_DEFAULT_OBJECTIVES_PATH = ".gaia/objectives.yaml";
inline constexpr int         ORCHESTRATOR_DEFAULT_MAX_CYCLES      = 100;
inline constexpr double      ORCHESTRATOR_DEFAULT_QUALITY_THRESHOLD = 0.90;

// ---------------------------------------------------------------------------
// Verdict enum (mirrors Python supervisor.py Verdict)
// ---------------------------------------------------------------------------

enum class Verdict {
    Continue,
    Abort,
    Pause,
    Remediate
};

std::string verdictToString(Verdict v);
Verdict stringToVerdict(const std::string& s);

// ---------------------------------------------------------------------------
// ExecutionResult
// ---------------------------------------------------------------------------

/// Result of executing a single objective.
/// Mirrors Python adapters.py ExecutionResult dataclass.
struct ExecutionResult {
    bool success = false;
    std::string objectiveId;
    std::vector<Artifact> artifacts;
    std::optional<double> qualityScore;
    std::optional<std::string> errorMessage;

    json toJson() const;
    static ExecutionResult fromJson(const json& j);
};

// ---------------------------------------------------------------------------
// ObjectiveExecutor callback
// ---------------------------------------------------------------------------

/// Callback signature for executing a single objective.
/// Phase 2: synchronous. Phase 3: may become std::future<ExecutionResult>.
/// The callback receives a mutable reference to the Objective so it can
/// update status, artifacts, and error messages in place.
using ObjectiveExecutor = std::function<ExecutionResult(Objective&)>;

// ---------------------------------------------------------------------------
// LogCallback
// ---------------------------------------------------------------------------

/// Optional logging callback. If not set, log messages are discarded.
using LogCallback = std::function<void(const std::string& message)>;

// ---------------------------------------------------------------------------
// OrchestratorConfig
// ---------------------------------------------------------------------------

/// Configuration for OrchestratorEngine.
/// Mirrors Python engine.py OrchestratorConfig dataclass.
struct OrchestratorConfig {
    std::string objectivesPath = ORCHESTRATOR_DEFAULT_OBJECTIVES_PATH;
    bool autoCommit = false;              // CRITICAL: default to False
    bool dryRun = false;
    bool enableEvaluation = false;
    int maxCycleIterations = ORCHESTRATOR_DEFAULT_MAX_CYCLES;
    bool enableNexus = true;
    bool enableSupervisor = false;
    bool enableGitSupervisor = false;
    bool enableParallelExecution = false; // Phase 3
    int maxParallelObjectives = 10;       // Phase 3
    bool serializeHooks = true;           // Phase 3
    bool enableRollback = true;           // Phase 3
    double qualityThreshold = ORCHESTRATOR_DEFAULT_QUALITY_THRESHOLD;

    /// Validate configuration. Throws std::invalid_argument on invalid values.
    void validate() const;

    /// Construct from JSON. Missing fields retain defaults.
    static OrchestratorConfig fromJson(const json& j);

    /// Serialize all fields to JSON.
    json toJson() const;
};

// ---------------------------------------------------------------------------
// CycleRecord
// ---------------------------------------------------------------------------

struct CycleRecord {
    int cycle = 0;
    std::string objectiveId;
    bool success = false;

    json toJson() const;
    static CycleRecord fromJson(const json& j);
};

// ---------------------------------------------------------------------------
// OrchestratorState
// ---------------------------------------------------------------------------

/// Runtime state of the orchestrator.
/// Mirrors Python engine.py OrchestratorState dataclass.
struct OrchestratorState {
    bool paused = false;
    int cycleCount = 0;
    int objectivesProcessed = 0;
    int objectivesFailed = 0;
    std::vector<CycleRecord> executionHistory;
    std::unordered_map<std::string, std::string> objectiveBranches;

    /// Record a completed dispatch-evaluate cycle.
    void recordCycle(const std::string& objectiveId, bool success);

    /// Serialize to dictionary (mirrors Python to_dict()).
    json toJson() const;

    /// Restore from JSON.
    static OrchestratorState fromJson(const json& j);
};

// ---------------------------------------------------------------------------
// EvaluationResult
// ---------------------------------------------------------------------------

/// Result of rule-based objective evaluation.
/// Mirrors Python engine.py ProjectOrchestrator.evaluate() return dict.
struct EvaluationResult {
    std::string verdict;   // "PASS", "FAIL", "REVIEW"
    std::string reason;
    std::string objectiveId;
    std::optional<double> qualityScore;

    json toJson() const;
};

// ---------------------------------------------------------------------------
// OrchestratorEngine
// ---------------------------------------------------------------------------

/// Core orchestrator engine.
///
/// Manages objective-driven project execution with:
///   - Dependency-aware scheduling via DependencyGraph
///   - Sequential dispatch loop (Phase 2)
///   - Callback-based objective execution
///   - Rule-based evaluation
///   - Pause/resume control
///   - Failure propagation to dependent objectives
///
/// Example:
///     OrchestratorEngine engine;
///     engine.setExecutor([](Objective& obj) -> ExecutionResult {
///         // Execute the objective...
///         return {true, obj.objectiveId};
///     });
///     engine.loadObjectives("project.json");
///     const auto& state = engine.run();
class OrchestratorEngine {
public:
    explicit OrchestratorEngine(const OrchestratorConfig& config = {});
    ~OrchestratorEngine() = default;

    // Non-copyable, non-movable (complex stateful object)
    OrchestratorEngine(const OrchestratorEngine&) = delete;
    OrchestratorEngine& operator=(const OrchestratorEngine&) = delete;
    OrchestratorEngine(OrchestratorEngine&&) = delete;
    OrchestratorEngine& operator=(OrchestratorEngine&&) = delete;

    // ---- Configuration ----

    const OrchestratorConfig& config() const { return config_; }
    void setConfig(const OrchestratorConfig& config);

    // ---- State access ----

    const OrchestratorState& state() const { return state_; }
    OrchestratorState& mutableState() { return state_; }

    // ---- Project access ----

    const std::optional<ProjectObjectives>& project() const { return project_; }

    // ---- Dependency graph access ----

    const DependencyGraph& dependencyGraph() const { return depGraph_; }

    // ---- Callback injection ----

    /// Set the objective execution callback.
    /// Required before calling run(). If not set, all executions fail.
    void setExecutor(ObjectiveExecutor executor);

    /// Set the logging callback. Optional.
    void setLogCallback(LogCallback callback);

    // ---- Lifecycle ----

    /// Load objectives from a JSON file.
    /// If path is empty, uses config_.objectivesPath.
    /// Phase 2: JSON format only. YAML support is Phase 3.
    void loadObjectives(const std::string& path = "");

    /// Run the dispatch-evaluate-update loop synchronously.
    /// Blocks until all objectives are completed/blocked or max cycles reached.
    /// Returns reference to final OrchestratorState.
    const OrchestratorState& run();

    // ---- Control ----

    /// Pause the orchestrator with an optional reason.
    void pause(const std::string& reason = "");

    /// Resume the orchestrator.
    void resume();

    // ---- Evaluation ----

    /// Rule-based evaluation of an execution result.
    /// Mirrors Python ProjectOrchestrator.evaluate().
    EvaluationResult evaluate(const ExecutionResult& result,
                              const Objective& objective) const;

    /// Safely transition an objective to a terminal state.
    /// Uses the required two-step pattern: QUEUED -> IN_PROGRESS -> target.
    /// Exposed publicly for use by adapters and test code.
    static void applyStatusTransition(Objective& objective, ObjectiveStatus target);

private:
    // ---- Internal helpers ----

    /// Find the highest-priority ready objective.
    /// Returns nullptr if none are ready.
    Objective* findNextReadyObjective();

    /// Execute a single objective through the injected executor.
    ExecutionResult executeObjective(Objective& objective);

    /// Mark objectives as BLOCKED if any dependency failed.
    void propagateFailuresToDependents(
        const std::vector<std::vector<std::string>>& remainingLevels,
        const std::unordered_set<std::string>& failedIds);

    /// Save objectives to file (respects dryRun mode).
    void saveObjectives();

    /// Log a message through the injected callback.
    void log(const std::string& message) const;

    // ---- State ----

    OrchestratorConfig config_;
    OrchestratorState state_;
    std::optional<ProjectObjectives> project_;
    DependencyGraph depGraph_;
    ObjectiveExecutor executor_;
    LogCallback logCallback_;
};

} // namespace gaia
