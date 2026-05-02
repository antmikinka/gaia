// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT

#include <gtest/gtest.h>
#include <gaia/orchestrator_api.h>

#include <atomic>
#include <chrono>
#include <thread>
#include <vector>

using namespace gaia;

// ============================================================================
// Basic Push/Get Tests
// ============================================================================

TEST(SseEventBrokerTest, PushAndGetEvents) {
    SseEventBroker broker(100);

    SseEvent event;
    event.id = "1";
    event.type = "test_event";
    event.data = "{\"key\":\"value\"}";
    event.timestamp = getCurrentTimestamp();

    broker.push(event);

    auto [events, maxIdx] = broker.getEventsSince(
        0, std::chrono::milliseconds(100));

    ASSERT_EQ(events.size(), 1u);
    EXPECT_EQ(events[0].type, "test_event");
    EXPECT_EQ(events[0].data, "{\"key\":\"value\"}");
    EXPECT_EQ(maxIdx, 1u);
}

TEST(SseEventBrokerTest, GetEventsSinceZero) {
    SseEventBroker broker(100);

    // Push two events
    SseEvent e1;
    e1.id = "1"; e1.type = "event_a"; e1.data = "{}";
    broker.push(e1);

    SseEvent e2;
    e2.id = "2"; e2.type = "event_b"; e2.data = "{}";
    broker.push(e2);

    auto [events, maxIdx] = broker.getEventsSince(
        0, std::chrono::milliseconds(100));

    ASSERT_EQ(events.size(), 2u);
    EXPECT_EQ(events[0].type, "event_a");
    EXPECT_EQ(events[1].type, "event_b");
    EXPECT_EQ(maxIdx, 2u);
}

TEST(SseEventBrokerTest, GetEventsSincePartial) {
    SseEventBroker broker(100);

    SseEvent e1;
    e1.id = "1"; e1.type = "first"; e1.data = "{}";
    broker.push(e1);

    SseEvent e2;
    e2.id = "2"; e2.type = "second"; e2.data = "{}";
    broker.push(e2);

    SseEvent e3;
    e3.id = "3"; e3.type = "third"; e3.data = "{}";
    broker.push(e3);

    // Get events since index 2 (should get only event 3)
    auto [events, maxIdx] = broker.getEventsSince(
        2, std::chrono::milliseconds(100));

    ASSERT_EQ(events.size(), 1u);
    EXPECT_EQ(events[0].type, "third");
    EXPECT_EQ(maxIdx, 3u);
}

TEST(SseEventBrokerTest, GetEventsSinceAll) {
    SseEventBroker broker(100);

    SseEvent e;
    e.id = "1"; e.type = "only"; e.data = "{}";
    broker.push(e);

    // Get events since index 1 (all events already seen)
    auto [events, maxIdx] = broker.getEventsSince(
        1, std::chrono::milliseconds(50));

    EXPECT_EQ(events.size(), 0u);
    EXPECT_EQ(maxIdx, 1u);
}

TEST(SseEventBrokerTest, GetEventsSinceBeyondRange) {
    SseEventBroker broker(100);

    // No events pushed
    auto [events, maxIdx] = broker.getEventsSince(
        0, std::chrono::milliseconds(50));

    EXPECT_EQ(events.size(), 0u);
    EXPECT_EQ(maxIdx, 0u);
}

TEST(SseEventBrokerTest, GetEventsTimeoutReturnsEmpty) {
    SseEventBroker broker(100);

    auto start = std::chrono::steady_clock::now();
    auto [events, maxIdx] = broker.getEventsSince(
        0, std::chrono::milliseconds(100));
    auto end = std::chrono::steady_clock::now();

    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        end - start).count();

    EXPECT_EQ(events.size(), 0u);
    // Should have waited at least close to the timeout
    EXPECT_GE(elapsed, 90);
}

TEST(SseEventBrokerTest, GetEventsReturnsImmediatelyWhenEventsExist) {
    SseEventBroker broker(100);

    SseEvent e;
    e.id = "1"; e.type = "ready"; e.data = "{}";
    broker.push(e);

    auto start = std::chrono::steady_clock::now();
    auto [events, maxIdx] = broker.getEventsSince(
        0, std::chrono::milliseconds(1000));
    auto end = std::chrono::steady_clock::now();

    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        end - start).count();

    ASSERT_EQ(events.size(), 1u);
    // Should return much faster than the 1000ms timeout
    EXPECT_LT(elapsed, 500);
}

// ============================================================================
// Blocking Get Tests
// ============================================================================

TEST(SseEventBrokerTest, BlockingGetWaitsForEvent) {
    SseEventBroker broker(100);

    std::atomic<bool> gotEvent = false;

    std::thread reader([&broker, &gotEvent]() {
        auto [events, maxIdx] = broker.getEventsSince(
            0, std::chrono::milliseconds(5000));
        if (!events.empty()) {
            gotEvent = true;
        }
    });

    // Small delay then push event
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    SseEvent e;
    e.id = "1"; e.type = "delayed"; e.data = "{}";
    broker.push(e);

    reader.join();
    EXPECT_TRUE(gotEvent);
}

TEST(SseEventBrokerTest, BlockingGetTimeoutOnNoEvents) {
    SseEventBroker broker(100);

    auto start = std::chrono::steady_clock::now();
    auto [events, maxIdx] = broker.getEventsSince(
        0, std::chrono::milliseconds(200));
    auto end = std::chrono::steady_clock::now();

    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
        end - start).count();

    EXPECT_EQ(events.size(), 0u);
    EXPECT_GE(elapsed, 190);
}

TEST(SseEventBrokerTest, BlockingGetMultipleEvents) {
    SseEventBroker broker(100);

    // Push 5 events
    for (int i = 0; i < 5; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "event_" + std::to_string(i);
        e.data = "{}";
        broker.push(e);
    }

    auto [events, maxIdx] = broker.getEventsSince(
        0, std::chrono::milliseconds(100));

    ASSERT_EQ(events.size(), 5u);
    EXPECT_EQ(maxIdx, 5u);
}

// ============================================================================
// Reconnection Tests (lastEventId simulation)
// ============================================================================

TEST(SseEventBrokerTest, ReconnectFromIndexZero) {
    SseEventBroker broker(100);

    // Simulate initial events
    for (int i = 0; i < 3; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "init";
        e.data = "{}";
        broker.push(e);
    }

    // Reconnect from 0 -- should get all events
    auto [events, maxIdx] = broker.getEventsSince(
        0, std::chrono::milliseconds(100));

    ASSERT_EQ(events.size(), 3u);
}

TEST(SseEventBrokerTest, ReconnectFromMiddleIndex) {
    SseEventBroker broker(100);

    for (int i = 0; i < 5; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "event_" + std::to_string(i);
        e.data = "{}";
        broker.push(e);
    }

    // Reconnect from index 3 -- should get events 4 and 5
    auto [events, maxIdx] = broker.getEventsSince(
        3, std::chrono::milliseconds(100));

    ASSERT_EQ(events.size(), 2u);
    EXPECT_EQ(events[0].type, "event_3");
    EXPECT_EQ(events[1].type, "event_4");
}

TEST(SseEventBrokerTest, ReconnectFromEndReturnsEmpty) {
    SseEventBroker broker(100);

    SseEvent e;
    e.id = "1"; e.type = "last"; e.data = "{}";
    broker.push(e);

    // Reconnect from end -- no new events
    auto [events, maxIdx] = broker.getEventsSince(
        1, std::chrono::milliseconds(50));

    EXPECT_EQ(events.size(), 0u);
}

TEST(SseEventBrokerTest, ReconnectAndCatchNewEvents) {
    SseEventBroker broker(100);

    // Initial events
    SseEvent e1;
    e1.id = "1"; e1.type = "old"; e1.data = "{}";
    broker.push(e1);

    // Simulate client catching up with new event
    SseEvent e2;
    e2.id = "2"; e2.type = "new"; e2.data = "{}";
    broker.push(e2);

    auto [events, maxIdx] = broker.getEventsSince(
        1, std::chrono::milliseconds(100));

    ASSERT_EQ(events.size(), 1u);
    EXPECT_EQ(events[0].type, "new");
}

// ============================================================================
// Concurrent Push/Get Tests
// ============================================================================

TEST(SseEventBrokerTest, PushConcurrent) {
    SseEventBroker broker(10000);
    const int numThreads = 10;
    const int eventsPerThread = 100;

    std::vector<std::thread> threads;
    for (int t = 0; t < numThreads; ++t) {
        threads.emplace_back([&broker, t, eventsPerThread]() {
            for (int i = 0; i < eventsPerThread; ++i) {
                SseEvent e;
                e.id = std::to_string(t * 1000 + i);
                e.type = "concurrent_push";
                e.data = "{\"thread\":" + std::to_string(t) + "}";
                e.timestamp = getCurrentTimestamp();
                broker.push(e);
            }
        });
    }

    for (auto& t : threads) {
        t.join();
    }

    EXPECT_EQ(broker.eventCount(),
              static_cast<size_t>(numThreads * eventsPerThread));
}

TEST(SseEventBrokerTest, GetConcurrent) {
    SseEventBroker broker(10000);

    // Pre-populate with events
    for (int i = 0; i < 1000; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "preloaded";
        e.data = "{}";
        broker.push(e);
    }

    const int numReaders = 5;
    std::vector<std::thread> threads;
    std::atomic<int> totalRead = 0;

    for (int t = 0; t < numReaders; ++t) {
        threads.emplace_back([&broker, &totalRead]() {
            auto [events, maxIdx] = broker.getEventsSince(
                0, std::chrono::milliseconds(100));
            totalRead += static_cast<int>(events.size());
        });
    }

    for (auto& t : threads) {
        t.join();
    }

    // All readers should have seen all events
    EXPECT_EQ(totalRead, 1000 * numReaders);
}

TEST(SseEventBrokerTest, PushGetConcurrent) {
    SseEventBroker broker(10000);
    const int numPushers = 5;
    const int numGetters = 5;
    const int eventsPerPusher = 50;

    std::atomic<int> totalPushed = 0;
    std::atomic<int> totalGot = 0;

    // Pusher threads
    std::vector<std::thread> pushers;
    for (int t = 0; t < numPushers; ++t) {
        pushers.emplace_back([&broker, &totalPushed, t, eventsPerPusher]() {
            for (int i = 0; i < eventsPerPusher; ++i) {
                SseEvent e;
                e.id = std::to_string(t * 1000 + i);
                e.type = "push_get_test";
                e.data = "{}";
                broker.push(e);
                totalPushed++;
            }
        });
    }

    // Getter threads
    std::vector<std::thread> getters;
    for (int t = 0; t < numGetters; ++t) {
        getters.emplace_back([&broker, &totalGot]() {
            for (int attempt = 0; attempt < 20; ++attempt) {
                auto [events, maxIdx] = broker.getEventsSince(
                    0, std::chrono::milliseconds(50));
                totalGot += static_cast<int>(events.size());
            }
        });
    }

    for (auto& t : pushers) t.join();
    for (auto& t : getters) t.join();

    EXPECT_EQ(totalPushed, numPushers * eventsPerPusher);
    // Getters may see varying counts due to timing, but should see something
    EXPECT_GT(totalGot, 0);
}

TEST(SseEventBrokerTest, ConcurrentStressTest) {
    SseEventBroker broker(100000);
    const int numThreads = 8;
    const int iterations = 200;

    std::vector<std::thread> threads;
    std::atomic<bool> done = false;

    for (int t = 0; t < numThreads; ++t) {
        threads.emplace_back([&broker, t, iterations, &done]() {
            for (int i = 0; i < iterations; ++i) {
                if (t % 2 == 0) {
                    // Even threads push
                    SseEvent e;
                    e.id = std::to_string(t * 10000 + i);
                    e.type = "stress";
                    e.data = "{}";
                    broker.push(e);
                } else {
                    // Odd threads get
                    broker.getEventsSince(0, std::chrono::milliseconds(10));
                }
            }
        });
    }

    for (auto& t : threads) {
        t.join();
    }

    // At least some events should have been pushed
    EXPECT_GT(broker.eventCount(), 0u);
}

// ============================================================================
// Pruning Tests
// ============================================================================

TEST(SseEventBrokerTest, PruneKeepsRecent) {
    SseEventBroker broker(100);

    for (int i = 0; i < 50; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "event_" + std::to_string(i);
        e.data = "{}";
        broker.push(e);
    }

    EXPECT_EQ(broker.eventCount(), 50u);

    broker.prune(10);

    EXPECT_EQ(broker.eventCount(), 10u);

    // Should have the most recent 10 events
    auto [events, maxIdx] = broker.getEventsSince(0, std::chrono::milliseconds(100));
    ASSERT_EQ(events.size(), 10u);
    EXPECT_EQ(events[0].type, "event_40");  // First of the last 10
    EXPECT_EQ(events[9].type, "event_49");  // Last event
}

TEST(SseEventBrokerTest, PruneDoesNotCrash) {
    SseEventBroker broker(100);

    // Push events
    for (int i = 0; i < 20; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "prune_test";
        e.data = "{}";
        broker.push(e);
    }

    // Prune while concurrent access might be happening
    std::thread pruner([&broker]() {
        broker.prune(5);
    });

    std::thread pusher([&broker]() {
        for (int i = 0; i < 10; ++i) {
            SseEvent e;
            e.id = std::to_string(100 + i);
            e.type = "concurrent";
            e.data = "{}";
            broker.push(e);
        }
    });

    pruner.join();
    pusher.join();

    // Should not crash
    EXPECT_GT(broker.eventCount(), 0u);
}

TEST(SseEventBrokerTest, PruneEmptyBroker) {
    SseEventBroker broker(100);

    // Pruning empty broker should not crash
    EXPECT_NO_THROW(broker.prune(10));
    EXPECT_EQ(broker.eventCount(), 0u);
}

TEST(SseEventBrokerTest, PruneMoreThanAvailable) {
    SseEventBroker broker(100);

    SseEvent e;
    e.id = "1"; e.type = "only"; e.data = "{}";
    broker.push(e);

    // Prune to keep 100 but only 1 exists
    broker.prune(100);

    EXPECT_EQ(broker.eventCount(), 1u);
}

TEST(SseEventBrokerTest, AutoPruneOnMaxEvents) {
    SseEventBroker broker(10);

    for (int i = 0; i < 20; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "auto_prune";
        e.data = "{}";
        broker.push(e);
    }

    // Should have auto-pruned
    EXPECT_LE(broker.eventCount(), 10u);
}

TEST(SseEventBrokerTest, MaxEventsLimit) {
    SseEventBroker broker(5);

    for (int i = 0; i < 15; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "limit_test";
        e.data = "{}";
        broker.push(e);
    }

    EXPECT_LE(broker.eventCount(), 10u);  // Prunes to maxEvents_/2 = 2 or 5
}

// ============================================================================
// Event ID Sequencing Tests
// ============================================================================

TEST(SseEventBrokerTest, MaxIndexIncrements) {
    SseEventBroker broker(100);

    EXPECT_EQ(broker.maxIndex(), 0u);

    SseEvent e;
    e.id = "1"; e.type = "first"; e.data = "{}";
    broker.push(e);

    EXPECT_EQ(broker.maxIndex(), 1u);

    SseEvent e2;
    e2.id = "2"; e2.type = "second"; e2.data = "{}";
    broker.push(e2);

    EXPECT_EQ(broker.maxIndex(), 2u);
}

TEST(SseEventBrokerTest, MaxIndexMatchesEventCount) {
    SseEventBroker broker(100);

    for (int i = 0; i < 10; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "count_test";
        e.data = "{}";
        broker.push(e);
    }

    EXPECT_EQ(broker.maxIndex(), broker.eventCount());
}

// ============================================================================
// EventCount Tests
// ============================================================================

TEST(SseEventBrokerTest, EventCountInitial) {
    SseEventBroker broker(100);
    EXPECT_EQ(broker.eventCount(), 0u);
}

TEST(SseEventBrokerTest, EventCountAfterPush) {
    SseEventBroker broker(100);

    for (int i = 0; i < 7; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "count";
        e.data = "{}";
        broker.push(e);
    }

    EXPECT_EQ(broker.eventCount(), 7u);
}

TEST(SseEventBrokerTest, EventCountAfterPrune) {
    SseEventBroker broker(100);

    for (int i = 0; i < 20; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "prune_count";
        e.data = "{}";
        broker.push(e);
    }

    EXPECT_EQ(broker.eventCount(), 20u);

    broker.prune(5);
    EXPECT_EQ(broker.eventCount(), 5u);
}

// ============================================================================
// Edge Cases
// ============================================================================

TEST(SseEventBrokerTest, EmptyEventData) {
    SseEventBroker broker(100);

    SseEvent e;
    e.id = "1";
    e.type = "empty_data";
    e.data = "";  // Empty data
    e.timestamp = getCurrentTimestamp();
    broker.push(e);

    auto [events, maxIdx] = broker.getEventsSince(
        0, std::chrono::milliseconds(100));

    ASSERT_EQ(events.size(), 1u);
    EXPECT_TRUE(events[0].data.empty());
}

TEST(SseEventBrokerTest, LargeEventData) {
    SseEventBroker broker(100);

    SseEvent e;
    e.id = "1";
    e.type = "large";
    e.data = std::string(10000, 'x');  // 10KB data
    broker.push(e);

    auto [events, maxIdx] = broker.getEventsSince(
        0, std::chrono::milliseconds(100));

    ASSERT_EQ(events.size(), 1u);
    EXPECT_EQ(events[0].data.size(), 10000u);
}

TEST(SseEventBrokerTest, JsonDataInEvent) {
    SseEventBroker broker(100);

    json payload;
    payload["objective_id"] = "obj-001";
    payload["success"] = true;
    payload["quality_score"] = 0.95;

    SseEvent e;
    e.id = "1";
    e.type = "objective_complete";
    e.data = payload.dump();
    broker.push(e);

    auto [events, maxIdx] = broker.getEventsSince(
        0, std::chrono::milliseconds(100));

    ASSERT_EQ(events.size(), 1u);
    json parsed = json::parse(events[0].data);
    EXPECT_EQ(parsed["objective_id"], "obj-001");
    EXPECT_EQ(parsed["success"], true);
    EXPECT_DOUBLE_EQ(parsed["quality_score"], 0.95);
}

TEST(SseEventBrokerTest, MultipleGetCallsSameIndex) {
    SseEventBroker broker(100);

    SseEvent e;
    e.id = "1"; e.type = "shared"; e.data = "{}";
    broker.push(e);

    // Two readers from same index should both see the event
    auto [events1, maxIdx1] = broker.getEventsSince(
        0, std::chrono::milliseconds(100));
    auto [events2, maxIdx2] = broker.getEventsSince(
        0, std::chrono::milliseconds(100));

    EXPECT_EQ(events1.size(), 1u);
    EXPECT_EQ(events2.size(), 1u);
    EXPECT_EQ(maxIdx1, 1u);
    EXPECT_EQ(maxIdx2, 1u);
}

TEST(SseEventBrokerTest, PushAfterPrune) {
    SseEventBroker broker(10);

    for (int i = 0; i < 20; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "before_prune";
        e.data = "{}";
        broker.push(e);
    }

    broker.prune(3);
    size_t countAfterPrune = broker.eventCount();

    SseEvent newEvent;
    newEvent.id = "new";
    newEvent.type = "after_prune";
    newEvent.data = "{}";
    broker.push(newEvent);

    EXPECT_EQ(broker.eventCount(), countAfterPrune + 1);

    // The new event should be retrievable
    auto [events, maxIdx] = broker.getEventsSince(
        countAfterPrune, std::chrono::milliseconds(100));
    ASSERT_EQ(events.size(), 1u);
    EXPECT_EQ(events[0].type, "after_prune");
}

TEST(SseEventBrokerTest, BrokerWithDefaultMaxEvents) {
    SseEventBroker broker;  // Default maxEvents = 10000

    SseEvent e;
    e.id = "1"; e.type = "default"; e.data = "{}";
    broker.push(e);

    EXPECT_EQ(broker.eventCount(), 1u);
    EXPECT_EQ(broker.maxIndex(), 1u);
}

TEST(SseEventBrokerTest, BrokerWithZeroMaxEvents) {
    SseEventBroker broker(0);  // Edge case: zero max

    SseEvent e;
    e.id = "1"; e.type = "zero_max"; e.data = "{}";
    broker.push(e);

    // Should handle gracefully -- at least not crash
    EXPECT_GE(broker.eventCount(), 0u);
}

// ============================================================================
// Pruning Edge-Case Tests (client index beyond pruned range)
// ============================================================================

TEST(SseEventBrokerTest, GetSinceBeyondPrunedRange) {
    // Regression: when a client's sinceIndex points past the pruned event
    // window, getEventsSince should return available events instead of
    // returning empty or blocking forever.
    SseEventBroker broker(10);

    // Push 20 events, triggering auto-prune to 5
    for (int i = 0; i < 20; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "event_" + std::to_string(i);
        e.data = "{}";
        broker.push(e);
    }

    // Client's sinceIndex is way ahead (simulating stale connection)
    auto [events, maxIdx] = broker.getEventsSince(
        15, std::chrono::milliseconds(50));

    // Should return all available events, not empty
    EXPECT_GT(events.size(), 0u);
    EXPECT_LE(events.size(), 10u);
}

TEST(SseEventBrokerTest, GetSinceEqualToCurrentSize) {
    SseEventBroker broker(100);

    SseEvent e;
    e.id = "1"; e.type = "only"; e.data = "{}";
    broker.push(e);

    // sinceIndex == events_.size() (1 == 1)
    auto [events, maxIdx] = broker.getEventsSince(
        1, std::chrono::milliseconds(50));

    // No new events beyond current end -- empty is correct here
    EXPECT_EQ(events.size(), 0u);
    EXPECT_EQ(maxIdx, 1u);
}

TEST(SseEventBrokerTest, PruneThenGetReturnsAvailableEvents) {
    SseEventBroker broker(10);

    // Fill beyond capacity
    for (int i = 0; i < 20; ++i) {
        SseEvent e;
        e.id = std::to_string(i + 1);
        e.type = "fill";
        e.data = "{}";
        broker.push(e);
    }

    // Manually prune to 3
    broker.prune(3);
    EXPECT_EQ(broker.eventCount(), 3u);

    // Client with old index (10) should get the 3 remaining events
    auto [events, maxIdx] = broker.getEventsSince(
        10, std::chrono::milliseconds(50));

    EXPECT_EQ(events.size(), 3u);
    EXPECT_EQ(maxIdx, 3u);
}
