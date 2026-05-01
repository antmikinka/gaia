// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT
//
// Orchestrator types for the GAIA C++ pipeline orchestration system.
// Ported from Python: src/gaia/orchestration/models.py

#pragma once

#include <algorithm>
#include <chrono>
#include <iomanip>
#include <optional>
#include <queue>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <nlohmann/json.hpp>

namespace gaia {

using json = nlohmann::json;

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

/// Generate an 8-character hexadecimal ID string (matches Python uuid4()[:8]).
inline std::string generateShortId() {
    static thread_local std::mt19937 gen{std::random_device{}()};
    std::uniform_int_distribution<uint32_t> dist;
    std::ostringstream oss;
    oss << std::hex << std::setfill('0') << std::setw(8) << dist(gen);
    return oss.str();
}

/// Get current UTC timestamp in ISO 8601 format.
inline std::string getCurrentTimestamp() {
    auto now = std::chrono::system_clock::now();
    auto timeT = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                  now.time_since_epoch()) % 1000;
    std::ostringstream oss;
#ifdef _MSC_VER
    struct tm timeInfo;
    gmtime_s(&timeInfo, &timeT);
    oss << std::put_time(&timeInfo, "%Y-%m-%dT%H:%M:%S");
#else
    oss << std::put_time(std::gmtime(&timeT), "%Y-%m-%dT%H:%M:%S");
#endif
    oss << '.' << std::setfill('0') << std::setw(3) << ms.count() << 'Z';
    return oss.str();
}

// ---------------------------------------------------------------------------
// ObjectiveStatus enum
// ---------------------------------------------------------------------------

enum class ObjectiveStatus {
    Queued,
    InProgress,
    Completed,
    Blocked,
    Cancelled
};

/// Convert ObjectiveStatus to its string representation.
inline std::string objectiveStatusToString(ObjectiveStatus s) {
    switch (s) {
        case ObjectiveStatus::Queued:       return "queued";
        case ObjectiveStatus::InProgress:   return "in_progress";
        case ObjectiveStatus::Completed:    return "completed";
        case ObjectiveStatus::Blocked:      return "blocked";
        case ObjectiveStatus::Cancelled:    return "cancelled";
    }
    return "unknown";
}

/// Convert string to ObjectiveStatus. Throws on invalid input.
inline ObjectiveStatus stringToObjectiveStatus(const std::string& s) {
    if (s == "queued")       return ObjectiveStatus::Queued;
    if (s == "in_progress")  return ObjectiveStatus::InProgress;
    if (s == "completed")    return ObjectiveStatus::Completed;
    if (s == "blocked")      return ObjectiveStatus::Blocked;
    if (s == "cancelled")    return ObjectiveStatus::Cancelled;
    throw std::invalid_argument("Invalid ObjectiveStatus string: " + s);
}

/// Check whether a transition from `from` to `to` is valid.
inline bool canTransition(ObjectiveStatus from, ObjectiveStatus to) {
    // Transition table (from Python models.py lines 54-69):
    // QUEUED       -> IN_PROGRESS, BLOCKED, CANCELLED
    // IN_PROGRESS  -> COMPLETED, BLOCKED, CANCELLED
    // BLOCKED      -> QUEUED, CANCELLED
    // COMPLETED    -> (none, terminal)
    // CANCELLED    -> (none, terminal)
    switch (from) {
        case ObjectiveStatus::Queued:
            return to == ObjectiveStatus::InProgress ||
                   to == ObjectiveStatus::Blocked ||
                   to == ObjectiveStatus::Cancelled;
        case ObjectiveStatus::InProgress:
            return to == ObjectiveStatus::Completed ||
                   to == ObjectiveStatus::Blocked ||
                   to == ObjectiveStatus::Cancelled;
        case ObjectiveStatus::Blocked:
            return to == ObjectiveStatus::Queued ||
                   to == ObjectiveStatus::Cancelled;
        case ObjectiveStatus::Completed:
        case ObjectiveStatus::Cancelled:
            return false;  // terminal states
    }
    return false;
}

// ---------------------------------------------------------------------------
// ObjectiveOutcome enum
// ---------------------------------------------------------------------------

enum class ObjectiveOutcome {
    Success,
    Failed,
    Skipped,
    ConflictDetected
};

inline std::string objectiveOutcomeToString(ObjectiveOutcome o) {
    switch (o) {
        case ObjectiveOutcome::Success:          return "success";
        case ObjectiveOutcome::Failed:           return "failed";
        case ObjectiveOutcome::Skipped:          return "skipped";
        case ObjectiveOutcome::ConflictDetected: return "conflict_detected";
    }
    return "unknown";
}

inline ObjectiveOutcome stringToObjectiveOutcome(const std::string& s) {
    if (s == "success")           return ObjectiveOutcome::Success;
    if (s == "failed")            return ObjectiveOutcome::Failed;
    if (s == "skipped")           return ObjectiveOutcome::Skipped;
    if (s == "conflict_detected") return ObjectiveOutcome::ConflictDetected;
    throw std::invalid_argument("Invalid ObjectiveOutcome string: " + s);
}

// ---------------------------------------------------------------------------
// Artifact
// ---------------------------------------------------------------------------

struct Artifact {
    std::string artifactId;
    std::string name;
    std::string artifactType = "generic";
    std::string urlOrPath;
    json metadata = json::object();
    std::string createdAt;

    Artifact()
        : artifactId(generateShortId()), createdAt(getCurrentTimestamp()) {}

    json toJson() const {
        json j;
        j["artifact_id"] = artifactId;
        j["name"] = name;
        j["artifact_type"] = artifactType;
        j["url_or_path"] = urlOrPath;
        j["metadata"] = metadata;
        j["created_at"] = createdAt;
        return j;
    }

    static Artifact fromJson(const json& j) {
        Artifact a;
        a.artifactId = j.value("artifact_id", generateShortId());
        a.name = j.value("name", std::string{});
        a.artifactType = j.value("artifact_type", std::string{"generic"});
        a.urlOrPath = j.value("url_or_path", std::string{});
        a.metadata = j.value("metadata", json::object());
        a.createdAt = j.value("created_at", getCurrentTimestamp());
        return a;
    }
};

// ---------------------------------------------------------------------------
// Objective
// ---------------------------------------------------------------------------

struct Objective {
    std::string objectiveId;
    std::string title;
    std::string description;
    ObjectiveStatus status = ObjectiveStatus::Queued;
    std::vector<std::string> dependencies;
    std::vector<Artifact> artifacts;
    int priority = 5;
    std::string phase = "DEVELOPMENT";
    json pipelineConfig = json::object();
    std::string createdAt;
    std::string updatedAt;
    std::optional<std::string> errorMessage;

    Objective()
        : objectiveId(generateShortId()),
          createdAt(getCurrentTimestamp()),
          updatedAt(getCurrentTimestamp()) {}

    /// Transition to a new status. Throws std::invalid_argument if invalid.
    void transitionTo(ObjectiveStatus newStatus) {
        if (!canTransition(status, newStatus)) {
            throw std::invalid_argument(
                "Invalid transition from " + objectiveStatusToString(status) +
                " to " + objectiveStatusToString(newStatus) +
                " for objective '" + title + "' (" + objectiveId + ")"
            );
        }
        status = newStatus;
        updatedAt = getCurrentTimestamp();
    }

    /// Add an artifact to this objective.
    void addArtifact(const Artifact& artifact) {
        artifacts.push_back(artifact);
        updatedAt = getCurrentTimestamp();
    }

    json toJson() const {
        json j;
        j["objective_id"] = objectiveId;
        j["title"] = title;
        j["description"] = description;
        j["status"] = objectiveStatusToString(status);
        j["dependencies"] = dependencies;
        json arts = json::array();
        for (const auto& a : artifacts) {
            arts.push_back(a.toJson());
        }
        j["artifacts"] = arts;
        j["priority"] = priority;
        j["phase"] = phase;
        j["pipeline_config"] = pipelineConfig;
        j["created_at"] = createdAt;
        j["updated_at"] = updatedAt;
        if (errorMessage.has_value()) {
            j["error_message"] = errorMessage.value();
        }
        return j;
    }

    static Objective fromJson(const json& j) {
        Objective obj;
        obj.objectiveId = j.value("objective_id", generateShortId());
        obj.title = j.value("title", std::string{});
        obj.description = j.value("description", std::string{});
        obj.status = stringToObjectiveStatus(
            j.value("status", std::string{"queued"}));
        obj.dependencies = j.value("dependencies", std::vector<std::string>{});
        obj.artifacts.clear();
        if (j.contains("artifacts") && j["artifacts"].is_array()) {
            for (const auto& a : j["artifacts"]) {
                obj.artifacts.push_back(Artifact::fromJson(a));
            }
        }
        obj.priority = j.value("priority", 5);
        obj.phase = j.value("phase", std::string{"DEVELOPMENT"});
        obj.pipelineConfig = j.value("pipeline_config", json::object());
        obj.createdAt = j.value("created_at", getCurrentTimestamp());
        obj.updatedAt = j.value("updated_at", getCurrentTimestamp());
        if (j.contains("error_message") && !j["error_message"].is_null()) {
            obj.errorMessage = j["error_message"].get<std::string>();
        }
        return obj;
    }
};

// ---------------------------------------------------------------------------
// ProjectObjectives
// ---------------------------------------------------------------------------

struct ProjectObjectives {
    std::string projectId;
    std::string name;
    std::vector<Objective> objectives;
    json metadata = json::object();

    ProjectObjectives() : projectId(generateShortId()) {}

    void addObjective(const Objective& objective) {
        objectives.push_back(objective);
    }

    const Objective* getObjective(const std::string& objectiveId) const {
        for (const auto& obj : objectives) {
            if (obj.objectiveId == objectiveId) {
                return &obj;
            }
        }
        return nullptr;
    }

    /// Return pointers to QUEUED objectives whose dependencies are all
    /// COMPLETED, sorted by priority (lower = higher priority).
    std::vector<Objective*> getReadyObjectives() {
        std::unordered_set<std::string> completedIds;
        for (const auto& obj : objectives) {
            if (obj.status == ObjectiveStatus::Completed) {
                completedIds.insert(obj.objectiveId);
            }
        }
        std::vector<Objective*> ready;
        for (auto& obj : objectives) {
            if (obj.status != ObjectiveStatus::Queued) {
                continue;
            }
            bool depsMet = true;
            for (const auto& depId : obj.dependencies) {
                if (completedIds.find(depId) == completedIds.end()) {
                    depsMet = false;
                    break;
                }
            }
            if (depsMet) {
                ready.push_back(&obj);
            }
        }
        std::sort(ready.begin(), ready.end(),
                  [](const Objective* a, const Objective* b) {
                      return a->priority < b->priority;
                  });
        return ready;
    }

    /// Return all objective IDs as an unordered_set.
    std::unordered_set<std::string> getAllObjectiveIds() const {
        std::unordered_set<std::string> ids;
        for (const auto& obj : objectives) {
            ids.insert(obj.objectiveId);
        }
        return ids;
    }

    json toJson() const {
        json j;
        j["project_id"] = projectId;
        j["name"] = name;
        json objs = json::array();
        for (const auto& o : objectives) {
            objs.push_back(o.toJson());
        }
        j["objectives"] = objs;
        j["metadata"] = metadata;
        return j;
    }

    static ProjectObjectives fromJson(const json& j) {
        ProjectObjectives proj;
        proj.projectId = j.value("project_id", generateShortId());
        proj.name = j.value("name", std::string{});
        proj.objectives.clear();
        if (j.contains("objectives") && j["objectives"].is_array()) {
            for (const auto& o : j["objectives"]) {
                proj.objectives.push_back(Objective::fromJson(o));
            }
        }
        proj.metadata = j.value("metadata", json::object());
        return proj;
    }
};

// ---------------------------------------------------------------------------
// ConflictReport
// ---------------------------------------------------------------------------

struct ConflictReport {
    std::vector<std::string> conflictingObjectiveIds;
    std::vector<std::string> affectedFiles;
    std::string timestamp;

    ConflictReport() : timestamp(getCurrentTimestamp()) {}

    json toJson() const {
        json j;
        j["conflicting_objective_ids"] = conflictingObjectiveIds;
        j["affected_files"] = affectedFiles;
        j["timestamp"] = timestamp;
        return j;
    }

    static ConflictReport fromJson(const json& j) {
        ConflictReport cr;
        cr.conflictingObjectiveIds =
            j.value("conflicting_objective_ids", std::vector<std::string>{});
        cr.affectedFiles =
            j.value("affected_files", std::vector<std::string>{});
        cr.timestamp = j.value("timestamp", getCurrentTimestamp());
        return cr;
    }
};

// ---------------------------------------------------------------------------
// LevelResult
// ---------------------------------------------------------------------------

struct LevelResult {
    int levelNumber;
    std::vector<std::string> objectiveIds;
    std::unordered_map<std::string, ObjectiveOutcome> outcomes;
    std::vector<ConflictReport> conflicts;
    int successCount = 0;
    int failureCount = 0;
    std::string verdict = "CONTINUE";
    std::string timestamp;

    LevelResult()
        : levelNumber(0), timestamp(getCurrentTimestamp()) {}

    json toJson() const {
        json j;
        j["level_number"] = levelNumber;
        j["objective_ids"] = objectiveIds;
        json outcomesJson = json::object();
        for (const auto& [id, outcome] : outcomes) {
            outcomesJson[id] = objectiveOutcomeToString(outcome);
        }
        j["outcomes"] = outcomesJson;
        json conflictsJson = json::array();
        for (const auto& c : conflicts) {
            conflictsJson.push_back(c.toJson());
        }
        j["conflicts"] = conflictsJson;
        j["success_count"] = successCount;
        j["failure_count"] = failureCount;
        j["verdict"] = verdict;
        j["timestamp"] = timestamp;
        return j;
    }

    static LevelResult fromJson(const json& j) {
        LevelResult lr;
        lr.levelNumber = j.value("level_number", 0);
        lr.objectiveIds = j.value("objective_ids", std::vector<std::string>{});
        lr.outcomes.clear();
        if (j.contains("outcomes") && j["outcomes"].is_object()) {
            for (const auto& [key, val] : j["outcomes"].items()) {
                lr.outcomes[key] = stringToObjectiveOutcome(val.get<std::string>());
            }
        }
        lr.conflicts.clear();
        if (j.contains("conflicts") && j["conflicts"].is_array()) {
            for (const auto& c : j["conflicts"]) {
                lr.conflicts.push_back(ConflictReport::fromJson(c));
            }
        }
        lr.successCount = j.value("success_count", 0);
        lr.failureCount = j.value("failure_count", 0);
        lr.verdict = j.value("verdict", std::string{"CONTINUE"});
        lr.timestamp = j.value("timestamp", getCurrentTimestamp());
        return lr;
    }
};

// ---------------------------------------------------------------------------
// DependencyGraph
// ---------------------------------------------------------------------------

class DependencyGraph {
public:
    DependencyGraph() = default;

    explicit DependencyGraph(const std::vector<Objective>& objectives) {
        build(objectives);
    }

    /// Build forward and reverse indices from objectives.
    void build(const std::vector<Objective>& objectives) {
        forward_.clear();
        reverse_.clear();
        allIds_.clear();

        for (const auto& obj : objectives) {
            allIds_.insert(obj.objectiveId);
            forward_[obj.objectiveId];         // ensure entry exists
            reverse_[obj.objectiveId];

            for (const auto& depId : obj.dependencies) {
                forward_[obj.objectiveId].insert(depId);
                reverse_[depId].insert(obj.objectiveId);
            }
        }
    }

    /// Add a single objective to the graph.
    void addObjective(const Objective& objective) {
        allIds_.insert(objective.objectiveId);
        forward_[objective.objectiveId];
        reverse_[objective.objectiveId];

        for (const auto& depId : objective.dependencies) {
            forward_[objective.objectiveId].insert(depId);
            reverse_[depId].insert(objective.objectiveId);
        }
    }

    /// Remove an objective and its edges from the graph.
    void removeObjective(const std::string& id) {
        allIds_.erase(id);

        // Remove forward edges: deps -> erase id from their reverse
        auto fwdIt = forward_.find(id);
        if (fwdIt != forward_.end()) {
            for (const auto& depId : fwdIt->second) {
                auto revIt = reverse_.find(depId);
                if (revIt != reverse_.end()) {
                    revIt->second.erase(id);
                }
            }
            forward_.erase(fwdIt);
        }

        // Remove reverse edges: dependents -> erase id from their forward
        auto revIt = reverse_.find(id);
        if (revIt != reverse_.end()) {
            for (const auto& depId : revIt->second) {
                auto fwdIt2 = forward_.find(depId);
                if (fwdIt2 != forward_.end()) {
                    fwdIt2->second.erase(id);
                }
            }
            reverse_.erase(revIt);
        }
    }

    /// Get the set of IDs that `id` depends on.
    std::unordered_set<std::string> getDependencies(const std::string& id) const {
        auto it = forward_.find(id);
        if (it != forward_.end()) return it->second;
        return {};
    }

    /// Get IDs that depend on `id` (reverse deps).
    std::unordered_set<std::string> getReverseDeps(const std::string& id) const {
        auto it = reverse_.find(id);
        if (it != reverse_.end()) return it->second;
        return {};
    }

    /// Return all node IDs in the graph.
    std::unordered_set<std::string> nodes() const {
        return allIds_;
    }

    /// Detect cycles using DFS-based approach.
    /// Returns vector of cycles, each cycle is a list of node IDs forming
    /// the loop (with the start repeated at the end).
    std::vector<std::vector<std::string>> detectCycles() const {
        std::vector<std::vector<std::string>> cycles;
        // 0 = unvisited, 1 = in-progress, 2 = done
        std::unordered_map<std::string, int> state;
        for (const auto& id : allIds_) {
            state[id] = 0;
        }
        std::vector<std::string> path;

        // We need a mutable path and recursive lambda. Use std::function.
        std::function<void(const std::string&)> dfs =
            [&](const std::string& node) {
                state[node] = 1;
                path.push_back(node);

                auto fwdIt = forward_.find(node);
                if (fwdIt != forward_.end()) {
                    for (const auto& depId : fwdIt->second) {
                        auto stateIt = state.find(depId);
                        if (stateIt == state.end()) {
                            continue;  // external dependency, skip
                        }
                        if (stateIt->second == 1) {
                            // Found cycle
                            auto cycleStart = std::find(
                                path.begin(), path.end(), depId);
                            std::vector<std::string> cycle(
                                cycleStart, path.end());
                            cycle.push_back(depId);
                            cycles.push_back(std::move(cycle));
                        } else if (stateIt->second == 0) {
                            dfs(depId);
                        }
                    }
                }

                path.pop_back();
                state[node] = 2;
            };

        for (const auto& id : allIds_) {
            if (state[id] == 0) {
                dfs(id);
            }
        }
        return cycles;
    }

    /// Return objectives in topological order (dependencies first).
    /// Throws std::runtime_error if cycles exist.
    std::vector<std::string> topologicalOrder() const {
        auto cycles = detectCycles();
        if (!cycles.empty()) {
            std::string cycleDesc;
            for (size_t i = 0; i < cycles[0].size(); ++i) {
                if (i > 0) cycleDesc += " -> ";
                cycleDesc += cycles[0][i];
            }
            throw std::runtime_error("Circular dependencies detected: " + cycleDesc);
        }

        // Kahn's algorithm
        std::unordered_map<std::string, int> inDegree;
        for (const auto& oid : allIds_) {
            int count = 0;
            auto fwdIt = forward_.find(oid);
            if (fwdIt != forward_.end()) {
                for (const auto& depId : fwdIt->second) {
                    if (allIds_.count(depId)) {
                        ++count;
                    }
                }
            }
            inDegree[oid] = count;
        }

        std::queue<std::string> q;
        for (const auto& [oid, deg] : inDegree) {
            if (deg == 0) q.push(oid);
        }

        std::vector<std::string> result;
        while (!q.empty()) {
            std::string node = q.front();
            q.pop();
            result.push_back(node);

            auto revIt = reverse_.find(node);
            if (revIt != reverse_.end()) {
                for (const auto& dependent : revIt->second) {
                    if (inDegree.count(dependent)) {
                        if (--inDegree[dependent] == 0) {
                            q.push(dependent);
                        }
                    }
                }
            }
        }

        return result;
    }

    /// Partition objectives into parallel-executable levels.
    /// Level 0 = no deps, Level 1 = deps all in Level 0, etc.
    /// Returns vector of levels, each level is a list of IDs.
    /// Throws std::runtime_error if cycles exist.
    std::vector<std::vector<std::string>> partitionIntoLevels() const {
        auto cycles = detectCycles();
        if (!cycles.empty()) {
            std::string cycleDesc;
            for (size_t i = 0; i < cycles[0].size(); ++i) {
                if (i > 0) cycleDesc += " -> ";
                cycleDesc += cycles[0][i];
            }
            throw std::runtime_error("Circular dependencies detected: " + cycleDesc);
        }

        std::unordered_map<std::string, int> inDegree;
        for (const auto& oid : allIds_) {
            int count = 0;
            auto fwdIt = forward_.find(oid);
            if (fwdIt != forward_.end()) {
                for (const auto& depId : fwdIt->second) {
                    if (allIds_.count(depId)) {
                        ++count;
                    }
                }
            }
            inDegree[oid] = count;
        }

        std::unordered_set<std::string> remaining = allIds_;
        std::vector<std::vector<std::string>> levels;
        int processed = 0;

        while (!remaining.empty()) {
            std::vector<std::string> level;
            for (const auto& oid : remaining) {
                if (inDegree.at(oid) == 0) {
                    level.push_back(oid);
                }
            }
            if (level.empty()) {
                break;
            }
            levels.push_back(level);
            processed += static_cast<int>(level.size());

            for (const auto& node : level) {
                remaining.erase(node);
                auto revIt = reverse_.find(node);
                if (revIt != reverse_.end()) {
                    for (const auto& dependent : revIt->second) {
                        auto degIt = inDegree.find(dependent);
                        if (degIt != inDegree.end()) {
                            --degIt->second;
                        }
                    }
                }
            }
        }

        if (processed != static_cast<int>(allIds_.size())) {
            throw std::runtime_error("Unable to partition all objectives into levels");
        }

        return levels;
    }

    /// Compute all objectives transitively affected by a change to `id`.
    /// Uses BFS on reverse edges.
    std::unordered_set<std::string> computeCascade(const std::string& id) const {
        std::unordered_set<std::string> affected;
        std::queue<std::string> q;
        q.push(id);

        while (!q.empty()) {
            std::string current = q.front();
            q.pop();
            auto revIt = reverse_.find(current);
            if (revIt != reverse_.end()) {
                for (const auto& dependent : revIt->second) {
                    if (affected.find(dependent) == affected.end()) {
                        affected.insert(dependent);
                        q.push(dependent);
                    }
                }
            }
        }
        return affected;
    }

    /// Compute max cascade depth from `id` using DFS.
    /// Returns 0 if no reverse dependencies.
    int maxCascadeDepth(const std::string& id) const {
        auto revIt = reverse_.find(id);
        if (revIt == reverse_.end() || revIt->second.empty()) {
            return 0;
        }

        int maxDepth = 0;
        std::unordered_set<std::string> visited;

        std::function<void(const std::string&, int)> dfs =
            [&](const std::string& node, int depth) {
                visited.insert(node);
                if (depth > maxDepth) maxDepth = depth;
                auto rIt = reverse_.find(node);
                if (rIt != reverse_.end()) {
                    for (const auto& dependent : rIt->second) {
                        if (visited.find(dependent) == visited.end()) {
                            dfs(dependent, depth + 1);
                        }
                    }
                }
            };

        dfs(id, 0);
        return maxDepth;
    }

private:
    /// Forward edges: objectiveId -> set of dependency IDs.
    std::unordered_map<std::string, std::unordered_set<std::string>> forward_;
    /// Reverse edges: objectiveId -> set of dependents.
    std::unordered_map<std::string, std::unordered_set<std::string>> reverse_;
    /// All known node IDs.
    std::unordered_set<std::string> allIds_;
};

} // namespace gaia
