// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT
//
// API types for the GAIA C++ Orchestrator REST server.
// Phase 5: SSE Bridge + REST API for GAIA C++ Orchestrator.

#pragma once

#include <optional>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "gaia/orchestrator_engine.h"
#include "gaia/orchestrator_supervisor.h"

namespace gaia {

using json = nlohmann::json;

// ---------------------------------------------------------------------------
// SseEvent — a single SSE event for broadcasting
// ---------------------------------------------------------------------------

struct SseEvent {
    std::string id;         // Sequential numeric ID (string for SSE compatibility)
    std::string type;       // Event type: objective_start, objective_complete, etc.
    std::string data;       // JSON payload string
    std::string timestamp;  // ISO 8601

    /// Serialize to SSE wire format: "event: type\ndata: payload\n\n"
    std::string toSseFormat() const;

    json toJson() const;
    static SseEvent fromJson(const json& j);
};

// ---------------------------------------------------------------------------
// API Event Type Constants
// ---------------------------------------------------------------------------

inline const char* const EVENT_OBJECTIVE_START    = "objective_start";
inline const char* const EVENT_OBJECTIVE_COMPLETE = "objective_complete";
inline const char* const EVENT_OBJECTIVE_FAILED   = "objective_failed";
inline const char* const EVENT_LEVEL_COMPLETE     = "level_complete";
inline const char* const EVENT_HEALTH_UPDATE      = "health_update";
inline const char* const EVENT_CIRCUIT_BREAKER    = "circuit_breaker";
inline const char* const EVENT_ORCHESTRATOR_STATE = "orchestrator_state";

// ---------------------------------------------------------------------------
// ApiOrchestratorState enum (for API consumers — distinct from OrchestratorState struct)
// ---------------------------------------------------------------------------

enum class ApiOrchestratorState {
    Idle,        // Not started
    Starting,    // Start requested, objectives loading
    Running,     // Execution in progress
    Paused,      // Paused by client
    Cancelling,  // Cancellation in progress
    Cancelled,   // Cancelled by client
    Done,        // Execution completed (all objectives)
    Error        // Unrecoverable error
};

inline std::string apiOrchestratorStateToString(ApiOrchestratorState s) {
    switch (s) {
        case ApiOrchestratorState::Idle:        return "idle";
        case ApiOrchestratorState::Starting:    return "starting";
        case ApiOrchestratorState::Running:     return "running";
        case ApiOrchestratorState::Paused:      return "paused";
        case ApiOrchestratorState::Cancelling:  return "cancelling";
        case ApiOrchestratorState::Cancelled:   return "cancelled";
        case ApiOrchestratorState::Done:        return "done";
        case ApiOrchestratorState::Error:       return "error";
    }
    return "unknown";
}

inline ApiOrchestratorState stringToApiOrchestratorState(const std::string& s) {
    if (s == "idle")        return ApiOrchestratorState::Idle;
    if (s == "starting")    return ApiOrchestratorState::Starting;
    if (s == "running")     return ApiOrchestratorState::Running;
    if (s == "paused")      return ApiOrchestratorState::Paused;
    if (s == "cancelling")  return ApiOrchestratorState::Cancelling;
    if (s == "cancelled")   return ApiOrchestratorState::Cancelled;
    if (s == "done")        return ApiOrchestratorState::Done;
    if (s == "error")       return ApiOrchestratorState::Error;
    throw std::invalid_argument("Invalid ApiOrchestratorState string: " + s);
}

// ---------------------------------------------------------------------------
// Request Types
// ---------------------------------------------------------------------------

/// POST /api/v1/orchestrator/start
struct StartRequest {
    std::optional<std::string> objectivesPath;  // Override config path
    std::optional<OrchestratorConfig> config;   // Override configuration

    json toJson() const;
    static StartRequest fromJson(const json& j);
};

/// POST /api/v1/orchestrator/pause
struct PauseRequest {
    std::string reason;  // Optional pause reason

    json toJson() const;
    static PauseRequest fromJson(const json& j);
};

/// PUT /api/v1/orchestrator/config
struct UpdateConfigRequest {
    OrchestratorConfig config;

    json toJson() const;
    static UpdateConfigRequest fromJson(const json& j);
};

// ---------------------------------------------------------------------------
// Response Types
// ---------------------------------------------------------------------------

/// Generic success response
struct ApiResponse {
    std::string status;       // "ok", "started", "paused", etc.
    std::string message;      // Human-readable description

    json toJson() const;
    static ApiResponse fromJson(const json& j);
};

/// GET /api/v1/orchestrator/status
struct StatusResponse {
    bool running = false;
    ApiOrchestratorState state = ApiOrchestratorState::Idle;
    OrchestratorState engineState;    // From OrchestratorEngine
    OrchestratorConfig config;        // Current configuration
    std::optional<ProjectObjectives> project;  // Loaded objectives (if any)

    json toJson() const;
    static StatusResponse fromJson(const json& j);
};

/// GET /api/v1/orchestrator/config
struct ConfigResponse {
    OrchestratorConfig config;

    json toJson() const;
    static ConfigResponse fromJson(const json& j);
};

/// GET /api/v1/orchestrator/health
struct HealthResponse {
    HealthScore health;
    std::string statusLabel;  // "healthy", "degraded", "critical"

    json toJson() const;
    static HealthResponse fromJson(const json& j);
};

/// GET /api/v1/orchestrator/levels
struct LevelsResponse {
    std::vector<LevelResult> levels;

    json toJson() const;
    static LevelsResponse fromJson(const json& j);
};

/// POST /api/v1/orchestrator/start
struct StartResponse {
    std::string status = "started";
    OrchestratorState state;

    json toJson() const;
    static StartResponse fromJson(const json& j);
};

// ---------------------------------------------------------------------------
// Error Response (consistent across all endpoints)
// ---------------------------------------------------------------------------

struct ErrorDetail {
    std::string code;       // Machine-readable: "INVALID_CONFIG", "ALREADY_RUNNING", etc.
    std::string message;    // Human-readable description
    std::optional<int> httpStatus;  // Expected HTTP status code

    json toJson() const;
    static ErrorDetail fromJson(const json& j);
};

/// Error response wrapper
struct ErrorResponse {
    ErrorDetail error;

    json toJson() const;
    static ErrorResponse fromJson(const json& j);
};

// ---------------------------------------------------------------------------
// Error Code Constants
// ---------------------------------------------------------------------------

inline const char* const ERR_INVALID_JSON         = "INVALID_JSON";
inline const char* const ERR_MISSING_FIELD        = "MISSING_FIELD";
inline const char* const ERR_INVALID_CONFIG       = "INVALID_CONFIG";
inline const char* const ERR_ALREADY_RUNNING      = "ALREADY_RUNNING";
inline const char* const ERR_NOT_RUNNING          = "NOT_RUNNING";
inline const char* const ERR_NOT_PAUSED           = "NOT_PAUSED";
inline const char* const ERR_CONFIG_LOCKED        = "CONFIG_LOCKED";
inline const char* const ERR_OBJECTIVES_NOT_FOUND = "OBJECTIVES_NOT_FOUND";
inline const char* const ERR_INTERNAL             = "INTERNAL_ERROR";
inline const char* const ERR_CANCEL_FAILED        = "CANCEL_FAILED";

// ---------------------------------------------------------------------------
// ServerConfig — server-level configuration
// ---------------------------------------------------------------------------

struct ServerConfig {
    std::string host = "0.0.0.0";
    int port = 8080;
    int threadPoolSize = 4;       // httplib worker threads
    int sseMaxEvents = 10000;     // Max SSE events retained
    int ssePollIntervalMs = 250;  // SSE polling interval
    bool enableCors = true;       // Enable CORS headers
    std::string allowedOrigins = "*";
    bool enableHttps = false;     // Requires OpenSSL
    std::string certPath;
    std::string keyPath;
    int shutdownTimeoutSec = 10;  // Max wait for orchestrator to finish

    json toJson() const;
    static ServerConfig fromJson(const json& j);
};

} // namespace gaia
