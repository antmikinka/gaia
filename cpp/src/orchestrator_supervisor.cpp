// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT
//
// Supervisor hierarchy implementation.
// Ported from Python: src/gaia/orchestration/supervisors/supervisor.py
//              src/gaia/orchestration/supervisors/git.py

#include "gaia/orchestrator_supervisor.h"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <stdexcept>

namespace gaia {

// ============================================================================
// ObjectiveOutcomeDetail
// ============================================================================

json ObjectiveOutcomeDetail::toJson() const {
    json j;
    j["objective_id"] = objectiveId;
    j["success"] = success;
    j["error_message"] = errorMessage;
    j["duration"] = duration;
    j["timestamp"] = timestamp;
    j["quality_score"] = qualityScore;
    return j;
}

ObjectiveOutcomeDetail ObjectiveOutcomeDetail::fromJson(const json& j) {
    ObjectiveOutcomeDetail o;
    o.objectiveId = j.value("objective_id", std::string{});
    o.success = j.value("success", false);
    o.errorMessage = j.value("error_message", std::string{});
    o.duration = j.value("duration", 0.0);
    o.timestamp = j.value("timestamp", getCurrentTimestamp());
    o.qualityScore = j.value("quality_score", 0.0);
    return o;
}

// ============================================================================
// CircuitBreaker
// ============================================================================

CircuitBreaker::CircuitBreaker()
    : mutex_(std::make_shared<std::mutex>()) {}

CircuitBreaker::CircuitBreaker(int failureThreshold,
                                int recoveryTimeoutSec,
                                int halfOpenMaxAttempts)
    : mutex_(std::make_shared<std::mutex>()),
      failureThreshold_(failureThreshold),
      recoveryTimeoutSec_(recoveryTimeoutSec),
      halfOpenMaxAttempts_(halfOpenMaxAttempts) {
}

bool CircuitBreaker::canExecute() {
    std::lock_guard<std::mutex> lock(*mutex_);
    checkOpenTimeout();

    switch (state_) {
        case CircuitState::Closed:
            return true;
        case CircuitState::Open:
            return false;
        case CircuitState::HalfOpen:
            return halfOpenAttemptCount_ < halfOpenMaxAttempts_;
    }
    return false;
}

void CircuitBreaker::recordSuccess() {
    std::lock_guard<std::mutex> lock(*mutex_);
    switch (state_) {
        case CircuitState::Closed:
            // Reset failure count on success in closed state
            failureCount_ = 0;
            break;
        case CircuitState::HalfOpen:
            // Success in half-open -> transition to closed
            state_ = CircuitState::Closed;
            failureCount_ = 0;
            halfOpenAttemptCount_ = 0;
            break;
        case CircuitState::Open:
            // Should not normally happen (canExecute blocks), but handle anyway
            break;
    }
}

void CircuitBreaker::recordFailure() {
    std::lock_guard<std::mutex> lock(*mutex_);
    lastFailureTime_ = std::chrono::steady_clock::now();

    switch (state_) {
        case CircuitState::Closed:
            ++failureCount_;
            if (failureCount_ >= failureThreshold_) {
                state_ = CircuitState::Open;
            }
            break;
        case CircuitState::HalfOpen:
            ++halfOpenAttemptCount_;
            // Any failure in half-open -> back to open
            state_ = CircuitState::Open;
            failureCount_ = 0;
            break;
        case CircuitState::Open:
            // Already open, just update failure time
            break;
    }
}

CircuitState CircuitBreaker::state() const {
    std::lock_guard<std::mutex> lock(*mutex_);
    // Don't auto-transition here — keep state() pure
    return state_;
}

void CircuitBreaker::reset() {
    std::lock_guard<std::mutex> lock(*mutex_);
    state_ = CircuitState::Closed;
    failureCount_ = 0;
    halfOpenAttemptCount_ = 0;
}

int CircuitBreaker::failureCount() const {
    std::lock_guard<std::mutex> lock(*mutex_);
    return failureCount_;
}

void CircuitBreaker::setFailureThreshold(int threshold) {
    std::lock_guard<std::mutex> lock(*mutex_);
    failureThreshold_ = threshold;
}

void CircuitBreaker::setRecoveryTimeoutSec(int seconds) {
    std::lock_guard<std::mutex> lock(*mutex_);
    recoveryTimeoutSec_ = seconds;
}

void CircuitBreaker::setHalfOpenMaxAttempts(int attempts) {
    std::lock_guard<std::mutex> lock(*mutex_);
    halfOpenMaxAttempts_ = attempts;
}

void CircuitBreaker::checkOpenTimeout() {
    // Must be called with mutex_ held
    if (state_ != CircuitState::Open) return;

    auto elapsed = std::chrono::steady_clock::now() - lastFailureTime_;
    auto timeout = std::chrono::seconds(recoveryTimeoutSec_);
    if (elapsed >= timeout) {
        state_ = CircuitState::HalfOpen;
        halfOpenAttemptCount_ = 0;
    }
}

json CircuitBreaker::toJson() const {
    std::lock_guard<std::mutex> lock(*mutex_);
    json j;
    j["state"] = circuitStateToString(state_);
    j["failure_count"] = failureCount_;
    j["failure_threshold"] = failureThreshold_;
    j["recovery_timeout_sec"] = recoveryTimeoutSec_;
    j["half_open_max_attempts"] = halfOpenMaxAttempts_;
    j["half_open_attempt_count"] = halfOpenAttemptCount_;
    return j;
}

CircuitBreaker CircuitBreaker::fromJson(const json& j) {
    CircuitBreaker cb;
    if (j.contains("failure_threshold")) {
        cb.failureThreshold_ = j["failure_threshold"].get<int>();
    }
    if (j.contains("recovery_timeout_sec")) {
        cb.recoveryTimeoutSec_ = j["recovery_timeout_sec"].get<int>();
    }
    if (j.contains("half_open_max_attempts")) {
        cb.halfOpenMaxAttempts_ = j["half_open_max_attempts"].get<int>();
    }
    // Restore failure count and state if serialized
    if (j.contains("failure_count")) {
        cb.failureCount_ = j["failure_count"].get<int>();
    }
    if (j.contains("state")) {
        std::string s = j["state"].get<std::string>();
        if (s == "open") {
            cb.state_ = CircuitState::Open;
            // lastFailureTime_ not serialized; set to now so recovery
            // timeout starts from deserialization time, not Unix epoch.
            cb.lastFailureTime_ = std::chrono::steady_clock::now();
        } else if (s == "half_open") {
            cb.state_ = CircuitState::HalfOpen;
            cb.halfOpenAttemptCount_ = 0;
            cb.lastFailureTime_ = std::chrono::steady_clock::now();
        } else {
            cb.state_ = CircuitState::Closed;
        }
    }
    return cb;
}

// ============================================================================
// HealthScore
// ============================================================================

void HealthScore::compute() {
    // Clamp component values
    successRate = std::max(0.0, std::min(1.0, successRate));
    qualityTrend = std::max(-1.0, std::min(1.0, qualityTrend));
    dependencyHealth = std::max(0.0, std::min(1.0, dependencyHealth));

    // Weighted formula
    overall = (successRate * 0.4) +
              ((qualityTrend + 1.0) / 2.0 * 0.3) +
              (dependencyHealth * 0.3);

    // Clamp overall
    overall = std::max(0.0, std::min(1.0, overall));
}

std::string HealthScore::statusLabel() const {
    if (overall >= 0.8) return "healthy";
    if (overall >= 0.5) return "degraded";
    return "critical";
}

json HealthScore::toJson() const {
    json j;
    j["success_rate"] = successRate;
    j["quality_trend"] = qualityTrend;
    j["dependency_health"] = dependencyHealth;
    j["overall"] = overall;
    j["status"] = statusLabel();
    return j;
}

HealthScore HealthScore::fromJson(const json& j) {
    HealthScore hs;
    hs.successRate = j.value("success_rate", 1.0);
    hs.qualityTrend = j.value("quality_trend", 0.0);
    hs.dependencyHealth = j.value("dependency_health", 1.0);
    hs.overall = j.value("overall", 1.0);
    return hs;
}

// ============================================================================
// SupervisorConfig
// ============================================================================

void SupervisorConfig::validate() const {
    if (healthCheckIntervalSec <= 0) {
        throw std::invalid_argument("healthCheckIntervalSec must be > 0");
    }
    if (minHealthScore < 0.0 || minHealthScore > 1.0) {
        throw std::invalid_argument("minHealthScore must be in [0.0, 1.0]");
    }
    if (maxConsecutiveFailures <= 0) {
        throw std::invalid_argument("maxConsecutiveFailures must be > 0");
    }
    if (maxRemediationAttempts <= 0) {
        throw std::invalid_argument("maxRemediationAttempts must be > 0");
    }
    if (circuitBreakerThreshold <= 0) {
        throw std::invalid_argument("circuitBreakerThreshold must be > 0");
    }
    if (circuitBreakerTimeoutSec <= 0) {
        throw std::invalid_argument("circuitBreakerTimeoutSec must be > 0");
    }
    if (qualityTrendWindow <= 0) {
        throw std::invalid_argument("qualityTrendWindow must be > 0");
    }
}

json SupervisorConfig::toJson() const {
    json j;
    j["health_check_interval_sec"] = healthCheckIntervalSec;
    j["min_health_score"] = minHealthScore;
    j["max_consecutive_failures"] = maxConsecutiveFailures;
    j["auto_remediate"] = autoRemediate;
    j["max_remediation_attempts"] = maxRemediationAttempts;
    j["circuit_breaker_threshold"] = circuitBreakerThreshold;
    j["circuit_breaker_timeout_sec"] = circuitBreakerTimeoutSec;
    j["enable_health_monitoring"] = enableHealthMonitoring;
    j["enable_circuit_breaker"] = enableCircuitBreaker;
    j["quality_trend_window"] = qualityTrendWindow;
    return j;
}

SupervisorConfig SupervisorConfig::fromJson(const json& j) {
    SupervisorConfig cfg;
    if (j.contains("health_check_interval_sec")) {
        cfg.healthCheckIntervalSec = j["health_check_interval_sec"].get<int>();
    }
    if (j.contains("min_health_score")) {
        cfg.minHealthScore = j["min_health_score"].get<double>();
    }
    if (j.contains("max_consecutive_failures")) {
        cfg.maxConsecutiveFailures = j["max_consecutive_failures"].get<int>();
    }
    if (j.contains("auto_remediate")) {
        cfg.autoRemediate = j["auto_remediate"].get<bool>();
    }
    if (j.contains("max_remediation_attempts")) {
        cfg.maxRemediationAttempts = j["max_remediation_attempts"].get<int>();
    }
    if (j.contains("circuit_breaker_threshold")) {
        cfg.circuitBreakerThreshold = j["circuit_breaker_threshold"].get<int>();
    }
    if (j.contains("circuit_breaker_timeout_sec")) {
        cfg.circuitBreakerTimeoutSec = j["circuit_breaker_timeout_sec"].get<int>();
    }
    if (j.contains("enable_health_monitoring")) {
        cfg.enableHealthMonitoring = j["enable_health_monitoring"].get<bool>();
    }
    if (j.contains("enable_circuit_breaker")) {
        cfg.enableCircuitBreaker = j["enable_circuit_breaker"].get<bool>();
    }
    if (j.contains("quality_trend_window")) {
        cfg.qualityTrendWindow = j["quality_trend_window"].get<int>();
    }
    cfg.validate();
    return cfg;
}

// ============================================================================
// SupervisorState
// ============================================================================

void SupervisorState::recordOutcome(const ObjectiveOutcomeDetail& outcome) {
    outcomes.push_back(outcome);

    if (outcome.success) {
        consecutiveFailures = 0;
    } else {
        ++consecutiveFailures;
        perObjectiveFailures[outcome.objectiveId]++;
    }
}

json SupervisorState::toJson() const {
    json j;
    json outcomesJson = json::array();
    for (const auto& o : outcomes) {
        outcomesJson.push_back(o.toJson());
    }
    j["outcomes"] = outcomesJson;
    j["consecutive_failures"] = consecutiveFailures;

    json perObjJson = json::object();
    for (const auto& [id, count] : perObjectiveFailures) {
        perObjJson[id] = count;
    }
    j["per_objective_failures"] = perObjJson;

    j["circuit_breaker_tripped"] = circuitBreakerTripped;
    j["last_health_score"] = lastHealthScore.toJson();
    j["remediation_attempts"] = remediationAttempts;
    return j;
}

SupervisorState SupervisorState::fromJson(const json& j) {
    SupervisorState s;
    s.outcomes.clear();
    if (j.contains("outcomes") && j["outcomes"].is_array()) {
        for (const auto& o : j["outcomes"]) {
            s.outcomes.push_back(ObjectiveOutcomeDetail::fromJson(o));
        }
    }
    s.consecutiveFailures = j.value("consecutive_failures", 0);
    s.perObjectiveFailures.clear();
    if (j.contains("per_objective_failures") && j["per_objective_failures"].is_object()) {
        for (const auto& [key, val] : j["per_objective_failures"].items()) {
            s.perObjectiveFailures[key] = val.get<int>();
        }
    }
    s.circuitBreakerTripped = j.value("circuit_breaker_tripped", false);
    if (j.contains("last_health_score")) {
        s.lastHealthScore = HealthScore::fromJson(j["last_health_score"]);
    }
    s.remediationAttempts = j.value("remediation_attempts", 0);
    return s;
}

// ============================================================================
// GitOperation
// ============================================================================

json GitOperation::toJson() const {
    json j;
    j["operation_name"] = operationName;
    j["success"] = success;
    j["duration"] = duration;
    j["timestamp"] = timestamp;
    j["error_message"] = errorMessage;
    return j;
}

GitOperation GitOperation::fromJson(const json& j) {
    GitOperation op;
    op.operationName = j.value("operation_name", std::string{});
    op.success = j.value("success", false);
    op.duration = j.value("duration", 0.0);
    op.timestamp = j.value("timestamp", getCurrentTimestamp());
    op.errorMessage = j.value("error_message", std::string{});
    return op;
}

// ============================================================================
// ProjectSupervisor
// ============================================================================

ProjectSupervisor::ProjectSupervisor(const SupervisorConfig& config)
    : config_(config) {
    config_.validate();
}

std::string ProjectSupervisor::evaluateLevel(const LevelResult& result,
                                              const ProjectObjectives& /*project*/) {
    std::lock_guard<std::mutex> lock(mutex_);

    // Record outcomes from level result
    for (const auto& [oid, outcome] : result.outcomes) {
        ObjectiveOutcomeDetail detail;
        detail.objectiveId = oid;
        detail.success = (outcome == ObjectiveOutcome::Success);
        if (!detail.success) {
            detail.errorMessage = objectiveOutcomeToString(outcome);
        }
        state_.recordOutcome(detail);
    }

    // Check circuit breaker
    if (config_.enableCircuitBreaker && state_.circuitBreakerTripped) {
        return "abort";
    }

    // All objectives failed -> abort
    if (result.failureCount > 0 && result.successCount == 0 && !result.objectiveIds.empty()) {
        // Update circuit breaker tripped status
        if (state_.consecutiveFailures >= config_.maxConsecutiveFailures) {
            state_.circuitBreakerTripped = true;
            if (config_.enableCircuitBreaker) {
                return "abort";
            }
        }
        return "abort";
    }

    // Some objectives failed -> remediate
    if (result.failureCount > 0) {
        return "remediate";
    }

    // Check if consecutive failures exceed threshold
    if (state_.consecutiveFailures >= config_.maxConsecutiveFailures) {
        state_.circuitBreakerTripped = true;
        if (config_.enableCircuitBreaker) {
            return "abort";
        }
    }

    // All passed -> continue
    return "continue";
}

HealthScore ProjectSupervisor::computeHealthScore(const ProjectObjectives& project) {
    std::lock_guard<std::mutex> lock(mutex_);

    HealthScore hs;

    // Success rate: completed / total objectives
    int total = static_cast<int>(project.objectives.size());
    if (total > 0) {
        int completed = 0;
        int blocked = 0;
        for (const auto& obj : project.objectives) {
            if (obj.status == ObjectiveStatus::Completed) {
                ++completed;
            } else if (obj.status == ObjectiveStatus::Blocked) {
                ++blocked;
            }
        }
        hs.successRate = static_cast<double>(completed) / static_cast<double>(total);

        // Dependency health: ratio of objectives with no blocking deps
        hs.dependencyHealth = 1.0 - (static_cast<double>(blocked) / static_cast<double>(total));
    }

    // Quality trend from recent outcomes
    hs.qualityTrend = computeQualityTrend();

    hs.compute();
    state_.lastHealthScore = hs;

    return hs;
}

bool ProjectSupervisor::checkPhaseCompletion(
    const std::vector<LevelResult>& levelResults) {
    // A phase is complete when all levels have been evaluated
    // Return true if any level has a terminal verdict (abort/pause/remediate)
    // or if all levels show "continue" (phase completed successfully)
    if (levelResults.empty()) return false;

    for (const auto& lr : levelResults) {
        if (lr.verdict == "abort" || lr.verdict == "pause" || lr.verdict == "remediate") {
            return true;
        }
    }

    // If last level has a continue verdict, phase is complete
    const auto& last = levelResults.back();
    return last.verdict == "continue";
}

bool ProjectSupervisor::shouldRemediate(const std::string& objectiveId) {
    std::lock_guard<std::mutex> lock(mutex_);

    if (!config_.autoRemediate) return false;
    if (state_.remediationAttempts >= config_.maxRemediationAttempts) return false;

    auto it = state_.perObjectiveFailures.find(objectiveId);
    if (it == state_.perObjectiveFailures.end()) return false;

    return it->second > 0;
}

int ProjectSupervisor::getConsecutiveFailures() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return state_.consecutiveFailures;
}

void ProjectSupervisor::recordOutcome(const ObjectiveOutcomeDetail& outcome) {
    std::lock_guard<std::mutex> lock(mutex_);
    state_.recordOutcome(outcome);
}

void ProjectSupervisor::reset() {
    std::lock_guard<std::mutex> lock(mutex_);
    state_ = SupervisorState{};
}

void ProjectSupervisor::setConfig(const SupervisorConfig& config) {
    config.validate();
    std::lock_guard<std::mutex> lock(mutex_);
    config_ = config;
}

double ProjectSupervisor::computeQualityTrend() const {
    // Must be called with mutex_ held
    if (state_.outcomes.empty()) return 0.0;

    // Use the most recent qualityTrendWindow outcomes
    int window = config_.qualityTrendWindow;
    int start = static_cast<int>(state_.outcomes.size()) > window
        ? static_cast<int>(state_.outcomes.size()) - window
        : 0;

    int successCount = 0;
    int totalInWindow = 0;
    double qualitySum = 0.0;

    for (int i = start; i < static_cast<int>(state_.outcomes.size()); ++i) {
        ++totalInWindow;
        if (state_.outcomes[static_cast<size_t>(i)].success) {
            ++successCount;
        }
        qualitySum += state_.outcomes[static_cast<size_t>(i)].qualityScore;
    }

    if (totalInWindow == 0) return 0.0;

    double successRatio = static_cast<double>(successCount) / static_cast<double>(totalInWindow);
    double avgQuality = qualitySum / static_cast<double>(totalInWindow);

    // Quality trend: positive if quality is improving, negative if declining
    // Map from [0,1] to [-1,+1]
    return (successRatio + avgQuality) / 2.0 * 2.0 - 1.0;
}

// ============================================================================
// GitSupervisor
// ============================================================================

GitSupervisor::GitSupervisor(GitWorker& gitWorker,
                              const SupervisorConfig& config)
    : gitWorker_(gitWorker),
      config_(config),
      circuitBreaker_(std::make_unique<CircuitBreaker>(
          config.circuitBreakerThreshold, config.circuitBreakerTimeoutSec)) {
}

std::optional<std::string> GitSupervisor::createWorktree(
    const std::string& objectiveId, const std::string& title)
{
    if (config_.enableCircuitBreaker && !circuitBreaker_->canExecute()) {
        GitOperation op;
        op.operationName = "create_worktree";
        op.success = false;
        op.errorMessage = "Circuit breaker is open";
        op.timestamp = getCurrentTimestamp();
        recordOperation(op);
        return std::nullopt;
    }

    auto startTime = std::chrono::steady_clock::now();
    GitOperation op;
    op.operationName = "create_worktree";

    try {
        auto result = gitWorker_.createWorktree(objectiveId, title);
        auto elapsed = std::chrono::steady_clock::now() - startTime;
        op.duration = std::chrono::duration<double>(elapsed).count();

        if (result.has_value()) {
            op.success = true;
            if (config_.enableCircuitBreaker) {
                circuitBreaker_->recordSuccess();
            }
        } else {
            op.success = false;
            op.errorMessage = "Worktree creation returned nullopt";
            if (config_.enableCircuitBreaker) {
                circuitBreaker_->recordFailure();
            }
        }

        recordOperation(op);
        return result;
    } catch (const std::exception& e) {
        auto elapsed = std::chrono::steady_clock::now() - startTime;
        op.duration = std::chrono::duration<double>(elapsed).count();
        op.success = false;
        op.errorMessage = e.what();

        if (config_.enableCircuitBreaker) {
            circuitBreaker_->recordFailure();
        }

        recordOperation(op);
        return std::nullopt;
    }
}

bool GitSupervisor::cleanupWorktree(const std::string& objectiveId) {
    if (config_.enableCircuitBreaker && !circuitBreaker_->canExecute()) {
        GitOperation op;
        op.operationName = "cleanup_worktree";
        op.success = false;
        op.errorMessage = "Circuit breaker is open";
        op.timestamp = getCurrentTimestamp();
        recordOperation(op);
        return false;
    }

    auto startTime = std::chrono::steady_clock::now();
    GitOperation op;
    op.operationName = "cleanup_worktree";

    try {
        bool result = gitWorker_.cleanupWorktree(objectiveId);
        auto elapsed = std::chrono::steady_clock::now() - startTime;
        op.duration = std::chrono::duration<double>(elapsed).count();
        op.success = result;

        if (result) {
            if (config_.enableCircuitBreaker) {
                circuitBreaker_->recordSuccess();
            }
        } else {
            op.errorMessage = "Cleanup returned false";
            if (config_.enableCircuitBreaker) {
                circuitBreaker_->recordFailure();
            }
        }

        recordOperation(op);
        return result;
    } catch (const std::exception& e) {
        auto elapsed = std::chrono::steady_clock::now() - startTime;
        op.duration = std::chrono::duration<double>(elapsed).count();
        op.success = false;
        op.errorMessage = e.what();

        if (config_.enableCircuitBreaker) {
            circuitBreaker_->recordFailure();
        }

        recordOperation(op);
        return false;
    }
}

bool GitSupervisor::rollbackBranch(const std::string& branch) {
    if (config_.enableCircuitBreaker && !circuitBreaker_->canExecute()) {
        GitOperation op;
        op.operationName = "rollback_branch";
        op.success = false;
        op.errorMessage = "Circuit breaker is open";
        op.timestamp = getCurrentTimestamp();
        recordOperation(op);
        return false;
    }

    auto startTime = std::chrono::steady_clock::now();
    GitOperation op;
    op.operationName = "rollback_branch";

    try {
        bool result = gitWorker_.rollbackBranch(branch);
        auto elapsed = std::chrono::steady_clock::now() - startTime;
        op.duration = std::chrono::duration<double>(elapsed).count();
        op.success = result;

        if (result) {
            if (config_.enableCircuitBreaker) {
                circuitBreaker_->recordSuccess();
            }
        } else {
            op.errorMessage = "Rollback returned false";
            if (config_.enableCircuitBreaker) {
                circuitBreaker_->recordFailure();
            }
        }

        recordOperation(op);
        return result;
    } catch (const std::exception& e) {
        auto elapsed = std::chrono::steady_clock::now() - startTime;
        op.duration = std::chrono::duration<double>(elapsed).count();
        op.success = false;
        op.errorMessage = e.what();

        if (config_.enableCircuitBreaker) {
            circuitBreaker_->recordFailure();
        }

        recordOperation(op);
        return false;
    }
}

std::vector<std::string> GitSupervisor::detectChangedFiles(
    const std::string& branch, const std::string& baseBranch)
{
    if (config_.enableCircuitBreaker && !circuitBreaker_->canExecute()) {
        GitOperation op;
        op.operationName = "detect_changed_files";
        op.success = false;
        op.errorMessage = "Circuit breaker is open";
        op.timestamp = getCurrentTimestamp();
        recordOperation(op);
        return {};
    }

    auto startTime = std::chrono::steady_clock::now();
    GitOperation op;
    op.operationName = "detect_changed_files";

    try {
        auto files = gitWorker_.detectChangedFiles(branch, baseBranch);
        auto elapsed = std::chrono::steady_clock::now() - startTime;
        op.duration = std::chrono::duration<double>(elapsed).count();
        op.success = true;

        if (config_.enableCircuitBreaker) {
            circuitBreaker_->recordSuccess();
        }

        recordOperation(op);
        return files;
    } catch (const std::exception& e) {
        auto elapsed = std::chrono::steady_clock::now() - startTime;
        op.duration = std::chrono::duration<double>(elapsed).count();
        op.success = false;
        op.errorMessage = e.what();

        if (config_.enableCircuitBreaker) {
            circuitBreaker_->recordFailure();
        }

        recordOperation(op);
        return {};
    }
}

void GitSupervisor::recordOperation(const GitOperation& operation) {
    std::lock_guard<std::mutex> lock(mutex_);
    operationLog_.push_back(operation);
}

} // namespace gaia
