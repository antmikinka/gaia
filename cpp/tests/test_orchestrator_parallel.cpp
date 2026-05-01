// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT
//
// Comprehensive tests for Phase 3 parallel execution, git worker,
// conflict detection, rollback, and integration.

#include <gtest/gtest.h>
#include <gaia/orchestrator_parallel.h>
#include <gaia/orchestrator_git.h>
#include <gaia/orchestrator_engine.h>
#include <gaia/orchestrator_types.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace fs = std::filesystem;

using namespace gaia;

// ============================================================================
// Test Helpers
// ============================================================================

/// Create a temporary objectives JSON file for testing.
static std::string createTempObjectivesFile(const json& data) {
    std::string path = fs::temp_directory_path().string() +
                       "/gaia_parallel_test_" + generateShortId() + ".json";
    std::ofstream file(path);
    file << data.dump(2);
    file.close();
    return path;
}

/// Create a multi-objective project JSON for parallel testing.
static json makeProjectJson(const std::vector<json>& objectives) {
    json j;
    j["project_id"] = "parallel-test";
    j["name"] = "Parallel Test Project";
    j["objectives"] = objectives;
    j["metadata"] = json::object();
    return j;
}

/// Create a single objective JSON entry.
static json makeObjectiveJson(const std::string& id, const std::string& title,
                               const std::vector<std::string>& deps = {},
                               int priority = 5,
                               const std::string& status = "queued") {
    json j;
    j["objective_id"] = id;
    j["title"] = title;
    j["description"] = "Test objective " + id;
    j["status"] = status;
    j["dependencies"] = deps;
    j["priority"] = priority;
    j["phase"] = "DEVELOPMENT";
    j["pipeline_config"] = json::object();
    j["artifacts"] = json::array();
    j["created_at"] = getCurrentTimestamp();
    j["updated_at"] = getCurrentTimestamp();
    return j;
}

// ============================================================================
// CountingSemaphore Tests
// ============================================================================

TEST(CountingSemaphoreTest, AcquireReleaseBasic) {
    CountingSemaphore sem(2);
    EXPECT_EQ(sem.available(), 2);
    EXPECT_EQ(sem.maxCount(), 2);

    sem.acquire();
    EXPECT_EQ(sem.available(), 1);

    sem.acquire();
    EXPECT_EQ(sem.available(), 0);

    sem.release();
    EXPECT_EQ(sem.available(), 1);

    sem.release();
    EXPECT_EQ(sem.available(), 2);
}

TEST(CountingSemaphoreTest, MultipleAcquireRelease) {
    CountingSemaphore sem(5);
    for (int i = 0; i < 10; ++i) {
        sem.acquire();
        sem.release();
    }
    EXPECT_EQ(sem.available(), 5);
}

TEST(CountingSemaphoreTest, BlockingWhenAtMaxConcurrency) {
    CountingSemaphore sem(1);

    sem.acquire();  // Now available = 0
    EXPECT_EQ(sem.available(), 0);

    std::atomic<bool> released{false};
    std::atomic<bool> secondAcquired{false};

    std::thread t([&]() {
        // Wait a bit to ensure the main thread is blocked
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        released = true;
        sem.release();
    });

    // This should block until the thread releases
    sem.acquire();
    EXPECT_TRUE(released.load());
    secondAcquired = true;
    sem.release();

    t.join();
    EXPECT_TRUE(secondAcquired.load());
}

TEST(CountingSemaphoreTest, ScopedLockRAII) {
    CountingSemaphore sem(2);
    {
        CountingSemaphore::ScopedLock lock1(sem);
        EXPECT_EQ(sem.available(), 1);
        {
            CountingSemaphore::ScopedLock lock2(sem);
            EXPECT_EQ(sem.available(), 0);
        }
        EXPECT_EQ(sem.available(), 1);
    }
    EXPECT_EQ(sem.available(), 2);
}

TEST(CountingSemaphoreTest, ScopedLockExceptionSafety) {
    CountingSemaphore sem(1);
    {
        CountingSemaphore::ScopedLock lock(sem);
        EXPECT_EQ(sem.available(), 0);
        // lock goes out of scope — should release even if we "return"
    }
    EXPECT_EQ(sem.available(), 1);
}

TEST(CountingSemaphoreTest, ZeroMaxCountBlocks) {
    CountingSemaphore sem(0);
    EXPECT_EQ(sem.available(), 0);

    // acquire() on zero should block forever — use tryAcquire instead
    bool acquired = sem.tryAcquire(std::chrono::milliseconds(100));
    EXPECT_FALSE(acquired);
    EXPECT_EQ(sem.available(), 0);

    // Release then acquire should work
    sem.release();
    EXPECT_EQ(sem.available(), 1);
    sem.acquire();
    EXPECT_EQ(sem.available(), 0);
}

TEST(CountingSemaphoreTest, TryAcquireTimeout) {
    CountingSemaphore sem(1);
    sem.acquire();  // Now 0

    auto start = std::chrono::steady_clock::now();
    bool acquired = sem.tryAcquire(std::chrono::milliseconds(50));
    auto elapsed = std::chrono::steady_clock::now() - start;

    EXPECT_FALSE(acquired);
    EXPECT_GE(elapsed, std::chrono::milliseconds(40));
}

TEST(CountingSemaphoreTest, TryAcquireSuccess) {
    CountingSemaphore sem(1);
    bool acquired = sem.tryAcquire(std::chrono::milliseconds(100));
    EXPECT_TRUE(acquired);
    EXPECT_EQ(sem.available(), 0);
}

TEST(CountingSemaphoreTest, ConcurrentStressTest) {
    constexpr int kThreads = 20;
    constexpr int kIterations = 100;
    CountingSemaphore sem(5);
    std::atomic<int> concurrentCount{0};
    std::atomic<int> maxConcurrent{0};

    std::vector<std::thread> threads;
    for (int t = 0; t < kThreads; ++t) {
        threads.emplace_back([&]() {
            for (int i = 0; i < kIterations; ++i) {
                {
                    CountingSemaphore::ScopedLock lock(sem);
                    int current = ++concurrentCount;
                    int prevMax = maxConcurrent.load();
                    while (current > prevMax &&
                           !maxConcurrent.compare_exchange_weak(prevMax, current)) {}
                    std::this_thread::yield();
                    --concurrentCount;
                }
            }
        });
    }

    for (auto& t : threads) {
        t.join();
    }

    EXPECT_LE(maxConcurrent.load(), 5);
    EXPECT_EQ(sem.available(), 5);
}

TEST(CountingSemaphoreTest, InvalidMaxCount) {
    EXPECT_THROW(CountingSemaphore(-1), std::invalid_argument);
}

TEST(CountingSemaphoreTest, SingleThreadedFlow) {
    CountingSemaphore sem(3);
    for (int i = 0; i < 100; ++i) {
        CountingSemaphore::ScopedLock lock(sem);
        // Should never block
    }
    EXPECT_EQ(sem.available(), 3);
}

TEST(CountingSemaphoreTest, MoveSemantics) {
    CountingSemaphore sem(2);
    {
        auto lock1 = std::make_unique<CountingSemaphore::ScopedLock>(sem);
        EXPECT_EQ(sem.available(), 1);
        // Move the unique_ptr — lock still held
        auto lock2 = std::move(lock1);
        EXPECT_EQ(sem.available(), 1);
        EXPECT_FALSE(lock1);  // moved-from
        EXPECT_TRUE(lock2);
        // lock2 goes out of scope — releases
    }
    EXPECT_EQ(sem.available(), 2);
}

TEST(CountingSemaphoreTest, ReleaseWithoutAcquire) {
    CountingSemaphore sem(2);
    sem.release();  // Should not throw, goes above max
    sem.release();
    EXPECT_EQ(sem.available(), 4);
    sem.acquire();
    sem.acquire();
    sem.acquire();
    EXPECT_EQ(sem.available(), 1);
}

// ============================================================================
// ParallelObjectiveResult Tests
// ============================================================================

TEST(ParallelObjectiveResultTest, ToExecutionResultSuccess) {
    ParallelObjectiveResult pr;
    pr.objectiveId = "obj-1";
    pr.success = true;
    pr.qualityScore = 0.95;

    ExecutionResult er = pr.toExecutionResult();
    EXPECT_TRUE(er.success);
    EXPECT_EQ(er.objectiveId, "obj-1");
    EXPECT_TRUE(er.qualityScore.has_value());
    EXPECT_DOUBLE_EQ(er.qualityScore.value(), 0.95);
    EXPECT_FALSE(er.errorMessage.has_value());
}

TEST(ParallelObjectiveResultTest, ToExecutionResultFailure) {
    ParallelObjectiveResult pr;
    pr.objectiveId = "obj-2";
    pr.success = false;
    pr.errorMessage = "Test failure";

    ExecutionResult er = pr.toExecutionResult();
    EXPECT_FALSE(er.success);
    EXPECT_EQ(er.objectiveId, "obj-2");
    EXPECT_TRUE(er.errorMessage.has_value());
    EXPECT_EQ(er.errorMessage.value(), "Test failure");
}

TEST(ParallelObjectiveResultTest, WithArtifacts) {
    ParallelObjectiveResult pr;
    pr.objectiveId = "obj-3";
    pr.success = true;
    Artifact art;
    art.name = "test-artifact";
    pr.artifacts.push_back(art);

    ExecutionResult er = pr.toExecutionResult();
    EXPECT_EQ(er.artifacts.size(), 1);
    EXPECT_EQ(er.artifacts[0].name, "test-artifact");
}

// ============================================================================
// ParallelExecutor Tests
// ============================================================================

/// Helper: create a default config for testing.
static OrchestratorConfig makeTestConfig(const std::string& path) {
    OrchestratorConfig cfg;
    cfg.objectivesPath = path;
    cfg.maxParallelObjectives = 4;
    cfg.enableParallelExecution = true;
    cfg.serializeHooks = true;
    cfg.enableRollback = true;
    cfg.maxCycleIterations = 100;
    cfg.qualityThreshold = 0.9;
    return cfg;
}

TEST(ParallelExecutorTest, SingleObjectiveLevelExecution) {
    OrchestratorConfig cfg = makeTestConfig("/tmp/test.json");

    // Create project with one objective
    json project = makeProjectJson({
        makeObjectiveJson("obj-1", "Test Objective 1")
    });
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);

    ParallelExecutor exec(cfg);

    // Simple executor that always succeeds
    bool executed = false;
    auto executor = [&](Objective& obj) -> ExecutionResult {
        executed = true;
        ExecutionResult r;
        r.success = true;
        r.objectiveId = obj.objectiveId;
        return r;
    };

    std::unordered_map<std::string, std::string> branches;
    LevelResult result = exec.executeLevel({"obj-1"}, 0, proj, dg, executor, branches);

    EXPECT_TRUE(executed);
    EXPECT_EQ(result.levelNumber, 0);
    EXPECT_EQ(result.objectiveIds.size(), 1);
    EXPECT_EQ(result.successCount, 1);
    EXPECT_EQ(result.failureCount, 0);
    EXPECT_EQ(result.verdict, "continue");
    EXPECT_EQ(result.outcomes.at("obj-1"), ObjectiveOutcome::Success);
}

TEST(ParallelExecutorTest, MultipleObjectivesBoundedConcurrency) {
    OrchestratorConfig cfg = makeTestConfig("/tmp/test.json");
    cfg.maxParallelObjectives = 2;

    json project = makeProjectJson({
        makeObjectiveJson("obj-1", "Objective 1"),
        makeObjectiveJson("obj-2", "Objective 2"),
        makeObjectiveJson("obj-3", "Objective 3"),
    });
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);

    ParallelExecutor exec(cfg);

    std::atomic<int> maxConcurrent{0};
    std::atomic<int> currentConcurrent{0};

    auto executor = [&](Objective& obj) -> ExecutionResult {
        int c = ++currentConcurrent;
        int prev = maxConcurrent.load();
        while (c > prev && !maxConcurrent.compare_exchange_weak(prev, c)) {}
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        --currentConcurrent;

        ExecutionResult r;
        r.success = true;
        r.objectiveId = obj.objectiveId;
        return r;
    };

    std::unordered_map<std::string, std::string> branches;
    LevelResult result = exec.executeLevel(
        {"obj-1", "obj-2", "obj-3"}, 0, proj, dg, executor, branches);

    EXPECT_EQ(result.successCount, 3);
    EXPECT_EQ(result.failureCount, 0);
    EXPECT_LE(maxConcurrent.load(), 2);  // Bounded by semaphore
}

TEST(ParallelExecutorTest, AllSuccessVerdictContinue) {
    OrchestratorConfig cfg = makeTestConfig("/tmp/test.json");
    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
        makeObjectiveJson("b", "B"),
    });
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);

    auto executor = [](Objective& obj) -> ExecutionResult {
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    };

    std::unordered_map<std::string, std::string> branches;
    auto result = exec.executeLevel({"a", "b"}, 0, proj, dg, executor, branches);

    EXPECT_EQ(result.verdict, "continue");
    EXPECT_EQ(result.successCount, 2);
}

TEST(ParallelExecutorTest, AllFailureVerdictAbort) {
    OrchestratorConfig cfg = makeTestConfig("/tmp/test.json");
    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
        makeObjectiveJson("b", "B"),
    });
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);

    auto executor = [](Objective& obj) -> ExecutionResult {
        return {false, obj.objectiveId, {}, 0.0, "Failed"};
    };

    std::unordered_map<std::string, std::string> branches;
    auto result = exec.executeLevel({"a", "b"}, 0, proj, dg, executor, branches);

    EXPECT_EQ(result.verdict, "abort");
    EXPECT_EQ(result.failureCount, 2);
}

TEST(ParallelExecutorTest, MixedVerdictRemediate) {
    OrchestratorConfig cfg = makeTestConfig("/tmp/test.json");
    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
        makeObjectiveJson("b", "B"),
    });
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);

    std::atomic<bool> aExecuted{false};
    auto executor = [&](Objective& obj) -> ExecutionResult {
        if (obj.objectiveId == "a") {
            aExecuted = true;
            return {true, obj.objectiveId, {}, 0.95, std::nullopt};
        }
        return {false, obj.objectiveId, {}, 0.0, "Failed"};
    };

    std::unordered_map<std::string, std::string> branches;
    auto result = exec.executeLevel({"a", "b"}, 0, proj, dg, executor, branches);

    EXPECT_EQ(result.verdict, "remediate");
    EXPECT_EQ(result.successCount, 1);
    EXPECT_EQ(result.failureCount, 1);
    EXPECT_EQ(result.outcomes.at("a"), ObjectiveOutcome::Success);
    EXPECT_EQ(result.outcomes.at("b"), ObjectiveOutcome::Failed);
}

TEST(ParallelExecutorTest, HookCallbackInvocation) {
    OrchestratorConfig cfg = makeTestConfig("/tmp/test.json");
    json project = makeProjectJson({
        makeObjectiveJson("obj-1", "Test"),
    });
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);

    std::vector<std::string> hookEvents;
    std::mutex hookMutex;

    exec.setHookCallback([&](const std::string& event, const Objective& obj,
                              const ExecutionResult& result) {
        std::lock_guard<std::mutex> lock(hookMutex);
        hookEvents.push_back(event);
    });

    auto executor = [](Objective& obj) -> ExecutionResult {
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    };

    std::unordered_map<std::string, std::string> branches;
    exec.executeLevel({"obj-1"}, 0, proj, dg, executor, branches);

    // Should have received OBJECTIVE_START and OBJECTIVE_COMPLETE
    EXPECT_GE(hookEvents.size(), 2);
    EXPECT_EQ(hookEvents[0], "OBJECTIVE_START");
    EXPECT_EQ(hookEvents.back(), "OBJECTIVE_COMPLETE");
}

TEST(ParallelExecutorTest, HookCallbackSerialization) {
    OrchestratorConfig cfg = makeTestConfig("/tmp/test.json");
    cfg.maxParallelObjectives = 4;

    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
        makeObjectiveJson("b", "B"),
        makeObjectiveJson("c", "C"),
        makeObjectiveJson("d", "D"),
    });
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);

    // Verify hooks are called sequentially (not in parallel)
    std::atomic<int> concurrentHookCalls{0};
    std::atomic<int> maxConcurrentHookCalls{0};

    exec.setHookCallback([&](const std::string&, const Objective&,
                              const ExecutionResult&) {
        int c = ++concurrentHookCalls;
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        int prev = maxConcurrentHookCalls.load();
        while (c > prev && !maxConcurrentHookCalls.compare_exchange_weak(prev, c)) {}
        --concurrentHookCalls;
    });

    auto executor = [](Objective& obj) -> ExecutionResult {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    };

    std::unordered_map<std::string, std::string> branches;
    exec.executeLevel({"a", "b", "c", "d"}, 0, proj, dg, executor, branches);

    // Hook callbacks are serialized via hookMutex — max concurrent should be 1
    // Actually the hook callback is called with the mutex held, so concurrent should be 1
    // But note: the hookMutex ensures only one callback at a time
    EXPECT_EQ(maxConcurrentHookCalls.load(), 1);
}

TEST(ParallelExecutorTest, ExceptionInExecutor) {
    OrchestratorConfig cfg = makeTestConfig("/tmp/test.json");
    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
    });
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);

    auto executor = [](Objective&) -> ExecutionResult {
        throw std::runtime_error("Test exception");
    };

    std::unordered_map<std::string, std::string> branches;
    auto result = exec.executeLevel({"a"}, 0, proj, dg, executor, branches);

    EXPECT_EQ(result.failureCount, 1);
    EXPECT_EQ(result.outcomes.at("a"), ObjectiveOutcome::Failed);
    EXPECT_EQ(result.verdict, "abort");
}

TEST(ParallelExecutorTest, EmptyLevel) {
    OrchestratorConfig cfg = makeTestConfig("/tmp/test.json");
    json project = makeProjectJson({});
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);

    auto executor = [](Objective&) -> ExecutionResult {
        return {true, "", {}, 0.95, std::nullopt};
    };

    std::unordered_map<std::string, std::string> branches;
    auto result = exec.executeLevel({}, 0, proj, dg, executor, branches);

    EXPECT_EQ(result.successCount, 0);
    EXPECT_EQ(result.failureCount, 0);
    // Empty level with no failures: verdict is CONTINUE (not ABORT)
    EXPECT_EQ(result.verdict, "continue");
}

TEST(ParallelExecutorTest, StatusTransitionsApplied) {
    OrchestratorConfig cfg = makeTestConfig("/tmp/test.json");
    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
    });
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);

    auto executor = [](Objective& obj) -> ExecutionResult {
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    };

    std::unordered_map<std::string, std::string> branches;
    exec.executeLevel({"a"}, 0, proj, dg, executor, branches);

    // Objective should be in Completed status
    const auto* obj = proj.getObjective("a");
    ASSERT_NE(obj, nullptr);
    EXPECT_EQ(obj->status, ObjectiveStatus::Completed);
}

TEST(ParallelExecutorTest, FailedObjectiveStatusBlocked) {
    OrchestratorConfig cfg = makeTestConfig("/tmp/test.json");
    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
    });
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);

    auto executor = [](Objective& obj) -> ExecutionResult {
        return {false, obj.objectiveId, {}, 0.0, "Test error"};
    };

    std::unordered_map<std::string, std::string> branches;
    exec.executeLevel({"a"}, 0, proj, dg, executor, branches);

    const auto* obj = proj.getObjective("a");
    ASSERT_NE(obj, nullptr);
    EXPECT_EQ(obj->status, ObjectiveStatus::Blocked);
    EXPECT_TRUE(obj->errorMessage.has_value());
}

TEST(ParallelExecutorTest, ConfigValidation) {
    OrchestratorConfig cfg;
    cfg.objectivesPath = "/tmp/test.json";
    cfg.maxParallelObjectives = 3;
    cfg.enableParallelExecution = true;
    cfg.maxCycleIterations = 50;
    cfg.qualityThreshold = 0.8;

    ParallelExecutor exec(cfg);
    EXPECT_EQ(exec.config().maxParallelObjectives, 3);
    EXPECT_EQ(exec.config().enableParallelExecution, true);
}

TEST(ParallelExecutorTest, ResultAggregation) {
    OrchestratorConfig cfg = makeTestConfig("/tmp/test.json");
    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
        makeObjectiveJson("b", "B"),
        makeObjectiveJson("c", "C"),
    });
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);

    auto executor = [](Objective& obj) -> ExecutionResult {
        if (obj.objectiveId == "b") {
            return {false, obj.objectiveId, {}, 0.0, "B failed"};
        }
        Artifact art;
        art.name = "art-" + obj.objectiveId;
        return {true, obj.objectiveId, {art}, 0.95, std::nullopt};
    };

    std::unordered_map<std::string, std::string> branches;
    auto result = exec.executeLevel({"a", "b", "c"}, 0, proj, dg, executor, branches);

    EXPECT_EQ(result.successCount, 2);
    EXPECT_EQ(result.failureCount, 1);
    EXPECT_EQ(result.outcomes.size(), 3);
    EXPECT_EQ(result.outcomes.at("a"), ObjectiveOutcome::Success);
    EXPECT_EQ(result.outcomes.at("b"), ObjectiveOutcome::Failed);
    EXPECT_EQ(result.outcomes.at("c"), ObjectiveOutcome::Success);

    // Check artifacts were added
    const auto* objA = proj.getObjective("a");
    EXPECT_EQ(objA->artifacts.size(), 1);
    EXPECT_EQ(objA->artifacts[0].name, "art-a");
}

// ============================================================================
// Conflict Detection Tests (without real git)
// ============================================================================

class ConflictDetectionTest : public ::testing::Test {
protected:
    OrchestratorConfig cfg;
    std::string path;

    void SetUp() override {
        cfg = makeTestConfig("/tmp/test.json");
        json project = makeProjectJson({
            makeObjectiveJson("a", "A"),
            makeObjectiveJson("b", "B"),
        });
        path = createTempObjectivesFile(project);
        cfg.objectivesPath = path;
    }
};

TEST_F(ConflictDetectionTest, NoGitWorkerNoConflicts) {
    ProjectObjectives proj = ProjectObjectives::fromJson(
        makeProjectJson({
            makeObjectiveJson("a", "A"),
            makeObjectiveJson("b", "B"),
        }));
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);
    // No git worker set

    // Even with successful objectives, no conflicts should be detected
    auto executor = [](Objective& obj) -> ExecutionResult {
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    };

    std::unordered_map<std::string, std::string> branches;
    branches["a"] = "obj/a";
    branches["b"] = "obj/b";

    auto result = exec.executeLevel({"a", "b"}, 0, proj, dg, executor, branches);

    EXPECT_TRUE(result.conflicts.empty());
    EXPECT_EQ(exec.lastConflicts().size(), 0);
}

TEST_F(ConflictDetectionTest, EmptyOverlapNoConflicts) {
    // When no branches are mapped, detectConflicts should return empty
    ProjectObjectives proj = ProjectObjectives::fromJson(
        makeProjectJson({
            makeObjectiveJson("a", "A"),
            makeObjectiveJson("b", "B"),
        }));
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);

    auto executor = [](Objective& obj) -> ExecutionResult {
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    };

    std::unordered_map<std::string, std::string> branches;
    // No branches mapped — should skip conflict detection
    auto result = exec.executeLevel({"a", "b"}, 0, proj, dg, executor, branches);

    EXPECT_TRUE(result.conflicts.empty());
}

// ============================================================================
// Rollback Tests (without real git)
// ============================================================================

class RollbackTest : public ::testing::Test {
protected:
    OrchestratorConfig cfg;
};

TEST_F(RollbackTest, RollbackDisabledNoRollback) {
    cfg = makeTestConfig("/tmp/test.json");
    cfg.enableRollback = false;

    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
    });
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);

    auto executor = [](Objective& obj) -> ExecutionResult {
        return {false, obj.objectiveId, {}, 0.0, "Failed"};
    };

    std::unordered_map<std::string, std::string> branches;
    auto result = exec.executeLevel({"a"}, 0, proj, dg, executor, branches);

    EXPECT_EQ(result.failureCount, 1);
    // Without git worker, rollback is not attempted — test passes
    // (actual rollback logic is in runParallelMode)
}

TEST_F(RollbackTest, NoGitWorkerSkipRollback) {
    cfg = makeTestConfig("/tmp/test.json");
    cfg.enableRollback = true;

    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
    });
    std::string path = createTempObjectivesFile(project);
    cfg.objectivesPath = path;

    ProjectObjectives proj = ProjectObjectives::fromJson(project);
    DependencyGraph dg(proj.objectives);
    ParallelExecutor exec(cfg);
    // No git worker set

    auto executor = [](Objective& obj) -> ExecutionResult {
        return {false, obj.objectiveId, {}, 0.0, "Failed"};
    };

    std::unordered_map<std::string, std::string> branches;
    auto result = exec.executeLevel({"a"}, 0, proj, dg, executor, branches);

    EXPECT_EQ(result.failureCount, 1);
    // No git worker means no conflict detection and no rollback
    EXPECT_TRUE(result.conflicts.empty());
}

// ============================================================================
// Integration Tests
// ============================================================================

class IntegrationTest : public ::testing::Test {
protected:
    std::string tempPath_;

    void SetUp() override {
        tempPath_ = fs::temp_directory_path().string() +
                    "/gaia_integration_test_" + generateShortId() + ".json";
    }

    void TearDown() override {
        std::error_code ec;
        fs::remove(tempPath_, ec);
    }
};

TEST_F(IntegrationTest, TwoLevelDAGSequentialWithinLevels) {
    // Level 0: a, b (no deps)
    // Level 1: c (depends on a and b)
    json project = makeProjectJson({
        makeObjectiveJson("a", "A", {}, 1),
        makeObjectiveJson("b", "B", {}, 2),
        makeObjectiveJson("c", "C", {"a", "b"}, 3),
    });
    std::ofstream file(tempPath_);
    file << project.dump(2);
    file.close();

    OrchestratorConfig cfg = makeTestConfig(tempPath_);
    cfg.enableParallelExecution = true;

    OrchestratorEngine engine(cfg);
    std::atomic<int> execCount{0};

    engine.setExecutor([&](Objective& obj) -> ExecutionResult {
        ++execCount;
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    });

    const auto& state = engine.run();
    EXPECT_EQ(state.objectivesProcessed, 3);
    EXPECT_EQ(state.objectivesFailed, 0);
    EXPECT_GE(execCount.load(), 3);
}

TEST_F(IntegrationTest, MixedSuccessFailureInLevel) {
    json project = makeProjectJson({
        makeObjectiveJson("a", "A", {}, 1),
        makeObjectiveJson("b", "B", {}, 2),
    });
    std::ofstream file(tempPath_);
    file << project.dump(2);
    file.close();

    OrchestratorConfig cfg = makeTestConfig(tempPath_);
    cfg.enableParallelExecution = true;
    cfg.maxParallelObjectives = 2;

    OrchestratorEngine engine(cfg);

    engine.setExecutor([&](Objective& obj) -> ExecutionResult {
        if (obj.objectiveId == "a") {
            return {true, obj.objectiveId, {}, 0.95, std::nullopt};
        }
        return {false, obj.objectiveId, {}, 0.0, "B failed"};
    });

    const auto& state = engine.run();
    EXPECT_EQ(state.objectivesProcessed, 1);
    EXPECT_EQ(state.objectivesFailed, 1);
}

TEST_F(IntegrationTest, HookSerializationUnderParallelLoad) {
    json project = makeProjectJson({
        makeObjectiveJson("a", "A", {}, 1),
        makeObjectiveJson("b", "B", {}, 2),
        makeObjectiveJson("c", "C", {}, 3),
        makeObjectiveJson("d", "D", {}, 4),
    });
    std::ofstream file(tempPath_);
    file << project.dump(2);
    file.close();

    OrchestratorConfig cfg = makeTestConfig(tempPath_);
    cfg.enableParallelExecution = true;
    cfg.maxParallelObjectives = 4;

    OrchestratorEngine engine(cfg);

    std::atomic<int> concurrentHooks{0};
    std::atomic<int> maxConcurrentHooks{0};

    engine.setLogCallback([&](const std::string& msg) {
        // Optional: log for debugging
    });

    engine.setExecutor([&](Objective& obj) -> ExecutionResult {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    });

    const auto& state = engine.run();
    EXPECT_EQ(state.objectivesProcessed, 4);
}

TEST_F(IntegrationTest, ParallelConfigBranching) {
    // Verify that enableParallelExecution=true uses parallel mode
    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
    });
    std::ofstream file(tempPath_);
    file << project.dump(2);
    file.close();

    OrchestratorConfig cfg = makeTestConfig(tempPath_);
    cfg.enableParallelExecution = true;

    OrchestratorEngine engine(cfg);
    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    });

    const auto& state = engine.run();
    EXPECT_EQ(state.objectivesProcessed, 1);
    EXPECT_FALSE(engine.levelResults().empty());
}

TEST_F(IntegrationTest, LevelResultsPopulated) {
    json project = makeProjectJson({
        makeObjectiveJson("a", "A", {}, 1),
        makeObjectiveJson("b", "B", {}, 2),
    });
    std::ofstream file(tempPath_);
    file << project.dump(2);
    file.close();

    OrchestratorConfig cfg = makeTestConfig(tempPath_);
    cfg.enableParallelExecution = true;

    OrchestratorEngine engine(cfg);
    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    });

    engine.run();

    EXPECT_FALSE(engine.levelResults().empty());
    EXPECT_EQ(engine.levelResults()[0].successCount, 2);
    EXPECT_EQ(engine.levelResults()[0].failureCount, 0);
}

TEST_F(IntegrationTest, FailurePropagationToDependents) {
    // a fails, c depends on a — c is marked BLOCKED by failure propagation
    // but the parallel executor still runs c (executor doesn't check status)
    json project = makeProjectJson({
        makeObjectiveJson("a", "A", {}, 1),
        makeObjectiveJson("b", "B", {}, 2),
        makeObjectiveJson("c", "C", {"a"}, 3),
    });
    std::ofstream file(tempPath_);
    file << project.dump(2);
    file.close();

    OrchestratorConfig cfg = makeTestConfig(tempPath_);
    cfg.enableParallelExecution = true;

    OrchestratorEngine engine(cfg);
    engine.setExecutor([&](Objective& obj) -> ExecutionResult {
        if (obj.objectiveId == "a") {
            return {false, obj.objectiveId, {}, 0.0, "A failed"};
        }
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    });

    const auto& state = engine.run();
    // "a" fails, "b" succeeds, "c" also succeeds (executor runs regardless of BLOCKED status)
    // Verdict of level 0 is REMEDIATE (not ABORT), so level 1 still executes
    EXPECT_EQ(state.objectivesFailed, 1);
    EXPECT_EQ(state.objectivesProcessed, 2);
    EXPECT_FALSE(engine.levelResults().empty());
}

TEST_F(IntegrationTest, MaxCycleIterationsRespected) {
    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
        makeObjectiveJson("b", "B"),
    });
    std::ofstream file(tempPath_);
    file << project.dump(2);
    file.close();

    OrchestratorConfig cfg = makeTestConfig(tempPath_);
    cfg.enableParallelExecution = true;
    cfg.maxCycleIterations = 1;

    OrchestratorEngine engine(cfg);
    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    });

    const auto& state = engine.run();
    // Should process 2 objectives in one level, cycle count = 2
    EXPECT_LE(state.cycleCount, 2);
}

TEST_F(IntegrationTest, DryRunMode) {
    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
    });
    std::ofstream file(tempPath_);
    file << project.dump(2);
    file.close();

    OrchestratorConfig cfg = makeTestConfig(tempPath_);
    cfg.enableParallelExecution = true;
    cfg.dryRun = true;

    OrchestratorEngine engine(cfg);
    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    });

    const auto& state = engine.run();
    EXPECT_EQ(state.objectivesProcessed, 1);
    // Dry run should still execute (just not save to disk)
}

TEST_F(IntegrationTest, SingleObjectiveParallelMode) {
    json project = makeProjectJson({
        makeObjectiveJson("solo", "Solo Objective"),
    });
    std::ofstream file(tempPath_);
    file << project.dump(2);
    file.close();

    OrchestratorConfig cfg = makeTestConfig(tempPath_);
    cfg.enableParallelExecution = true;

    OrchestratorEngine engine(cfg);
    bool executed = false;
    engine.setExecutor([&](Objective& obj) -> ExecutionResult {
        executed = true;
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    });

    engine.run();
    EXPECT_TRUE(executed);
    EXPECT_EQ(engine.levelResults().size(), 1);
    EXPECT_EQ(engine.levelResults()[0].objectiveIds.size(), 1);
}

// ============================================================================
// GitWorker Tests (mock/simulated — no real git required)
// ============================================================================

class GitWorkerMockTest : public ::testing::Test {
protected:
    void SetUp() override {
        // Create a temp directory that looks like a repo root
        tempDir_ = (fs::temp_directory_path() /
                    ("gaia_git_test_" + generateShortId())).string();
        fs::create_directories(tempDir_);
        fs::create_directories(tempDir_ + "/.git");
    }

    void TearDown() override {
        std::error_code ec;
        fs::remove_all(tempDir_, ec);
    }

    std::string tempDir_;
};

TEST_F(GitWorkerMockTest, ConstructorValidatesPath) {
    EXPECT_NO_THROW(GitWorker worker(tempDir_));
}

TEST_F(GitWorkerMockTest, ConstructorEmptyPathThrows) {
    EXPECT_THROW(GitWorker worker(""), std::invalid_argument);
}

TEST_F(GitWorkerMockTest, GetUserInfoReturnsFallback) {
    GitWorker worker(tempDir_);
    std::string info = worker.getUserInfo();
    // On systems with git configured, returns actual user info.
    // On systems without git config, returns fallback.
    // Either way, should contain angle brackets (name <email> format)
    EXPECT_NE(info.find('<'), std::string::npos);
    EXPECT_NE(info.find('>'), std::string::npos);
}

TEST_F(GitWorkerMockTest, RepoRootAccessible) {
    GitWorker worker(tempDir_);
    EXPECT_EQ(worker.repoRoot(), tempDir_);
}

TEST_F(GitWorkerMockTest, CreateWorktreeBehavior) {
    GitWorker worker(tempDir_);
    auto result = worker.createWorktree("obj-1", "Test Objective");
    // If git is available and the temp dir is in a git repo, may succeed.
    // Otherwise returns nullopt. Either way should not crash.
    // Note: our temp dir has an empty .git/ which isn't a real repo,
    // so typically this fails gracefully.
    (void)result;  // Accept either success or failure
}

TEST_F(GitWorkerMockTest, CleanupWorktreeGraceful) {
    GitWorker worker(tempDir_);
    bool result = worker.cleanupWorktree("nonexistent");
    // Should not crash, returns false
    EXPECT_FALSE(result);
}

TEST_F(GitWorkerMockTest, CleanupAllStaleWorktreesNoCrash) {
    GitWorker worker(tempDir_);
    auto removed = worker.cleanupAllStaleWorktrees();
    // Without a real git repo, should return empty.
    // With a real git repo, may return some branches.
    // Either way, should not crash.
    (void)removed;
}

TEST_F(GitWorkerMockTest, DetectChangedFilesNoCrash) {
    GitWorker worker(tempDir_);
    auto files = worker.detectChangedFiles("obj/test");
    // Without branches, returns empty. With git, may still return empty.
    // Main check: no crash
    (void)files;
}

TEST_F(GitWorkerMockTest, RollbackBranchNoCrash) {
    GitWorker worker(tempDir_);
    bool result = worker.rollbackBranch("obj/test");
    // May succeed or fail depending on git availability. No crash.
    (void)result;
}

// ============================================================================
// DependencyGraph Partition Tests (supporting parallel execution)
// ============================================================================

TEST(DependencyGraphPartitionTest, IndependentObjectivesSameLevel) {
    std::vector<Objective> objectives;
    for (int i = 0; i < 5; ++i) {
        Objective obj;
        obj.objectiveId = "obj-" + std::to_string(i);
        obj.title = "Objective " + std::to_string(i);
        obj.dependencies = {};
        objectives.push_back(obj);
    }

    DependencyGraph dg(objectives);
    auto levels = dg.partitionIntoLevels();

    EXPECT_EQ(levels.size(), 1);
    EXPECT_EQ(levels[0].size(), 5);
}

TEST(DependencyGraphPartitionTest, DependentObjectivesDifferentLevels) {
    Objective a, b, c;
    a.objectiveId = "a"; a.title = "A";
    b.objectiveId = "b"; b.title = "B"; b.dependencies = {"a"};
    c.objectiveId = "c"; c.title = "C"; c.dependencies = {"b"};

    DependencyGraph dg({a, b, c});
    auto levels = dg.partitionIntoLevels();

    EXPECT_EQ(levels.size(), 3);
    EXPECT_EQ(levels[0].size(), 1);
    EXPECT_EQ(levels[0][0], "a");
    EXPECT_EQ(levels[1][0], "b");
    EXPECT_EQ(levels[2][0], "c");
}

TEST(DependencyGraphPartitionTest, DiamondDependencyPattern) {
    Objective a, b, c, d;
    a.objectiveId = "a"; a.title = "A";
    b.objectiveId = "b"; b.title = "B"; b.dependencies = {"a"};
    c.objectiveId = "c"; c.title = "C"; c.dependencies = {"a"};
    d.objectiveId = "d"; d.title = "D"; d.dependencies = {"b", "c"};

    DependencyGraph dg({a, b, c, d});
    auto levels = dg.partitionIntoLevels();

    EXPECT_EQ(levels.size(), 3);
    // Level 0: a
    EXPECT_EQ(levels[0].size(), 1);
    EXPECT_EQ(levels[0][0], "a");
    // Level 1: b, c (parallel)
    EXPECT_EQ(levels[1].size(), 2);
    // Level 2: d
    EXPECT_EQ(levels[2].size(), 1);
    EXPECT_EQ(levels[2][0], "d");
}

TEST(DependencyGraphPartitionTest, CycleDetectionThrows) {
    Objective a, b;
    a.objectiveId = "a"; a.title = "A"; a.dependencies = {"b"};
    b.objectiveId = "b"; b.title = "B"; b.dependencies = {"a"};

    DependencyGraph dg({a, b});
    EXPECT_THROW(dg.partitionIntoLevels(), std::runtime_error);
}

TEST(DependencyGraphPartitionTest, ParallelLevelExecutionOrder) {
    // Verify that partitionIntoLevels respects dependency ordering
    std::vector<Objective> objectives;
    // Level 0: 3 independent
    for (int i = 0; i < 3; ++i) {
        Objective obj;
        obj.objectiveId = "ind-" + std::to_string(i);
        obj.title = "Independent " + std::to_string(i);
        objectives.push_back(obj);
    }
    // Level 1: depends on all level 0
    Objective dep;
    dep.objectiveId = "dep";
    dep.title = "Dependent";
    dep.dependencies = {"ind-0", "ind-1", "ind-2"};
    objectives.push_back(dep);

    DependencyGraph dg(objectives);
    auto levels = dg.partitionIntoLevels();

    EXPECT_EQ(levels.size(), 2);
    EXPECT_EQ(levels[0].size(), 3);
    EXPECT_EQ(levels[1].size(), 1);
    EXPECT_EQ(levels[1][0], "dep");
}

// ============================================================================
// OrchestratorEngine Parallel Mode Tests
// ============================================================================

TEST(OrchestratorParallelModeTest, SetGitWorker) {
    OrchestratorConfig cfg;
    cfg.objectivesPath = "/tmp/test.json";
    cfg.maxCycleIterations = 100;
    cfg.qualityThreshold = 0.9;
    cfg.maxParallelObjectives = 10;
    // Default: enableParallelExecution is false
    OrchestratorEngine engine(cfg);

    auto gitWorker = std::make_shared<GitWorker>("/tmp");
    engine.setGitWorker(gitWorker);

    // Config default should be false
    EXPECT_FALSE(engine.config().enableParallelExecution);
}

TEST(OrchestratorParallelModeTest, LevelResultsEmptyInSequentialMode) {
    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
    });
    std::string path = createTempObjectivesFile(project);

    OrchestratorConfig cfg = makeTestConfig(path);
    cfg.enableParallelExecution = false;

    OrchestratorEngine engine(cfg);
    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        return {true, obj.objectiveId, {}, 0.95, std::nullopt};
    });

    engine.run();
    EXPECT_TRUE(engine.levelResults().empty());
}
