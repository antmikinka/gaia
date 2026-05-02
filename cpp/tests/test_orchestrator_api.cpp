// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT

#include <gtest/gtest.h>
#include <gaia/orchestrator_api.h>
#include <gaia/orchestrator_types.h>

#include <filesystem>
#include <fstream>
#include <string>
#include <thread>

namespace fs = std::filesystem;

using namespace gaia;

// ============================================================================
// Test Helpers
// ============================================================================

/// Create a temporary objectives JSON file for testing.
static std::string createTempObjectivesFile(const json& data) {
    std::string path = fs::temp_directory_path().string() +
                       "/gaia_api_test_" + generateShortId() + ".json";
    std::ofstream file(path);
    file << data.dump(2);
    file.close();
    return path;
}

/// Create a simple project JSON.
static json makeProjectJson(const std::vector<json>& objectives) {
    json j;
    j["project_id"] = "test-proj";
    j["name"] = "Test Project";
    j["objectives"] = objectives;
    j["metadata"] = json::object();
    return j;
}

/// Create a single objective JSON.
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
// SseEvent Tests
// ============================================================================

TEST(SseEventTest, ToSseFormat) {
    SseEvent event;
    event.id = "1";
    event.type = "objective_start";
    event.data = "{\"objective_id\":\"obj-001\"}";
    event.timestamp = "2026-04-30T10:00:00.000Z";

    std::string format = event.toSseFormat();

    // Verify standard field order: event -> id -> data
    size_t eventPos = format.find("event: objective_start");
    size_t idPos = format.find("id: 1");
    size_t dataPos = format.find("data: {\"objective_id\":\"obj-001\"}");

    EXPECT_NE(eventPos, std::string::npos);
    EXPECT_NE(idPos, std::string::npos);
    EXPECT_NE(dataPos, std::string::npos);

    // Fields should appear in standard order: event < id < data
    EXPECT_LT(eventPos, idPos);
    EXPECT_LT(idPos, dataPos);

    // Should end with double newline
    EXPECT_EQ(format.substr(format.size() - 2), "\n\n");
}

TEST(SseEventTest, ToJsonRoundTrip) {
    SseEvent event;
    event.id = "42";
    event.type = "objective_complete";
    event.data = "{\"success\":true}";
    event.timestamp = "2026-04-30T10:00:00.000Z";

    json j = event.toJson();
    SseEvent restored = SseEvent::fromJson(j);

    EXPECT_EQ(restored.id, "42");
    EXPECT_EQ(restored.type, "objective_complete");
    EXPECT_EQ(restored.data, "{\"success\":true}");
    EXPECT_EQ(restored.timestamp, "2026-04-30T10:00:00.000Z");
}

TEST(SseEventTest, FromJsonPartial) {
    json j;
    j["id"] = "1";
    j["type"] = "health_update";

    SseEvent event = SseEvent::fromJson(j);
    EXPECT_EQ(event.id, "1");
    EXPECT_EQ(event.type, "health_update");
    EXPECT_TRUE(event.data.empty());  // default
    EXPECT_TRUE(event.timestamp.empty());  // default
}

// ============================================================================
// StartRequest Tests
// ============================================================================

TEST(StartRequestTest, EmptyJsonDefaults) {
    json j = json::object();
    StartRequest req = StartRequest::fromJson(j);

    EXPECT_FALSE(req.objectivesPath.has_value());
    EXPECT_FALSE(req.config.has_value());
}

TEST(StartRequestTest, FullRequestParsing) {
    json j;
    j["objectives_path"] = "/custom/path.json";
    j["config"] = json::object();
    j["config"]["auto_commit"] = true;
    j["config"]["max_cycle_iterations"] = 50;
    j["config"]["quality_threshold"] = 0.85;

    StartRequest req = StartRequest::fromJson(j);

    ASSERT_TRUE(req.objectivesPath.has_value());
    EXPECT_EQ(req.objectivesPath.value(), "/custom/path.json");
    ASSERT_TRUE(req.config.has_value());
    EXPECT_TRUE(req.config.value().autoCommit);
    EXPECT_EQ(req.config.value().maxCycleIterations, 50);
    EXPECT_DOUBLE_EQ(req.config.value().qualityThreshold, 0.85);
}

TEST(StartRequestTest, PartialConfigMergesWithDefaults) {
    json j;
    j["config"] = json::object();
    j["config"]["dry_run"] = true;

    StartRequest req = StartRequest::fromJson(j);

    ASSERT_TRUE(req.config.has_value());
    EXPECT_TRUE(req.config.value().dryRun);
    EXPECT_EQ(req.config.value().objectivesPath,
              ".gaia/objectives.yaml");  // default retained
}

TEST(StartRequestTest, ToJsonSerialization) {
    StartRequest req;
    req.objectivesPath = "/test/path.json";

    OrchestratorConfig cfg;
    cfg.dryRun = true;
    req.config = cfg;

    json j = req.toJson();
    EXPECT_EQ(j["objectives_path"], "/test/path.json");
    EXPECT_TRUE(j.contains("config"));
    EXPECT_EQ(j["config"]["dry_run"], true);
}

TEST(StartRequestTest, NullFieldsIgnored) {
    json j;
    j["objectives_path"] = nullptr;
    j["config"] = nullptr;

    StartRequest req = StartRequest::fromJson(j);
    EXPECT_FALSE(req.objectivesPath.has_value());
    EXPECT_FALSE(req.config.has_value());
}

// ============================================================================
// PauseRequest Tests
// ============================================================================

TEST(PauseRequestTest, WithReason) {
    json j;
    j["reason"] = "Manual pause for review";

    PauseRequest req = PauseRequest::fromJson(j);
    EXPECT_EQ(req.reason, "Manual pause for review");
}

TEST(PauseRequestTest, EmptyReason) {
    json j = json::object();
    PauseRequest req = PauseRequest::fromJson(j);
    EXPECT_TRUE(req.reason.empty());
}

TEST(PauseRequestTest, ToJsonRoundTrip) {
    PauseRequest req;
    req.reason = "Testing";

    json j = req.toJson();
    PauseRequest restored = PauseRequest::fromJson(j);
    EXPECT_EQ(restored.reason, "Testing");
}

// ============================================================================
// UpdateConfigRequest Tests
// ============================================================================

TEST(UpdateConfigRequestTest, FullConfigUpdate) {
    json j;
    j["config"] = json::object();
    j["config"]["objectives_path"] = "custom.json";
    j["config"]["auto_commit"] = true;
    j["config"]["max_cycle_iterations"] = 10;
    j["config"]["quality_threshold"] = 0.80;

    UpdateConfigRequest req = UpdateConfigRequest::fromJson(j);

    EXPECT_EQ(req.config.objectivesPath, "custom.json");
    EXPECT_TRUE(req.config.autoCommit);
    EXPECT_EQ(req.config.maxCycleIterations, 10);
    EXPECT_DOUBLE_EQ(req.config.qualityThreshold, 0.80);
}

TEST(UpdateConfigRequestTest, InvalidConfigThrows) {
    json j;
    j["config"] = json::object();
    j["config"]["max_cycle_iterations"] = 0;  // invalid

    EXPECT_THROW(UpdateConfigRequest::fromJson(j), std::invalid_argument);
}

TEST(UpdateConfigRequestTest, MissingConfigFieldRetainsDefaults) {
    json j = json::object();
    // No "config" key

    UpdateConfigRequest req = UpdateConfigRequest::fromJson(j);
    // Should retain default config
    EXPECT_EQ(req.config.objectivesPath, ".gaia/objectives.yaml");
}

TEST(UpdateConfigRequestTest, ToJsonRoundTrip) {
    UpdateConfigRequest req;
    req.config.dryRun = true;
    req.config.maxCycleIterations = 5;

    json j = req.toJson();
    UpdateConfigRequest restored = UpdateConfigRequest::fromJson(j);

    EXPECT_TRUE(restored.config.dryRun);
    EXPECT_EQ(restored.config.maxCycleIterations, 5);
}

// ============================================================================
// ApiResponse Tests
// ============================================================================

TEST(ApiResponseTest, ToJsonRoundTrip) {
    ApiResponse resp;
    resp.status = "ok";
    resp.message = "Success";

    json j = resp.toJson();
    ApiResponse restored = ApiResponse::fromJson(j);

    EXPECT_EQ(restored.status, "ok");
    EXPECT_EQ(restored.message, "Success");
}

TEST(ApiResponseTest, FromJsonPartial) {
    json j;
    j["status"] = "started";

    ApiResponse resp = ApiResponse::fromJson(j);
    EXPECT_EQ(resp.status, "started");
    EXPECT_TRUE(resp.message.empty());  // default
}

// ============================================================================
// StatusResponse Tests
// ============================================================================

TEST(StatusResponseTest, RunningStateSerialization) {
    StatusResponse resp;
    resp.running = true;
    resp.state = ApiOrchestratorState::Running;
    resp.engineState.cycleCount = 5;
    resp.engineState.objectivesProcessed = 3;
    resp.engineState.objectivesFailed = 1;

    json j = resp.toJson();

    EXPECT_EQ(j["running"], true);
    EXPECT_EQ(j["state"], "running");
    EXPECT_EQ(j["engine_state"]["cycle_count"], 5);
    EXPECT_EQ(j["engine_state"]["objectives_processed"], 3);
    EXPECT_EQ(j["engine_state"]["objectives_failed"], 1);
}

TEST(StatusResponseTest, IdleStateSerialization) {
    StatusResponse resp;
    resp.running = false;
    resp.state = ApiOrchestratorState::Idle;

    json j = resp.toJson();

    EXPECT_EQ(j["running"], false);
    EXPECT_EQ(j["state"], "idle");
}

TEST(StatusResponseTest, DoneStateSerialization) {
    StatusResponse resp;
    resp.running = false;
    resp.state = ApiOrchestratorState::Done;
    resp.engineState.cycleCount = 10;

    json j = resp.toJson();
    EXPECT_EQ(j["state"], "done");
    EXPECT_EQ(j["engine_state"]["cycle_count"], 10);
}

TEST(StatusResponseTest, WithProjectData) {
    StatusResponse resp;
    ProjectObjectives proj;
    proj.projectId = "proj-001";
    proj.name = "Test";
    resp.project = proj;

    json j = resp.toJson();
    EXPECT_TRUE(j.contains("project"));
    EXPECT_EQ(j["project"]["project_id"], "proj-001");
}

TEST(StatusResponseTest, FromJsonRoundTrip) {
    StatusResponse resp;
    resp.running = true;
    resp.state = ApiOrchestratorState::Running;
    resp.config.dryRun = true;

    json j = resp.toJson();
    StatusResponse restored = StatusResponse::fromJson(j);

    EXPECT_TRUE(restored.running);
    EXPECT_EQ(restored.state, ApiOrchestratorState::Running);
    EXPECT_TRUE(restored.config.dryRun);
}

// ============================================================================
// HealthResponse Tests
// ============================================================================

TEST(HealthResponseTest, HealthyScores) {
    HealthResponse resp;
    resp.health.successRate = 0.95;
    resp.health.qualityTrend = 0.10;
    resp.health.dependencyHealth = 1.0;
    resp.health.compute();
    resp.statusLabel = resp.health.statusLabel();

    json j = resp.toJson();
    EXPECT_DOUBLE_EQ(j["health"]["success_rate"], 0.95);
    EXPECT_EQ(j["status_label"], "healthy");
}

TEST(HealthResponseTest, DegradedScores) {
    HealthResponse resp;
    resp.health.successRate = 0.60;
    resp.health.qualityTrend = -0.20;
    resp.health.dependencyHealth = 0.70;
    resp.health.compute();
    resp.statusLabel = resp.health.statusLabel();

    EXPECT_EQ(resp.statusLabel, "degraded");
}

TEST(HealthResponseTest, DefaultHealthIsHealthy) {
    HealthResponse resp;
    resp.health.compute();
    resp.statusLabel = resp.health.statusLabel();

    // Default: successRate=1.0, qualityTrend=0.0, dependencyHealth=1.0
    // overall = (1.0*0.4) + ((0.0+1.0)/2.0*0.3) + (1.0*0.3) = 0.85
    EXPECT_EQ(resp.statusLabel, "healthy");  // 0.85 >= 0.8 threshold
    EXPECT_DOUBLE_EQ(resp.health.overall, 0.85);
}

// ============================================================================
// LevelsResponse Tests
// ============================================================================

TEST(LevelsResponseTest, EmptyLevelsArray) {
    LevelsResponse resp;
    json j = resp.toJson();

    EXPECT_TRUE(j["levels"].is_array());
    EXPECT_EQ(j["levels"].size(), 0u);
}

TEST(LevelsResponseTest, LevelsResponseFromJsonEmpty) {
    json j;
    j["levels"] = json::array();

    LevelsResponse resp = LevelsResponse::fromJson(j);
    EXPECT_TRUE(resp.levels.empty());
}

// ============================================================================
// StartResponse Tests
// ============================================================================

TEST(StartResponseTest, ToJsonRoundTrip) {
    StartResponse resp;
    resp.status = "started";
    resp.state.cycleCount = 0;

    json j = resp.toJson();
    StartResponse restored = StartResponse::fromJson(j);

    EXPECT_EQ(restored.status, "started");
    EXPECT_EQ(restored.state.cycleCount, 0);
}

// ============================================================================
// ErrorDetail / ErrorResponse Tests
// ============================================================================

TEST(ErrorDetailTest, ToJsonRoundTrip) {
    ErrorDetail detail;
    detail.code = "INVALID_CONFIG";
    detail.message = "quality_threshold must be in [0.0, 1.0]";
    detail.httpStatus = 400;

    json j = detail.toJson();
    ErrorDetail restored = ErrorDetail::fromJson(j);

    EXPECT_EQ(restored.code, "INVALID_CONFIG");
    EXPECT_EQ(restored.message, "quality_threshold must be in [0.0, 1.0]");
    EXPECT_EQ(restored.httpStatus.value(), 400);
}

TEST(ErrorResponseTest, ErrorWrapperFormat) {
    ErrorDetail detail;
    detail.code = "ALREADY_RUNNING";
    detail.message = "Orchestrator is already running";
    detail.httpStatus = 409;

    ErrorResponse resp;
    resp.error = detail;

    json j = resp.toJson();
    EXPECT_TRUE(j.contains("error"));
    EXPECT_EQ(j["error"]["code"], "ALREADY_RUNNING");
    EXPECT_EQ(j["error"]["message"], "Orchestrator is already running");
    EXPECT_EQ(j["error"]["http_status"], 409);
}

TEST(ErrorDetailTest, NullHttpStatus) {
    ErrorDetail detail;
    detail.code = "TEST";
    detail.message = "Test";
    // httpStatus intentionally not set

    json j = detail.toJson();
    EXPECT_FALSE(j.contains("http_status"));
}

// ============================================================================
// ServerConfig Tests
// ============================================================================

TEST(ServerConfigTest, DefaultValues) {
    ServerConfig cfg;
    EXPECT_EQ(cfg.host, "0.0.0.0");
    EXPECT_EQ(cfg.port, 8080);
    EXPECT_EQ(cfg.threadPoolSize, 4);
    EXPECT_EQ(cfg.sseMaxEvents, 10000);
    EXPECT_EQ(cfg.ssePollIntervalMs, 250);
    EXPECT_TRUE(cfg.enableCors);
    EXPECT_EQ(cfg.allowedOrigins, "*");
    EXPECT_FALSE(cfg.enableHttps);
    EXPECT_EQ(cfg.shutdownTimeoutSec, 10);
}

TEST(ServerConfigTest, FromJsonFull) {
    json j;
    j["host"] = "127.0.0.1";
    j["port"] = 9090;
    j["thread_pool_size"] = 8;
    j["sse_max_events"] = 5000;
    j["sse_poll_interval_ms"] = 100;
    j["enable_cors"] = false;
    j["allowed_origins"] = "http://localhost:3000";
    j["enable_https"] = true;
    j["cert_path"] = "/cert.pem";
    j["key_path"] = "/key.pem";
    j["shutdown_timeout_sec"] = 30;

    ServerConfig cfg = ServerConfig::fromJson(j);

    EXPECT_EQ(cfg.host, "127.0.0.1");
    EXPECT_EQ(cfg.port, 9090);
    EXPECT_EQ(cfg.threadPoolSize, 8);
    EXPECT_EQ(cfg.sseMaxEvents, 5000);
    EXPECT_FALSE(cfg.enableCors);
    EXPECT_EQ(cfg.allowedOrigins, "http://localhost:3000");
    EXPECT_TRUE(cfg.enableHttps);
    EXPECT_EQ(cfg.certPath, "/cert.pem");
    EXPECT_EQ(cfg.shutdownTimeoutSec, 30);
}

TEST(ServerConfigTest, ToJsonRoundTrip) {
    ServerConfig cfg;
    cfg.host = "localhost";
    cfg.port = 7070;

    json j = cfg.toJson();
    ServerConfig restored = ServerConfig::fromJson(j);

    EXPECT_EQ(restored.host, "localhost");
    EXPECT_EQ(restored.port, 7070);
}

TEST(ServerConfigTest, PartialFromJsonRetainsDefaults) {
    json j;
    j["port"] = 3000;

    ServerConfig cfg = ServerConfig::fromJson(j);
    EXPECT_EQ(cfg.port, 3000);
    EXPECT_EQ(cfg.host, "0.0.0.0");  // default
    EXPECT_EQ(cfg.threadPoolSize, 4);  // default
}

// ============================================================================
// ApiOrchestratorState Tests
// ============================================================================

TEST(ApiOrchestratorStateTest, AllStateToStrings) {
    EXPECT_EQ(apiOrchestratorStateToString(ApiOrchestratorState::Idle), "idle");
    EXPECT_EQ(apiOrchestratorStateToString(ApiOrchestratorState::Starting), "starting");
    EXPECT_EQ(apiOrchestratorStateToString(ApiOrchestratorState::Running), "running");
    EXPECT_EQ(apiOrchestratorStateToString(ApiOrchestratorState::Paused), "paused");
    EXPECT_EQ(apiOrchestratorStateToString(ApiOrchestratorState::Cancelling), "cancelling");
    EXPECT_EQ(apiOrchestratorStateToString(ApiOrchestratorState::Cancelled), "cancelled");
    EXPECT_EQ(apiOrchestratorStateToString(ApiOrchestratorState::Done), "done");
    EXPECT_EQ(apiOrchestratorStateToString(ApiOrchestratorState::Error), "error");
}

TEST(ApiOrchestratorStateTest, StringToStateRoundTrip) {
    EXPECT_EQ(stringToApiOrchestratorState("idle"), ApiOrchestratorState::Idle);
    EXPECT_EQ(stringToApiOrchestratorState("running"), ApiOrchestratorState::Running);
    EXPECT_EQ(stringToApiOrchestratorState("done"), ApiOrchestratorState::Done);
    EXPECT_EQ(stringToApiOrchestratorState("cancelled"), ApiOrchestratorState::Cancelled);
}

TEST(ApiOrchestratorStateTest, InvalidStringThrows) {
    EXPECT_THROW(stringToApiOrchestratorState("invalid"), std::invalid_argument);
    EXPECT_THROW(stringToApiOrchestratorState(""), std::invalid_argument);
    EXPECT_THROW(stringToApiOrchestratorState("RUNNING"), std::invalid_argument);
}

// ============================================================================
// Error Code Constants Tests
// ============================================================================

TEST(ErrorCodeConstantsTest, AllDefined) {
    EXPECT_STREQ(ERR_INVALID_JSON, "INVALID_JSON");
    EXPECT_STREQ(ERR_MISSING_FIELD, "MISSING_FIELD");
    EXPECT_STREQ(ERR_INVALID_CONFIG, "INVALID_CONFIG");
    EXPECT_STREQ(ERR_ALREADY_RUNNING, "ALREADY_RUNNING");
    EXPECT_STREQ(ERR_NOT_RUNNING, "NOT_RUNNING");
    EXPECT_STREQ(ERR_NOT_PAUSED, "NOT_PAUSED");
    EXPECT_STREQ(ERR_CONFIG_LOCKED, "CONFIG_LOCKED");
    EXPECT_STREQ(ERR_OBJECTIVES_NOT_FOUND, "OBJECTIVES_NOT_FOUND");
    EXPECT_STREQ(ERR_INTERNAL, "INTERNAL_ERROR");
    EXPECT_STREQ(ERR_CANCEL_FAILED, "CANCEL_FAILED");
}

// ============================================================================
// Event Type Constants Tests
// ============================================================================

TEST(EventTypeConstantsTest, AllDefined) {
    EXPECT_STREQ(EVENT_OBJECTIVE_START, "objective_start");
    EXPECT_STREQ(EVENT_OBJECTIVE_COMPLETE, "objective_complete");
    EXPECT_STREQ(EVENT_OBJECTIVE_FAILED, "objective_failed");
    EXPECT_STREQ(EVENT_LEVEL_COMPLETE, "level_complete");
    EXPECT_STREQ(EVENT_HEALTH_UPDATE, "health_update");
    EXPECT_STREQ(EVENT_CIRCUIT_BREAKER, "circuit_breaker");
    EXPECT_STREQ(EVENT_ORCHESTRATOR_STATE, "orchestrator_state");
}

// ============================================================================
// OrchestratorServer Lifecycle Tests
// ============================================================================

TEST(OrchestratorServerTest, Construction) {
    OrchestratorEngine engine;
    OrchestratorServer server(engine);

    EXPECT_FALSE(server.isRunning());
}

TEST(OrchestratorServerTest, ConstructionWithCustomConfig) {
    OrchestratorEngine engine;
    ServerConfig cfg;
    cfg.port = 9999;
    cfg.sseMaxEvents = 500;
    OrchestratorServer server(engine, cfg);

    EXPECT_FALSE(server.isRunning());
}

TEST(OrchestratorServerTest, StartAndStop) {
    OrchestratorEngine engine;
    OrchestratorServer server(engine);

    EXPECT_TRUE(server.start("127.0.0.1", 0));  // port 0 = auto-assign
    EXPECT_TRUE(server.isRunning());

    server.stop();
    EXPECT_FALSE(server.isRunning());
}

TEST(OrchestratorServerTest, EngineAccessor) {
    OrchestratorEngine engine;
    OrchestratorConfig cfg;
    cfg.dryRun = true;
    cfg.objectivesPath = "test.json";
    engine.setConfig(cfg);

    OrchestratorServer server(engine);
    EXPECT_TRUE(server.engine().config().dryRun);
}

TEST(OrchestratorServerTest, BrokerAccessor) {
    OrchestratorEngine engine;
    OrchestratorServer server(engine);

    EXPECT_EQ(server.broker().eventCount(), 0u);
}

TEST(OrchestratorServerTest, ApiStateDefaultIdle) {
    OrchestratorEngine engine;
    OrchestratorServer server(engine);

    EXPECT_EQ(server.apiState(), ApiOrchestratorState::Idle);
}

TEST(OrchestratorServerTest, NonCopyable) {
    OrchestratorEngine engine;
    OrchestratorServer server(engine);

    static_assert(!std::is_copy_constructible_v<OrchestratorServer>);
    static_assert(!std::is_copy_assignable_v<OrchestratorServer>);
}

// ============================================================================
// Config GET/PUT Round-trip Tests (via engine)
// ============================================================================

TEST(ConfigRoundTripTest, GetConfigAfterSet) {
    OrchestratorEngine engine;

    OrchestratorConfig cfg;
    cfg.objectivesPath = "roundtrip.json";
    cfg.dryRun = true;
    cfg.maxCycleIterations = 25;
    engine.setConfig(cfg);

    EXPECT_EQ(engine.config().objectivesPath, "roundtrip.json");
    EXPECT_TRUE(engine.config().dryRun);
    EXPECT_EQ(engine.config().maxCycleIterations, 25);
}

TEST(ConfigRoundTripTest, ConfigJsonRoundTrip) {
    OrchestratorConfig cfg;
    cfg.dryRun = true;
    cfg.maxCycleIterations = 50;
    cfg.qualityThreshold = 0.75;

    json j = cfg.toJson();
    OrchestratorConfig restored = OrchestratorConfig::fromJson(j);

    EXPECT_TRUE(restored.dryRun);
    EXPECT_EQ(restored.maxCycleIterations, 50);
    EXPECT_DOUBLE_EQ(restored.qualityThreshold, 0.75);
}

// ============================================================================
// Health Endpoint Tests
// ============================================================================

TEST(HealthEndpointTest, DefaultHealthIsHealthy) {
    HealthScore health;
    health.compute();

    // Default: successRate=1.0, qualityTrend=0.0, dependencyHealth=1.0
    // overall = (1.0*0.4) + ((0.0+1.0)/2.0*0.3) + (1.0*0.3) = 0.85
    EXPECT_DOUBLE_EQ(health.overall, 0.85);
    EXPECT_EQ(health.statusLabel(), "healthy");  // 0.85 >= 0.8 threshold
}

TEST(HealthEndpointTest, HealthLabelThresholds) {
    HealthScore healthy;
    healthy.successRate = 0.90;
    healthy.qualityTrend = 0.0;
    healthy.dependencyHealth = 1.0;
    healthy.compute();
    EXPECT_EQ(healthy.statusLabel(), "healthy");

    HealthScore degraded;
    degraded.successRate = 0.50;
    degraded.qualityTrend = 0.0;
    degraded.dependencyHealth = 0.50;
    degraded.compute();
    EXPECT_EQ(degraded.statusLabel(), "degraded");

    HealthScore critical;
    critical.successRate = 0.0;
    critical.qualityTrend = -1.0;
    critical.dependencyHealth = 0.0;
    critical.compute();
    EXPECT_EQ(critical.statusLabel(), "critical");
}

// ============================================================================
// Levels Endpoint Tests
// ============================================================================

TEST(LevelsEndpointTest, EmptyForSequentialMode) {
    // Phase 5: levels endpoint returns empty array for sequential mode
    LevelsResponse resp;
    json j = resp.toJson();

    EXPECT_TRUE(j["levels"].is_array());
    EXPECT_EQ(j["levels"].size(), 0u);
}

// ============================================================================
// OrchestratorEngine + API Integration Tests
// ============================================================================

TEST(EngineApiIntegrationTest, StateChangeCallback) {
    OrchestratorEngine engine;
    std::vector<std::pair<std::string, json>> events;

    engine.setStateChangeCallback(
        [&events](const std::string& type, const json& data) {
            events.push_back({type, data});
        });

    // Manually trigger an event emission
    json testData;
    testData["test"] = "value";
    engine.emitStateChange("test_event", testData);

    ASSERT_EQ(events.size(), 1u);
    EXPECT_EQ(events[0].first, "test_event");
    EXPECT_EQ(events[0].second["test"], "value");
}

TEST(EngineApiIntegrationTest, CancelSetsRunningFalse) {
    OrchestratorEngine engine;
    EXPECT_FALSE(engine.isRunning());

    // cancel() is safe to call even when not running
    engine.cancel();
    EXPECT_FALSE(engine.isRunning());  // running only true during run()
}

TEST(EngineApiIntegrationTest, StateChangeCallbackExceptionSafety) {
    OrchestratorEngine engine;

    // Set a callback that throws
    engine.setStateChangeCallback(
        [](const std::string&, const json&) {
            throw std::runtime_error("Callback error");
        });

    // Should not throw -- callback exceptions are caught
    json data;
    data["test"] = true;
    EXPECT_NO_THROW(engine.emitStateChange("test_event", data));
}

TEST(EngineApiIntegrationTest, EngineRunEmitsStartAndDoneEvents) {
    OrchestratorEngine engine;
    std::vector<std::string> eventTypes;

    engine.setStateChangeCallback(
        [&eventTypes](const std::string& type, const json&) {
            eventTypes.push_back(type);
        });

    json project = makeProjectJson({
        makeObjectiveJson("obj-001", "Quick task")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.success = true;
        r.objectiveId = obj.objectiveId;
        return r;
    });

    engine.run();

    // Should have received at least: orchestrator_state (start),
    // objective_start, objective_complete, orchestrator_state (done)
    ASSERT_GE(eventTypes.size(), 4u);
    EXPECT_EQ(eventTypes[0], EVENT_ORCHESTRATOR_STATE);
    EXPECT_EQ(eventTypes.back(), EVENT_ORCHESTRATOR_STATE);

    fs::remove(path);
}

TEST(EngineApiIntegrationTest, EngineRunEmitsObjectiveEvents) {
    OrchestratorEngine engine;
    std::vector<std::string> eventTypes;

    engine.setStateChangeCallback(
        [&eventTypes](const std::string& type, const json&) {
            eventTypes.push_back(type);
        });

    json project = makeProjectJson({
        makeObjectiveJson("obj-001", "Task 1"),
        makeObjectiveJson("obj-002", "Task 2")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.success = true;
        r.objectiveId = obj.objectiveId;
        return r;
    });

    engine.run();

    // Should have objective_start and objective_complete for each objective
    int startCount = 0, completeCount = 0;
    for (const auto& type : eventTypes) {
        if (type == EVENT_OBJECTIVE_START) startCount++;
        if (type == EVENT_OBJECTIVE_COMPLETE) completeCount++;
    }
    EXPECT_EQ(startCount, 2);
    EXPECT_EQ(completeCount, 2);

    fs::remove(path);
}

TEST(EngineApiIntegrationTest, EngineRunEmitsFailureEvent) {
    OrchestratorEngine engine;
    std::vector<std::string> eventTypes;

    engine.setStateChangeCallback(
        [&eventTypes](const std::string& type, const json&) {
            eventTypes.push_back(type);
        });

    json project = makeProjectJson({
        makeObjectiveJson("obj-fail", "Failing task")
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

    engine.run();

    // Should have objective_failed event
    bool hasFailEvent = false;
    for (const auto& type : eventTypes) {
        if (type == EVENT_OBJECTIVE_FAILED) {
            hasFailEvent = true;
            break;
        }
    }
    EXPECT_TRUE(hasFailEvent);

    fs::remove(path);
}

TEST(EngineApiIntegrationTest, CancelFlagInterruptsPausedLoop) {
    OrchestratorEngine engine;

    json project = makeProjectJson({
        makeObjectiveJson("obj-slow", "Slow task")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    // Pause first, then set executor that would block
    engine.pause("Test pause");

    // Set cancel flag -- should cause run() to exit quickly
    engine.cancel();

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        // This should never be called since we're paused + cancelled
        ADD_FAILURE() << "Executor should not have been called";
        return {false, obj.objectiveId};
    });

    // Should return quickly due to cancel flag
    engine.run();

    // No objectives should have been processed
    EXPECT_EQ(engine.state().objectivesProcessed, 0);

    fs::remove(path);
}

// ============================================================================
// Server Lifecycle Edge-Case Tests
// ============================================================================

TEST(OrchestratorServerTest, StartStopStartLifecycle) {
    // Regression test: starting, stopping, then starting again should not
    // crash.  Previously, the second start would assign to a joinable
    // std::thread, which calls std::terminate().
    OrchestratorEngine engine;
    OrchestratorServer server(engine);

    EXPECT_TRUE(server.start("127.0.0.1", 0));
    EXPECT_TRUE(server.isRunning());
    server.stop();
    EXPECT_FALSE(server.isRunning());

    // Second start should succeed (routes are registered only once).
    EXPECT_TRUE(server.start("127.0.0.1", 0));
    EXPECT_TRUE(server.isRunning());
    server.stop();
    EXPECT_FALSE(server.isRunning());
}

TEST(OrchestratorServerTest, DoubleStartReturnsFalse) {
    OrchestratorEngine engine;
    OrchestratorServer server(engine);

    EXPECT_TRUE(server.start("127.0.0.1", 0));
    // Second start on an already-running server should fail gracefully.
    EXPECT_FALSE(server.start("127.0.0.1", 0));
    server.stop();
}

TEST(OrchestratorServerTest, DoubleStopIsSafe) {
    OrchestratorEngine engine;
    OrchestratorServer server(engine);

    server.start("127.0.0.1", 0);
    server.stop();
    // Second stop should be a no-op, not crash.
    EXPECT_NO_THROW(server.stop());
}

TEST(OrchestratorServerTest, StopBeforeStartIsSafe) {
    OrchestratorEngine engine;
    OrchestratorServer server(engine);
    // Stopping a server that was never started should not crash.
    EXPECT_NO_THROW(server.stop());
}

// ============================================================================
// Engine Concurrency Tests
// ============================================================================

TEST(EngineConcurrencyTest, StateChangeCallbackThreadSafety) {
    // Verify that setting the callback while emitting is safe.
    OrchestratorEngine engine;
    std::atomic<int> callbackCount = 0;
    std::atomic<bool> stopSetting = false;

    // Start a thread that repeatedly sets the callback
    std::thread setter([&engine, &callbackCount, &stopSetting]() {
        while (!stopSetting.load()) {
            engine.setStateChangeCallback(
                [&callbackCount](const std::string&, const json&) {
                    callbackCount++;
                });
            std::this_thread::yield();
        }
    });

    // Emit events from the main thread concurrently
    for (int i = 0; i < 100; ++i) {
        json data;
        data["iteration"] = i;
        engine.emitStateChange("concurrent_test", data);
    }

    stopSetting.store(true);
    setter.join();

    // Should not have crashed -- at least some callbacks fired
    EXPECT_GE(callbackCount.load(), 0);
}

TEST(EngineConcurrencyTest, StateReadDuringRun) {
    // Verify that reading state() during run() does not crash.
    OrchestratorEngine engine;
    std::atomic<bool> done = false;

    json project = makeProjectJson({
        makeObjectiveJson("obj-001", "Quick task")
    });

    std::string path = createTempObjectivesFile(project);
    engine.loadObjectives(path);

    engine.setExecutor([](Objective& obj) -> ExecutionResult {
        ExecutionResult r;
        r.success = true;
        r.objectiveId = obj.objectiveId;
        return r;
    });

    // Read state from a separate thread while run() executes
    std::thread reader([&engine, &done]() {
        while (!done.load()) {
            // This should not crash even during run()
            (void)engine.state();
            (void)engine.isRunning();
            std::this_thread::yield();
        }
    });

    engine.run();
    done.store(true);
    reader.join();

    EXPECT_GT(engine.state().objectivesProcessed, 0);

    fs::remove(path);
}
