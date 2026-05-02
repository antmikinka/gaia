// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT
//
// Server and SSE event broker for the GAIA C++ Orchestrator REST API.
// Phase 5: SSE Bridge + REST API for GAIA C++ Orchestrator.

#pragma once

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <httplib.h>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include "gaia/orchestrator_api_types.h"

namespace gaia {

// ---------------------------------------------------------------------------
// Forward declaration
// ---------------------------------------------------------------------------

class OrchestratorEngine;

// ---------------------------------------------------------------------------
// SseEventBroker — thread-safe event queue for SSE streaming
// ---------------------------------------------------------------------------

class SseEventBroker {
public:
    explicit SseEventBroker(size_t maxEvents = 10000);

    /// Push a new event from the orchestrator thread.
    /// Thread-safe: can be called concurrently with getEventsSince().
    void push(const SseEvent& event);

    /// Atomically assign a sequential ID and push the event.
    /// Thread-safe: generates unique IDs even under concurrent calls.
    void pushWithId(SseEvent& event);

    /// Get all events with index > sinceIndex.
    /// Blocks until new events arrive or timeout elapses.
    /// Returns pair of (events, current_max_index).
    std::pair<std::vector<SseEvent>, size_t> getEventsSince(
        size_t sinceIndex,
        std::chrono::milliseconds timeout);

    /// Current number of events in the log.
    size_t eventCount() const;

    /// Prune old events, keeping only the most recent keepCount.
    void prune(size_t keepCount);

    /// Get the current maximum event index (for client reconnection).
    size_t maxIndex() const;

private:
    mutable std::mutex mutex_;
    std::condition_variable cv_;
    std::vector<SseEvent> events_;  // Append-only event log
    size_t maxEvents_;              // Maximum events before pruning
    std::atomic<size_t> nextId_{1}; // Atomic sequential event ID counter
};

// ---------------------------------------------------------------------------
// OrchestratorServer — httplib::Server wrapper with SSE support
// ---------------------------------------------------------------------------

class OrchestratorServer {
public:
    /// Construct with a reference to an existing OrchestratorEngine.
    explicit OrchestratorServer(OrchestratorEngine& engine,
                                const ServerConfig& config = {});
    ~OrchestratorServer();

    // Non-copyable
    OrchestratorServer(const OrchestratorServer&) = delete;
    OrchestratorServer& operator=(const OrchestratorServer&) = delete;

    /// Start the HTTP server and SSE broker.
    /// Returns true on success, false on bind failure.
    bool start(const std::string& host = "0.0.0.0", int port = 8080);

    /// Stop the HTTP server and cancel any running execution.
    /// Blocks until all threads have joined.
    void stop();

    /// Check if the server is currently running.
    bool isRunning() const;

    /// Get the SSE event broker (for external event injection).
    SseEventBroker& broker() { return broker_; }

    /// Get the underlying engine (for executor configuration).
    OrchestratorEngine& engine() { return engine_; }

    /// Get the current API orchestrator state.
    ApiOrchestratorState apiState() const;

private:
    void registerRoutes();
    void handleStart(const httplib::Request& req, httplib::Response& res);
    void handlePause(const httplib::Request& req, httplib::Response& res);
    void handleResume(const httplib::Request& req, httplib::Response& res);
    void handleStatus(const httplib::Request& req, httplib::Response& res);
    void handleCancel(const httplib::Request& req, httplib::Response& res);
    void handleGetConfig(const httplib::Request& req, httplib::Response& res);
    void handleUpdateConfig(const httplib::Request& req, httplib::Response& res);
    void handleHealth(const httplib::Request& req, httplib::Response& res);
    void handleLevels(const httplib::Request& req, httplib::Response& res);
    void handleSseEvents(const httplib::Request& req, httplib::Response& res);
    void handleOptions(const httplib::Request& req, httplib::Response& res);

    void runOrchestratorLoop();
    void emitEvent(const std::string& eventType, const json& data);
    void sendError(httplib::Response& res, const std::string& code,
                   const std::string& message, int httpStatus);
    void addCorsHeaders(httplib::Response& res);

    ServerConfig serverConfig_;
    OrchestratorEngine& engine_;
    SseEventBroker broker_;
    httplib::Server svr_;
    std::atomic<bool> serverRunning_ = false;
    std::atomic<ApiOrchestratorState> apiState_ = ApiOrchestratorState::Idle;
    std::atomic<bool> routesRegistered_ = false;
    std::thread orchestratorThread_;
    std::optional<std::thread> httpThread_;
};

} // namespace gaia
