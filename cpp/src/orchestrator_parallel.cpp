// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT
//
// Parallel execution implementation.
// Ported from Python: src/gaia/orchestration/engine.py (_run_level_parallel)

#include "gaia/orchestrator_parallel.h"
#include "gaia/orchestrator_git.h"

#include <algorithm>
#include <stdexcept>
#include <thread>

namespace gaia {

// ---------------------------------------------------------------------------
// CountingSemaphore
// ---------------------------------------------------------------------------

CountingSemaphore::CountingSemaphore(int maxCount)
    : maxCount_(maxCount), available_(maxCount) {
    if (maxCount < 0) {
        throw std::invalid_argument("Semaphore maxCount must be >= 0");
    }
}

void CountingSemaphore::acquire() {
    std::unique_lock<std::mutex> lock(mutex_);
    cv_.wait(lock, [this] { return available_ > 0; });
    --available_;
}

bool CountingSemaphore::tryAcquire(std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> lock(mutex_);
    bool acquired = cv_.wait_for(lock, timeout, [this] { return available_ > 0; });
    if (acquired) {
        --available_;
    }
    return acquired;
}

void CountingSemaphore::release() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        // Always increment — maxCount_ is the initial capacity target, not a hard ceiling.
        // This ensures release/acquire pairs work correctly even when initialized with 0.
        ++available_;
    }
    cv_.notify_one();
}

// ---------------------------------------------------------------------------
// ParallelObjectiveResult
// ---------------------------------------------------------------------------

ExecutionResult ParallelObjectiveResult::toExecutionResult() const {
    ExecutionResult r;
    r.success = success;
    r.objectiveId = objectiveId;
    r.artifacts = artifacts;
    if (qualityScore > 0.0) {
        r.qualityScore = qualityScore;
    }
    if (!errorMessage.empty()) {
        r.errorMessage = errorMessage;
    }
    return r;
}

// ---------------------------------------------------------------------------
// ParallelExecutor
// ---------------------------------------------------------------------------

ParallelExecutor::ParallelExecutor(const OrchestratorConfig& config)
    : config_(config) {
}

LevelResult ParallelExecutor::executeLevel(
    const std::vector<std::string>& levelObjectiveIds,
    int levelNumber,
    ProjectObjectives& project,
    const DependencyGraph& /*depGraph*/,
    const ObjectiveExecutor& executor,
    std::unordered_map<std::string, std::string>& branches)
{
    LevelResult result;
    result.levelNumber = levelNumber;
    result.objectiveIds = levelObjectiveIds;
    result.timestamp = getCurrentTimestamp();

    // Build mutable objective map BEFORE launching any futures (C-3 fix)
    std::unordered_map<std::string, Objective*> objMap;
    for (const auto& oid : levelObjectiveIds) {
        for (auto& obj : project.objectives) {
            if (obj.objectiveId == oid) {
                objMap[oid] = &obj;
                break;
            }
        }
    }

    // Step 1: Fire OBJECTIVE_START hooks (serialized via hookMutex) (C-2 fix)
    std::unordered_set<std::string> haltedIds;
    for (const auto& [oid, obj] : objMap) {
        if (hookCallback_) {
            ExecutionResult emptyResult;
            emptyResult.objectiveId = oid;
            emptyResult.success = false;
            emptyResult.errorMessage = "Hook halted execution";
            std::lock_guard<std::mutex> hookLock(hookMutex_);
            hookCallback_("OBJECTIVE_START", *obj, emptyResult);
            // Hook can signal halt via the result — check if hook set success=false
            // For now hooks throw to halt; haltedIds populated if hook returns halt signal
        }
    }

    // Step 2: Launch executions in parallel with bounded concurrency
    CountingSemaphore semaphore(config_.maxParallelObjectives);

    // C-4 fix: Store objective ID inside the lambda so each future carries
    // its own identity — no index-based lookup needed.
    std::vector<std::future<ParallelObjectiveResult>> futures;
    futures.reserve(objMap.size());
    for (const auto& [oid, obj] : objMap) {
        if (haltedIds.count(oid)) {
            continue;
        }
        futures.push_back(
            std::async(std::launch::async, [this, obj, &semaphore, &executor]() {
                return executeSingle(*obj, executor, semaphore);
            })
        );
    }

    // Step 3: Wait for all futures and collect results
    // C-4 fix: Each ParallelObjectiveResult already carries its objectiveId
    // (set in executeSingle), so we use it directly instead of indexing.
    int successCount = 0;
    int failureCount = 0;

    for (auto& future : futures) {
        ParallelObjectiveResult pr;
        try {
            pr = future.get();
        } catch (const std::exception& e) {
            pr.success = false;
            pr.errorMessage = e.what();
            // objectiveId is already set in executeSingle; only override if empty
            if (pr.objectiveId.empty()) {
                pr.objectiveId = "unknown";
            }
        }

        Objective* obj = objMap.count(pr.objectiveId) ? objMap.at(pr.objectiveId) : nullptr;

        // Step 4: Apply status transitions sequentially
        if (pr.success) {
            if (obj) {
                OrchestratorEngine::applyStatusTransition(*obj, ObjectiveStatus::Completed);
                for (const auto& artifact : pr.artifacts) {
                    obj->addArtifact(artifact);
                }
            }
            result.outcomes[pr.objectiveId] = ObjectiveOutcome::Success;
            ++successCount;
        } else {
            if (obj) {
                OrchestratorEngine::applyStatusTransition(*obj, ObjectiveStatus::Blocked);
                obj->errorMessage = pr.errorMessage;
            }
            result.outcomes[pr.objectiveId] = ObjectiveOutcome::Failed;
            ++failureCount;
        }

        result.successCount = successCount;
        result.failureCount = failureCount;
    }

    // Detect conflicts among successfully completed objectives
    std::vector<std::string> completedIds;
    for (const auto& [oid, outcome] : result.outcomes) {
        if (outcome == ObjectiveOutcome::Success) {
            completedIds.push_back(oid);
        }
    }

    if (!completedIds.empty() && gitWorker_) {
        result.conflicts = detectConflicts(completedIds, branches);
        lastConflicts_ = result.conflicts;
    }

    // Step 5: Fire completion hooks (serialized)
    for (const auto& [oid, outcome] : result.outcomes) {
        if (!objMap.count(oid)) continue;
        Objective* obj = objMap.at(oid);

        std::string event = (outcome == ObjectiveOutcome::Success)
            ? "OBJECTIVE_COMPLETE" : "OBJECTIVE_FAILED";

        if (hookCallback_) {
            ExecutionResult execResult = objMap[oid] ? ExecutionResult{} : ExecutionResult{};
            execResult.objectiveId = oid;
            execResult.success = (outcome == ObjectiveOutcome::Success);
            if (outcome == ObjectiveOutcome::Failed && obj && obj->errorMessage.has_value()) {
                execResult.errorMessage = obj->errorMessage.value();
            }

            std::lock_guard<std::mutex> hookLock(hookMutex_);
            hookCallback_(event, *obj, execResult);
        }
    }

    // Determine verdict (lowercase to match Python Verdict enum)
    if (failureCount == static_cast<int>(levelObjectiveIds.size()) && !levelObjectiveIds.empty()) {
        result.verdict = "abort";
    } else if (failureCount > 0) {
        result.verdict = "remediate";
    } else {
        result.verdict = "continue";
    }

    return result;
}

ParallelObjectiveResult ParallelExecutor::executeSingle(
    Objective& objective,
    const ObjectiveExecutor& executor,
    CountingSemaphore& semaphore)
{
    ParallelObjectiveResult result;
    result.objectiveId = objective.objectiveId;
    result.startTime = getCurrentTimestamp();

    // Acquire semaphore slot (blocks if at max concurrency)
    CountingSemaphore::ScopedLock lock(semaphore);

    // Execute the objective
    ExecutionResult execResult;
    try {
        execResult = executor(objective);
    } catch (const std::exception& e) {
        result.success = false;
        result.errorMessage = e.what();
        result.endTime = getCurrentTimestamp();
        return result;
    }

    result.success = execResult.success;
    result.artifacts = execResult.artifacts;
    result.qualityScore = execResult.qualityScore.value_or(0.0);
    if (execResult.errorMessage.has_value()) {
        result.errorMessage = execResult.errorMessage.value();
    }
    result.endTime = getCurrentTimestamp();

    return result;
}

std::vector<ConflictReport> ParallelExecutor::detectConflicts(
    const std::vector<std::string>& completedIds,
    const std::unordered_map<std::string, std::string>& branches)
{
    std::vector<ConflictReport> conflicts;

    if (!gitWorker_) {
        return conflicts;
    }

    // Collect changed files per objective
    struct ObjectiveFiles {
        std::string objectiveId;
        std::vector<std::string> files;
    };

    std::vector<ObjectiveFiles> objFileSets;

    for (const auto& oid : completedIds) {
        auto branchIt = branches.find(oid);
        if (branchIt == branches.end() || branchIt->second.empty()) {
            continue;
        }

        std::vector<std::string> changedFiles;
        {
            std::lock_guard<std::mutex> gitLock(gitOpMutex_);
            changedFiles = gitWorker_->detectChangedFiles(branchIt->second);
        }

        if (!changedFiles.empty()) {
            objFileSets.push_back({oid, std::move(changedFiles)});
        }
    }

    // Pairwise intersection of file sets
    for (size_t i = 0; i < objFileSets.size(); ++i) {
        for (size_t j = i + 1; j < objFileSets.size(); ++j) {
            std::unordered_set<std::string> filesA(
                objFileSets[i].files.begin(), objFileSets[i].files.end());

            std::vector<std::string> overlap;
            for (const auto& file : objFileSets[j].files) {
                if (filesA.count(file)) {
                    overlap.push_back(file);
                }
            }

            if (!overlap.empty()) {
                ConflictReport report;
                report.conflictingObjectiveIds = {
                    objFileSets[i].objectiveId,
                    objFileSets[j].objectiveId
                };
                report.affectedFiles = std::move(overlap);
                report.timestamp = getCurrentTimestamp();
                conflicts.push_back(std::move(report));
            }
        }
    }

    return conflicts;
}

} // namespace gaia
