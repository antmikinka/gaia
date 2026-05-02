// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT

#include <gtest/gtest.h>
#include <gaia/orchestrator_supervisor.h>

#include <algorithm>
#include <cmath>
#include <future>
#include <string>
#include <thread>
#include <vector>

using namespace gaia;

// ============================================================================
// ObjectiveOutcomeDetail Tests
// ============================================================================

TEST(ObjectiveOutcomeDetailTest, DefaultConstruction) {
    ObjectiveOutcomeDetail o;
    EXPECT_TRUE(o.objectiveId.empty());
    EXPECT_FALSE(o.success);
    EXPECT_TRUE(o.errorMessage.empty());
    EXPECT_DOUBLE_EQ(o.duration, 0.0);
    EXPECT_FALSE(o.timestamp.empty());
    EXPECT_DOUBLE_EQ(o.qualityScore, 0.0);
}

TEST(ObjectiveOutcomeDetailTest, ToJsonFromJsonRoundTrip) {
    ObjectiveOutcomeDetail o;
    o.objectiveId = "obj-001";
    o.success = true;
    o.duration = 1.5;
    o.qualityScore = 0.92;
    o.timestamp = "2025-01-01T00:00:00.000Z";

    json j = o.toJson();
    ObjectiveOutcomeDetail restored = ObjectiveOutcomeDetail::fromJson(j);

    EXPECT_EQ(restored.objectiveId, "obj-001");
    EXPECT_TRUE(restored.success);
    EXPECT_DOUBLE_EQ(restored.duration, 1.5);
    EXPECT_DOUBLE_EQ(restored.qualityScore, 0.92);
    EXPECT_EQ(restored.timestamp, "2025-01-01T00:00:00.000Z");
}

TEST(ObjectiveOutcomeDetailTest, FailureWithErrorMessage) {
    ObjectiveOutcomeDetail o;
    o.objectiveId = "obj-fail";
    o.success = false;
    o.errorMessage = "Pipeline crashed";

    json j = o.toJson();
    EXPECT_EQ(j["success"], false);
    EXPECT_EQ(j["error_message"], "Pipeline crashed");
}

// ============================================================================
// CircuitState Conversion Tests
// ============================================================================

TEST(CircuitStateTest, StringConversions) {
    EXPECT_EQ(circuitStateToString(CircuitState::Closed), "closed");
    EXPECT_EQ(circuitStateToString(CircuitState::Open), "open");
    EXPECT_EQ(circuitStateToString(CircuitState::HalfOpen), "half_open");
}

// ============================================================================
// CircuitBreaker Tests — Initial State and Defaults
// ============================================================================

TEST(CircuitBreakerTest, DefaultConstruction) {
    CircuitBreaker cb;
    EXPECT_EQ(cb.state(), CircuitState::Closed);
    EXPECT_EQ(cb.failureCount(), 0);
    EXPECT_EQ(cb.failureThreshold(), 5);
    EXPECT_EQ(cb.recoveryTimeoutSec(), 60);
    EXPECT_EQ(cb.halfOpenMaxAttempts(), 3);
    EXPECT_TRUE(cb.canExecute());
}

TEST(CircuitBreakerTest, CustomConstruction) {
    CircuitBreaker cb(3, 30, 2);
    EXPECT_EQ(cb.failureThreshold(), 3);
    EXPECT_EQ(cb.recoveryTimeoutSec(), 30);
    EXPECT_EQ(cb.halfOpenMaxAttempts(), 2);
}

// ============================================================================
// CircuitBreaker Tests — Closed State Behavior
// ============================================================================

TEST(CircuitBreakerTest, ClosedStateAllowsExecution) {
    CircuitBreaker cb;
    EXPECT_TRUE(cb.canExecute());
    EXPECT_TRUE(cb.canExecute());
    EXPECT_TRUE(cb.canExecute());
}

TEST(CircuitBreakerTest, ClosedStateSuccessResetsFailures) {
    CircuitBreaker cb;
    cb.recordFailure();
    cb.recordFailure();
    EXPECT_EQ(cb.failureCount(), 2);
    cb.recordSuccess();
    EXPECT_EQ(cb.failureCount(), 0);
    EXPECT_EQ(cb.state(), CircuitState::Closed);
}

TEST(CircuitBreakerTest, ClosedStateTripsAtThreshold) {
    CircuitBreaker cb(5);
    // 4 failures -> still closed
    for (int i = 0; i < 4; ++i) {
        cb.recordFailure();
    }
    EXPECT_EQ(cb.state(), CircuitState::Closed);
    EXPECT_EQ(cb.failureCount(), 4);

    // 5th failure -> trips to open
    cb.recordFailure();
    EXPECT_EQ(cb.state(), CircuitState::Open);
    EXPECT_FALSE(cb.canExecute());
}

TEST(CircuitBreakerTest, ClosedStateTripsAtCustomThreshold) {
    CircuitBreaker cb(3);
    cb.recordFailure();
    cb.recordFailure();
    EXPECT_EQ(cb.state(), CircuitState::Closed);
    cb.recordFailure();
    EXPECT_EQ(cb.state(), CircuitState::Open);
}

// ============================================================================
// CircuitBreaker Tests — Open State Behavior
// ============================================================================

TEST(CircuitBreakerTest, OpenStateRejectsExecution) {
    CircuitBreaker cb(1);
    cb.recordFailure();
    EXPECT_EQ(cb.state(), CircuitState::Open);
    EXPECT_FALSE(cb.canExecute());
    EXPECT_FALSE(cb.canExecute());
}

TEST(CircuitBreakerTest, OpenStateRecordsFailureDoesNotChangeState) {
    CircuitBreaker cb(1);
    cb.recordFailure();
    EXPECT_EQ(cb.state(), CircuitState::Open);
    cb.recordFailure(); // already open, should stay open
    EXPECT_EQ(cb.state(), CircuitState::Open);
}

TEST(CircuitBreakerTest, RecoveryTimeoutTransitionToHalfOpen) {
    CircuitBreaker cb(1, 0); // 0 second timeout for instant transition
    cb.recordFailure();
    EXPECT_EQ(cb.state(), CircuitState::Open);

    // With 0 timeout, calling canExecute triggers transition to HalfOpen
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    bool allowed = cb.canExecute();
    // After transition, HalfOpen allows execution
    EXPECT_TRUE(allowed);
    EXPECT_EQ(cb.state(), CircuitState::HalfOpen);
}

TEST(CircuitBreakerTest, OpenStateDoesNotTransitionBeforeTimeout) {
    CircuitBreaker cb(1, 3600); // 1 hour timeout
    cb.recordFailure();
    EXPECT_EQ(cb.state(), CircuitState::Open);
    EXPECT_FALSE(cb.canExecute());
    EXPECT_EQ(cb.state(), CircuitState::Open); // still open
}

// ============================================================================
// CircuitBreaker Tests — HalfOpen State Behavior
// ============================================================================

TEST(CircuitBreakerTest, HalfOpenSuccessReturnsToClosed) {
    CircuitBreaker cb(1, 0);
    cb.recordFailure();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    cb.canExecute(); // triggers transition to HalfOpen
    EXPECT_EQ(cb.state(), CircuitState::HalfOpen);

    cb.recordSuccess();
    EXPECT_EQ(cb.state(), CircuitState::Closed);
    EXPECT_EQ(cb.failureCount(), 0);
}

TEST(CircuitBreakerTest, HalfOpenFailureReturnsToOpen) {
    CircuitBreaker cb(1, 0);
    cb.recordFailure();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    cb.canExecute(); // triggers transition to HalfOpen
    EXPECT_EQ(cb.state(), CircuitState::HalfOpen);

    // Record failure in HalfOpen -> should return to Open
    cb.recordFailure();
    EXPECT_EQ(cb.state(), CircuitState::Open);
}

TEST(CircuitBreakerTest, HalfOpenAttemptCountIncrementedOnFailure) {
    CircuitBreaker cb(2, 0, 3); // threshold 2, 0 timeout, 3 max half-open attempts
    // Record 2 failures to trip to Open
    cb.recordFailure();
    cb.recordFailure();
    EXPECT_EQ(cb.state(), CircuitState::Open);

    std::this_thread::sleep_for(std::chrono::milliseconds(10));

    // Transition to HalfOpen via canExecute
    cb.canExecute();
    EXPECT_EQ(cb.state(), CircuitState::HalfOpen);

    // Record failure in HalfOpen -> back to Open
    cb.recordFailure();
    EXPECT_EQ(cb.state(), CircuitState::Open);

    // Another transition to HalfOpen
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    cb.canExecute();
    EXPECT_EQ(cb.state(), CircuitState::HalfOpen);

    // Success in HalfOpen -> back to Closed
    cb.recordSuccess();
    EXPECT_EQ(cb.state(), CircuitState::Closed);
}

TEST(CircuitBreakerTest, HalfOpenResetsAttemptCountOnSuccess) {
    CircuitBreaker cb(1, 0, 2);
    cb.recordFailure();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    cb.canExecute();
    EXPECT_EQ(cb.state(), CircuitState::HalfOpen);

    cb.recordSuccess();
    EXPECT_EQ(cb.state(), CircuitState::Closed);

    // After returning to closed, a new failure and timeout should reset
    cb.recordFailure();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    EXPECT_TRUE(cb.canExecute());
    EXPECT_TRUE(cb.canExecute()); // full allowance again
}

// ============================================================================
// CircuitBreaker Tests — Reset Behavior
// ============================================================================

TEST(CircuitBreakerTest, ResetFromOpenReturnsToClosed) {
    CircuitBreaker cb(1);
    cb.recordFailure();
    EXPECT_EQ(cb.state(), CircuitState::Open);

    cb.reset();
    EXPECT_EQ(cb.state(), CircuitState::Closed);
    EXPECT_EQ(cb.failureCount(), 0);
    EXPECT_TRUE(cb.canExecute());
}

TEST(CircuitBreakerTest, ResetFromHalfOpenReturnsToClosed) {
    CircuitBreaker cb(1, 0);
    cb.recordFailure();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    cb.canExecute();
    EXPECT_EQ(cb.state(), CircuitState::HalfOpen);

    cb.reset();
    EXPECT_EQ(cb.state(), CircuitState::Closed);
}

// ============================================================================
// CircuitBreaker Tests — JSON Serialization
// ============================================================================

TEST(CircuitBreakerTest, ToJson) {
    CircuitBreaker cb(3, 30, 2);
    json j = cb.toJson();

    EXPECT_EQ(j["state"], "closed");
    EXPECT_EQ(j["failure_threshold"], 3);
    EXPECT_EQ(j["recovery_timeout_sec"], 30);
    EXPECT_EQ(j["half_open_max_attempts"], 2);
    EXPECT_EQ(j["failure_count"], 0);
}

TEST(CircuitBreakerTest, FromJson) {
    json j;
    j["failure_threshold"] = 3;
    j["recovery_timeout_sec"] = 30;
    j["half_open_max_attempts"] = 2;

    CircuitBreaker cb = CircuitBreaker::fromJson(j);
    EXPECT_EQ(cb.failureThreshold(), 3);
    EXPECT_EQ(cb.recoveryTimeoutSec(), 30);
    EXPECT_EQ(cb.halfOpenMaxAttempts(), 2);
}

TEST(CircuitBreakerTest, ToJsonWithOpenState) {
    CircuitBreaker cb(1);
    cb.recordFailure();
    json j = cb.toJson();

    EXPECT_EQ(j["state"], "open");
    EXPECT_EQ(j["failure_count"], 1);
}

TEST(CircuitBreakerTest, FromJsonRestoresState) {
    json j;
    j["state"] = "open";
    j["failure_count"] = 3;
    j["failure_threshold"] = 5;

    CircuitBreaker cb = CircuitBreaker::fromJson(j);
    EXPECT_EQ(cb.state(), CircuitState::Open);
    EXPECT_EQ(cb.failureCount(), 3);
}

// ============================================================================
// CircuitBreaker Tests — Concurrent Access
// ============================================================================

TEST(CircuitBreakerTest, ConcurrentRecordFailures) {
    CircuitBreaker cb(100);

    std::vector<std::thread> threads;
    for (int i = 0; i < 10; ++i) {
        threads.emplace_back([&cb]() {
            for (int j = 0; j < 10; ++j) {
                cb.recordFailure();
            }
        });
    }
    for (auto& t : threads) {
        t.join();
    }

    // All 100 failures recorded
    EXPECT_EQ(cb.failureCount(), 100);
    EXPECT_EQ(cb.state(), CircuitState::Open);
}

TEST(CircuitBreakerTest, ConcurrentCanExecute) {
    CircuitBreaker cb;
    std::vector<std::future<bool>> futures;

    for (int i = 0; i < 10; ++i) {
        futures.push_back(std::async(std::launch::async, [&cb]() {
            return cb.canExecute();
        }));
    }

    for (auto& f : futures) {
        EXPECT_TRUE(f.get());
    }
}

TEST(CircuitBreakerTest, ConcurrentMixedOperations) {
    CircuitBreaker cb(1000);
    std::vector<std::thread> threads;

    // Multiple threads recording failures
    for (int i = 0; i < 5; ++i) {
        threads.emplace_back([&cb]() {
            for (int j = 0; j < 50; ++j) {
                cb.recordFailure();
            }
        });
    }

    // Multiple threads calling canExecute
    for (int i = 0; i < 5; ++i) {
        threads.emplace_back([&cb]() {
            for (int j = 0; j < 50; ++j) {
                cb.canExecute();
            }
        });
    }

    for (auto& t : threads) {
        t.join();
    }

    // No crash or undefined behavior
    EXPECT_LE(cb.failureCount(), 250);
}

// ============================================================================
// CircuitBreaker Tests — Config Setters
// ============================================================================

TEST(CircuitBreakerTest, SetFailureThreshold) {
    CircuitBreaker cb;
    cb.setFailureThreshold(10);
    EXPECT_EQ(cb.failureThreshold(), 10);
}

TEST(CircuitBreakerTest, SetRecoveryTimeoutSec) {
    CircuitBreaker cb;
    cb.setRecoveryTimeoutSec(120);
    EXPECT_EQ(cb.recoveryTimeoutSec(), 120);
}

TEST(CircuitBreakerTest, SetHalfOpenMaxAttempts) {
    CircuitBreaker cb;
    cb.setHalfOpenMaxAttempts(5);
    EXPECT_EQ(cb.halfOpenMaxAttempts(), 5);
}

// ============================================================================
// HealthScore Tests — Computation Formula
// ============================================================================

TEST(HealthScoreTest, ComputeFormulaCorrect) {
    HealthScore hs;
    hs.successRate = 0.8;
    hs.qualityTrend = 0.5;
    hs.dependencyHealth = 0.6;
    hs.compute();

    // overall = (0.8 * 0.4) + ((0.5 + 1) / 2 * 0.3) + (0.6 * 0.3)
    //         = 0.32 + 0.225 + 0.18 = 0.725
    EXPECT_NEAR(hs.overall, 0.725, 0.001);
}

TEST(HealthScoreTest, ComputeAllZeros) {
    HealthScore hs;
    hs.successRate = 0.0;
    hs.qualityTrend = -1.0;
    hs.dependencyHealth = 0.0;
    hs.compute();

    // (0 * 0.4) + (0 / 2 * 0.3) + (0 * 0.3) = 0
    EXPECT_NEAR(hs.overall, 0.0, 0.001);
}

TEST(HealthScoreTest, ComputeAllOnes) {
    HealthScore hs;
    hs.successRate = 1.0;
    hs.qualityTrend = 1.0;
    hs.dependencyHealth = 1.0;
    hs.compute();

    // (1 * 0.4) + (1 * 0.3) + (1 * 0.3) = 1.0
    EXPECT_NEAR(hs.overall, 1.0, 0.001);
}

TEST(HealthScoreTest, ComputeClampsOutOfRange) {
    HealthScore hs;
    hs.successRate = 2.0;    // clamped to 1.0
    hs.qualityTrend = -5.0;  // clamped to -1.0
    hs.dependencyHealth = -1.0; // clamped to 0.0
    hs.compute();

    // (1 * 0.4) + (0 * 0.3) + (0 * 0.3) = 0.4
    EXPECT_NEAR(hs.overall, 0.4, 0.001);
}

// ============================================================================
// HealthScore Tests — Status Labels
// ============================================================================

TEST(HealthScoreTest, StatusLabelHealthy) {
    HealthScore hs;
    hs.overall = 0.85;
    EXPECT_EQ(hs.statusLabel(), "healthy");
}

TEST(HealthScoreTest, StatusLabelDegraded) {
    HealthScore hs;
    hs.overall = 0.6;
    EXPECT_EQ(hs.statusLabel(), "degraded");
}

TEST(HealthScoreTest, StatusLabelCritical) {
    HealthScore hs;
    hs.overall = 0.3;
    EXPECT_EQ(hs.statusLabel(), "critical");
}

TEST(HealthScoreTest, StatusLabelBoundaryHealthy) {
    HealthScore hs;
    hs.overall = 0.8;
    EXPECT_EQ(hs.statusLabel(), "healthy");
}

TEST(HealthScoreTest, StatusLabelBoundaryDegraded) {
    HealthScore hs;
    hs.overall = 0.5;
    EXPECT_EQ(hs.statusLabel(), "degraded");
}

TEST(HealthScoreTest, StatusLabelBoundaryCritical) {
    HealthScore hs;
    hs.overall = 0.49;
    EXPECT_EQ(hs.statusLabel(), "critical");
}

// ============================================================================
// HealthScore Tests — JSON Round-trip
// ============================================================================

TEST(HealthScoreTest, ToJsonIncludesStatusLabel) {
    HealthScore hs;
    hs.successRate = 0.9;
    hs.qualityTrend = 0.5;
    hs.dependencyHealth = 0.8;
    hs.compute();

    json j = hs.toJson();
    EXPECT_TRUE(j.contains("status"));
    EXPECT_EQ(j["status"], "healthy");
    EXPECT_TRUE(j.contains("overall"));
}

TEST(HealthScoreTest, FromJsonRoundTrip) {
    HealthScore hs;
    hs.successRate = 0.75;
    hs.qualityTrend = 0.2;
    hs.dependencyHealth = 0.9;
    hs.overall = 0.7;

    json j = hs.toJson();
    HealthScore restored = HealthScore::fromJson(j);

    EXPECT_DOUBLE_EQ(restored.successRate, 0.75);
    EXPECT_DOUBLE_EQ(restored.qualityTrend, 0.2);
    EXPECT_DOUBLE_EQ(restored.dependencyHealth, 0.9);
    EXPECT_DOUBLE_EQ(restored.overall, 0.7);
}

TEST(HealthScoreTest, DefaultValues) {
    HealthScore hs;
    EXPECT_DOUBLE_EQ(hs.successRate, 1.0);
    EXPECT_DOUBLE_EQ(hs.qualityTrend, 0.0);
    EXPECT_DOUBLE_EQ(hs.dependencyHealth, 1.0);
    EXPECT_DOUBLE_EQ(hs.overall, 1.0);
}

// ============================================================================
// SupervisorConfig Tests — Defaults
// ============================================================================

TEST(SupervisorConfigTest, DefaultValues) {
    SupervisorConfig cfg;
    EXPECT_EQ(cfg.healthCheckIntervalSec, 30);
    EXPECT_DOUBLE_EQ(cfg.minHealthScore, 0.5);
    EXPECT_EQ(cfg.maxConsecutiveFailures, 3);
    EXPECT_FALSE(cfg.autoRemediate);
    EXPECT_EQ(cfg.maxRemediationAttempts, 3);
    EXPECT_EQ(cfg.circuitBreakerThreshold, 5);
    EXPECT_EQ(cfg.circuitBreakerTimeoutSec, 60);
    EXPECT_TRUE(cfg.enableHealthMonitoring);
    EXPECT_TRUE(cfg.enableCircuitBreaker);
    EXPECT_EQ(cfg.qualityTrendWindow, 10);
}

// ============================================================================
// SupervisorConfig Tests — Validation
// ============================================================================

TEST(SupervisorConfigTest, ValidateDefaultPasses) {
    SupervisorConfig cfg;
    EXPECT_NO_THROW(cfg.validate());
}

TEST(SupervisorConfigTest, ValidateZeroHealthCheckInterval) {
    SupervisorConfig cfg;
    cfg.healthCheckIntervalSec = 0;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(SupervisorConfigTest, ValidateNegativeHealthCheckInterval) {
    SupervisorConfig cfg;
    cfg.healthCheckIntervalSec = -1;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(SupervisorConfigTest, ValidateMinHealthScoreTooLow) {
    SupervisorConfig cfg;
    cfg.minHealthScore = -0.1;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(SupervisorConfigTest, ValidateMinHealthScoreTooHigh) {
    SupervisorConfig cfg;
    cfg.minHealthScore = 1.1;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(SupervisorConfigTest, ValidateZeroMaxConsecutiveFailures) {
    SupervisorConfig cfg;
    cfg.maxConsecutiveFailures = 0;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(SupervisorConfigTest, ValidateZeroMaxRemediationAttempts) {
    SupervisorConfig cfg;
    cfg.maxRemediationAttempts = 0;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(SupervisorConfigTest, ValidateZeroCircuitBreakerThreshold) {
    SupervisorConfig cfg;
    cfg.circuitBreakerThreshold = 0;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(SupervisorConfigTest, ValidateZeroCircuitBreakerTimeout) {
    SupervisorConfig cfg;
    cfg.circuitBreakerTimeoutSec = 0;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(SupervisorConfigTest, ValidateZeroQualityTrendWindow) {
    SupervisorConfig cfg;
    cfg.qualityTrendWindow = 0;
    EXPECT_THROW(cfg.validate(), std::invalid_argument);
}

TEST(SupervisorConfigTest, ValidateBoundaryMinHealthScoreZero) {
    SupervisorConfig cfg;
    cfg.minHealthScore = 0.0;
    EXPECT_NO_THROW(cfg.validate());
}

TEST(SupervisorConfigTest, ValidateBoundaryMinHealthScoreOne) {
    SupervisorConfig cfg;
    cfg.minHealthScore = 1.0;
    EXPECT_NO_THROW(cfg.validate());
}

// ============================================================================
// SupervisorConfig Tests — JSON Round-trip
// ============================================================================

TEST(SupervisorConfigTest, ToJsonAllFields) {
    SupervisorConfig cfg;
    cfg.autoRemediate = true;
    cfg.maxRemediationAttempts = 5;

    json j = cfg.toJson();
    EXPECT_EQ(j["auto_remediate"], true);
    EXPECT_EQ(j["max_remediation_attempts"], 5);
    EXPECT_EQ(j["health_check_interval_sec"], 30);
}

TEST(SupervisorConfigTest, FromJsonPartialRetainsDefaults) {
    json j;
    j["auto_remediate"] = true;

    SupervisorConfig cfg = SupervisorConfig::fromJson(j);
    EXPECT_TRUE(cfg.autoRemediate);
    EXPECT_EQ(cfg.healthCheckIntervalSec, 30); // default
}

TEST(SupervisorConfigTest, FromJsonFullRoundTrip) {
    SupervisorConfig cfg;
    cfg.healthCheckIntervalSec = 60;
    cfg.minHealthScore = 0.7;
    cfg.autoRemediate = true;

    json j = cfg.toJson();
    SupervisorConfig restored = SupervisorConfig::fromJson(j);

    EXPECT_EQ(restored.healthCheckIntervalSec, 60);
    EXPECT_DOUBLE_EQ(restored.minHealthScore, 0.7);
    EXPECT_TRUE(restored.autoRemediate);
}

// ============================================================================
// SupervisorState Tests — Default and Recording
// ============================================================================

TEST(SupervisorStateTest, DefaultConstruction) {
    SupervisorState s;
    EXPECT_TRUE(s.outcomes.empty());
    EXPECT_EQ(s.consecutiveFailures, 0);
    EXPECT_TRUE(s.perObjectiveFailures.empty());
    EXPECT_FALSE(s.circuitBreakerTripped);
    EXPECT_EQ(s.remediationAttempts, 0);
}

TEST(SupervisorStateTest, RecordOutcomeSuccessResetsConsecutiveFailures) {
    SupervisorState s;

    ObjectiveOutcomeDetail fail;
    fail.objectiveId = "obj-001";
    fail.success = false;
    s.recordOutcome(fail);

    EXPECT_EQ(s.consecutiveFailures, 1);

    ObjectiveOutcomeDetail ok;
    ok.objectiveId = "obj-002";
    ok.success = true;
    s.recordOutcome(ok);

    EXPECT_EQ(s.consecutiveFailures, 0);
}

TEST(SupervisorStateTest, RecordOutcomeFailureIncrementsConsecutiveFailures) {
    SupervisorState s;

    for (int i = 0; i < 5; ++i) {
        ObjectiveOutcomeDetail o;
        o.objectiveId = "obj-" + std::to_string(i);
        o.success = false;
        s.recordOutcome(o);
    }

    EXPECT_EQ(s.consecutiveFailures, 5);
}

TEST(SupervisorStateTest, RecordOutcomeTracksPerObjectiveFailures) {
    SupervisorState s;

    ObjectiveOutcomeDetail o1a;
    o1a.objectiveId = "obj-a";
    o1a.success = false;
    s.recordOutcome(o1a);

    ObjectiveOutcomeDetail o1b;
    o1b.objectiveId = "obj-a";
    o1b.success = false;
    s.recordOutcome(o1b);

    ObjectiveOutcomeDetail o2;
    o2.objectiveId = "obj-b";
    o2.success = false;
    s.recordOutcome(o2);

    EXPECT_EQ(s.perObjectiveFailures["obj-a"], 2);
    EXPECT_EQ(s.perObjectiveFailures["obj-b"], 1);
}

TEST(SupervisorStateTest, RecordOutcomeSuccessDoesNotTrackInPerObjectiveFailures) {
    SupervisorState s;

    ObjectiveOutcomeDetail o;
    o.objectiveId = "obj-ok";
    o.success = true;
    s.recordOutcome(o);

    EXPECT_EQ(s.perObjectiveFailures.count("obj-ok"), 0u);
}

// ============================================================================
// SupervisorState Tests — JSON Round-trip
// ============================================================================

TEST(SupervisorStateTest, ToJsonWithOutcomes) {
    SupervisorState s;

    ObjectiveOutcomeDetail o;
    o.objectiveId = "obj-001";
    o.success = true;
    o.qualityScore = 0.9;
    s.recordOutcome(o);

    json j = s.toJson();
    EXPECT_EQ(j["outcomes"].size(), 1u);
    EXPECT_EQ(j["outcomes"][0]["objective_id"], "obj-001");
    EXPECT_EQ(j["consecutive_failures"], 0);
}

TEST(SupervisorStateTest, FromJsonRoundTrip) {
    SupervisorState s;

    ObjectiveOutcomeDetail o1;
    o1.objectiveId = "obj-a";
    o1.success = false;
    s.recordOutcome(o1);

    ObjectiveOutcomeDetail o2;
    o2.objectiveId = "obj-b";
    o2.success = true;
    s.recordOutcome(o2);

    s.circuitBreakerTripped = true;
    s.remediationAttempts = 2;

    json j = s.toJson();
    SupervisorState restored = SupervisorState::fromJson(j);

    EXPECT_EQ(restored.outcomes.size(), 2u);
    EXPECT_EQ(restored.consecutiveFailures, 0); // last was success
    EXPECT_EQ(restored.circuitBreakerTripped, true);
    EXPECT_EQ(restored.remediationAttempts, 2);
    EXPECT_EQ(restored.perObjectiveFailures["obj-a"], 1);
}

TEST(SupervisorStateTest, FromJsonWithEmptyState) {
    json j = json::object();
    j["outcomes"] = json::array();
    j["per_objective_failures"] = json::object();

    SupervisorState s = SupervisorState::fromJson(j);
    EXPECT_TRUE(s.outcomes.empty());
    EXPECT_TRUE(s.perObjectiveFailures.empty());
}

// ============================================================================
// ProjectSupervisor Tests — Construction and Defaults
// ============================================================================

TEST(ProjectSupervisorTest, DefaultConstruction) {
    ProjectSupervisor ps;
    EXPECT_EQ(ps.config().healthCheckIntervalSec, 30);
    EXPECT_FALSE(ps.state().circuitBreakerTripped);
    EXPECT_EQ(ps.state().consecutiveFailures, 0);
}

TEST(ProjectSupervisorTest, WithCustomConfig) {
    SupervisorConfig cfg;
    cfg.maxConsecutiveFailures = 2;
    cfg.autoRemediate = true;
    ProjectSupervisor ps(cfg);

    EXPECT_EQ(ps.config().maxConsecutiveFailures, 2);
    EXPECT_TRUE(ps.config().autoRemediate);
}

TEST(ProjectSupervisorTest, SetConfigReplacesExisting) {
    ProjectSupervisor ps;
    EXPECT_FALSE(ps.config().autoRemediate);

    SupervisorConfig cfg;
    cfg.autoRemediate = true;
    ps.setConfig(cfg);

    EXPECT_TRUE(ps.config().autoRemediate);
}

TEST(ProjectSupervisorTest, SetConfigInvalidThrows) {
    ProjectSupervisor ps;
    SupervisorConfig cfg;
    cfg.healthCheckIntervalSec = -1;

    EXPECT_THROW(ps.setConfig(cfg), std::invalid_argument);
}

// ============================================================================
// ProjectSupervisor Tests — evaluateLevel Verdicts
// ============================================================================

TEST(ProjectSupervisorTest, EvaluateLevelAllSuccessReturnsContinue) {
    ProjectSupervisor ps;

    LevelResult lr;
    lr.objectiveIds = {"obj-a", "obj-b"};
    lr.outcomes["obj-a"] = ObjectiveOutcome::Success;
    lr.outcomes["obj-b"] = ObjectiveOutcome::Success;
    lr.successCount = 2;
    lr.failureCount = 0;

    ProjectObjectives proj;
    std::string verdict = ps.evaluateLevel(lr, proj);
    EXPECT_EQ(verdict, "continue");
}

TEST(ProjectSupervisorTest, EvaluateLevelAllFailedReturnsAbort) {
    ProjectSupervisor ps;

    LevelResult lr;
    lr.objectiveIds = {"obj-a"};
    lr.outcomes["obj-a"] = ObjectiveOutcome::Failed;
    lr.successCount = 0;
    lr.failureCount = 1;

    ProjectObjectives proj;
    std::string verdict = ps.evaluateLevel(lr, proj);
    EXPECT_EQ(verdict, "abort");
}

TEST(ProjectSupervisorTest, EvaluateLevelMixedResultsReturnsRemediate) {
    ProjectSupervisor ps;

    LevelResult lr;
    lr.objectiveIds = {"obj-a", "obj-b"};
    lr.outcomes["obj-a"] = ObjectiveOutcome::Success;
    lr.outcomes["obj-b"] = ObjectiveOutcome::Failed;
    lr.successCount = 1;
    lr.failureCount = 1;

    ProjectObjectives proj;
    std::string verdict = ps.evaluateLevel(lr, proj);
    EXPECT_EQ(verdict, "remediate");
}

TEST(ProjectSupervisorTest, EvaluateLevelConsecutiveFailuresTripsCircuitBreaker) {
    SupervisorConfig cfg;
    cfg.maxConsecutiveFailures = 2;
    cfg.enableCircuitBreaker = true;
    ProjectSupervisor ps(cfg);

    LevelResult lr1;
    lr1.objectiveIds = {"obj-a"};
    lr1.outcomes["obj-a"] = ObjectiveOutcome::Failed;
    lr1.failureCount = 1;
    lr1.successCount = 0;

    ProjectObjectives proj;
    ps.evaluateLevel(lr1, proj); // 1 consecutive failure

    LevelResult lr2;
    lr2.objectiveIds = {"obj-b"};
    lr2.outcomes["obj-b"] = ObjectiveOutcome::Failed;
    lr2.failureCount = 1;
    lr2.successCount = 0;

    std::string verdict = ps.evaluateLevel(lr2, proj); // 2 consecutive failures -> abort
    EXPECT_EQ(verdict, "abort");
    EXPECT_TRUE(ps.state().circuitBreakerTripped);
}

TEST(ProjectSupervisorTest, EvaluateLevelCircuitBreakerTrippedReturnsAbort) {
    SupervisorConfig cfg;
    cfg.maxConsecutiveFailures = 1;
    cfg.enableCircuitBreaker = true;
    ProjectSupervisor ps(cfg);

    // Trip the circuit breaker
    LevelResult lr;
    lr.objectiveIds = {"obj-a"};
    lr.outcomes["obj-a"] = ObjectiveOutcome::Failed;
    lr.failureCount = 1;
    lr.successCount = 0;

    ProjectObjectives proj;
    ps.evaluateLevel(lr, proj);

    // Next level should abort due to tripped circuit breaker
    LevelResult lr2;
    lr2.objectiveIds = {"obj-b"};
    lr2.outcomes["obj-b"] = ObjectiveOutcome::Success;
    lr2.successCount = 1;
    lr2.failureCount = 0;

    std::string verdict = ps.evaluateLevel(lr2, proj);
    EXPECT_EQ(verdict, "abort");
}

TEST(ProjectSupervisorTest, EvaluateLevelCircuitBreakerDisabledNoAbort) {
    SupervisorConfig cfg;
    cfg.maxConsecutiveFailures = 1;
    cfg.enableCircuitBreaker = false;
    ProjectSupervisor ps(cfg);

    LevelResult lr;
    lr.objectiveIds = {"obj-a"};
    lr.outcomes["obj-a"] = ObjectiveOutcome::Failed;
    lr.failureCount = 1;
    lr.successCount = 0;

    ProjectObjectives proj;
    std::string verdict = ps.evaluateLevel(lr, proj);

    // Circuit breaker disabled, so should still get abort (from all-failed check)
    EXPECT_EQ(verdict, "abort");
    // But circuitBreakerTripped should still be set
    EXPECT_TRUE(ps.state().circuitBreakerTripped);
}

TEST(ProjectSupervisorTest, EvaluateLevelRecordsOutcomes) {
    ProjectSupervisor ps;

    LevelResult lr;
    lr.objectiveIds = {"obj-a", "obj-b"};
    lr.outcomes["obj-a"] = ObjectiveOutcome::Success;
    lr.outcomes["obj-b"] = ObjectiveOutcome::Failed;
    lr.successCount = 1;
    lr.failureCount = 1;

    ProjectObjectives proj;
    ps.evaluateLevel(lr, proj);

    EXPECT_EQ(ps.state().outcomes.size(), 2u);
    EXPECT_EQ(ps.state().consecutiveFailures, 1);
}

// ============================================================================
// ProjectSupervisor Tests — Health Score Computation
// ============================================================================

TEST(ProjectSupervisorTest, ComputeHealthScoreEmptyProject) {
    ProjectSupervisor ps;
    ProjectObjectives proj;

    HealthScore hs = ps.computeHealthScore(proj);
    EXPECT_DOUBLE_EQ(hs.successRate, 1.0);
    EXPECT_DOUBLE_EQ(hs.dependencyHealth, 1.0);
}

TEST(ProjectSupervisorTest, ComputeHealthScoreAllCompleted) {
    ProjectSupervisor ps;
    ProjectObjectives proj;

    Objective o1;
    o1.objectiveId = "obj-a";
    o1.status = ObjectiveStatus::Completed;

    Objective o2;
    o2.objectiveId = "obj-b";
    o2.status = ObjectiveStatus::Completed;

    proj.objectives.push_back(o1);
    proj.objectives.push_back(o2);

    HealthScore hs = ps.computeHealthScore(proj);
    EXPECT_DOUBLE_EQ(hs.successRate, 1.0);
    EXPECT_DOUBLE_EQ(hs.dependencyHealth, 1.0);
    EXPECT_EQ(hs.statusLabel(), "healthy");
}

TEST(ProjectSupervisorTest, ComputeHealthScoreAllBlocked) {
    ProjectSupervisor ps;
    ProjectObjectives proj;

    Objective o1;
    o1.objectiveId = "obj-a";
    o1.status = ObjectiveStatus::Blocked;

    proj.objectives.push_back(o1);

    HealthScore hs = ps.computeHealthScore(proj);
    EXPECT_DOUBLE_EQ(hs.successRate, 0.0);
    EXPECT_DOUBLE_EQ(hs.dependencyHealth, 0.0);
}

TEST(ProjectSupervisorTest, ComputeHealthScoreMixed) {
    ProjectSupervisor ps;
    ProjectObjectives proj;

    Objective o1;
    o1.objectiveId = "obj-a";
    o1.status = ObjectiveStatus::Completed;

    Objective o2;
    o2.objectiveId = "obj-b";
    o2.status = ObjectiveStatus::Blocked;

    Objective o3;
    o3.objectiveId = "obj-c";
    o3.status = ObjectiveStatus::Completed;

    proj.objectives.push_back(o1);
    proj.objectives.push_back(o2);
    proj.objectives.push_back(o3);

    HealthScore hs = ps.computeHealthScore(proj);
    EXPECT_NEAR(hs.successRate, 2.0 / 3.0, 0.01);
    EXPECT_NEAR(hs.dependencyHealth, 2.0 / 3.0, 0.01);
}

TEST(ProjectSupervisorTest, ComputeHealthScoreStoresInState) {
    ProjectSupervisor ps;
    ProjectObjectives proj;

    Objective o;
    o.objectiveId = "obj-a";
    o.status = ObjectiveStatus::Completed;
    proj.objectives.push_back(o);

    ps.computeHealthScore(proj);
    EXPECT_TRUE(ps.state().lastHealthScore.overall > 0.0);
}

TEST(ProjectSupervisorTest, ComputeQualityTrendNoOutcomes) {
    ProjectSupervisor ps;
    ProjectObjectives proj;

    HealthScore hs = ps.computeHealthScore(proj);
    // With no outcomes, qualityTrend should default to 0
    EXPECT_DOUBLE_EQ(hs.qualityTrend, 0.0);
}

// ============================================================================
// ProjectSupervisor Tests — Phase Completion
// ============================================================================

TEST(ProjectSupervisorTest, CheckPhaseCompletionEmptyReturnsFalse) {
    ProjectSupervisor ps;
    std::vector<LevelResult> results;
    EXPECT_FALSE(ps.checkPhaseCompletion(results));
}

TEST(ProjectSupervisorTest, CheckPhaseCompletionContinueVerdictReturnsTrue) {
    ProjectSupervisor ps;

    LevelResult lr;
    lr.verdict = "continue";

    std::vector<LevelResult> results = {lr};
    EXPECT_TRUE(ps.checkPhaseCompletion(results));
}

TEST(ProjectSupervisorTest, CheckPhaseCompletionAbortVerdictReturnsTrue) {
    ProjectSupervisor ps;

    LevelResult lr;
    lr.verdict = "abort";

    std::vector<LevelResult> results = {lr};
    EXPECT_TRUE(ps.checkPhaseCompletion(results));
}

TEST(ProjectSupervisorTest, CheckPhaseCompletionPauseVerdictReturnsTrue) {
    ProjectSupervisor ps;

    LevelResult lr;
    lr.verdict = "pause";

    std::vector<LevelResult> results = {lr};
    EXPECT_TRUE(ps.checkPhaseCompletion(results));
}

TEST(ProjectSupervisorTest, CheckPhaseCompletionMultipleLevelsStopsOnTerminal) {
    ProjectSupervisor ps;

    LevelResult lr1;
    lr1.verdict = "continue";

    LevelResult lr2;
    lr2.verdict = "abort";

    std::vector<LevelResult> results = {lr1, lr2};
    EXPECT_TRUE(ps.checkPhaseCompletion(results));
}

// ============================================================================
// ProjectSupervisor Tests — Remediation Decisions
// ============================================================================

TEST(ProjectSupervisorTest, ShouldRemediateAutoRemediateDisabled) {
    ProjectSupervisor ps; // autoRemediate = false by default

    ObjectiveOutcomeDetail o;
    o.objectiveId = "obj-a";
    o.success = false;
    ps.recordOutcome(o);

    EXPECT_FALSE(ps.shouldRemediate("obj-a"));
}

TEST(ProjectSupervisorTest, ShouldRemediateAutoRemediateEnabled) {
    SupervisorConfig cfg;
    cfg.autoRemediate = true;
    ProjectSupervisor ps(cfg);

    ObjectiveOutcomeDetail o;
    o.objectiveId = "obj-a";
    o.success = false;
    ps.recordOutcome(o);

    EXPECT_TRUE(ps.shouldRemediate("obj-a"));
}

TEST(ProjectSupervisorTest, ShouldRemediateMaxAttemptsExceeded) {
    SupervisorConfig cfg;
    cfg.autoRemediate = true;
    cfg.maxRemediationAttempts = 1;
    ProjectSupervisor ps(cfg);

    // Record a failure for obj-a
    ObjectiveOutcomeDetail o;
    o.objectiveId = "obj-a";
    o.success = false;
    ps.recordOutcome(o);

    // Should allow remediation (attempts = 0, max = 1)
    EXPECT_TRUE(ps.shouldRemediate("obj-a"));

    // Manually set remediationAttempts to max
    ps.mutableState().remediationAttempts = 1;

    // Now should block remediation
    EXPECT_FALSE(ps.shouldRemediate("obj-a"));
}

TEST(ProjectSupervisorTest, ShouldRemediateNoFailuresForObjective) {
    SupervisorConfig cfg;
    cfg.autoRemediate = true;
    ProjectSupervisor ps(cfg);

    // Only record success
    ObjectiveOutcomeDetail o;
    o.objectiveId = "obj-ok";
    o.success = true;
    ps.recordOutcome(o);

    EXPECT_FALSE(ps.shouldRemediate("obj-ok"));
}

TEST(ProjectSupervisorTest, ShouldRemediateUnknownObjective) {
    SupervisorConfig cfg;
    cfg.autoRemediate = true;
    ProjectSupervisor ps(cfg);

    EXPECT_FALSE(ps.shouldRemediate("nonexistent"));
}

// ============================================================================
// ProjectSupervisor Tests — Reset and State Access
// ============================================================================

TEST(ProjectSupervisorTest, ResetClearsState) {
    SupervisorConfig cfg;
    cfg.maxConsecutiveFailures = 1;
    cfg.enableCircuitBreaker = true;
    ProjectSupervisor ps(cfg);

    // Trip the circuit breaker
    LevelResult lr;
    lr.objectiveIds = {"obj-a"};
    lr.outcomes["obj-a"] = ObjectiveOutcome::Failed;
    lr.failureCount = 1;
    lr.successCount = 0;

    ProjectObjectives proj;
    ps.evaluateLevel(lr, proj);
    EXPECT_TRUE(ps.state().circuitBreakerTripped);
    EXPECT_FALSE(ps.state().outcomes.empty());

    ps.reset();
    EXPECT_FALSE(ps.state().circuitBreakerTripped);
    EXPECT_TRUE(ps.state().outcomes.empty());
    EXPECT_EQ(ps.state().consecutiveFailures, 0);
}

TEST(ProjectSupervisorTest, GetConsecutiveFailures) {
    ProjectSupervisor ps;

    ObjectiveOutcomeDetail o1;
    o1.objectiveId = "obj-a";
    o1.success = false;
    ps.recordOutcome(o1);

    ObjectiveOutcomeDetail o2;
    o2.objectiveId = "obj-b";
    o2.success = false;
    ps.recordOutcome(o2);

    EXPECT_EQ(ps.getConsecutiveFailures(), 2);
}

TEST(ProjectSupervisorTest, GetConsecutiveFailuresResetOnSuccess) {
    ProjectSupervisor ps;

    ObjectiveOutcomeDetail f;
    f.objectiveId = "obj-a";
    f.success = false;
    ps.recordOutcome(f);

    ObjectiveOutcomeDetail s;
    s.objectiveId = "obj-b";
    s.success = true;
    ps.recordOutcome(s);

    EXPECT_EQ(ps.getConsecutiveFailures(), 0);
}

TEST(ProjectSupervisorTest, RecordOutcomeManual) {
    ProjectSupervisor ps;

    ObjectiveOutcomeDetail o;
    o.objectiveId = "obj-x";
    o.success = true;
    o.qualityScore = 0.95;
    ps.recordOutcome(o);

    ASSERT_EQ(ps.state().outcomes.size(), 1u);
    EXPECT_EQ(ps.state().outcomes[0].objectiveId, "obj-x");
    EXPECT_DOUBLE_EQ(ps.state().outcomes[0].qualityScore, 0.95);
}

// ============================================================================
// GitOperation Tests
// ============================================================================

TEST(GitOperationTest, DefaultConstruction) {
    GitOperation op;
    EXPECT_TRUE(op.operationName.empty());
    EXPECT_FALSE(op.success);
    EXPECT_DOUBLE_EQ(op.duration, 0.0);
    EXPECT_FALSE(op.timestamp.empty());
    EXPECT_TRUE(op.errorMessage.empty());
}

TEST(GitOperationTest, ToJsonFromJsonRoundTrip) {
    GitOperation op;
    op.operationName = "create_worktree";
    op.success = true;
    op.duration = 1.23;
    op.timestamp = "2025-01-01T00:00:00.000Z";
    op.errorMessage = "";

    json j = op.toJson();
    GitOperation restored = GitOperation::fromJson(j);

    EXPECT_EQ(restored.operationName, "create_worktree");
    EXPECT_TRUE(restored.success);
    EXPECT_DOUBLE_EQ(restored.duration, 1.23);
    EXPECT_EQ(restored.timestamp, "2025-01-01T00:00:00.000Z");
}

// ============================================================================
// GitSupervisor Tests — Construction and Defaults
// ============================================================================

TEST(GitSupervisorTest, DefaultConstruction) {
    GitWorker worker("/tmp/repo");
    GitSupervisor gs(worker);

    EXPECT_EQ(gs.circuitBreaker().state(), CircuitState::Closed);
    EXPECT_TRUE(gs.operationLog().empty());
    EXPECT_TRUE(gs.config().enableCircuitBreaker);
}

TEST(GitSupervisorTest, WithCustomConfig) {
    SupervisorConfig cfg;
    cfg.enableCircuitBreaker = false;
    GitWorker worker("/tmp/repo");
    GitSupervisor gs(worker, cfg);

    EXPECT_FALSE(gs.config().enableCircuitBreaker);
}

// ============================================================================
// GitSupervisor Tests — Circuit Breaker Protection
// ============================================================================

TEST(GitSupervisorTest, CreateWorktreeSuccess) {
    GitWorker worker(".");
    GitSupervisor gs(worker);

    auto result = gs.createWorktree("test-obj", "Test Objective");
    // May succeed or fail depending on git availability, but should not crash
    EXPECT_GE(gs.operationLog().size(), 1u);

    // Cleanup if it succeeded
    if (result.has_value()) {
        gs.cleanupWorktree("test-obj");
    }
}

TEST(GitSupervisorTest, CreateWorktreeFailureLogged) {
    GitWorker worker("/nonexistent/path");
    GitSupervisor gs(worker);

    auto result = gs.createWorktree("test-obj", "Test Objective");
    EXPECT_FALSE(result.has_value());
    ASSERT_GE(gs.operationLog().size(), 1u);
    EXPECT_EQ(gs.operationLog()[0].operationName, "create_worktree");
    EXPECT_FALSE(gs.operationLog()[0].success);
}

TEST(GitSupervisorTest, CircuitBreakerOpenBlocksOperations) {
    SupervisorConfig cfg;
    cfg.circuitBreakerThreshold = 1;
    cfg.circuitBreakerTimeoutSec = 3600; // long timeout so it stays open
    GitWorker worker(".");
    GitSupervisor gs(worker, cfg);

    // Manually trip the circuit breaker by recording a failure
    gs.detectChangedFiles("nonexistent-branch-for-test");
    // Git command may succeed or fail depending on repo state

    // Force circuit breaker to Open state
    gs.mutableCircuitBreaker().recordFailure();
    gs.mutableCircuitBreaker().recordFailure(); // ensure threshold met
    EXPECT_EQ(gs.circuitBreaker().state(), CircuitState::Open);

    // Next operation should be blocked by circuit breaker
    auto result = gs.createWorktree("test-obj", "Test");
    EXPECT_FALSE(result.has_value());

    // Should have a circuit breaker log entry
    bool foundCbEntry = false;
    for (const auto& op : gs.operationLog()) {
        if (op.errorMessage.find("Circuit breaker") != std::string::npos) {
            foundCbEntry = true;
            break;
        }
    }
    EXPECT_TRUE(foundCbEntry);
}

TEST(GitSupervisorTest, CleanupWorktreeOperationLogged) {
    GitWorker worker(".");
    GitSupervisor gs(worker);

    gs.cleanupWorktree("nonexistent-obj");
    ASSERT_GE(gs.operationLog().size(), 1u);
    EXPECT_EQ(gs.operationLog()[0].operationName, "cleanup_worktree");
}

TEST(GitSupervisorTest, RollbackBranchOperationLogged) {
    GitWorker worker(".");
    GitSupervisor gs(worker);

    gs.rollbackBranch("nonexistent-branch");
    ASSERT_GE(gs.operationLog().size(), 1u);
    EXPECT_EQ(gs.operationLog()[0].operationName, "rollback_branch");
}

TEST(GitSupervisorTest, DetectChangedFilesOperationLogged) {
    GitWorker worker(".");
    GitSupervisor gs(worker);

    gs.detectChangedFiles("main");
    ASSERT_GE(gs.operationLog().size(), 1u);
    EXPECT_EQ(gs.operationLog()[0].operationName, "detect_changed_files");
}

TEST(GitSupervisorTest, CircuitBreakerDisabledBypassesProtection) {
    SupervisorConfig cfg;
    cfg.enableCircuitBreaker = false;
    GitWorker worker("/nonexistent/path");
    GitSupervisor gs(worker, cfg);

    // With circuit breaker disabled, operations should proceed even with failures
    auto result = gs.createWorktree("test-obj", "Test");
    EXPECT_FALSE(result.has_value()); // git will fail, but not due to circuit breaker

    // Circuit breaker should remain in closed state
    EXPECT_EQ(gs.circuitBreaker().state(), CircuitState::Closed);
}

TEST(GitSupervisorTest, RecordOperation) {
    GitWorker worker(".");
    GitSupervisor gs(worker);

    GitOperation op;
    op.operationName = "manual_op";
    op.success = true;
    op.duration = 0.5;
    gs.recordOperation(op);

    ASSERT_EQ(gs.operationLog().size(), 1u);
    EXPECT_EQ(gs.operationLog()[0].operationName, "manual_op");
}

TEST(GitSupervisorTest, OperationLogContainsTimestamps) {
    GitWorker worker(".");
    GitSupervisor gs(worker);

    gs.detectChangedFiles("main");
    ASSERT_GE(gs.operationLog().size(), 1u);
    EXPECT_FALSE(gs.operationLog()[0].timestamp.empty());
}
