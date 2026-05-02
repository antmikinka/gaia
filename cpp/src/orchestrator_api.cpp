// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT
//
// REST API server implementation for the GAIA C++ Orchestrator.
// Phase 5: SSE Bridge + REST API for GAIA C++ Orchestrator.

#include "gaia/orchestrator_api.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <memory>
#include <stdexcept>
#include <thread>

namespace gaia {

// ============================================================================
// SseEvent serialization
// ============================================================================

std::string SseEvent::toSseFormat() const {
    // Standard SSE field order: event, id, data (matches handleSseEvents output).
    // Browsers accept any order, but consistency matters for debugging and
    // compatibility with strict SSE parsers.
    return "event: " + type + "\nid: " + id + "\ndata: " + data + "\n\n";
}

json SseEvent::toJson() const {
    json j;
    j["id"] = id;
    j["type"] = type;
    j["data"] = data;
    j["timestamp"] = timestamp;
    return j;
}

SseEvent SseEvent::fromJson(const json& j) {
    SseEvent e;
    e.id = j.value("id", std::string{});
    e.type = j.value("type", std::string{});
    e.data = j.value("data", std::string{});
    e.timestamp = j.value("timestamp", std::string{});
    return e;
}

// ============================================================================
// StartRequest
// ============================================================================

json StartRequest::toJson() const {
    json j;
    if (objectivesPath.has_value()) {
        j["objectives_path"] = objectivesPath.value();
    }
    if (config.has_value()) {
        j["config"] = config.value().toJson();
    }
    return j;
}

StartRequest StartRequest::fromJson(const json& j) {
    StartRequest req;
    if (j.contains("objectives_path") && !j["objectives_path"].is_null()) {
        req.objectivesPath = j["objectives_path"].get<std::string>();
    }
    if (j.contains("config") && !j["config"].is_null()) {
        req.config = OrchestratorConfig::fromJson(j["config"]);
    }
    return req;
}

// ============================================================================
// PauseRequest
// ============================================================================

json PauseRequest::toJson() const {
    json j;
    j["reason"] = reason;
    return j;
}

PauseRequest PauseRequest::fromJson(const json& j) {
    PauseRequest req;
    req.reason = j.value("reason", std::string{});
    return req;
}

// ============================================================================
// UpdateConfigRequest
// ============================================================================

json UpdateConfigRequest::toJson() const {
    json j;
    j["config"] = config.toJson();
    return j;
}

UpdateConfigRequest UpdateConfigRequest::fromJson(const json& j) {
    UpdateConfigRequest req;
    if (j.contains("config")) {
        req.config = OrchestratorConfig::fromJson(j["config"]);
    }
    return req;
}

// ============================================================================
// ApiResponse
// ============================================================================

json ApiResponse::toJson() const {
    json j;
    j["status"] = status;
    j["message"] = message;
    return j;
}

ApiResponse ApiResponse::fromJson(const json& j) {
    ApiResponse resp;
    resp.status = j.value("status", std::string{});
    resp.message = j.value("message", std::string{});
    return resp;
}

// ============================================================================
// StatusResponse
// ============================================================================

json StatusResponse::toJson() const {
    json j;
    j["running"] = running;
    j["state"] = apiOrchestratorStateToString(state);
    j["engine_state"] = engineState.toJson();
    j["config"] = config.toJson();
    if (project.has_value()) {
        j["project"] = project.value().toJson();
    }
    return j;
}

StatusResponse StatusResponse::fromJson(const json& j) {
    StatusResponse resp;
    resp.running = j.value("running", false);
    if (j.contains("state")) {
        resp.state = stringToApiOrchestratorState(j["state"].get<std::string>());
    }
    if (j.contains("engine_state")) {
        resp.engineState = OrchestratorState::fromJson(j["engine_state"]);
    }
    if (j.contains("config")) {
        resp.config = OrchestratorConfig::fromJson(j["config"]);
    }
    if (j.contains("project")) {
        resp.project = ProjectObjectives::fromJson(j["project"]);
    }
    return resp;
}

// ============================================================================
// ConfigResponse
// ============================================================================

json ConfigResponse::toJson() const {
    json j;
    j["config"] = config.toJson();
    return j;
}

ConfigResponse ConfigResponse::fromJson(const json& j) {
    ConfigResponse resp;
    if (j.contains("config")) {
        resp.config = OrchestratorConfig::fromJson(j["config"]);
    }
    return resp;
}

// ============================================================================
// HealthResponse
// ============================================================================

json HealthResponse::toJson() const {
    json j;
    j["health"] = health.toJson();
    j["status_label"] = statusLabel;
    return j;
}

HealthResponse HealthResponse::fromJson(const json& j) {
    HealthResponse resp;
    if (j.contains("health")) {
        resp.health = HealthScore::fromJson(j["health"]);
    }
    resp.statusLabel = j.value("status_label", std::string{});
    return resp;
}

// ============================================================================
// LevelsResponse
// ============================================================================

json LevelsResponse::toJson() const {
    json j;
    json levelsArr = json::array();
    for (const auto& level : levels) {
        levelsArr.push_back(level.toJson());
    }
    j["levels"] = levelsArr;
    return j;
}

LevelsResponse LevelsResponse::fromJson(const json& j) {
    LevelsResponse resp;
    resp.levels.clear();
    if (j.contains("levels") && j["levels"].is_array()) {
        for (const auto& l : j["levels"]) {
            resp.levels.push_back(LevelResult::fromJson(l));
        }
    }
    return resp;
}

// ============================================================================
// StartResponse
// ============================================================================

json StartResponse::toJson() const {
    json j;
    j["status"] = status;
    j["state"] = state.toJson();
    return j;
}

StartResponse StartResponse::fromJson(const json& j) {
    StartResponse resp;
    resp.status = j.value("status", std::string{});
    if (j.contains("state")) {
        resp.state = OrchestratorState::fromJson(j["state"]);
    }
    return resp;
}

// ============================================================================
// ErrorDetail
// ============================================================================

json ErrorDetail::toJson() const {
    json j;
    j["code"] = code;
    j["message"] = message;
    if (httpStatus.has_value()) {
        j["http_status"] = httpStatus.value();
    }
    return j;
}

ErrorDetail ErrorDetail::fromJson(const json& j) {
    ErrorDetail detail;
    detail.code = j.value("code", std::string{});
    detail.message = j.value("message", std::string{});
    if (j.contains("http_status") && !j["http_status"].is_null()) {
        detail.httpStatus = j["http_status"].get<int>();
    }
    return detail;
}

// ============================================================================
// ErrorResponse
// ============================================================================

json ErrorResponse::toJson() const {
    json j;
    j["error"] = error.toJson();
    return j;
}

ErrorResponse ErrorResponse::fromJson(const json& j) {
    ErrorResponse resp;
    if (j.contains("error")) {
        resp.error = ErrorDetail::fromJson(j["error"]);
    }
    return resp;
}

// ============================================================================
// ServerConfig
// ============================================================================

json ServerConfig::toJson() const {
    json j;
    j["host"] = host;
    j["port"] = port;
    j["thread_pool_size"] = threadPoolSize;
    j["sse_max_events"] = sseMaxEvents;
    j["sse_poll_interval_ms"] = ssePollIntervalMs;
    j["enable_cors"] = enableCors;
    j["allowed_origins"] = allowedOrigins;
    j["enable_https"] = enableHttps;
    j["cert_path"] = certPath;
    j["key_path"] = keyPath;
    j["shutdown_timeout_sec"] = shutdownTimeoutSec;
    return j;
}

ServerConfig ServerConfig::fromJson(const json& j) {
    ServerConfig cfg;
    if (j.contains("host")) cfg.host = j["host"].get<std::string>();
    if (j.contains("port")) cfg.port = j["port"].get<int>();
    if (j.contains("thread_pool_size")) cfg.threadPoolSize = j["thread_pool_size"].get<int>();
    if (j.contains("sse_max_events")) cfg.sseMaxEvents = j["sse_max_events"].get<int>();
    if (j.contains("sse_poll_interval_ms")) cfg.ssePollIntervalMs = j["sse_poll_interval_ms"].get<int>();
    if (j.contains("enable_cors")) cfg.enableCors = j["enable_cors"].get<bool>();
    if (j.contains("allowed_origins")) cfg.allowedOrigins = j["allowed_origins"].get<std::string>();
    if (j.contains("enable_https")) cfg.enableHttps = j["enable_https"].get<bool>();
    if (j.contains("cert_path")) cfg.certPath = j["cert_path"].get<std::string>();
    if (j.contains("key_path")) cfg.keyPath = j["key_path"].get<std::string>();
    if (j.contains("shutdown_timeout_sec")) cfg.shutdownTimeoutSec = j["shutdown_timeout_sec"].get<int>();
    return cfg;
}

// ============================================================================
// SseEventBroker implementation
// ============================================================================

SseEventBroker::SseEventBroker(size_t maxEvents)
    : maxEvents_(maxEvents) {}

void SseEventBroker::push(const SseEvent& event) {
    std::lock_guard<std::mutex> lock(mutex_);
    events_.push_back(event);
    // Auto-prune if exceeding limit
    if (events_.size() > maxEvents_) {
        size_t keep = maxEvents_ / 2;
        events_.erase(events_.begin(), events_.begin() + static_cast<long>(events_.size() - keep));
    }
    cv_.notify_all();
}

void SseEventBroker::pushWithId(SseEvent& event) {
    event.id = std::to_string(nextId_.fetch_add(1));
    std::lock_guard<std::mutex> lock(mutex_);
    events_.push_back(event);
    // Auto-prune if exceeding limit
    if (events_.size() > maxEvents_) {
        size_t keep = maxEvents_ / 2;
        events_.erase(events_.begin(), events_.begin() + static_cast<long>(events_.size() - keep));
    }
    cv_.notify_all();
}

std::pair<std::vector<SseEvent>, size_t> SseEventBroker::getEventsSince(
    size_t sinceIndex,
    std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> lock(mutex_);

    // If the client's index is beyond the current event log (e.g., after
    // pruning), return all available events immediately rather than waiting
    // for a condition that can never be satisfied.
    if (sinceIndex > events_.size()) {
        size_t maxIdx = events_.size();
        std::vector<SseEvent> result(events_);
        return {std::move(result), maxIdx};
    }

    // sinceIndex == events_.size() means client has seen all events.
    // Wait for new events or timeout.
    cv_.wait_for(lock, timeout, [this, sinceIndex] {
        return events_.size() > sinceIndex;
    });

    size_t maxIdx = events_.size();
    std::vector<SseEvent> result;
    if (sinceIndex < events_.size()) {
        result.assign(events_.begin() + static_cast<long>(sinceIndex), events_.end());
    }
    return {std::move(result), maxIdx};
}

size_t SseEventBroker::eventCount() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return events_.size();
}

void SseEventBroker::prune(size_t keepCount) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (events_.size() > keepCount) {
        events_.erase(events_.begin(),
                      events_.begin() + static_cast<long>(events_.size() - keepCount));
    }
}

size_t SseEventBroker::maxIndex() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return events_.size();
}

// ============================================================================
// OrchestratorServer implementation
// ============================================================================

OrchestratorServer::OrchestratorServer(OrchestratorEngine& engine,
                                        const ServerConfig& config)
    : serverConfig_(config),
      engine_(engine),
      broker_(config.sseMaxEvents) {}

OrchestratorServer::~OrchestratorServer() {
    stop();
}

bool OrchestratorServer::start(const std::string& host, int port) {
    if (serverRunning_.load()) {
        return false;
    }

    serverConfig_.host = host;
    serverConfig_.port = port;

    // Configure the HTTP server thread pool.
    // new_task_queue controls the worker thread count (default is 8).
    svr_.new_task_queue = []() {
        return new httplib::ThreadPool(8);
    };

    // Register routes only once across the server lifetime.
    // Re-adding routes on restart would create duplicate handlers.
    if (!routesRegistered_.load()) {
        bool expected = false;
        if (routesRegistered_.compare_exchange_strong(expected, true)) {
            registerRoutes();
        }
    }

    serverRunning_.store(true);
    apiState_.store(ApiOrchestratorState::Idle);

    // Start HTTP server in background thread
    httpThread_.emplace([this]() {
        svr_.listen(serverConfig_.host, serverConfig_.port);
    });

    // Wait for server to be ready (blocking until bound)
    svr_.wait_until_ready();

    return svr_.is_running();
}

void OrchestratorServer::stop() {
    if (!serverRunning_.load()) {
        return;
    }

    serverRunning_.store(false);

    // Cancel any running orchestrator execution
    if (apiState_.load() == ApiOrchestratorState::Running ||
        apiState_.load() == ApiOrchestratorState::Paused) {
        engine_.cancel();
    }

    // Wait for orchestrator thread to finish
    if (orchestratorThread_.joinable()) {
        orchestratorThread_.join();
    }

    // Stop HTTP server
    svr_.stop();

    // Wait for HTTP thread to finish
    if (httpThread_.has_value() && httpThread_->joinable()) {
        httpThread_->join();
    }

    apiState_.store(ApiOrchestratorState::Idle);
}

bool OrchestratorServer::isRunning() const {
    return serverRunning_.load();
}

ApiOrchestratorState OrchestratorServer::apiState() const {
    return apiState_.load();
}

void OrchestratorServer::registerRoutes() {
    // CORS preflight handler
    svr_.Options("/api/v1/(.*)", [this](const httplib::Request& req,
                                         httplib::Response& res) {
        handleOptions(req, res);
    });

    svr_.Options("/api/v1/orchestrator/start", [this](const httplib::Request& req,
                                                       httplib::Response& res) {
        handleOptions(req, res);
    });

    svr_.Options("/api/v1/orchestrator/status", [this](const httplib::Request& req,
                                                        httplib::Response& res) {
        handleOptions(req, res);
    });

    // Lifecycle endpoints
    svr_.Post("/api/v1/orchestrator/start", [this](const httplib::Request& req,
                                                    httplib::Response& res) {
        handleStart(req, res);
    });

    svr_.Post("/api/v1/orchestrator/pause", [this](const httplib::Request& req,
                                                    httplib::Response& res) {
        handlePause(req, res);
    });

    svr_.Post("/api/v1/orchestrator/resume", [this](const httplib::Request& req,
                                                     httplib::Response& res) {
        handleResume(req, res);
    });

    svr_.Post("/api/v1/orchestrator/cancel", [this](const httplib::Request& req,
                                                     httplib::Response& res) {
        handleCancel(req, res);
    });

    // Status endpoint
    svr_.Get("/api/v1/orchestrator/status", [this](const httplib::Request& req,
                                                    httplib::Response& res) {
        handleStatus(req, res);
    });

    // Config endpoints
    svr_.Get("/api/v1/orchestrator/config", [this](const httplib::Request& req,
                                                    httplib::Response& res) {
        handleGetConfig(req, res);
    });

    svr_.Put("/api/v1/orchestrator/config", [this](const httplib::Request& req,
                                                    httplib::Response& res) {
        handleUpdateConfig(req, res);
    });

    // Health endpoint
    svr_.Get("/api/v1/orchestrator/health", [this](const httplib::Request& req,
                                                    httplib::Response& res) {
        handleHealth(req, res);
    });

    // Levels endpoint
    svr_.Get("/api/v1/orchestrator/levels", [this](const httplib::Request& req,
                                                    httplib::Response& res) {
        handleLevels(req, res);
    });

    // SSE events endpoint — uses chunked transfer for text/event-stream
    svr_.Get("/api/v1/sse/events", [this](const httplib::Request& req,
                                           httplib::Response& res) {
        handleSseEvents(req, res);
    });
}

void OrchestratorServer::addCorsHeaders(httplib::Response& res) {
    if (serverConfig_.enableCors) {
        res.set_header("Access-Control-Allow-Origin",
                       serverConfig_.allowedOrigins.c_str());
        res.set_header("Access-Control-Allow-Methods",
                       "GET, POST, PUT, DELETE, OPTIONS");
        res.set_header("Access-Control-Allow-Headers",
                       "Content-Type, Authorization");
    }
}

void OrchestratorServer::sendError(httplib::Response& res,
                                    const std::string& code,
                                    const std::string& message,
                                    int httpStatus) {
    res.status = httpStatus;
    res.set_header("Content-Type", "application/json");
    addCorsHeaders(res);

    ErrorDetail detail;
    detail.code = code;
    detail.message = message;
    detail.httpStatus = httpStatus;

    ErrorResponse resp;
    resp.error = detail;

    res.set_content(resp.toJson().dump(), "application/json");
}

void OrchestratorServer::handleOptions(const httplib::Request& /*req*/,
                                        httplib::Response& res) {
    res.status = 204;
    addCorsHeaders(res);
}

void OrchestratorServer::handleStart(const httplib::Request& req,
                                      httplib::Response& res) {
    addCorsHeaders(res);
    res.set_header("Content-Type", "application/json");

    try {
        // Atomically check and transition from a terminal/idle state to Starting.
        // This prevents TOCTOU races when concurrent start requests arrive.
        auto expected = apiState_.load();
        if (expected != ApiOrchestratorState::Idle &&
            expected != ApiOrchestratorState::Done &&
            expected != ApiOrchestratorState::Cancelled) {
            sendError(res, ERR_ALREADY_RUNNING,
                      "Orchestrator is already running", 409);
            return;
        }
        if (!apiState_.compare_exchange_strong(expected, ApiOrchestratorState::Starting)) {
            sendError(res, ERR_ALREADY_RUNNING,
                      "Orchestrator is already running", 409);
            return;
        }

        // Parse request body
        StartRequest startReq;
        if (!req.body.empty()) {
            json body = json::parse(req.body);
            startReq = StartRequest::fromJson(body);
        }

        // Apply config overrides if provided
        if (startReq.config.has_value()) {
            engine_.setConfig(startReq.config.value());
        }

        // State already set to Starting by CAS above

        // Emit starting event
        json startingData;
        startingData["state"] = "starting";
        startingData["timestamp"] = getCurrentTimestamp();
        emitEvent(EVENT_ORCHESTRATOR_STATE, startingData);

        // Load objectives
        if (startReq.objectivesPath.has_value()) {
            engine_.loadObjectives(startReq.objectivesPath.value());
        } else if (!engine_.project().has_value()) {
            engine_.loadObjectives();
        }

        // Set state change callback to bridge to SSE broker
        engine_.setStateChangeCallback(
            [this](const std::string& eventType, const json& data) {
                emitEvent(eventType, data);
            });

        // Set running state
        apiState_.store(ApiOrchestratorState::Running);

        // Emit running event
        json runningData;
        runningData["state"] = "running";
        runningData["timestamp"] = getCurrentTimestamp();
        emitEvent(EVENT_ORCHESTRATOR_STATE, runningData);

        // Start orchestrator in background thread
        // Ensure any previous run's thread is fully cleaned up first.
        // Assigning to a joinable std::thread calls std::terminate().
        if (orchestratorThread_.joinable()) {
            orchestratorThread_.join();
        }
        orchestratorThread_ = std::thread(&OrchestratorServer::runOrchestratorLoop, this);

        // Return success response
        StartResponse startResp;
        startResp.state = engine_.state();
        res.status = 200;
        res.set_content(startResp.toJson().dump(), "application/json");
    } catch (const json::parse_error& e) {
        sendError(res, ERR_INVALID_JSON, e.what(), 400);
    } catch (const std::invalid_argument& e) {
        sendError(res, ERR_INVALID_CONFIG, e.what(), 400);
    } catch (const std::runtime_error& e) {
        sendError(res, ERR_OBJECTIVES_NOT_FOUND, e.what(), 500);
    } catch (const std::exception& e) {
        sendError(res, ERR_INTERNAL, e.what(), 500);
    }
}

void OrchestratorServer::handlePause(const httplib::Request& req,
                                      httplib::Response& res) {
    addCorsHeaders(res);
    res.set_header("Content-Type", "application/json");

    try {
        auto currentState = apiState_.load();
        if (currentState != ApiOrchestratorState::Running) {
            sendError(res, ERR_NOT_RUNNING,
                      "Orchestrator is not running", 400);
            return;
        }

        std::string reason;
        if (!req.body.empty()) {
            json body = json::parse(req.body);
            PauseRequest pauseReq = PauseRequest::fromJson(body);
            reason = pauseReq.reason;
        }

        engine_.pause(reason);
        apiState_.store(ApiOrchestratorState::Paused);

        json pauseData;
        pauseData["state"] = "paused";
        pauseData["reason"] = reason;
        pauseData["timestamp"] = getCurrentTimestamp();
        emitEvent(EVENT_ORCHESTRATOR_STATE, pauseData);

        ApiResponse resp;
        resp.status = "paused";
        resp.message = "Orchestrator paused" + (reason.empty() ? "" : ": " + reason);
        res.status = 200;
        res.set_content(resp.toJson().dump(), "application/json");
    } catch (const json::parse_error& e) {
        sendError(res, ERR_INVALID_JSON, e.what(), 400);
    } catch (const std::exception& e) {
        sendError(res, ERR_INTERNAL, e.what(), 500);
    }
}

void OrchestratorServer::handleResume(const httplib::Request& /*req*/,
                                       httplib::Response& res) {
    addCorsHeaders(res);
    res.set_header("Content-Type", "application/json");

    try {
        auto currentState = apiState_.load();
        if (currentState != ApiOrchestratorState::Paused) {
            sendError(res, ERR_NOT_PAUSED,
                      "Orchestrator is not paused", 400);
            return;
        }

        engine_.resume();
        apiState_.store(ApiOrchestratorState::Running);

        json resumeData;
        resumeData["state"] = "running";
        resumeData["timestamp"] = getCurrentTimestamp();
        emitEvent(EVENT_ORCHESTRATOR_STATE, resumeData);

        ApiResponse resp;
        resp.status = "resumed";
        resp.message = "Orchestrator resumed";
        res.status = 200;
        res.set_content(resp.toJson().dump(), "application/json");
    } catch (const std::exception& e) {
        sendError(res, ERR_INTERNAL, e.what(), 500);
    }
}

void OrchestratorServer::handleStatus(const httplib::Request& /*req*/,
                                       httplib::Response& res) {
    addCorsHeaders(res);
    res.set_header("Content-Type", "application/json");

    try {
        StatusResponse resp;
        resp.running = engine_.isRunning();
        resp.state = apiState_.load();
        resp.engineState = engine_.getStateSnapshot();
        resp.config = engine_.config();
        resp.project = engine_.project();

        res.status = 200;
        res.set_content(resp.toJson().dump(), "application/json");
    } catch (const std::exception& e) {
        sendError(res, ERR_INTERNAL, e.what(), 500);
    }
}

void OrchestratorServer::handleCancel(const httplib::Request& /*req*/,
                                       httplib::Response& res) {
    addCorsHeaders(res);
    res.set_header("Content-Type", "application/json");

    try {
        auto currentState = apiState_.load();
        if (currentState != ApiOrchestratorState::Running &&
            currentState != ApiOrchestratorState::Paused) {
            sendError(res, ERR_NOT_RUNNING,
                      "Orchestrator is not running", 400);
            return;
        }

        apiState_.store(ApiOrchestratorState::Cancelling);

        json cancelData;
        cancelData["state"] = "cancelling";
        cancelData["timestamp"] = getCurrentTimestamp();
        emitEvent(EVENT_ORCHESTRATOR_STATE, cancelData);

        engine_.cancel();

        // Wait for orchestrator thread to finish
        if (orchestratorThread_.joinable()) {
            orchestratorThread_.join();
        }

        apiState_.store(ApiOrchestratorState::Cancelled);

        json cancelledData;
        cancelledData["state"] = "cancelled";
        cancelledData["timestamp"] = getCurrentTimestamp();
        emitEvent(EVENT_ORCHESTRATOR_STATE, cancelledData);

        ApiResponse resp;
        resp.status = "cancelled";
        resp.message = "Orchestrator cancelled";
        res.status = 200;
        res.set_content(resp.toJson().dump(), "application/json");
    } catch (const std::exception& e) {
        sendError(res, ERR_INTERNAL, e.what(), 500);
    }
}

void OrchestratorServer::handleGetConfig(const httplib::Request& /*req*/,
                                          httplib::Response& res) {
    addCorsHeaders(res);
    res.set_header("Content-Type", "application/json");

    try {
        ConfigResponse resp;
        resp.config = engine_.config();

        res.status = 200;
        res.set_content(resp.toJson().dump(), "application/json");
    } catch (const std::exception& e) {
        sendError(res, ERR_INTERNAL, e.what(), 500);
    }
}

void OrchestratorServer::handleUpdateConfig(const httplib::Request& req,
                                             httplib::Response& res) {
    addCorsHeaders(res);
    res.set_header("Content-Type", "application/json");

    try {
        auto currentState = apiState_.load();
        if (currentState == ApiOrchestratorState::Running ||
            currentState == ApiOrchestratorState::Starting) {
            sendError(res, ERR_CONFIG_LOCKED,
                      "Cannot update config while orchestrator is running", 409);
            return;
        }

        json body = json::parse(req.body);
        UpdateConfigRequest updateReq = UpdateConfigRequest::fromJson(body);

        engine_.setConfig(updateReq.config);

        ConfigResponse resp;
        resp.config = engine_.config();
        ApiResponse apiResp;
        apiResp.status = "updated";
        apiResp.message = "Configuration updated";

        json combined;
        combined["config"] = resp.config.toJson();
        combined["status"] = apiResp.status;

        res.status = 200;
        res.set_content(combined.dump(), "application/json");
    } catch (const json::parse_error& e) {
        sendError(res, ERR_INVALID_JSON, e.what(), 400);
    } catch (const std::invalid_argument& e) {
        sendError(res, ERR_INVALID_CONFIG, e.what(), 400);
    } catch (const std::exception& e) {
        sendError(res, ERR_INTERNAL, e.what(), 500);
    }
}

void OrchestratorServer::handleHealth(const httplib::Request& /*req*/,
                                       httplib::Response& res) {
    addCorsHeaders(res);
    res.set_header("Content-Type", "application/json");

    try {
        HealthResponse resp;
        resp.health.compute();
        resp.statusLabel = resp.health.statusLabel();

        res.status = 200;
        res.set_content(resp.toJson().dump(), "application/json");
    } catch (const std::exception& e) {
        sendError(res, ERR_INTERNAL, e.what(), 500);
    }
}

void OrchestratorServer::handleLevels(const httplib::Request& /*req*/,
                                       httplib::Response& res) {
    addCorsHeaders(res);
    res.set_header("Content-Type", "application/json");

    try {
        // Phase 5: Return empty array for sequential execution mode.
        // See design document Section 6.3 for details.
        LevelsResponse resp;
        // resp.levels is empty by default

        res.status = 200;
        res.set_content(resp.toJson().dump(), "application/json");
    } catch (const std::exception& e) {
        sendError(res, ERR_INTERNAL, e.what(), 500);
    }
}

void OrchestratorServer::handleSseEvents(const httplib::Request& req,
                                          httplib::Response& res) {
    res.set_header("Content-Type", "text/event-stream");
    res.set_header("Cache-Control", "no-cache");
    res.set_header("Connection", "keep-alive");
    res.set_header("X-Accel-Buffering", "no");
    addCorsHeaders(res);

    size_t sinceIndex = 0;

    // Support reconnection via both SSE-standard Last-Event-ID header
    // and the query parameter fallback (?lastEventId=N).
    std::string lastEventId = req.get_header_value("Last-Event-ID");
    if (!lastEventId.empty()) {
        try {
            sinceIndex = std::stoull(lastEventId);
        } catch (...) {
            sinceIndex = 0;
        }
    } else if (req.has_param("lastEventId")) {
        try {
            sinceIndex = std::stoull(req.get_param_value("lastEventId"));
        } catch (...) {
            sinceIndex = 0;
        }
    }

    auto pollInterval = std::chrono::milliseconds(serverConfig_.ssePollIntervalMs);
    auto keepaliveInterval = std::chrono::seconds(30);
    auto lastKeepalive = std::chrono::steady_clock::now();

    res.set_chunked_content_provider(
        "text/event-stream",
        [this, sinceIndex, pollInterval, keepaliveInterval,
         lastKeepalive](size_t /*offset*/, httplib::DataSink& sink) mutable -> bool {
            if (!serverRunning_.load()) {
                return false;
            }

            // Send keepalive heartbeat periodically
            auto now = std::chrono::steady_clock::now();
            if (now - lastKeepalive >= keepaliveInterval) {
                sink.os << ": heartbeat\n\n";
                lastKeepalive = now;
            }

            auto [events, maxIdx] = broker_.getEventsSince(sinceIndex, pollInterval);
            for (const auto& evt : events) {
                // SSE format per spec: event, id, data fields
                sink.os << "event: " << evt.type << "\n";
                sink.os << "id: " << evt.id << "\n";
                sink.os << "data: " << evt.data << "\n\n";
                sinceIndex++;
            }
            return true;  // Keep connection open
        }
    );
}

void OrchestratorServer::runOrchestratorLoop() {
    try {
        engine_.run();
    } catch (const std::exception& e) {
        json errorData;
        errorData["state"] = "error";
        errorData["message"] = e.what();
        errorData["timestamp"] = getCurrentTimestamp();
        emitEvent(EVENT_ORCHESTRATOR_STATE, errorData);
    }

    // Transition to Done only if not cancelled.
    // When cancelled, handleCancel() will set the state to Cancelled and
    // emit the appropriate event.  Emitting "done" here during cancellation
    // would produce a misleading event sequence in the SSE stream.
    auto currentState = apiState_.load();
    if (currentState == ApiOrchestratorState::Running) {
        apiState_.store(ApiOrchestratorState::Done);

        json doneData;
        doneData["state"] = "done";
        doneData["cycle_count"] = engine_.state().cycleCount;
        doneData["objectives_processed"] = engine_.state().objectivesProcessed;
        doneData["objectives_failed"] = engine_.state().objectivesFailed;
        doneData["timestamp"] = getCurrentTimestamp();
        emitEvent(EVENT_ORCHESTRATOR_STATE, doneData);
    }
}

void OrchestratorServer::emitEvent(const std::string& eventType,
                                    const json& data) {
    SseEvent event;
    event.type = eventType;
    event.data = data.dump();
    event.timestamp = getCurrentTimestamp();

    broker_.pushWithId(event);
}

} // namespace gaia
