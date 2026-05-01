// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT
//
// Parallel execution types and executor for the GAIA C++ pipeline orchestration system.
// Ported from Python: src/gaia/orchestration/engine.py (_run_level_parallel)

#pragma once

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "gaia/orchestrator_engine.h"
#include "gaia/orchestrator_types.h"

namespace gaia {

// ---------------------------------------------------------------------------
// HookCallback — fires at OBJECTIVE_START, OBJECTIVE_COMPLETE, OBJECTIVE_FAILED
// ---------------------------------------------------------------------------

using HookCallback = std::function<void(const std::string& event,
                                        const Objective& objective,
                                        const ExecutionResult& result)>;

// ---------------------------------------------------------------------------
// Forward declarations
// ---------------------------------------------------------------------------

class GitWorker;
using GitWorkerPtr = std::shared_ptr<GitWorker>;

// ---------------------------------------------------------------------------
// CountingSemaphore — C++17 equivalent of Python's asyncio.Semaphore
// ---------------------------------------------------------------------------

/// A thread-safe counting semaphore using std::mutex + std::condition_variable.
/// Blocks when the count reaches zero, releases when incremented.
class CountingSemaphore {
public:
    explicit CountingSemaphore(int maxCount);

    /// Block until a slot is available, then decrement the count.
    void acquire();

    /// Try to acquire within a timeout. Returns true if acquired.
    bool tryAcquire(std::chrono::milliseconds timeout);

    /// Increment the count and notify one waiter.
    void release();

    /// RAII scoped lock guard for the semaphore.
    class ScopedLock {
    public:
        explicit ScopedLock(CountingSemaphore& sem) : sem_(sem) { sem_.acquire(); }
        ~ScopedLock() { sem_.release(); }

        ScopedLock(const ScopedLock&) = delete;
        ScopedLock& operator=(const ScopedLock&) = delete;
        ScopedLock(ScopedLock&&) = default;
        ScopedLock& operator=(ScopedLock&&) = default;

    private:
        CountingSemaphore& sem_;
    };

    int maxCount() const { return maxCount_; }
    int available() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return available_;
    }

private:
    mutable std::mutex mutex_;
    std::condition_variable cv_;
    int maxCount_;
    int available_;
};

// ---------------------------------------------------------------------------
// ParallelObjectiveResult
// ---------------------------------------------------------------------------

/// Result of executing a single objective in parallel mode.
struct ParallelObjectiveResult {
    std::string objectiveId;
    bool success = false;
    std::vector<Artifact> artifacts;
    double qualityScore = 0.0;
    std::string errorMessage;
    std::string startTime;
    std::string endTime;

    /// Convert to existing ExecutionResult type.
    ExecutionResult toExecutionResult() const;
};

// ---------------------------------------------------------------------------
// ConflictReport (lightweight internal variant)
// ---------------------------------------------------------------------------

struct ParallelConflictReport {
    std::vector<std::string> objectiveIds;
    std::vector<std::string> affectedFiles;
};

// ---------------------------------------------------------------------------
// ParallelExecutor
// ---------------------------------------------------------------------------

/// Executes a dependency level in parallel with bounded concurrency.
///
/// Mirrors Python _run_level_parallel:
///   1. Fire OBJECTIVE_START hooks (serialized via hookMutex)
///   2. Launch executions via std::async with semaphore-bounded concurrency
///   3. Wait for all futures
///   4. Apply status transitions sequentially
///   5. Fire completion hooks (serialized)
///   6. Detect conflicts if gitWorker available
///   7. Return LevelResult with verdict
class ParallelExecutor {
public:
    explicit ParallelExecutor(const OrchestratorConfig& config);

    /// Execute all objectives in a single dependency level in parallel.
    ///
    /// \param levelObjectiveIds  Objective IDs in this level
    /// \param levelNumber        Current level number (0-based)
    /// \param project            Project objectives (mutable for status updates)
    /// \param depGraph           Dependency graph (for failure propagation)
    /// \param executor           The objective executor callback
    /// \param branches           Map of objectiveId -> branch name
    /// \return                   LevelResult with outcomes and verdict
    LevelResult executeLevel(
        const std::vector<std::string>& levelObjectiveIds,
        int levelNumber,
        ProjectObjectives& project,
        const DependencyGraph& depGraph,
        const ObjectiveExecutor& executor,
        std::unordered_map<std::string, std::string>& branches);

    /// Set the hook callback for firing events.
    void setHookCallback(HookCallback callback) { hookCallback_ = std::move(callback); }

    /// Set the git worker for conflict detection and rollback.
    void setGitWorker(GitWorkerPtr worker) { gitWorker_ = std::move(worker); }

    /// Get the last detected conflicts.
    const std::vector<ConflictReport>& lastConflicts() const { return lastConflicts_; }

    /// Get config.
    const OrchestratorConfig& config() const { return config_; }

private:
    /// Execute a single objective, wrapped with semaphore acquire/release.
    ParallelObjectiveResult executeSingle(
        Objective& objective,
        const ObjectiveExecutor& executor,
        CountingSemaphore& semaphore);

    /// Detect file-level conflicts among completed objectives.
    std::vector<ConflictReport> detectConflicts(
        const std::vector<std::string>& completedIds,
        const std::unordered_map<std::string, std::string>& branches);

    OrchestratorConfig config_;
    HookCallback hookCallback_;
    GitWorkerPtr gitWorker_;
    std::mutex hookMutex_;       // Serializes hook callbacks
    std::mutex gitOpMutex_;      // Serializes git operations
    std::vector<ConflictReport> lastConflicts_;
};

} // namespace gaia
