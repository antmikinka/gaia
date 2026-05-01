// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT
//
// Orchestrator Engine implementation.
// Ported from Python: src/gaia/orchestration/engine.py

#include "gaia/orchestrator_engine.h"

#include <algorithm>
#include <fstream>
#include <stdexcept>
#include <thread>
#include <unordered_set>

namespace gaia {

// ---------------------------------------------------------------------------
// Verdict conversion
// ---------------------------------------------------------------------------

std::string verdictToString(Verdict v) {
    switch (v) {
        case Verdict::Continue:  return "continue";
        case Verdict::Abort:     return "abort";
        case Verdict::Pause:     return "pause";
        case Verdict::Remediate: return "remediate";
    }
    return "unknown";
}

Verdict stringToVerdict(const std::string& s) {
    if (s == "continue" || s == "CONTINUE") return Verdict::Continue;
    if (s == "abort"    || s == "ABORT")    return Verdict::Abort;
    if (s == "pause"    || s == "PAUSE")    return Verdict::Pause;
    if (s == "remediate" || s == "REMEDIATE") return Verdict::Remediate;
    throw std::invalid_argument("Invalid Verdict string: " + s);
}

// ---------------------------------------------------------------------------
// ExecutionResult
// ---------------------------------------------------------------------------

json ExecutionResult::toJson() const {
    json j;
    j["success"] = success;
    j["objective_id"] = objectiveId;
    json arts = json::array();
    for (const auto& a : artifacts) {
        arts.push_back(a.toJson());
    }
    j["artifacts"] = arts;
    if (qualityScore.has_value()) {
        j["quality_score"] = qualityScore.value();
    }
    if (errorMessage.has_value()) {
        j["error_message"] = errorMessage.value();
    }
    return j;
}

ExecutionResult ExecutionResult::fromJson(const json& j) {
    ExecutionResult r;
    r.success = j.value("success", false);
    r.objectiveId = j.value("objective_id", std::string{});
    r.artifacts.clear();
    if (j.contains("artifacts") && j["artifacts"].is_array()) {
        for (const auto& a : j["artifacts"]) {
            r.artifacts.push_back(Artifact::fromJson(a));
        }
    }
    if (j.contains("quality_score") && !j["quality_score"].is_null()) {
        r.qualityScore = j["quality_score"].get<double>();
    }
    if (j.contains("error_message") && !j["error_message"].is_null()) {
        r.errorMessage = j["error_message"].get<std::string>();
    }
    return r;
}

// ---------------------------------------------------------------------------
// OrchestratorConfig
// ---------------------------------------------------------------------------

void OrchestratorConfig::validate() const {
    if (objectivesPath.empty()) {
        throw std::invalid_argument("objectivesPath must not be empty");
    }
    if (maxCycleIterations <= 0) {
        throw std::invalid_argument("maxCycleIterations must be > 0");
    }
    if (maxParallelObjectives <= 0) {
        throw std::invalid_argument("maxParallelObjectives must be > 0");
    }
    if (qualityThreshold < 0.0 || qualityThreshold > 1.0) {
        throw std::invalid_argument("qualityThreshold must be in [0.0, 1.0]");
    }
}

OrchestratorConfig OrchestratorConfig::fromJson(const json& j) {
    OrchestratorConfig cfg;
    if (j.contains("objectives_path")) {
        cfg.objectivesPath = j["objectives_path"].get<std::string>();
    }
    if (j.contains("auto_commit")) {
        cfg.autoCommit = j["auto_commit"].get<bool>();
    }
    if (j.contains("dry_run")) {
        cfg.dryRun = j["dry_run"].get<bool>();
    }
    if (j.contains("enable_evaluation")) {
        cfg.enableEvaluation = j["enable_evaluation"].get<bool>();
    }
    if (j.contains("max_cycle_iterations")) {
        cfg.maxCycleIterations = j["max_cycle_iterations"].get<int>();
    }
    if (j.contains("enable_nexus")) {
        cfg.enableNexus = j["enable_nexus"].get<bool>();
    }
    if (j.contains("enable_supervisor")) {
        cfg.enableSupervisor = j["enable_supervisor"].get<bool>();
    }
    if (j.contains("enable_git_supervisor")) {
        cfg.enableGitSupervisor = j["enable_git_supervisor"].get<bool>();
    }
    if (j.contains("enable_parallel_execution")) {
        cfg.enableParallelExecution = j["enable_parallel_execution"].get<bool>();
    }
    if (j.contains("max_parallel_objectives")) {
        cfg.maxParallelObjectives = j["max_parallel_objectives"].get<int>();
    }
    if (j.contains("serialize_hooks")) {
        cfg.serializeHooks = j["serialize_hooks"].get<bool>();
    }
    if (j.contains("enable_rollback")) {
        cfg.enableRollback = j["enable_rollback"].get<bool>();
    }
    if (j.contains("quality_threshold")) {
        cfg.qualityThreshold = j["quality_threshold"].get<double>();
    }
    cfg.validate();
    return cfg;
}

json OrchestratorConfig::toJson() const {
    json j;
    j["objectives_path"] = objectivesPath;
    j["auto_commit"] = autoCommit;
    j["dry_run"] = dryRun;
    j["enable_evaluation"] = enableEvaluation;
    j["max_cycle_iterations"] = maxCycleIterations;
    j["enable_nexus"] = enableNexus;
    j["enable_supervisor"] = enableSupervisor;
    j["enable_git_supervisor"] = enableGitSupervisor;
    j["enable_parallel_execution"] = enableParallelExecution;
    j["max_parallel_objectives"] = maxParallelObjectives;
    j["serialize_hooks"] = serializeHooks;
    j["enable_rollback"] = enableRollback;
    j["quality_threshold"] = qualityThreshold;
    return j;
}

// ---------------------------------------------------------------------------
// CycleRecord
// ---------------------------------------------------------------------------

json CycleRecord::toJson() const {
    json j;
    j["cycle"] = cycle;
    j["objective_id"] = objectiveId;
    j["success"] = success;
    return j;
}

CycleRecord CycleRecord::fromJson(const json& j) {
    CycleRecord r;
    r.cycle = j.value("cycle", 0);
    r.objectiveId = j.value("objective_id", std::string{});
    r.success = j.value("success", false);
    return r;
}

// ---------------------------------------------------------------------------
// OrchestratorState
// ---------------------------------------------------------------------------

void OrchestratorState::recordCycle(const std::string& objectiveId, bool success) {
    cycleCount++;
    executionHistory.push_back({cycleCount, objectiveId, success});
    if (success) {
        objectivesProcessed++;
    } else {
        objectivesFailed++;
    }
}

json OrchestratorState::toJson() const {
    json j;
    j["paused"] = paused;
    j["cycle_count"] = cycleCount;
    j["objectives_processed"] = objectivesProcessed;
    j["objectives_failed"] = objectivesFailed;
    json history = json::array();
    for (const auto& r : executionHistory) {
        history.push_back(r.toJson());
    }
    j["execution_history"] = history;
    j["objective_branches"] = json(objectiveBranches);
    return j;
}

OrchestratorState OrchestratorState::fromJson(const json& j) {
    OrchestratorState s;
    s.paused = j.value("paused", false);
    s.cycleCount = j.value("cycle_count", 0);
    s.objectivesProcessed = j.value("objectives_processed", 0);
    s.objectivesFailed = j.value("objectives_failed", 0);
    s.executionHistory.clear();
    if (j.contains("execution_history") && j["execution_history"].is_array()) {
        for (const auto& r : j["execution_history"]) {
            s.executionHistory.push_back(CycleRecord::fromJson(r));
        }
    }
    s.objectiveBranches.clear();
    if (j.contains("objective_branches") && j["objective_branches"].is_object()) {
        for (const auto& [key, val] : j["objective_branches"].items()) {
            s.objectiveBranches[key] = val.get<std::string>();
        }
    }
    return s;
}

// ---------------------------------------------------------------------------
// EvaluationResult
// ---------------------------------------------------------------------------

json EvaluationResult::toJson() const {
    json j;
    j["verdict"] = verdict;
    j["reason"] = reason;
    j["objective_id"] = objectiveId;
    if (qualityScore.has_value()) {
        j["quality_score"] = qualityScore.value();
    }
    return j;
}

// ---------------------------------------------------------------------------
// OrchestratorEngine
// ---------------------------------------------------------------------------

OrchestratorEngine::OrchestratorEngine(const OrchestratorConfig& config)
    : config_(config), logCallback_(nullptr) {
    config_.validate();
    log("OrchestratorEngine initialized");
}

void OrchestratorEngine::setConfig(const OrchestratorConfig& config) {
    config.validate();
    config_ = config;
    log("OrchestratorEngine configuration updated");
}

void OrchestratorEngine::setExecutor(ObjectiveExecutor executor) {
    executor_ = std::move(executor);
}

void OrchestratorEngine::setLogCallback(LogCallback callback) {
    logCallback_ = std::move(callback);
}

void OrchestratorEngine::loadObjectives(const std::string& path) {
    std::string filePath = path.empty() ? config_.objectivesPath : path;

    std::ifstream file(filePath);
    if (!file.is_open()) {
        throw std::runtime_error("Cannot open objectives file: " + filePath);
    }

    std::string content((std::istreambuf_iterator<char>(file)),
                         std::istreambuf_iterator<char>());
    file.close();

    json j = json::parse(content);
    project_ = ProjectObjectives::fromJson(j);
    depGraph_.build(project_->objectives);

    log("Loaded " + std::to_string(project_->objectives.size()) +
        " objectives from " + filePath);
}

const OrchestratorState& OrchestratorEngine::run() {
    if (!project_.has_value()) {
        loadObjectives();
    }

    log("Starting orchestrator dispatch loop");

    while (state_.cycleCount < config_.maxCycleIterations) {
        // Check pause state
        while (state_.paused) {
            log("Orchestrator paused, waiting...");
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }

        // Find next ready objective
        Objective* objective = findNextReadyObjective();
        if (objective == nullptr) {
            // Check if project is done or blocked
            bool allDone = true;
            bool hasInProgress = false;
            bool hasQueuedWithResolvableDeps = false;

            for (const auto& obj : project_->objectives) {
                if (obj.status != ObjectiveStatus::Completed &&
                    obj.status != ObjectiveStatus::Cancelled) {
                    allDone = false;
                    if (obj.status == ObjectiveStatus::InProgress) hasInProgress = true;
                    if (obj.status == ObjectiveStatus::Queued) {
                        // Check if all dependencies are either COMPLETED or not yet terminal
                        bool depsResolvable = true;
                        for (const auto& depId : obj.dependencies) {
                            const auto* dep = project_->getObjective(depId);
                            if (dep != nullptr &&
                                (dep->status == ObjectiveStatus::Blocked ||
                                 dep->status == ObjectiveStatus::Cancelled)) {
                                depsResolvable = false;
                                break;
                            }
                        }
                        if (depsResolvable) {
                            hasQueuedWithResolvableDeps = true;
                        }
                    }
                }
            }

            if (allDone) {
                log("All objectives completed or cancelled -- project done");
                break;
            }

            if (!hasInProgress && !hasQueuedWithResolvableDeps) {
                log("Project is stuck -- remaining objectives have blocked dependencies");
                break;
            }

            log("No ready objectives -- waiting for dependencies");
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
            continue;
        }

        // Check for circular dependencies
        auto cycles = depGraph_.detectCycles();
        if (!cycles.empty()) {
            std::string cycleDesc;
            for (size_t i = 0; i < cycles[0].size(); ++i) {
                if (i > 0) cycleDesc += " -> ";
                cycleDesc += cycles[0][i];
            }
            log("Circular dependencies detected: " + cycleDesc);
            break;
        }

        // Dispatch to executor
        ExecutionResult result = executeObjective(*objective);

        // Update objective status based on result
        if (result.success) {
            applyStatusTransition(*objective, ObjectiveStatus::Completed);
            for (const auto& artifact : result.artifacts) {
                objective->addArtifact(artifact);
            }
        } else {
            applyStatusTransition(*objective, ObjectiveStatus::Blocked);
            objective->errorMessage = result.errorMessage;

            // Propagate failure to dependent objectives that are still queued
            std::unordered_set<std::string> failedIds;
            for (const auto& o : project_->objectives) {
                if (o.status == ObjectiveStatus::Blocked) {
                    failedIds.insert(o.objectiveId);
                }
            }

            // Build remaining levels from queued objectives via topological sort
            std::vector<std::vector<std::string>> remainingLevels;
            std::vector<std::string> level0;
            for (const auto& o : project_->objectives) {
                if (o.status == ObjectiveStatus::Queued) {
                    level0.push_back(o.objectiveId);
                }
            }
            if (!level0.empty()) {
                remainingLevels.push_back(level0);
            }

            if (!failedIds.empty() && !remainingLevels.empty()) {
                propagateFailuresToDependents(remainingLevels, failedIds);
            }
        }

        // Evaluate result (if evaluation is enabled)
        if (config_.enableEvaluation) {
            auto evalResult = evaluate(result, *objective);
            log("Evaluation: " + evalResult.verdict + " for " +
                objective->objectiveId);
        }

        // Record cycle
        state_.recordCycle(objective->objectiveId, result.success);

        // Save objectives (if not dry run)
        if (!config_.dryRun) {
            saveObjectives();
        }
    }

    log("Orchestrator dispatch loop finished -- cycles: " +
        std::to_string(state_.cycleCount) +
        ", processed: " + std::to_string(state_.objectivesProcessed) +
        ", failed: " + std::to_string(state_.objectivesFailed));

    return state_;
}

void OrchestratorEngine::pause(const std::string& reason) {
    state_.paused = true;
    log("Orchestrator paused: " + reason);
}

void OrchestratorEngine::resume() {
    state_.paused = false;
    log("Orchestrator resumed");
}

Objective* OrchestratorEngine::findNextReadyObjective() {
    if (!project_.has_value()) return nullptr;

    auto ready = project_->getReadyObjectives();
    if (ready.empty()) return nullptr;

    return ready[0]; // Highest priority (sorted by getReadyObjectives)
}

ExecutionResult OrchestratorEngine::executeObjective(Objective& objective) {
    if (!executor_) {
        log("No executor configured for objective: " + objective.objectiveId);
        ExecutionResult result;
        result.success = false;
        result.objectiveId = objective.objectiveId;
        result.errorMessage = "No objective executor configured";
        return result;
    }

    return executor_(objective);
}

void OrchestratorEngine::applyStatusTransition(Objective& objective,
                                                ObjectiveStatus target) {
    try {
        if (objective.status == ObjectiveStatus::Queued) {
            objective.transitionTo(ObjectiveStatus::InProgress);
        }
        objective.transitionTo(target);
    } catch (const std::invalid_argument&) {
        // Already in terminal state or invalid transition -- skip silently
    }
}

void OrchestratorEngine::propagateFailuresToDependents(
    const std::vector<std::vector<std::string>>& remainingLevels,
    const std::unordered_set<std::string>& failedIds) {

    for (const auto& level : remainingLevels) {
        for (const auto& objId : level) {
            if (!project_.has_value()) continue;

            // Find mutable pointer to objective (getObjective returns const)
            Objective* obj = nullptr;
            for (auto& o : project_->objectives) {
                if (o.objectiveId == objId) {
                    obj = &o;
                    break;
                }
            }
            if (obj == nullptr) continue;
            if (obj->status != ObjectiveStatus::Queued) continue;

            // Check if any dependency is in failedIds
            auto deps = depGraph_.getDependencies(objId);
            bool hasFailedDep = false;
            std::string failedDepId;
            for (const auto& depId : deps) {
                if (failedIds.count(depId) > 0) {
                    hasFailedDep = true;
                    failedDepId = depId;
                    break;
                }
            }

            if (hasFailedDep) {
                try {
                    obj->transitionTo(ObjectiveStatus::Blocked);
                    obj->errorMessage = "Dependency failed: " + failedDepId;
                } catch (const std::invalid_argument&) {
                    // Already in terminal state
                }
            }
        }
    }
}

void OrchestratorEngine::saveObjectives() {
    if (!project_.has_value()) return;

    json j = project_->toJson();
    std::ofstream file(config_.objectivesPath);
    if (!file.is_open()) {
        log("Failed to open objectives file for writing: " + config_.objectivesPath);
        return;
    }
    file << j.dump(2);
    file.close();
    log("Objectives saved to " + config_.objectivesPath);
}

void OrchestratorEngine::log(const std::string& message) const {
    if (logCallback_) {
        logCallback_(message);
    }
}

EvaluationResult OrchestratorEngine::evaluate(const ExecutionResult& result,
                                               const Objective& objective) const {
    if (!result.success) {
        return {
            "FAIL",
            result.errorMessage.value_or("Pipeline execution failed"),
            objective.objectiveId,
            result.qualityScore
        };
    }

    double score = result.qualityScore.value_or(-1.0);
    if (score < 0.0) {
        return {
            "PASS",
            "Pipeline succeeded without quality score",
            objective.objectiveId,
            std::nullopt
        };
    }

    if (score >= config_.qualityThreshold) {
        return {
            "PASS",
            "Quality score " + std::to_string(score) + " >= threshold " +
                std::to_string(config_.qualityThreshold),
            objective.objectiveId,
            score
        };
    }

    return {
        "REVIEW",
        "Quality score " + std::to_string(score) + " below threshold " +
            std::to_string(config_.qualityThreshold),
        objective.objectiveId,
        score
    };
}

} // namespace gaia
