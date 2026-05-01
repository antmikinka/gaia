// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT
//
// Git worker for the GAIA C++ pipeline orchestration system.
// Ported from Python: src/gaia/orchestration/engine.py (worktree, rollback)
//              src/gaia/orchestration/supervisors/git.py (GitSupervisor)

#pragma once

#include <optional>
#include <string>
#include <vector>

namespace gaia {

// ---------------------------------------------------------------------------
// GitWorker — manages git worktrees, rollback, and conflict detection
// ---------------------------------------------------------------------------

/// Cross-platform git subprocess wrapper for orchestrator operations:
///   - Worktree creation and cleanup
///   - Changed file detection
///   - Branch rollback
///   - Stale worktree cleanup
class GitWorker {
public:
    explicit GitWorker(const std::string& repoRoot);

    // ---- Worktree lifecycle ----

    /// Create a worktree for an objective.
    /// Creates branch: obj/{objectiveId}-{slug}
    /// Creates worktree at: {repoRoot}/.gaia/worktrees/{objectiveId}/
    /// Returns the branch name on success, nullopt on failure.
    std::optional<std::string> createWorktree(const std::string& objectiveId,
                                               const std::string& title);

    /// Remove a specific worktree. Branch is retained for audit.
    /// Returns true on success.
    bool cleanupWorktree(const std::string& objectiveId);

    /// Clean up all stale worktrees matching obj/* prefix.
    /// Returns list of removed branch names.
    std::vector<std::string> cleanupAllStaleWorktrees();

    // ---- Conflict detection ----

    /// Get list of files changed on a branch compared to its base.
    std::vector<std::string> detectChangedFiles(const std::string& branch,
                                                  const std::string& baseBranch = "main");

    // ---- Rollback ----

    /// Rollback a branch: git stash && git checkout -- .
    /// Returns true on success.
    bool rollbackBranch(const std::string& branch);

    // ---- Utility ----

    /// Get git user info string (name <email>) or fallback.
    std::string getUserInfo();

    /// Get the repo root path.
    const std::string& repoRoot() const { return repoRoot_; }

    // Internal process result type (exposed for static helper functions)
    struct ProcessResult {
        int exitCode = -1;
        std::string stdout_;
        std::string stderr_;
    };

private:

    /// Run a git command with optional timeout.
    /// Cross-platform: uses CreateProcess on Windows, popen on POSIX.
    ProcessResult runCommand(const std::vector<std::string>& args,
                              int timeoutSec = 30);

    std::string repoRoot_;
    static constexpr int DEFAULT_TIMEOUT_SEC = 30;
};

} // namespace gaia
