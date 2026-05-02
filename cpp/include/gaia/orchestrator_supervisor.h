// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT
//
// Supervisor hierarchy for the GAIA C++ pipeline orchestration system.
// Ported from Python: src/gaia/orchestration/supervisors/supervisor.py
//              src/gaia/orchestration/supervisors/git.py

#pragma once

#include <atomic>
#include <chrono>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "gaia/orchestrator_engine.h"
#include "gaia/orchestrator_git.h"
#include "gaia/orchestrator_types.h"

namespace gaia {

// ---------------------------------------------------------------------------
// ObjectiveOutcomeDetail — detailed outcome record per objective execution
// ---------------------------------------------------------------------------
/// NOTE: ObjectiveOutcome (without "Detail") is an enum in orchestrator_types.h.
/// This struct holds the detailed per-execution outcome data.

struct ObjectiveOutcomeDetail {
    std::string objectiveId;
    bool success = false;
    std::string errorMessage;
    double duration = 0.0;        // seconds
    std::string timestamp;
    double qualityScore = 0.0;

    ObjectiveOutcomeDetail()
        : timestamp(getCurrentTimestamp()) {}

    json toJson() const;
    static ObjectiveOutcomeDetail fromJson(const json& j);
};

// ---------------------------------------------------------------------------
// CircuitBreaker — state machine for fault tolerance
// ---------------------------------------------------------------------------

enum class CircuitState {
    Closed,
    Open,
    HalfOpen
};

inline std::string circuitStateToString(CircuitState s) {
    switch (s) {
        case CircuitState::Closed:   return "closed";
        case CircuitState::Open:     return "open";
        case CircuitState::HalfOpen: return "half_open";
    }
    return "unknown";
}

/// Thread-safe circuit breaker implementing the resilience pattern.
///
/// State transitions:
///   Closed   -> Open       when failureCount >= failureThreshold
///   Open     -> HalfOpen   after recoveryTimeoutSec elapses
///   HalfOpen -> Closed     on success
///   HalfOpen -> Open       on failure (or after halfOpenMaxAttempts failures)
class CircuitBreaker {
public:
    CircuitBreaker();
    explicit CircuitBreaker(int failureThreshold,
                             int recoveryTimeoutSec = 60,
                             int halfOpenMaxAttempts = 3);

    /// Check whether an execution is allowed.
    bool canExecute();

    /// Record a successful execution.
    void recordSuccess();

    /// Record a failed execution.
    void recordFailure();

    /// Current circuit state.
    CircuitState state() const;

    /// Reset the circuit breaker to Closed state.
    void reset();

    /// Current failure count (0 in Closed, accumulative in HalfOpen).
    int failureCount() const;

    // ---- Configuration ----

    void setFailureThreshold(int threshold);
    void setRecoveryTimeoutSec(int seconds);
    void setHalfOpenMaxAttempts(int attempts);

    int failureThreshold() const { return failureThreshold_; }
    int recoveryTimeoutSec() const { return recoveryTimeoutSec_; }
    int halfOpenMaxAttempts() const { return halfOpenMaxAttempts_; }

    // ---- JSON ----

    json toJson() const;
    static CircuitBreaker fromJson(const json& j);

private:
    /// Internal: transition from Open to HalfOpen if timeout has elapsed.
    void checkOpenTimeout();

    mutable std::shared_ptr<std::mutex> mutex_;
    CircuitState state_ = CircuitState::Closed;
    int failureThreshold_ = 5;
    int recoveryTimeoutSec_ = 60;
    int halfOpenMaxAttempts_ = 3;
    int failureCount_ = 0;
    int halfOpenAttemptCount_ = 0;
    std::chrono::steady_clock::time_point lastFailureTime_;
};

// ---------------------------------------------------------------------------
// HealthScore — composite health metric
// ---------------------------------------------------------------------------

/// Composite health score for a project or objective set.
/// overall = (successRate * 0.4) + ((qualityTrend + 1) / 2 * 0.3) + (dependencyHealth * 0.3)
struct HealthScore {
    double successRate = 1.0;         // 0.0 to 1.0
    double qualityTrend = 0.0;        // -1.0 to +1.0
    double dependencyHealth = 1.0;    // 0.0 to 1.0
    double overall = 1.0;             // computed by compute()

    /// Compute the overall score from component values.
    void compute();

    /// Status label based on overall score.
    /// "healthy" >= 0.8, "degraded" >= 0.5, "critical" < 0.5
    std::string statusLabel() const;

    json toJson() const;
    static HealthScore fromJson(const json& j);
};

// ---------------------------------------------------------------------------
// SupervisorConfig — 10 configurable parameters
// ---------------------------------------------------------------------------

struct SupervisorConfig {
    int healthCheckIntervalSec = 30;
    double minHealthScore = 0.5;
    int maxConsecutiveFailures = 3;
    bool autoRemediate = false;
    int maxRemediationAttempts = 3;
    int circuitBreakerThreshold = 5;
    int circuitBreakerTimeoutSec = 60;
    bool enableHealthMonitoring = true;
    bool enableCircuitBreaker = true;
    int qualityTrendWindow = 10;

    /// Validate configuration. Throws std::invalid_argument on invalid values.
    void validate() const;

    json toJson() const;
    static SupervisorConfig fromJson(const json& j);
};

// ---------------------------------------------------------------------------
// SupervisorState — runtime tracking
// ---------------------------------------------------------------------------

struct SupervisorState {
    std::vector<ObjectiveOutcomeDetail> outcomes;
    int consecutiveFailures = 0;
    std::unordered_map<std::string, int> perObjectiveFailures;
    bool circuitBreakerTripped = false;
    HealthScore lastHealthScore;
    int remediationAttempts = 0;

    /// Record an outcome and update internal counters.
    void recordOutcome(const ObjectiveOutcomeDetail& outcome);

    json toJson() const;
    static SupervisorState fromJson(const json& j);
};

// ---------------------------------------------------------------------------
// GitOperation — audit log entry for git supervisor
// ---------------------------------------------------------------------------

struct GitOperation {
    std::string operationName;
    bool success = false;
    double duration = 0.0;
    std::string timestamp;
    std::string errorMessage;

    GitOperation()
        : timestamp(getCurrentTimestamp()) {}

    json toJson() const;
    static GitOperation fromJson(const json& j);
};

// ---------------------------------------------------------------------------
// ProjectSupervisor — evaluates level results and manages project health
// ---------------------------------------------------------------------------

class ProjectSupervisor {
public:
    explicit ProjectSupervisor(const SupervisorConfig& config = {});

    /// Evaluate a level result and return a verdict string.
    /// Returns: "continue", "abort", "remediate", or "pause"
    std::string evaluateLevel(const LevelResult& result,
                              const ProjectObjectives& project);

    /// Compute the current health score for the project.
    HealthScore computeHealthScore(const ProjectObjectives& project);

    /// Check whether a phase (sequence of level results) is complete.
    /// A phase is complete when all levels have been processed.
    bool checkPhaseCompletion(const std::vector<LevelResult>& levelResults);

    /// Determine whether remediation should be attempted for an objective.
    bool shouldRemediate(const std::string& objectiveId);

    /// Get the current consecutive failure count.
    int getConsecutiveFailures() const;

    /// Record an outcome manually.
    void recordOutcome(const ObjectiveOutcomeDetail& outcome);

    /// Reset the supervisor state.
    void reset();

    // ---- Configuration ----

    const SupervisorConfig& config() const { return config_; }
    void setConfig(const SupervisorConfig& config);

    // ---- State ----

    const SupervisorState& state() const { return state_; }
    SupervisorState& mutableState() { return state_; }

private:
    /// Compute quality trend from recent outcomes.
    double computeQualityTrend() const;

    SupervisorConfig config_;
    SupervisorState state_;
    mutable std::mutex mutex_;
};

// ---------------------------------------------------------------------------
// GitSupervisor — wraps GitWorker with circuit breaker protection
// ---------------------------------------------------------------------------

class GitSupervisor {
public:
    explicit GitSupervisor(GitWorker& gitWorker,
                           const SupervisorConfig& config = {});

    // ---- Worktree lifecycle (wrapped with circuit breaker) ----

    std::optional<std::string> createWorktree(const std::string& objectiveId,
                                               const std::string& title);
    bool cleanupWorktree(const std::string& objectiveId);

    // ---- Rollback ----

    bool rollbackBranch(const std::string& branch);

    // ---- Conflict detection ----

    std::vector<std::string> detectChangedFiles(
        const std::string& branch,
        const std::string& baseBranch = "main");

    // ---- State access ----

    const CircuitBreaker& circuitBreaker() const { return *circuitBreaker_; }
    CircuitBreaker& mutableCircuitBreaker() { return *circuitBreaker_; }
    const std::vector<GitOperation>& operationLog() const { return operationLog_; }
    const SupervisorConfig& config() const { return config_; }

    // ---- Internal ----

    void recordOperation(const GitOperation& operation);

private:
    GitWorker& gitWorker_;
    SupervisorConfig config_;
    std::unique_ptr<CircuitBreaker> circuitBreaker_;
    std::vector<GitOperation> operationLog_;
    mutable std::mutex mutex_;
};

} // namespace gaia
