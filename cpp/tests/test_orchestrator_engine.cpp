// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT

#include <gtest/gtest.h>
#include <gaia/orchestrator_engine.h>

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <string>
#include <unordered_set>

namespace fs = std::filesystem;

using namespace gaia;

// ============================================================================
// Test Helpers
// ============================================================================

/// Create a temporary objectives JSON file for testing.
static std::string createTempObjectivesFile(const json& data) {
    std::string path = fs::temp_directory_path().string() +
                       "/gaia_test_objectives_" + generateShortId() + ".json";
    std::ofstream file(path);
    file << data.dump(2);
    file.close();
    return path;
}

/// Create a simple single-objective project JSON.
static json makeProjectJson(const std::vector<json>& objectives) {
    json j;
    j["project_id"] = "test-proj";
    j["name"] = "Test Project";
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
// Verdict Tests
// ============================================================================

TEST(VerdictTest, StringRoundTrip) {
    EXPECT_EQ(verdictToString(Verdict::Continue), "continue");
    EXPECT_EQ(verdictToString(Verdict::Abort), "abort");
    EXPECT_EQ(verdictToString(Verdict::Pause), "pause");
    EXPECT_EQ(verdictToString(Verdict::Remediate), "remediate");

    EXPECT_EQ(stringToVerdict("continue"), Verdict::Continue);
    EXPECT_EQ(stringToVerdict("abort"), Verdict::Abort);
    EXPECT_EQ(stringToVerdict("pause"), Verdict::Pause);
    EXPECT_EQ(stringToVerdict("remediate"), Verdict::Remediate);
}

TEST(VerdictTest, CaseInsensitive) {
    EXPECT_EQ(stringToVerdict("CONTINUE"), Verdict::Continue);
    EXPECT_EQ(stringToVerdict("ABORT"), Verdict::Abort);
    EXPECT_EQ(stringToVerdict("PAUSE"), Verdict::Pause);
    EXPECT_EQ(stringToVerdict("REMEDIATE"), Verdict::Remediate);
}

TEST(VerdictTest, InvalidStringThrows) {
    EXPECT_THROW(stringToVerdict("invalid"), std::invalid_argument);
    EXPECT_THROW(stringToVerdict(""), std::invalid_argument);
}

// ============================================================================
// ExecutionResult Tests
// ============================================================================

TEST(ExecutionResultTest, DefaultSuccessResult) {
    ExecutionResult r;
    EXPECT_FALSE(r.success);
    EXPECT_TRUE(r.objectiveId.empty());
    EXPECT_TRUE(r.artifacts.empty());
    EXPECT_FALSE(r.qualityScore.has_value());
    EXPECT_FALSE(r.errorMessage.has_value());
}

TEST(ExecutionResultTest, SuccessWithQualityScore) {
    ExecutionResult r;
    r.success = true;
    r.objectiveId = "obj-001";
    r.qualityScore = 0.95;

    json j = r.toJson();
    ExecutionResult restored = ExecutionResult::fromJson(j);

    EXPECT_TRUE(restored.success);
    EXPECT_EQ(restored.objectiveId, "obj-001");
    EXPECT_TRUE(restored.qualityScore.has_value());
    EXPECT_DOUBLE_EQ(restored.qualityScore.value(), 0.95);
}

TEST(ExecutionResultTest, FailureResult) {
    ExecutionResult r;
    r.success = false;
    r.objectiveId = "obj-002";
    r.errorMessage = "Pipeline crashed";

    json j = r.toJson();
    ExecutionResult restored = ExecutionResult::fromJson(j);

    EXPECT_FALSE(restored.success);
    EXPECT_EQ(restored.objectiveId, "obj-002");
    EXPECT_TRUE(restored.errorMessage.has_value());
    EXPECT_EQ(restored.errorMessage.value(), "Pipeline crashed");
}

TEST(ExecutionResultTest, WithArtifacts) {
    ExecutionResult r;
    r.success = true;
    r.objectiveId = "obj-003";

    Artifact art;
    art.name = "output.txt";
    art.artifactType = "file";
    art.urlOrPath = "/tmp/output.txt";
    r.artifacts.push_back(art);

    json j = r.toJson();
    EXPECT_EQ(j["artifacts"][0]["name"], "output.txt");
}

TEST(ExecutionResultTest, NullFieldsPreserved) {
    ExecutionResult r;
    r.success = true;
    r.objectiveId = "obj-null";
    // qualityScore and errorMessage intentionally not set

    json j = r.toJson();
    EXPECT_FALSE(j.contains("quality_score"));
    EXPECT_FALSE(j.contains("error_message"));

    ExecutionResult restored = ExecutionResult::fromJson(j);
    EXPECT_FALSE(restored.qualityScore.has_value());
    EXPECT_FALSE(restored.errorMessage.has_value());
}

// ============================================================================
// OrchestratorConfig Tests
// ============================================================================

TEST(OrchestratorConfigTest, DefaultConstruction) {
    OrchestratorConfig cfg;
    EXPECT_EQ(cfg.objectivesPath, ".gaia/objectives.yaml");
    EXPECT_FALSE(cfg.autoCommit);
    EXPECT_FALSE(cfg.dryRun);
    EXPECT_FALSE(cfg.enableEvaluation);
    EXPECT_EQ(cfg.maxCycleIterations, 100);
    EXPECT_TRUE(cfg.enableNexus);
    EXPECT_FALSE(cfg.enableSupervisor);
    EXPECT_FALSE(cfg.enableGitSupervisor);
    EXPECT_FALSE(cfg.enableParallelExecution);
    EXPECT_EQ(cfg.maxParallelObjectives, 10);
    EXPECT_TRUE(cfg.serializeHooks);
    EXPECT_TRUE(cfg.enableRollback);
    EXPECT_DOUBLE_EQ(cfg.qualityThreshold, 0.90);
}

TEST(OrchestratorConfigTest, FromJsonFull) {
    json j;
    j["objectives_path"] = "custom/path.yaml";
    j["auto_commit"] = true;
    j["dry_run"] = true;
    j["enable_evaluation"] = true;
    j["max_cycle_iterations"] = 50;
    j["enable_nexus"] = false;
    j["enable_supervisor"] = true;
    j["enable_git_supervisor"] = true;
    j["enable_parallel_execution"] = true;
    j["max_parallel_objectives"] = 5;
    j["serialize_hooks"] = false;
    j["enable_rollback"] = false;
    j["quality_threshold"] = 0.85;

    OrchestratorConfig cfg = OrchestratorConfig::fromJson(j);

    EXPECT_EQ(cfg.objectivesPath, "custom/path.yaml");
    EXPECT_TRUE(cfg.autoCommit);
    EXPECT_TRUE(cfg.dryRun);
    EXPECT_TRUE(cfg.enableEvaluation);
    EXPECT_EQ(cfg.maxCycleIterations, 50);
    EXPECT_FALSE(cfg.enableNexus);
    EXPECT_TRUE(cfg.enableSupervisor);
    EXPECT_TRUE(cfg.enableGitSupervisor);
    EXPECT_TRUE(cfg.enableParallelExecution);
    EXPECT_EQ(cfg.maxParallelObjectives, 5);
    EXPECT_FALSE(cfg.serializeHooks);
    EXPECT_FALSE(cfg.enableRollback);
    EXPECT_DOUBLE_EQ(cfg.qualityThreshold, 0.85);
}

TEST(OrchestratorConfigTest, FromJsonPartialRetainsDefaults) {
    json j;
    j["dry_run"] = true;

    OrchestratorConfig cfg = OrchestratorConfig::fromJson(j);

    EXPECT_TRUE(cfg.dryRun);
    EXPECT_EQ(cfg.objectivesPath, ".gaia/objectives.yaml"); // default
    EXPECT_EQ(cfg.maxCycleIterations, 100);                 // default
    EXPECT_DOUBLE_EQ(cfg.qualityThreshold, 0.90);           // default
}

TEST(OrchestratorConfigTest, ToJsonRoundTrip) {
    OrchestratorConfig cfg;
    cfg.dryRun = true;
    cfg.maxCycleIterations = 10;
    cfg.qualityThreshold = 0.80;

    json j = cfg.toJson();
    OrchestratorConfig restored = OrchestratorConfig::fromJson(j);

    EXPECT_TRUE(restored.dryRun);
    EXPECT_EQ(restored.maxCycleIterations, 10);
    EXPECT_DOUBLE_EQ(restored.qualityThreshold, 0.80);
}

TEST(OrchestratorConfigTest, ValidateEmptyPath) {
    OrchestratorConfig cfg;
    cfg.objectivesPath = "";
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(OrchestratorConfigTest, ValidateZeroMaxCycles) {
    OrchestratorConfig cfg;
    cfg.maxCycleIterations = 0;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(OrchestratorConfigTest, ValidateNegativeMaxCycles) {
    OrchestratorConfig cfg;
    cfg.maxCycleIterations = -1;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(OrchestratorConfigTest, ValidateZeroParallel) {
    OrchestratorConfig cfg;
    cfg.maxParallelObjectives = 0;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(OrchestratorConfigTest, ValidateInvalidQualityHigh) {
    OrchestratorConfig cfg;
    cfg.qualityThreshold = 1.5;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(OrchestratorConfigTest, ValidateInvalidQualityLow) {
    OrchestratorConfig cfg;
    cfg.qualityThreshold = -0.1;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(OrchestratorConfigTest, ValidateBoundaryQualityZero) {
    OrchestratorConfig cfg;
    cfg.qualityThreshold = 0.0;
    cfg.objectivesPath = "test.json"; // avoid empty path error
    EXPECT_NO_THROW(cfg.validate());
}

TEST(OrchestratorConfigTest, ValidateBoundaryQualityOne) {
    OrchestratorConfig cfg;
    cfg.qualityThreshold = 1.0;
    cfg.objectivesPath = "test.json";
    EXPECT_NO_THROW(cfg.validate());
}

// ============================================================================
// OrchestratorState Tests
// ============================================================================

TEST(OrchestratorStateTest, DefaultConstruction) {
    OrchestratorState s;
    EXPECT_FALSE(s.paused);
    EXPECT_EQ(s.cycleCount, 0);
    EXPECT_EQ(s.objectivesProcessed, 0);
    EXPECT_EQ(s.objectivesFailed, 0);
    EXPECT_TRUE(s.executionHistory.empty());
    EXPECT_TRUE(s.objectiveBranches.empty());
}

TEST(OrchestratorStateTest, RecordCycleSuccess) {
    OrchestratorState s;
    s.recordCycle("obj-001", true);

    EXPECT_EQ(s.cycleCount, 1);
    EXPECT_EQ(s.objectivesProcessed, 1);
    EXPECT_EQ(s.objectivesFailed, 0);
    ASSERT_EQ(s.executionHistory.size(), 1u);
    EXPECT_EQ(s.executionHistory[0].objectiveId, "obj-001");
    EXPECT_TRUE(s.executionHistory[0].success);
    EXPECT_EQ(s.executionHistory[0].cycle, 1);
}

TEST(OrchestratorStateTest, RecordCycleFailure) {
    OrchestratorState s;
    s.recordCycle("obj-002", false);

    EXPECT_EQ(s.cycleCount, 1);
    EXPECT_EQ(s.objectivesProcessed, 0);
    EXPECT_EQ(s.objectivesFailed, 1);
    ASSERT_EQ(s.executionHistory.size(), 1u);
    EXPECT_FALSE(s.executionHistory[0].success);
}

TEST(OrchestratorStateTest, RecordCycleMultiple) {
    OrchestratorState s;
    s.recordCycle("obj-a", true);
    s.recordCycle("obj-b", true);
    s.recordCycle("obj-c", false);
    s.recordCycle("obj-d", true);

    EXPECT_EQ(s.cycleCount, 4);
    EXPECT_EQ(s.objectivesProcessed, 3);
    EXPECT_EQ(s.objectivesFailed, 1);
    ASSERT_EQ(s.executionHistory.size(), 4u);
    EXPECT_EQ(s.executionHistory[3].cycle, 4);
}

TEST(OrchestratorStateTest, ToJson) {
    OrchestratorState s;
    s.paused = true;
    s.recordCycle("obj-001", true);
    s.recordCycle("obj-002", false);
    s.objectiveBranches["obj-001"] = "obj/001-slug";

    json j = s.toJson();

    EXPECT_EQ(j["paused"], true);
    EXPECT_EQ(j["cycle_count"], 2);
    EXPECT_EQ(j["objectives_processed"], 1);
    EXPECT_EQ(j["objectives_failed"], 1);
    EXPECT_EQ(j["execution_history"].size(), 2u);
    EXPECT_EQ(j["objective_branches"]["obj-001"], "obj/001-slug");
}

TEST(OrchestratorStateTest, FromJsonRoundTrip) {
    OrchestratorState s;
    s.recordCycle("obj-x", true);
    s.objectiveBranches["obj-x"] = "branch-1";

    json j = s.toJson();
    OrchestratorState restored = OrchestratorState::fromJson(j);

    EXPECT_EQ(restored.cycleCount, 1);
    EXPECT_EQ(restored.objectivesProcessed, 1);
    EXPECT_EQ(restored.objectiveBranches["obj-x"], "branch-1");
}

// ============================================================================
// OrchestratorEngine Construction Tests
// ============================================================================

TEST(OrchestratorEngineTest, DefaultConstruction) {
    OrchestratorEngine engine;
    EXPECT_FALSE(engine.project().has_value());
    EXPECT_EQ(engine.state().cycleCount, 0);
}

TEST(OrchestratorEngineTest, WithCustomConfig) {
    OrchestratorConfig cfg;
    cfg.dryRun = true;
    cfg.maxCycleIterations = 5;
    cfg.objectivesPath = "test.json";

    OrchestratorEngine engine(cfg);

    EXPECT_TRUE(engine.config().dryRun);
    EXPECT_EQ(engine.config().maxCycleIterations, 5);
}

TEST(OrchestratorEngineTest, NonCopyable) {
    OrchestratorEngine engine;
    // Verify non-copyable at compile time -- these should not compile:
    // OrchestratorEngine copy(engine);
    // OrchestratorEngine assigned = engine;
    static_assert(!std::is_copy_constructible_v<OrchestratorEngine>);
    static_assert(!std::is_copy_assignable_v<OrchestratorEngine>);
}

TEST(OrchestratorEngineTest, NonMovable) {
    OrchestratorEngine engine;
    static_assert(!std::is_move_constructible_v<OrchestratorEngine>);
    static_assert(!std::is_move_assignable_v<OrchestratorEngine>);
}

TEST(OrchestratorEngineTest, SetExecutor) {
    OrchestratorEngine engine;
    int callCount = 0;

    engine.setExecutor([&callCount](Objective& obj) -> ExecutionResult {
        callCount++;
        ExecutionResult r;
        r.success = true;
        r.objectiveId = obj.objectiveId;
        return r;
    });

    // Executor is set; it will be called when run() executes objectives
}

TEST(OrchestratorEngineTest, SetLogCallback) {
    OrchestratorEngine engine;
    std::vector<std::string> logs;

    engine.setLogCallback([&logs](const std::string& msg) {
        logs.push_back(msg);
    });

    // Logger callback set; messages will be captured
}

TEST(OrchestratorEngineTest, SetConfigReplacesExisting) {
    OrchestratorEngine engine;
    EXPECT_EQ(engine.config().maxCycleIterations, 100);

    OrchestratorConfig cfg;
    cfg.maxCycleIterations = 10;
    cfg.objectivesPath = "test.json";
    engine.setConfig(cfg);

    EXPECT_EQ(engine.config().maxCycleIterations, 10);
}

TEST(OrchestratorEngineTest, SetConfigInvalid) {
    OrchestratorEngine engine;

    OrchestratorConfig cfg;
    cfg.objectivesPath = ""; // invalid
    EXPECT_THROW(engine.setConfig(cfg), std::invalid_argument);
}

// ============================================================================
// OrchestratorEngine loadObjectives Tests
// ============================================================================

TEST(OrchestratorEngineTest, LoadObjectivesFromJson) {
    OrchestratorEngine engine;

    json project = makeProjectJson({
        makeObjectiveJson("obj-001", "First task"),
        makeObjectiveJson("obj-002", "Second task", {"obj-001"})
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);
    fs::remove(path);

    ASSERT_TRUE(engine.project().has_value());
    EXPECT_EQ(engine.project()->objectives.size(), 2u);
}

TEST(OrchestratorEngineTest, LoadObjectivesInvalidPath) {
    OrchestratorEngine engine;
    EXPECT_THROW(engine.loadObjectives("/nonexistent/path.json"),
                 std::runtime_error);
}

TEST(OrchestratorEngineTest, LoadObjectivesBuildsDepGraph) {
    OrchestratorEngine engine;

    json project = makeProjectJson({
        makeObjectiveJson("a", "A"),
        makeObjectiveJson("b", "B", {"a"}),
        makeObjectiveJson("c", "C", {"a", "b"})
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);
    fs::remove(path);

    auto deps = engine.dependencyGraph().getDependencies("c");
    EXPECT_EQ(deps.size(), 2u);
    EXPECT_NE(deps.find("a"), deps.end());
    EXPECT_NE(deps.find("b"), deps.end());
}

// ============================================================================
// OrchestratorEngine run() -- Sequential Dispatch Loop
// ============================================================================

TEST(OrchestratorEngineTest, RunSingleObjectiveSucceeds) {
    OrchestratorEngine engine;

    json project = makeProjectJson({
        makeObjectiveJson("obj-001", "Single task")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.success = true;
        r.objectiveId = obj.objectiveId;
        r.qualityScore = 0.95;
        return r;
    });

    const auto& state = engine.run();

    EXPECT_EQ(state.cycleCount, 1);
    EXPECT_EQ(state.objectivesProcessed, 1);
    EXPECT_EQ(state.objectivesFailed, 0);

    // Objective should be completed
    const auto* obj = engine.project()->getObjective("obj-001");
    ASSERT_NE(obj, nullptr);
    EXPECT_EQ(obj->status, ObjectiveStatus::Completed);

    fs::remove(path);
}

TEST(OrchestratorEngineTest, RunSingleObjectiveFails) {
    OrchestratorEngine engine;

    json project = makeProjectJson({
        makeObjectiveJson("obj-001", "Failing task")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.success = false;
        r.objectiveId = obj.objectiveId;
        r.errorMessage = "Pipeline error";
        return r;
    });

    const auto& state = engine.run();

    EXPECT_EQ(state.cycleCount, 1);
    EXPECT_EQ(state.objectivesProcessed, 0);
    EXPECT_EQ(state.objectivesFailed, 1);

    const auto* obj = engine.project()->getObjective("obj-001");
    ASSERT_NE(obj, nullptr);
    EXPECT_EQ(obj->status, ObjectiveStatus::Blocked);

    fs::remove(path);
}

TEST(OrchestratorEngineTest, RunTwoDependentObjectives) {
    OrchestratorEngine engine;

    json project = makeProjectJson({
        makeObjectiveJson("obj-001", "First"),
        makeObjectiveJson("obj-002", "Second", {"obj-001"})
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.success = true;
        r.objectiveId = obj.objectiveId;
        return r;
    });

    const auto& state = engine.run();

    EXPECT_EQ(state.cycleCount, 2);
    EXPECT_EQ(state.objectivesProcessed, 2);

    // Both objectives should be completed
    EXPECT_EQ(engine.project()->getObjective("obj-001")->status,
              ObjectiveStatus::Completed);
    EXPECT_EQ(engine.project()->getObjective("obj-002")->status,
              ObjectiveStatus::Completed);

    fs::remove(path);
}

TEST(OrchestratorEngineTest, RunThreeObjectivesMixedSuccess) {
    OrchestratorEngine engine;

    json project = makeProjectJson({
        makeObjectiveJson("obj-a", "Will succeed"),
        makeObjectiveJson("obj-b", "Will fail"),
        makeObjectiveJson("obj-c", "Depends on b", {"obj-b"})
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    // Succeed for obj-a, fail for obj-b
    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.objectiveId = obj.objectiveId;
        r.success = (obj.objectiveId == "obj-a");
        if (!r.success) r.errorMessage = "Failed";
        return r;
    });

    const auto& state = engine.run();

    // obj-a runs and succeeds (1 cycle)
    // obj-b runs and fails (1 cycle)
    // obj-c has dep on obj-b (failed) -- should be blocked via propagation
    EXPECT_EQ(state.cycleCount, 2);
    EXPECT_EQ(state.objectivesProcessed, 1);
    EXPECT_EQ(state.objectivesFailed, 1);

    EXPECT_EQ(engine.project()->getObjective("obj-a")->status,
              ObjectiveStatus::Completed);
    EXPECT_EQ(engine.project()->getObjective("obj-b")->status,
              ObjectiveStatus::Blocked);

    fs::remove(path);
}

TEST(OrchestratorEngineTest, RunNoExecutor) {
    OrchestratorEngine engine;

    json project = makeProjectJson({
        makeObjectiveJson("obj-001", "No executor")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    // No executor set -- execution should fail
    const auto& state = engine.run();

    EXPECT_EQ(state.cycleCount, 1);
    EXPECT_EQ(state.objectivesFailed, 1);

    const auto* obj = engine.project()->getObjective("obj-001");
    ASSERT_NE(obj, nullptr);
    EXPECT_EQ(obj->status, ObjectiveStatus::Blocked);
    EXPECT_TRUE(obj->errorMessage.has_value());

    fs::remove(path);
}

TEST(OrchestratorEngineTest, RunDryRun) {
    OrchestratorConfig cfg;
    cfg.dryRun = true;
    cfg.objectivesPath = "test.json"; // won't be written to
    OrchestratorEngine engine(cfg);

    json project = makeProjectJson({
        makeObjectiveJson("obj-001", "Dry run test")
    });

    // Load directly from JSON data instead of file path for dry run test
    engine.mutableState(); // just to verify state access works

    // For dry run, we still load from a temp file but don't write back
    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.success = true;
        r.objectiveId = obj.objectiveId;
        return r;
    });

    const auto& state = engine.run();
    EXPECT_EQ(state.objectivesProcessed, 1);

    fs::remove(path);
}

TEST(OrchestratorEngineTest, RunMaxCyclesReached) {
    OrchestratorConfig cfg;
    cfg.maxCycleIterations = 2;
    cfg.objectivesPath = "test.json";
    OrchestratorEngine engine(cfg);

    // 3 objectives but max 2 cycles
    json project = makeProjectJson({
        makeObjectiveJson("obj-a", "A"),
        makeObjectiveJson("obj-b", "B"),
        makeObjectiveJson("obj-c", "C")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.success = true;
        r.objectiveId = obj.objectiveId;
        return r;
    });

    const auto& state = engine.run();

    EXPECT_EQ(state.cycleCount, 2); // stopped at max
    // Only 2 of 3 objectives completed
    EXPECT_EQ(state.objectivesProcessed, 2);

    fs::remove(path);
}

TEST(OrchestratorEngineTest, RunAllCompletedBeforeMaxCycles) {
    OrchestratorEngine engine;

    // 2 objectives, both succeed
    json project = makeProjectJson({
        makeObjectiveJson("obj-a", "A"),
        makeObjectiveJson("obj-b", "B")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.success = true;
        r.objectiveId = obj.objectiveId;
        return r;
    });

    const auto& state = engine.run();

    // Should exit early after 2 cycles (all done), not at 100
    EXPECT_EQ(state.cycleCount, 2);

    fs::remove(path);
}

TEST(OrchestratorEngineTest, RunAllCompletedAlready) {
    OrchestratorEngine engine;

    // All objectives already completed
    json project = makeProjectJson({
        makeObjectiveJson("obj-a", "A", {}, 5, "completed"),
        makeObjectiveJson("obj-b", "B", {}, 5, "completed")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    int executeCount = 0;
    engine.setExecutor([&executeCount](Objective& obj) -> ExecutionResult {
        executeCount++;
        return {true, obj.objectiveId};
    });

    const auto& state = engine.run();

    // Should exit immediately without executing anything
    EXPECT_EQ(state.cycleCount, 0);
    EXPECT_EQ(executeCount, 0);

    fs::remove(path);
}

TEST(OrchestratorEngineTest, RunPriorityOrder) {
    OrchestratorEngine engine;

    // Three objectives with different priorities
    json project = makeProjectJson({
        makeObjectiveJson("obj-low", "Low priority", {}, 10),
        makeObjectiveJson("obj-high", "High priority", {}, 1),
        makeObjectiveJson("obj-mid", "Medium priority", {}, 5)
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    std::vector<std::string> executionOrder;
    engine.setExecutor([&executionOrder](Objective& obj) -> ExecutionResult {
        executionOrder.push_back(obj.objectiveId);
        return {true, obj.objectiveId};
    });

    engine.run();

    // Should execute in priority order: high (1), mid (5), low (10)
    ASSERT_EQ(executionOrder.size(), 3u);
    EXPECT_EQ(executionOrder[0], "obj-high");
    EXPECT_EQ(executionOrder[1], "obj-mid");
    EXPECT_EQ(executionOrder[2], "obj-low");

    fs::remove(path);
}

TEST(OrchestratorEngineTest, RunWithArtifacts) {
    OrchestratorEngine engine;

    json project = makeProjectJson({
        makeObjectiveJson("obj-001", "Produce artifacts")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.success = true;
        r.objectiveId = obj.objectiveId;

        Artifact art;
        art.name = "output.txt";
        art.artifactType = "file";
        art.urlOrPath = "/tmp/output.txt";
        r.artifacts.push_back(art);
        return r;
    });

    engine.run();

    const auto* obj = engine.project()->getObjective("obj-001");
    ASSERT_NE(obj, nullptr);
    EXPECT_EQ(obj->status, ObjectiveStatus::Completed);
    EXPECT_EQ(obj->artifacts.size(), 1u);
    EXPECT_EQ(obj->artifacts[0].name, "output.txt");

    fs::remove(path);
}

// ============================================================================
// Status Transition Tests (_apply_status_transition)
// ============================================================================

TEST(StatusTransitionTest, QueuedToCompleted) {
    Objective o;
    o.objectiveId = "obj-t1";
    o.title = "Transition Test";
    EXPECT_EQ(o.status, ObjectiveStatus::Queued);

    OrchestratorEngine::applyStatusTransition(o, ObjectiveStatus::Completed);

    EXPECT_EQ(o.status, ObjectiveStatus::Completed);
}

TEST(StatusTransitionTest, QueuedToBlocked) {
    Objective o;
    o.objectiveId = "obj-t2";
    o.title = "Transition Test";
    EXPECT_EQ(o.status, ObjectiveStatus::Queued);

    OrchestratorEngine::applyStatusTransition(o, ObjectiveStatus::Blocked);

    EXPECT_EQ(o.status, ObjectiveStatus::Blocked);
}

TEST(StatusTransitionTest, InProgressToCompleted) {
    Objective o;
    o.objectiveId = "obj-t3";
    o.title = "Transition Test";
    o.status = ObjectiveStatus::InProgress;

    OrchestratorEngine::applyStatusTransition(o, ObjectiveStatus::Completed);

    EXPECT_EQ(o.status, ObjectiveStatus::Completed);
}

TEST(StatusTransitionTest, InProgressToBlocked) {
    Objective o;
    o.objectiveId = "obj-t4";
    o.title = "Transition Test";
    o.status = ObjectiveStatus::InProgress;

    OrchestratorEngine::applyStatusTransition(o, ObjectiveStatus::Blocked);

    EXPECT_EQ(o.status, ObjectiveStatus::Blocked);
}

TEST(StatusTransitionTest, AlreadyCompletedNoOp) {
    Objective o;
    o.objectiveId = "obj-t5";
    o.title = "Transition Test";
    o.status = ObjectiveStatus::Completed;

    // Should not throw even though COMPLETED -> COMPLETED is invalid
    EXPECT_NO_THROW(OrchestratorEngine::applyStatusTransition(
        o, ObjectiveStatus::Completed));

    EXPECT_EQ(o.status, ObjectiveStatus::Completed);
}

TEST(StatusTransitionTest, AlreadyCancelledNoOp) {
    Objective o;
    o.objectiveId = "obj-t6";
    o.title = "Transition Test";
    o.status = ObjectiveStatus::Cancelled;

    EXPECT_NO_THROW(OrchestratorEngine::applyStatusTransition(
        o, ObjectiveStatus::Blocked));

    EXPECT_EQ(o.status, ObjectiveStatus::Cancelled);
}

// ============================================================================
// Evaluation Tests
// ============================================================================

TEST(EvaluationTest, PassWithQualityAboveThreshold) {
    OrchestratorEngine engine;

    ExecutionResult result;
    result.success = true;
    result.objectiveId = "obj-e1";
    result.qualityScore = 0.95;

    Objective obj;
    obj.objectiveId = "obj-e1";

    auto eval = engine.evaluate(result, obj);

    EXPECT_EQ(eval.verdict, "PASS");
    EXPECT_TRUE(eval.qualityScore.has_value());
}

TEST(EvaluationTest, PassWithoutQualityScore) {
    OrchestratorEngine engine;

    ExecutionResult result;
    result.success = true;
    result.objectiveId = "obj-e2";
    // qualityScore not set

    Objective obj;
    obj.objectiveId = "obj-e2";

    auto eval = engine.evaluate(result, obj);

    EXPECT_EQ(eval.verdict, "PASS");
    EXPECT_EQ(eval.reason, "Pipeline succeeded without quality score");
}

TEST(EvaluationTest, ReviewWithQualityBelowThreshold) {
    OrchestratorEngine engine;

    ExecutionResult result;
    result.success = true;
    result.objectiveId = "obj-e3";
    result.qualityScore = 0.75;

    Objective obj;
    obj.objectiveId = "obj-e3";

    auto eval = engine.evaluate(result, obj);

    EXPECT_EQ(eval.verdict, "REVIEW");
    EXPECT_EQ(eval.objectiveId, "obj-e3");
    EXPECT_TRUE(eval.qualityScore.has_value());
    EXPECT_DOUBLE_EQ(eval.qualityScore.value(), 0.75);
}

TEST(EvaluationTest, FailWhenExecutionFailed) {
    OrchestratorEngine engine;

    ExecutionResult result;
    result.success = false;
    result.objectiveId = "obj-e4";
    result.errorMessage = "Pipeline error";

    Objective obj;
    obj.objectiveId = "obj-e4";

    auto eval = engine.evaluate(result, obj);

    EXPECT_EQ(eval.verdict, "FAIL");
    EXPECT_EQ(eval.objectiveId, "obj-e4");
}

TEST(EvaluationTest, ExactThresholdIsPass) {
    OrchestratorEngine engine;

    ExecutionResult result;
    result.success = true;
    result.objectiveId = "obj-e5";
    result.qualityScore = 0.90; // exactly at threshold

    Objective obj;
    obj.objectiveId = "obj-e5";

    auto eval = engine.evaluate(result, obj);

    EXPECT_EQ(eval.verdict, "PASS");
}

TEST(EvaluationTest, CustomThreshold) {
    OrchestratorConfig cfg;
    cfg.qualityThreshold = 0.70;
    cfg.objectivesPath = "test.json";
    OrchestratorEngine engine(cfg);

    ExecutionResult result;
    result.success = true;
    result.objectiveId = "obj-e6";
    result.qualityScore = 0.80; // above custom threshold, below default

    Objective obj;
    obj.objectiveId = "obj-e6";

    auto eval = engine.evaluate(result, obj);

    EXPECT_EQ(eval.verdict, "PASS");
}

TEST(EvaluationTest, BelowCustomThreshold) {
    OrchestratorConfig cfg;
    cfg.qualityThreshold = 0.90;
    cfg.objectivesPath = "test.json";
    OrchestratorEngine engine(cfg);

    ExecutionResult result;
    result.success = true;
    result.objectiveId = "obj-e7";
    result.qualityScore = 0.85;

    Objective obj;
    obj.objectiveId = "obj-e7";

    auto eval = engine.evaluate(result, obj);

    EXPECT_EQ(eval.verdict, "REVIEW");
}

// ============================================================================
// Failure Propagation Tests (exercised through run())
// ============================================================================

TEST(FailurePropagationTest, DependentGetsBlockedViaRun) {
    OrchestratorEngine engine;

    // obj-a will fail, obj-b depends on obj-a and should get blocked
    json project = makeProjectJson({
        makeObjectiveJson("obj-a", "Will fail"),
        makeObjectiveJson("obj-b", "Depends on a", {"obj-a"})
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    // Fail only obj-a
    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.objectiveId = obj.objectiveId;
        r.success = (obj.objectiveId != "obj-a");
        if (!r.success) r.errorMessage = "Failed";
        return r;
    });

    engine.run();

    // obj-a should be BLOCKED (failed execution)
    EXPECT_EQ(engine.project()->getObjective("obj-a")->status,
              ObjectiveStatus::Blocked);

    // obj-b should be BLOCKED due to failure propagation from obj-a
    EXPECT_EQ(engine.project()->getObjective("obj-b")->status,
              ObjectiveStatus::Blocked);
    EXPECT_TRUE(engine.project()->getObjective("obj-b")->errorMessage.has_value());
    EXPECT_EQ(engine.project()->getObjective("obj-b")->errorMessage.value(),
              "Dependency failed: obj-a");

    fs::remove(path);
}

TEST(FailurePropagationTest, NoDepsUnaffectedViaRun) {
    OrchestratorEngine engine;

    // obj-a fails, obj-b is independent (no deps on a)
    json project = makeProjectJson({
        makeObjectiveJson("obj-a", "Will fail"),
        makeObjectiveJson("obj-b", "Independent")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.objectiveId = obj.objectiveId;
        r.success = (obj.objectiveId != "obj-a");
        if (!r.success) r.errorMessage = "Failed";
        return r;
    });

    engine.run();

    // Both should have been attempted since they're independent
    // obj-a fails, obj-b succeeds
    EXPECT_EQ(engine.project()->getObjective("obj-a")->status,
              ObjectiveStatus::Blocked);
    EXPECT_EQ(engine.project()->getObjective("obj-b")->status,
              ObjectiveStatus::Completed);

    fs::remove(path);
}

TEST(FailurePropagationTest, CascadeBlocking) {
    OrchestratorEngine engine;

    // a -> b -> c: if b fails, c should not run
    json project = makeProjectJson({
        makeObjectiveJson("a", "Root"),
        makeObjectiveJson("b", "Depends on a", {"a"}),
        makeObjectiveJson("c", "Depends on b", {"b"})
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    // Succeed a, fail b
    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.objectiveId = obj.objectiveId;
        r.success = (obj.objectiveId == "a");
        if (!r.success) r.errorMessage = "Failed";
        return r;
    });

    engine.run();

    // a completes, b fails, c is blocked due to failure propagation
    EXPECT_EQ(engine.project()->getObjective("a")->status,
              ObjectiveStatus::Completed);
    EXPECT_EQ(engine.project()->getObjective("b")->status,
              ObjectiveStatus::Blocked);
    EXPECT_EQ(engine.project()->getObjective("c")->status,
              ObjectiveStatus::Blocked);
    EXPECT_TRUE(engine.project()->getObjective("c")->errorMessage.has_value());
    EXPECT_EQ(engine.project()->getObjective("c")->errorMessage.value(),
              "Dependency failed: b");

    fs::remove(path);
}

TEST(FailurePropagationTest, BlockedErrorMessageContainsDependencyId) {
    OrchestratorEngine engine;

    // obj-a will fail, obj-b depends on obj-a
    // When obj-b is blocked, its errorMessage should reference "obj-a",
    // not "obj-b" (the original bug used the wrong variable)
    json project = makeProjectJson({
        makeObjectiveJson("obj-a", "Will fail"),
        makeObjectiveJson("obj-b", "Depends on a", {"obj-a"}),
        makeObjectiveJson("obj-c", "Depends on a and b", {"obj-a", "obj-b"})
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    // Fail obj-a, succeed everything else
    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.objectiveId = obj.objectiveId;
        r.success = (obj.objectiveId != "obj-a");
        if (!r.success) r.errorMessage = "Pipeline error";
        return r;
    });

    engine.run();

    // obj-a fails, obj-b and obj-c should be blocked via propagation
    const auto* objB = engine.project()->getObjective("obj-b");
    ASSERT_NE(objB, nullptr);
    EXPECT_EQ(objB->status, ObjectiveStatus::Blocked);
    ASSERT_TRUE(objB->errorMessage.has_value());
    // The error message MUST contain the dependency ID "obj-a", not "obj-b"
    EXPECT_TRUE(objB->errorMessage.value().find("obj-a") != std::string::npos)
        << "Expected error message to contain 'obj-a' (the failed dependency), "
        << "but got: " << objB->errorMessage.value();
    // Verify it does NOT incorrectly reference the objective's own ID
    EXPECT_TRUE(objB->errorMessage.value().find("obj-b") == std::string::npos)
        << "Error message should not contain the blocked objective's own ID";

    // Also verify obj-c was blocked with the right dependency reference
    const auto* objC = engine.project()->getObjective("obj-c");
    ASSERT_NE(objC, nullptr);
    EXPECT_EQ(objC->status, ObjectiveStatus::Blocked);
    ASSERT_TRUE(objC->errorMessage.has_value());
    EXPECT_TRUE(objC->errorMessage.value().find("obj-a") != std::string::npos ||
                objC->errorMessage.value().find("obj-b") != std::string::npos)
        << "Expected error message to contain a failed dependency ID";

    fs::remove(path);
}

// ============================================================================
// Pause/Resume Tests
// ============================================================================

TEST(PauseResumeTest, PauseSetsState) {
    OrchestratorEngine engine;
    engine.pause("Testing");

    EXPECT_TRUE(engine.state().paused);
}

TEST(PauseResumeTest, ResumeClearsState) {
    OrchestratorEngine engine;
    engine.pause("Testing");
    engine.resume();

    EXPECT_FALSE(engine.state().paused);
}

TEST(PauseResumeTest, PauseWithReason) {
    OrchestratorEngine engine;
    engine.pause("Manual pause for maintenance");

    EXPECT_TRUE(engine.state().paused);
}

// ============================================================================
// Dependency Graph Integration Tests
// ============================================================================

TEST(DepGraphIntegrationTest, LoadObjectivesLevelsCorrect) {
    OrchestratorEngine engine;

    // Diamond dependency:
    //     a
    //    / \
    //   b   c
    //    \ /
    //     d
    json project = makeProjectJson({
        makeObjectiveJson("a", "Root"),
        makeObjectiveJson("b", "Left", {"a"}),
        makeObjectiveJson("c", "Right", {"a"}),
        makeObjectiveJson("d", "Bottom", {"b", "c"})
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    auto levels = engine.dependencyGraph().partitionIntoLevels();

    EXPECT_EQ(levels.size(), 3u);
    // Level 0: a
    // Level 1: b, c
    // Level 2: d

    std::unordered_set<std::string> level0(levels[0].begin(), levels[0].end());
    EXPECT_EQ(level0.count("a"), 1u);

    std::unordered_set<std::string> level1(levels[1].begin(), levels[1].end());
    EXPECT_EQ(level1.count("b"), 1u);
    EXPECT_EQ(level1.count("c"), 1u);

    std::unordered_set<std::string> level2(levels[2].begin(), levels[2].end());
    EXPECT_EQ(level2.count("d"), 1u);

    fs::remove(path);
}

TEST(DepGraphIntegrationTest, DiamondExecutionOrder) {
    OrchestratorEngine engine;

    json project = makeProjectJson({
        makeObjectiveJson("a", "Root"),
        makeObjectiveJson("b", "Left", {"a"}),
        makeObjectiveJson("c", "Right", {"a"}),
        makeObjectiveJson("d", "Bottom", {"b", "c"})
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    std::vector<std::string> executionOrder;
    engine.setExecutor([&executionOrder](Objective& obj) -> ExecutionResult {
        executionOrder.push_back(obj.objectiveId);
        return {true, obj.objectiveId};
    });

    engine.run();

    // a must run before b and c; b and c must run before d
    auto posA = std::find(executionOrder.begin(), executionOrder.end(), "a") -
                executionOrder.begin();
    auto posB = std::find(executionOrder.begin(), executionOrder.end(), "b") -
                executionOrder.begin();
    auto posC = std::find(executionOrder.begin(), executionOrder.end(), "c") -
                executionOrder.begin();
    auto posD = std::find(executionOrder.begin(), executionOrder.end(), "d") -
                executionOrder.begin();

    EXPECT_LT(posA, posB);
    EXPECT_LT(posA, posC);
    EXPECT_LT(posB, posD);
    EXPECT_LT(posC, posD);

    fs::remove(path);
}

// ============================================================================
// Edge Case Tests
// ============================================================================

TEST(EdgeCaseTest, RunWithCancelledObjective) {
    OrchestratorEngine engine;

    json project = makeProjectJson({
        makeObjectiveJson("obj-done", "Already cancelled", {}, 5, "cancelled"),
        makeObjectiveJson("obj-work", "Work to do")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        return {true, obj.objectiveId};
    });

    const auto& state = engine.run();

    // Only obj-work should be executed
    EXPECT_EQ(state.objectivesProcessed, 1);
    EXPECT_EQ(state.cycleCount, 1);

    fs::remove(path);
}

TEST(EdgeCaseTest, RunWithMixedStatuses) {
    OrchestratorEngine engine;

    json project = makeProjectJson({
        makeObjectiveJson("obj-done", "Done", {}, 5, "completed"),
        makeObjectiveJson("obj-work", "Work", {}),
        makeObjectiveJson("obj-blocked", "Blocked", {}, 5, "blocked")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        return {true, obj.objectiveId};
    });

    const auto& state = engine.run();

    // Only obj-work should be executed (QUEUED and ready)
    EXPECT_EQ(state.objectivesProcessed, 1);
    EXPECT_EQ(state.cycleCount, 1);

    fs::remove(path);
}

TEST(EdgeCaseTest, RunWithEmptyObjectivesFile) {
    OrchestratorEngine engine;

    json project = makeProjectJson({});

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    const auto& state = engine.run();

    // No cycles needed -- nothing to execute
    EXPECT_EQ(state.cycleCount, 0);

    fs::remove(path);
}

// ============================================================================
// LogCallback Tests
// ============================================================================

TEST(LogCallbackTest, LoggerReceivesMessages) {
    OrchestratorEngine engine;
    std::vector<std::string> logs;

    engine.setLogCallback([&logs](const std::string& msg) {
        logs.push_back(msg);
    });

    json project = makeProjectJson({
        makeObjectiveJson("obj-log", "Log test")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        return {true, obj.objectiveId};
    });

    engine.run();

    // Should have received log messages
    EXPECT_FALSE(logs.empty());

    fs::remove(path);
}
