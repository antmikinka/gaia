// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT

#include <gtest/gtest.h>
#include <gaia/orchestrator_types.h>

#include <algorithm>
#include <cmath>
#include <set>
#include <string>
#include <unordered_set>

using namespace gaia;

// ---------------------------------------------------------------------------
// ObjectiveStatus Tests
// ---------------------------------------------------------------------------

TEST(ObjectiveStatusTest, StringRoundTrip) {
    EXPECT_EQ(objectiveStatusToString(ObjectiveStatus::Queued), "queued");
    EXPECT_EQ(objectiveStatusToString(ObjectiveStatus::InProgress), "in_progress");
    EXPECT_EQ(objectiveStatusToString(ObjectiveStatus::Completed), "completed");
    EXPECT_EQ(objectiveStatusToString(ObjectiveStatus::Blocked), "blocked");
    EXPECT_EQ(objectiveStatusToString(ObjectiveStatus::Cancelled), "cancelled");

    EXPECT_EQ(stringToObjectiveStatus("queued"), ObjectiveStatus::Queued);
    EXPECT_EQ(stringToObjectiveStatus("in_progress"), ObjectiveStatus::InProgress);
    EXPECT_EQ(stringToObjectiveStatus("completed"), ObjectiveStatus::Completed);
    EXPECT_EQ(stringToObjectiveStatus("blocked"), ObjectiveStatus::Blocked);
    EXPECT_EQ(stringToObjectiveStatus("cancelled"), ObjectiveStatus::Cancelled);
}

TEST(ObjectiveStatusTest, InvalidStringThrows) {
    EXPECT_THROW(stringToObjectiveStatus("invalid"), std::invalid_argument);
    EXPECT_THROW(stringToObjectiveStatus(""), std::invalid_argument);
    EXPECT_THROW(stringToObjectiveStatus("QUEUED"), std::invalid_argument);
}

TEST(ObjectiveStatusTest, ValidTransitions) {
    // QUEUED -> IN_PROGRESS, BLOCKED, CANCELLED
    EXPECT_TRUE(canTransition(ObjectiveStatus::Queued, ObjectiveStatus::InProgress));
    EXPECT_TRUE(canTransition(ObjectiveStatus::Queued, ObjectiveStatus::Blocked));
    EXPECT_TRUE(canTransition(ObjectiveStatus::Queued, ObjectiveStatus::Cancelled));

    // IN_PROGRESS -> COMPLETED, BLOCKED, CANCELLED
    EXPECT_TRUE(canTransition(ObjectiveStatus::InProgress, ObjectiveStatus::Completed));
    EXPECT_TRUE(canTransition(ObjectiveStatus::InProgress, ObjectiveStatus::Blocked));
    EXPECT_TRUE(canTransition(ObjectiveStatus::InProgress, ObjectiveStatus::Cancelled));

    // BLOCKED -> QUEUED, CANCELLED
    EXPECT_TRUE(canTransition(ObjectiveStatus::Blocked, ObjectiveStatus::Queued));
    EXPECT_TRUE(canTransition(ObjectiveStatus::Blocked, ObjectiveStatus::Cancelled));
}

TEST(ObjectiveStatusTest, InvalidTransitions) {
    // Terminal states have no outgoing transitions
    EXPECT_FALSE(canTransition(ObjectiveStatus::Completed, ObjectiveStatus::Queued));
    EXPECT_FALSE(canTransition(ObjectiveStatus::Completed, ObjectiveStatus::InProgress));
    EXPECT_FALSE(canTransition(ObjectiveStatus::Cancelled, ObjectiveStatus::Queued));
    EXPECT_FALSE(canTransition(ObjectiveStatus::Cancelled, ObjectiveStatus::Completed));

    // QUEUED -> COMPLETED is not a direct transition
    EXPECT_FALSE(canTransition(ObjectiveStatus::Queued, ObjectiveStatus::Completed));

    // IN_PROGRESS -> QUEUED is not allowed
    EXPECT_FALSE(canTransition(ObjectiveStatus::InProgress, ObjectiveStatus::Queued));

    // COMPLETED -> QUEUED
    EXPECT_FALSE(canTransition(ObjectiveStatus::Completed, ObjectiveStatus::Queued));
}

// ---------------------------------------------------------------------------
// ObjectiveOutcome Tests
// ---------------------------------------------------------------------------

TEST(ObjectiveOutcomeTest, StringRoundTrip) {
    EXPECT_EQ(objectiveOutcomeToString(ObjectiveOutcome::Success), "success");
    EXPECT_EQ(objectiveOutcomeToString(ObjectiveOutcome::Failed), "failed");
    EXPECT_EQ(objectiveOutcomeToString(ObjectiveOutcome::Skipped), "skipped");
    EXPECT_EQ(objectiveOutcomeToString(ObjectiveOutcome::ConflictDetected), "conflict_detected");

    EXPECT_EQ(stringToObjectiveOutcome("success"), ObjectiveOutcome::Success);
    EXPECT_EQ(stringToObjectiveOutcome("failed"), ObjectiveOutcome::Failed);
    EXPECT_EQ(stringToObjectiveOutcome("skipped"), ObjectiveOutcome::Skipped);
    EXPECT_EQ(stringToObjectiveOutcome("conflict_detected"), ObjectiveOutcome::ConflictDetected);
}

TEST(ObjectiveOutcomeTest, InvalidStringThrows) {
    EXPECT_THROW(stringToObjectiveOutcome("invalid"), std::invalid_argument);
    EXPECT_THROW(stringToObjectiveOutcome("SUCCESS"), std::invalid_argument);
}

// ---------------------------------------------------------------------------
// generateShortId / getCurrentTimestamp Tests
// ---------------------------------------------------------------------------

TEST(UtilityTest, GenerateShortIdNotEmpty) {
    std::string id = generateShortId();
    EXPECT_FALSE(id.empty());
}

TEST(UtilityTest, GenerateShortIdIsHex) {
    for (int i = 0; i < 10; ++i) {
        std::string id = generateShortId();
        EXPECT_EQ(id.size(), 8u);
        for (char c : id) {
            EXPECT_TRUE(std::isxdigit(static_cast<unsigned char>(c)));
        }
    }
}

TEST(UtilityTest, GenerateShortIdsAreLikelyUnique) {
    std::unordered_set<std::string> ids;
    for (int i = 0; i < 100; ++i) {
        ids.insert(generateShortId());
    }
    // With 8 hex digits, 100 unique IDs is very likely
    EXPECT_EQ(ids.size(), 100u);
}

TEST(UtilityTest, GetCurrentTimestampNotEmpty) {
    std::string ts = getCurrentTimestamp();
    EXPECT_FALSE(ts.empty());
}

TEST(UtilityTest, GetCurrentTimestampIsoFormat) {
    std::string ts = getCurrentTimestamp();
    // Format: YYYY-MM-DDTHH:MM:SS.mmmZ (at least 24 chars)
    EXPECT_GE(ts.size(), 20u);
    EXPECT_EQ(ts.back(), 'Z');
    EXPECT_EQ(ts[4], '-');
    EXPECT_EQ(ts[7], '-');
    EXPECT_EQ(ts[10], 'T');
}

// ---------------------------------------------------------------------------
// Artifact Tests
// ---------------------------------------------------------------------------

TEST(ArtifactTest, DefaultConstruction) {
    Artifact a;
    EXPECT_FALSE(a.artifactId.empty());
    EXPECT_TRUE(a.name.empty());
    EXPECT_EQ(a.artifactType, "generic");
    EXPECT_TRUE(a.urlOrPath.empty());
    EXPECT_TRUE(a.metadata.is_object());
    EXPECT_FALSE(a.createdAt.empty());
}

TEST(ArtifactTest, ToJsonFromJsonRoundTrip) {
    Artifact a;
    a.name = "test-artifact";
    a.artifactType = "commit";
    a.urlOrPath = "https://github.com/example/commit/abc123";
    a.metadata = json::object({{"author", "alice"}, {"reviewed", true}});
    a.createdAt = "2025-01-01T00:00:00.000Z";

    json j = a.toJson();
    Artifact restored = Artifact::fromJson(j);

    EXPECT_EQ(restored.name, "test-artifact");
    EXPECT_EQ(restored.artifactType, "commit");
    EXPECT_EQ(restored.urlOrPath, "https://github.com/example/commit/abc123");
    EXPECT_EQ(restored.metadata["author"], "alice");
    EXPECT_EQ(restored.metadata["reviewed"], true);
    EXPECT_EQ(restored.createdAt, "2025-01-01T00:00:00.000Z");
}

TEST(ArtifactTest, PartialFromJson) {
    json j = json::object();
    j["name"] = "partial";

    Artifact a = Artifact::fromJson(j);
    EXPECT_EQ(a.name, "partial");
    EXPECT_EQ(a.artifactType, "generic");  // default
    EXPECT_FALSE(a.artifactId.empty());    // generated
    EXPECT_FALSE(a.createdAt.empty());     // generated
}

// ---------------------------------------------------------------------------
// Objective Tests
// ---------------------------------------------------------------------------

TEST(ObjectiveTest, DefaultConstruction) {
    Objective o;
    EXPECT_FALSE(o.objectiveId.empty());
    EXPECT_TRUE(o.title.empty());
    EXPECT_TRUE(o.description.empty());
    EXPECT_EQ(o.status, ObjectiveStatus::Queued);
    EXPECT_TRUE(o.dependencies.empty());
    EXPECT_TRUE(o.artifacts.empty());
    EXPECT_EQ(o.priority, 5);
    EXPECT_EQ(o.phase, "DEVELOPMENT");
    EXPECT_TRUE(o.pipelineConfig.is_object());
    EXPECT_FALSE(o.createdAt.empty());
    EXPECT_FALSE(o.updatedAt.empty());
    EXPECT_FALSE(o.errorMessage.has_value());
}

TEST(ObjectiveTest, ToJsonFromJsonRoundTrip) {
    Objective o;
    o.objectiveId = "obj-001";
    o.title = "Build module";
    o.description = "Compile the core module";
    o.status = ObjectiveStatus::Completed;
    o.dependencies = {"obj-000"};
    o.priority = 1;
    o.phase = "DEVELOPMENT";
    o.pipelineConfig = json::object({{"timeout", 300}});
    o.errorMessage = "some error";
    o.createdAt = "2025-01-01T00:00:00.000Z";
    o.updatedAt = "2025-01-01T00:01:00.000Z";

    Artifact art;
    art.name = "binary";
    art.artifactType = "commit";
    art.urlOrPath = "/path/to/binary";
    o.artifacts.push_back(art);

    json j = o.toJson();

    EXPECT_EQ(j["objective_id"], "obj-001");
    EXPECT_EQ(j["title"], "Build module");
    EXPECT_EQ(j["status"], "completed");
    EXPECT_EQ(j["dependencies"][0], "obj-000");
    EXPECT_EQ(j["priority"], 1);
    EXPECT_EQ(j["phase"], "DEVELOPMENT");
    EXPECT_EQ(j["error_message"], "some error");
    EXPECT_EQ(j["artifacts"][0]["name"], "binary");

    Objective restored = Objective::fromJson(j);
    EXPECT_EQ(restored.objectiveId, "obj-001");
    EXPECT_EQ(restored.title, "Build module");
    EXPECT_EQ(restored.status, ObjectiveStatus::Completed);
    EXPECT_EQ(restored.dependencies.size(), 1u);
    EXPECT_EQ(restored.dependencies[0], "obj-000");
    EXPECT_EQ(restored.priority, 1);
    EXPECT_EQ(restored.errorMessage.value(), "some error");
    EXPECT_EQ(restored.artifacts.size(), 1u);
    EXPECT_EQ(restored.artifacts[0].name, "binary");
}

TEST(ObjectiveTest, TransitionToValid) {
    Objective o;
    EXPECT_EQ(o.status, ObjectiveStatus::Queued);

    o.transitionTo(ObjectiveStatus::InProgress);
    EXPECT_EQ(o.status, ObjectiveStatus::InProgress);

    o.transitionTo(ObjectiveStatus::Completed);
    EXPECT_EQ(o.status, ObjectiveStatus::Completed);
}

TEST(ObjectiveTest, TransitionToInvalid) {
    Objective o;

    // COMPLETED -> QUEUED is invalid
    o.transitionTo(ObjectiveStatus::InProgress);
    o.transitionTo(ObjectiveStatus::Completed);
    EXPECT_THROW(o.transitionTo(ObjectiveStatus::Queued), std::invalid_argument);

    // QUEUED -> COMPLETED directly is invalid
    Objective o2;
    o2.title = "test";
    EXPECT_THROW(o2.transitionTo(ObjectiveStatus::Completed), std::invalid_argument);
}

TEST(ObjectiveTest, AddArtifact) {
    Objective o;
    EXPECT_TRUE(o.artifacts.empty());

    Artifact art;
    art.name = "report";
    art.artifactType = "document";
    o.addArtifact(art);

    EXPECT_EQ(o.artifacts.size(), 1u);
    EXPECT_EQ(o.artifacts[0].name, "report");
}

TEST(ObjectiveTest, FromJsonWithNullErrorMessage) {
    json j = json::object();
    j["objective_id"] = "obj-null-err";
    j["error_message"] = nullptr;

    Objective o = Objective::fromJson(j);
    EXPECT_FALSE(o.errorMessage.has_value());
}

// ---------------------------------------------------------------------------
// ProjectObjectives Tests
// ---------------------------------------------------------------------------

TEST(ProjectObjectivesTest, AddObjectiveAndGetObjective) {
    ProjectObjectives proj;
    Objective o;
    o.objectiveId = "obj-001";
    o.title = "First";

    proj.addObjective(o);

    const Objective* found = proj.getObjective("obj-001");
    ASSERT_NE(found, nullptr);
    EXPECT_EQ(found->title, "First");

    EXPECT_EQ(proj.getObjective("nonexistent"), nullptr);
}

TEST(ProjectObjectivesTest, GetReadyObjectivesDepsMet) {
    ProjectObjectives proj;

    Objective o1;
    o1.objectiveId = "obj-001";
    o1.priority = 2;

    Objective o2;
    o2.objectiveId = "obj-002";
    o2.priority = 1;
    o2.dependencies = {"obj-001"};

    Objective o3;
    o3.objectiveId = "obj-003";
    o3.priority = 3;

    proj.addObjective(o1);
    proj.addObjective(o2);
    proj.addObjective(o3);

    // None are ready yet (o1 and o3 are QUEUED with no deps, so they should be ready)
    auto ready = proj.getReadyObjectives();
    ASSERT_EQ(ready.size(), 2u);
    // Sorted by priority: o2 has dep on o1 so not ready, o1 (pri=2) and o3 (pri=3)
    EXPECT_EQ(ready[0]->objectiveId, "obj-001");  // priority 2
    EXPECT_EQ(ready[1]->objectiveId, "obj-003");  // priority 3
}

TEST(ProjectObjectivesTest, GetReadyObjectivesWithCompletedDeps) {
    ProjectObjectives proj;

    Objective o1;
    o1.objectiveId = "obj-001";
    o1.priority = 1;
    o1.status = ObjectiveStatus::Completed;

    Objective o2;
    o2.objectiveId = "obj-002";
    o2.priority = 2;
    o2.dependencies = {"obj-001"};

    Objective o3;
    o3.objectiveId = "obj-003";
    o3.priority = 3;
    o3.dependencies = {"obj-001"};

    proj.addObjective(o1);
    proj.addObjective(o2);
    proj.addObjective(o3);

    auto ready = proj.getReadyObjectives();
    ASSERT_EQ(ready.size(), 2u);
    EXPECT_EQ(ready[0]->objectiveId, "obj-002");  // priority 2
    EXPECT_EQ(ready[1]->objectiveId, "obj-003");  // priority 3
}

TEST(ProjectObjectivesTest, GetReadyObjectivesDepsNotMet) {
    ProjectObjectives proj;

    Objective o1;
    o1.objectiveId = "obj-001";
    o1.status = ObjectiveStatus::InProgress;

    Objective o2;
    o2.objectiveId = "obj-002";
    o2.dependencies = {"obj-001"};

    proj.addObjective(o1);
    proj.addObjective(o2);

    auto ready = proj.getReadyObjectives();
    EXPECT_EQ(ready.size(), 0u);  // o1 is IN_PROGRESS, not COMPLETED
}

TEST(ProjectObjectivesTest, GetAllObjectiveIds) {
    ProjectObjectives proj;

    Objective o1; o1.objectiveId = "a";
    Objective o2; o2.objectiveId = "b";
    Objective o3; o3.objectiveId = "c";

    proj.addObjective(o1);
    proj.addObjective(o2);
    proj.addObjective(o3);

    auto ids = proj.getAllObjectiveIds();
    EXPECT_EQ(ids.size(), 3u);
    EXPECT_NE(ids.find("a"), ids.end());
    EXPECT_NE(ids.find("b"), ids.end());
    EXPECT_NE(ids.find("c"), ids.end());
}

TEST(ProjectObjectivesTest, ToJsonFromJsonRoundTrip) {
    ProjectObjectives proj;
    proj.projectId = "proj-001";
    proj.name = "Test Project";
    proj.metadata = json::object({{"owner", "team-a"}});

    Objective o;
    o.objectiveId = "obj-001";
    o.title = "Setup";
    proj.addObjective(o);

    json j = proj.toJson();
    ProjectObjectives restored = ProjectObjectives::fromJson(j);

    EXPECT_EQ(restored.projectId, "proj-001");
    EXPECT_EQ(restored.name, "Test Project");
    EXPECT_EQ(restored.metadata["owner"], "team-a");
    ASSERT_EQ(restored.objectives.size(), 1u);
    EXPECT_EQ(restored.objectives[0].objectiveId, "obj-001");
    EXPECT_EQ(restored.objectives[0].title, "Setup");
}

TEST(ProjectObjectivesTest, EmptyProject) {
    ProjectObjectives proj;
    EXPECT_TRUE(proj.objectives.empty());
    EXPECT_EQ(proj.getAllObjectiveIds().size(), 0u);
    EXPECT_EQ(proj.getReadyObjectives().size(), 0u);
    EXPECT_EQ(proj.getObjective("anything"), nullptr);
}

// ---------------------------------------------------------------------------
// DependencyGraph Tests
// ---------------------------------------------------------------------------

TEST(DependencyGraphTest, BuildFromObjectives) {
    Objective o1; o1.objectiveId = "a";
    Objective o2; o2.objectiveId = "b"; o2.dependencies = {"a"};
    Objective o3; o3.objectiveId = "c"; o3.dependencies = {"a", "b"};

    std::vector<Objective> objs = {o1, o2, o3};
    DependencyGraph graph(objs);

    EXPECT_EQ(graph.nodes().size(), 3u);
    EXPECT_EQ(graph.getDependencies("a").size(), 0u);
    EXPECT_EQ(graph.getDependencies("b").size(), 1u);
    EXPECT_EQ(graph.getDependencies("c").size(), 2u);
}

TEST(DependencyGraphTest, ReverseDeps) {
    Objective o1; o1.objectiveId = "a";
    Objective o2; o2.objectiveId = "b"; o2.dependencies = {"a"};
    Objective o3; o3.objectiveId = "c"; o3.dependencies = {"a"};

    std::vector<Objective> objs = {o1, o2, o3};
    DependencyGraph graph(objs);

    auto revA = graph.getReverseDeps("a");
    EXPECT_EQ(revA.size(), 2u);
    EXPECT_NE(revA.find("b"), revA.end());
    EXPECT_NE(revA.find("c"), revA.end());
}

TEST(DependencyGraphTest, DetectCyclesNone) {
    Objective o1; o1.objectiveId = "a";
    Objective o2; o2.objectiveId = "b"; o2.dependencies = {"a"};
    Objective o3; o3.objectiveId = "c"; o3.dependencies = {"b"};

    std::vector<Objective> objs = {o1, o2, o3};
    DependencyGraph graph(objs);

    auto cycles = graph.detectCycles();
    EXPECT_EQ(cycles.size(), 0u);
}

TEST(DependencyGraphTest, DetectCyclesSingleCycle) {
    Objective o1; o1.objectiveId = "a"; o1.dependencies = {"c"};
    Objective o2; o2.objectiveId = "b"; o2.dependencies = {"a"};
    Objective o3; o3.objectiveId = "c"; o3.dependencies = {"b"};

    std::vector<Objective> objs = {o1, o2, o3};
    DependencyGraph graph(objs);

    auto cycles = graph.detectCycles();
    EXPECT_GE(cycles.size(), 1u);
    // The cycle should contain a, b, c
    std::set<std::string> cycleNodes(cycles[0].begin(), cycles[0].end() - 1);
    EXPECT_EQ(cycleNodes.size(), 3u);
    EXPECT_NE(cycleNodes.find("a"), cycleNodes.end());
    EXPECT_NE(cycleNodes.find("b"), cycleNodes.end());
    EXPECT_NE(cycleNodes.find("c"), cycleNodes.end());
}

TEST(DependencyGraphTest, DetectCyclesMultiple) {
    // Two disjoint cycles: a->b->a and c->d->c
    Objective o1; o1.objectiveId = "a"; o1.dependencies = {"b"};
    Objective o2; o2.objectiveId = "b"; o2.dependencies = {"a"};
    Objective o3; o3.objectiveId = "c"; o3.dependencies = {"d"};
    Objective o4; o4.objectiveId = "d"; o4.dependencies = {"c"};

    std::vector<Objective> objs = {o1, o2, o3, o4};
    DependencyGraph graph(objs);

    auto cycles = graph.detectCycles();
    EXPECT_GE(cycles.size(), 2u);
}

TEST(DependencyGraphTest, TopologicalOrderValid) {
    Objective o1; o1.objectiveId = "a";
    Objective o2; o2.objectiveId = "b"; o2.dependencies = {"a"};
    Objective o3; o3.objectiveId = "c"; o3.dependencies = {"a", "b"};

    std::vector<Objective> objs = {o1, o2, o3};
    DependencyGraph graph(objs);

    auto order = graph.topologicalOrder();
    EXPECT_EQ(order.size(), 3u);

    // a must come before b, b before c
    auto posA = std::find(order.begin(), order.end(), "a") - order.begin();
    auto posB = std::find(order.begin(), order.end(), "b") - order.begin();
    auto posC = std::find(order.begin(), order.end(), "c") - order.begin();
    EXPECT_LT(posA, posB);
    EXPECT_LT(posB, posC);
}

TEST(DependencyGraphTest, TopologicalOrderCycleThrows) {
    Objective o1; o1.objectiveId = "a"; o1.dependencies = {"b"};
    Objective o2; o2.objectiveId = "b"; o2.dependencies = {"a"};

    std::vector<Objective> objs = {o1, o2};
    DependencyGraph graph(objs);

    EXPECT_THROW(graph.topologicalOrder(), std::runtime_error);
}

TEST(DependencyGraphTest, PartitionIntoLevelsCorrectParallelism) {
    // Level 0: a, b (no deps)
    // Level 1: c (depends on a, b)
    // Level 2: d (depends on c)
    Objective o1; o1.objectiveId = "a";
    Objective o2; o2.objectiveId = "b";
    Objective o3; o3.objectiveId = "c"; o3.dependencies = {"a", "b"};
    Objective o4; o4.objectiveId = "d"; o4.dependencies = {"c"};

    std::vector<Objective> objs = {o1, o2, o3, o4};
    DependencyGraph graph(objs);

    auto levels = graph.partitionIntoLevels();
    EXPECT_EQ(levels.size(), 3u);

    // Level 0 should have a and b
    std::set<std::string> level0(levels[0].begin(), levels[0].end());
    EXPECT_EQ(level0.size(), 2u);
    EXPECT_NE(level0.find("a"), level0.end());
    EXPECT_NE(level0.find("b"), level0.end());

    // Level 1 should have c
    EXPECT_EQ(levels[1].size(), 1u);
    EXPECT_EQ(levels[1][0], "c");

    // Level 2 should have d
    EXPECT_EQ(levels[2].size(), 1u);
    EXPECT_EQ(levels[2][0], "d");
}

TEST(DependencyGraphTest, PartitionIntoLevelsCycleThrows) {
    Objective o1; o1.objectiveId = "a"; o1.dependencies = {"b"};
    Objective o2; o2.objectiveId = "b"; o2.dependencies = {"a"};

    std::vector<Objective> objs = {o1, o2};
    DependencyGraph graph(objs);

    EXPECT_THROW(graph.partitionIntoLevels(), std::runtime_error);
}

TEST(DependencyGraphTest, ComputeCascade) {
    // a -> b -> c
    // a -> d
    Objective o1; o1.objectiveId = "a";
    Objective o2; o2.objectiveId = "b"; o2.dependencies = {"a"};
    Objective o3; o3.objectiveId = "c"; o3.dependencies = {"b"};
    Objective o4; o4.objectiveId = "d"; o4.dependencies = {"a"};

    std::vector<Objective> objs = {o1, o2, o3, o4};
    DependencyGraph graph(objs);

    auto cascade = graph.computeCascade("a");
    EXPECT_EQ(cascade.size(), 3u);  // b, c, d
    EXPECT_NE(cascade.find("b"), cascade.end());
    EXPECT_NE(cascade.find("c"), cascade.end());
    EXPECT_NE(cascade.find("d"), cascade.end());

    auto cascadeC = graph.computeCascade("c");
    EXPECT_EQ(cascadeC.size(), 0u);  // nothing depends on c
}

TEST(DependencyGraphTest, MaxCascadeDepth) {
    // a -> b -> c -> d  (depth 3)
    Objective o1; o1.objectiveId = "a";
    Objective o2; o2.objectiveId = "b"; o2.dependencies = {"a"};
    Objective o3; o3.objectiveId = "c"; o3.dependencies = {"b"};
    Objective o4; o4.objectiveId = "d"; o4.dependencies = {"c"};

    std::vector<Objective> objs = {o1, o2, o3, o4};
    DependencyGraph graph(objs);

    EXPECT_EQ(graph.maxCascadeDepth("a"), 3);
    EXPECT_EQ(graph.maxCascadeDepth("b"), 2);
    EXPECT_EQ(graph.maxCascadeDepth("c"), 1);
    EXPECT_EQ(graph.maxCascadeDepth("d"), 0);
}

TEST(DependencyGraphTest, ExternalDependenciesHandled) {
    // Objective depends on an external ID not in the graph
    Objective o1; o1.objectiveId = "a"; o1.dependencies = {"external"};

    std::vector<Objective> objs = {o1};
    DependencyGraph graph(objs);

    auto cycles = graph.detectCycles();
    EXPECT_EQ(cycles.size(), 0u);

    auto order = graph.topologicalOrder();
    EXPECT_EQ(order.size(), 1u);
    EXPECT_EQ(order[0], "a");
}

TEST(DependencyGraphTest, DiamondDependency) {
    //     a
    //    / \
    //   b   c
    //    \ /
    //     d
    Objective o1; o1.objectiveId = "a";
    Objective o2; o2.objectiveId = "b"; o2.dependencies = {"a"};
    Objective o3; o3.objectiveId = "c"; o3.dependencies = {"a"};
    Objective o4; o4.objectiveId = "d"; o4.dependencies = {"b", "c"};

    std::vector<Objective> objs = {o1, o2, o3, o4};
    DependencyGraph graph(objs);

    auto order = graph.topologicalOrder();
    EXPECT_EQ(order.size(), 4u);
    auto posA = std::find(order.begin(), order.end(), "a") - order.begin();
    auto posB = std::find(order.begin(), order.end(), "b") - order.begin();
    auto posC = std::find(order.begin(), order.end(), "c") - order.begin();
    auto posD = std::find(order.begin(), order.end(), "d") - order.begin();
    EXPECT_LT(posA, posB);
    EXPECT_LT(posA, posC);
    EXPECT_LT(posB, posD);
    EXPECT_LT(posC, posD);

    auto levels = graph.partitionIntoLevels();
    EXPECT_EQ(levels.size(), 3u);
    // Level 0: a
    // Level 1: b, c (parallel)
    // Level 2: d
    std::set<std::string> level1(levels[1].begin(), levels[1].end());
    EXPECT_EQ(level1.size(), 2u);
    EXPECT_NE(level1.find("b"), level1.end());
    EXPECT_NE(level1.find("c"), level1.end());
}

TEST(DependencyGraphTest, EmptyGraph) {
    DependencyGraph graph;
    EXPECT_EQ(graph.nodes().size(), 0u);
    EXPECT_EQ(graph.detectCycles().size(), 0u);
    EXPECT_EQ(graph.topologicalOrder().size(), 0u);
    EXPECT_EQ(graph.partitionIntoLevels().size(), 0u);
    EXPECT_EQ(graph.computeCascade("any").size(), 0u);
    EXPECT_EQ(graph.maxCascadeDepth("any"), 0);
}

TEST(DependencyGraphTest, SingleNode) {
    Objective o; o.objectiveId = "single";

    std::vector<Objective> objs = {o};
    DependencyGraph graph(objs);

    EXPECT_EQ(graph.nodes().size(), 1u);
    EXPECT_EQ(graph.detectCycles().size(), 0u);

    auto order = graph.topologicalOrder();
    EXPECT_EQ(order.size(), 1u);
    EXPECT_EQ(order[0], "single");

    auto levels = graph.partitionIntoLevels();
    EXPECT_EQ(levels.size(), 1u);
    EXPECT_EQ(levels[0].size(), 1u);

    EXPECT_EQ(graph.maxCascadeDepth("single"), 0);
    EXPECT_EQ(graph.computeCascade("single").size(), 0u);
}

TEST(DependencyGraphTest, SelfDependency) {
    Objective o; o.objectiveId = "self"; o.dependencies = {"self"};

    std::vector<Objective> objs = {o};
    DependencyGraph graph(objs);

    auto cycles = graph.detectCycles();
    EXPECT_GE(cycles.size(), 1u);

    EXPECT_THROW(graph.topologicalOrder(), std::runtime_error);
    EXPECT_THROW(graph.partitionIntoLevels(), std::runtime_error);
}

TEST(DependencyGraphTest, AddAndRemoveObjective) {
    DependencyGraph graph;

    Objective o1; o1.objectiveId = "a";
    Objective o2; o2.objectiveId = "b"; o2.dependencies = {"a"};

    graph.addObjective(o1);
    graph.addObjective(o2);
    EXPECT_EQ(graph.nodes().size(), 2u);

    graph.removeObjective("a");
    EXPECT_EQ(graph.nodes().size(), 1u);
    EXPECT_EQ(graph.getDependencies("b").size(), 0u);  // edge to "a" removed
}

TEST(DependencyGraphTest, BuildRebuildsIndices) {
    Objective o1; o1.objectiveId = "x";
    std::vector<Objective> objs1 = {o1};

    DependencyGraph graph(objs1);
    EXPECT_EQ(graph.nodes().size(), 1u);

    Objective o2; o2.objectiveId = "y";
    std::vector<Objective> objs2 = {o2};

    graph.build(objs2);
    EXPECT_EQ(graph.nodes().size(), 1u);
    auto nodes = graph.nodes();
    EXPECT_NE(nodes.find("y"), nodes.end());
    EXPECT_EQ(nodes.count("x"), 0u);  // old node gone
}

// ---------------------------------------------------------------------------
// ConflictReport Tests
// ---------------------------------------------------------------------------

TEST(ConflictReportTest, DefaultConstruction) {
    ConflictReport cr;
    EXPECT_TRUE(cr.conflictingObjectiveIds.empty());
    EXPECT_TRUE(cr.affectedFiles.empty());
    EXPECT_FALSE(cr.timestamp.empty());
}

TEST(ConflictReportTest, ToJsonFromJsonRoundTrip) {
    ConflictReport cr;
    cr.conflictingObjectiveIds = {"obj-001", "obj-002"};
    cr.affectedFiles = {"main.py", "config.yaml"};
    cr.timestamp = "2025-06-15T10:30:00.000Z";

    json j = cr.toJson();
    ConflictReport restored = ConflictReport::fromJson(j);

    EXPECT_EQ(restored.conflictingObjectiveIds.size(), 2u);
    EXPECT_EQ(restored.conflictingObjectiveIds[0], "obj-001");
    EXPECT_EQ(restored.conflictingObjectiveIds[1], "obj-002");
    EXPECT_EQ(restored.affectedFiles.size(), 2u);
    EXPECT_EQ(restored.affectedFiles[0], "main.py");
    EXPECT_EQ(restored.affectedFiles[1], "config.yaml");
    EXPECT_EQ(restored.timestamp, "2025-06-15T10:30:00.000Z");
}

// ---------------------------------------------------------------------------
// LevelResult Tests
// ---------------------------------------------------------------------------

TEST(LevelResultTest, DefaultConstruction) {
    LevelResult lr;
    EXPECT_EQ(lr.levelNumber, 0);
    EXPECT_TRUE(lr.objectiveIds.empty());
    EXPECT_TRUE(lr.outcomes.empty());
    EXPECT_TRUE(lr.conflicts.empty());
    EXPECT_EQ(lr.successCount, 0);
    EXPECT_EQ(lr.failureCount, 0);
    EXPECT_EQ(lr.verdict, "CONTINUE");
    EXPECT_FALSE(lr.timestamp.empty());
}

TEST(LevelResultTest, ToJsonFromJsonRoundTrip) {
    LevelResult lr;
    lr.levelNumber = 2;
    lr.objectiveIds = {"obj-a", "obj-b", "obj-c"};
    lr.outcomes["obj-a"] = ObjectiveOutcome::Success;
    lr.outcomes["obj-b"] = ObjectiveOutcome::Failed;
    lr.outcomes["obj-c"] = ObjectiveOutcome::Skipped;
    lr.successCount = 1;
    lr.failureCount = 1;
    lr.verdict = "CONTINUE_WITH_WARNINGS";
    lr.timestamp = "2025-07-20T12:00:00.000Z";

    ConflictReport cr;
    cr.conflictingObjectiveIds = {"obj-a", "obj-b"};
    cr.affectedFiles = {"shared.h"};
    cr.timestamp = "2025-07-20T12:00:00.000Z";
    lr.conflicts.push_back(cr);

    json j = lr.toJson();

    LevelResult restored = LevelResult::fromJson(j);

    EXPECT_EQ(restored.levelNumber, 2);
    EXPECT_EQ(restored.objectiveIds.size(), 3u);
    EXPECT_EQ(restored.outcomes.size(), 3u);
    EXPECT_EQ(restored.outcomes["obj-a"], ObjectiveOutcome::Success);
    EXPECT_EQ(restored.outcomes["obj-b"], ObjectiveOutcome::Failed);
    EXPECT_EQ(restored.outcomes["obj-c"], ObjectiveOutcome::Skipped);
    EXPECT_EQ(restored.successCount, 1);
    EXPECT_EQ(restored.failureCount, 1);
    EXPECT_EQ(restored.verdict, "CONTINUE_WITH_WARNINGS");
    EXPECT_EQ(restored.timestamp, "2025-07-20T12:00:00.000Z");
    ASSERT_EQ(restored.conflicts.size(), 1u);
    EXPECT_EQ(restored.conflicts[0].affectedFiles[0], "shared.h");
}

TEST(LevelResultTest, FromJsonPartial) {
    json j = json::object();
    j["level_number"] = 1;
    j["objective_ids"] = json::array({"only-one"});

    LevelResult lr = LevelResult::fromJson(j);
    EXPECT_EQ(lr.levelNumber, 1);
    EXPECT_EQ(lr.objectiveIds.size(), 1u);
    EXPECT_EQ(lr.objectiveIds[0], "only-one");
    EXPECT_EQ(lr.successCount, 0);  // default
    EXPECT_EQ(lr.failureCount, 0);  // default
    EXPECT_EQ(lr.verdict, "CONTINUE");  // default
}

// ---------------------------------------------------------------------------
// Additional Coverage Gap Tests (per quality review)
// ---------------------------------------------------------------------------

TEST(ObjectiveTest, BlockedStatusRoundTrip) {
    Objective o;
    o.objectiveId = "obj-blocked";
    o.status = ObjectiveStatus::Blocked;

    json j = o.toJson();
    EXPECT_EQ(j["status"], "blocked");

    Objective restored = Objective::fromJson(j);
    EXPECT_EQ(restored.status, ObjectiveStatus::Blocked);
}

TEST(LevelResultTest, FromJsonInvalidOutcomeThrows) {
    json j = json::object();
    j["level_number"] = 1;
    j["outcomes"] = json::object({{"obj-x", "invalid_outcome"}});

    EXPECT_THROW(LevelResult::fromJson(j), std::invalid_argument);
}

TEST(ObjectiveTest, FromJsonMissingStatusDefaultsToQueued) {
    json j = json::object();
    j["objective_id"] = "obj-no-status";
    j["title"] = "No status field";
    // No "status" key provided

    Objective o = Objective::fromJson(j);
    EXPECT_EQ(o.status, ObjectiveStatus::Queued);
}

TEST(ConflictReportTest, FromJsonWithEmptyArrays) {
    json j = json::object();
    j["conflicting_objective_ids"] = json::array();
    j["affected_files"] = json::array();
    j["timestamp"] = "2025-08-01T00:00:00.000Z";

    ConflictReport cr = ConflictReport::fromJson(j);
    EXPECT_TRUE(cr.conflictingObjectiveIds.empty());
    EXPECT_TRUE(cr.affectedFiles.empty());
    EXPECT_EQ(cr.timestamp, "2025-08-01T00:00:00.000Z");
}

TEST(DependencyGraphTest, ComputeCascadeNoReverseDeps) {
    // Single node with no dependents — cascade should be empty
    Objective o; o.objectiveId = "leaf";

    std::vector<Objective> objs = {o};
    DependencyGraph graph(objs);

    auto cascade = graph.computeCascade("leaf");
    EXPECT_EQ(cascade.size(), 0u);
}
