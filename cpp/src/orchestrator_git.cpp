// Copyright(C) 2025-2026 Advanced Micro Devices, Inc. All rights reserved.
// SPDX-License-Identifier: MIT
//
// Git worker implementation — cross-platform subprocess handling.
// Ported from Python: src/gaia/orchestration/engine.py (worktree, rollback)
//              src/gaia/orchestration/supervisors/git.py (GitSupervisor)

#include "gaia/orchestrator_git.h"

#include <algorithm>
#include <filesystem>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace fs = std::filesystem;

namespace gaia {

// ---------------------------------------------------------------------------
// Cross-platform process execution
// ---------------------------------------------------------------------------

#ifdef _WIN32

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tchar.h>
#include <strsafe.h>

// Helper: build a command-line string from args, properly quoted.
static std::string buildCommandLine(const std::vector<std::string>& args) {
    std::string cmd;
    for (size_t i = 0; i < args.size(); ++i) {
        if (i > 0) cmd += " ";
        // Quote the argument if it contains spaces
        if (args[i].find(' ') != std::string::npos) {
            cmd += "\"" + args[i] + "\"";
        } else {
            cmd += args[i];
        }
    }
    return cmd;
}

static GitWorker::ProcessResult runProcessWin32(const std::string& commandLine,
                                                 int timeoutSec) {
    GitWorker::ProcessResult result;
    SECURITY_ATTRIBUTES saAttr = {};
    saAttr.nLength = sizeof(SECURITY_ATTRIBUTES);
    saAttr.bInheritHandle = TRUE;
    saAttr.lpSecurityDescriptor = nullptr;

    HANDLE hStdOutRead = nullptr, hStdOutWrite = nullptr;
    HANDLE hStdErrRead = nullptr, hStdErrWrite = nullptr;

    // Create pipes for stdout and stderr
    if (!CreatePipe(&hStdOutRead, &hStdOutWrite, &saAttr, 0)) {
        result.stderr_ = "CreatePipe stdout failed";
        return result;
    }
    SetHandleInformation(hStdOutRead, HANDLE_FLAG_INHERIT, 0);

    if (!CreatePipe(&hStdErrRead, &hStdErrWrite, &saAttr, 0)) {
        result.stderr_ = "CreatePipe stderr failed";
        CloseHandle(hStdOutRead);
        CloseHandle(hStdOutWrite);
        return result;
    }
    SetHandleInformation(hStdErrRead, HANDLE_FLAG_INHERIT, 0);

    STARTUPINFOA si = {};
    si.cb = sizeof(STARTUPINFOA);
    si.hStdError = hStdErrWrite;
    si.hStdOutput = hStdOutWrite;
    si.dwFlags |= STARTF_USESTDHANDLES;

    PROCESS_INFORMATION pi = {};

    // Make a mutable copy of the command line (CreateProcessA modifies it)
    std::vector<char> cmdBuf(commandLine.begin(), commandLine.end());
    cmdBuf.push_back('\0');

    BOOL success = CreateProcessA(
        nullptr,        // Application name (use command line)
        cmdBuf.data(),  // Command line
        nullptr,        // Process security attributes
        nullptr,        // Thread security attributes
        TRUE,           // Inherit handles
        CREATE_NO_WINDOW,
        nullptr,        // Use parent environment
        nullptr,        // Use parent current directory
        &si,
        &pi
    );

    // Close write ends (child has them)
    CloseHandle(hStdOutWrite);
    CloseHandle(hStdErrWrite);

    if (!success) {
        result.exitCode = -1;
        result.stderr_ = "CreateProcess failed: error " +
            std::to_string(GetLastError());
        CloseHandle(hStdOutRead);
        CloseHandle(hStdErrRead);
        return result;
    }

    // Wait for process with timeout
    DWORD waitResult = WaitForSingleObject(pi.hProcess,
                                            static_cast<DWORD>(timeoutSec * 1000));

    if (waitResult == WAIT_TIMEOUT) {
        TerminateProcess(pi.hProcess, 1);
        result.stderr_ = "Process timed out after " +
            std::to_string(timeoutSec) + " seconds";
        result.exitCode = -2;
    } else if (waitResult == WAIT_OBJECT_0) {
        DWORD exitCode;
        GetExitCodeProcess(pi.hProcess, &exitCode);
        result.exitCode = static_cast<int>(exitCode);
    } else {
        result.exitCode = -1;
        result.stderr_ = "WaitForSingleObject failed";
    }

    // Read stdout
    char buffer[4096];
    DWORD bytesRead;
    while (ReadFile(hStdOutRead, buffer, sizeof(buffer) - 1, &bytesRead, nullptr)
           && bytesRead > 0) {
        buffer[bytesRead] = '\0';
        result.stdout_ += buffer;
    }

    // Read stderr
    while (ReadFile(hStdErrRead, buffer, sizeof(buffer) - 1, &bytesRead, nullptr)
           && bytesRead > 0) {
        buffer[bytesRead] = '\0';
        result.stderr_ += buffer;
    }

    // Trim trailing whitespace from stdout
    while (!result.stdout_.empty() &&
           (result.stdout_.back() == '\n' || result.stdout_.back() == '\r')) {
        result.stdout_.pop_back();
    }
    while (!result.stderr_.empty() &&
           (result.stderr_.back() == '\n' || result.stderr_.back() == '\r')) {
        result.stderr_.pop_back();
    }

    // Cleanup
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    CloseHandle(hStdOutRead);
    CloseHandle(hStdErrRead);

    return result;
}

#else  // POSIX

#include <cstdio>
#include <cstdlib>
#include <sys/wait.h>

static GitWorker::ProcessResult runProcessPosix(const std::string& commandLine) {
    GitWorker::ProcessResult result;

    FILE* pipe = popen(commandLine.c_str(), "r");
    if (!pipe) {
        result.exitCode = -1;
        result.stderr_ = "popen failed";
        return result;
    }

    char buffer[4096];
    while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
        result.stdout_ += buffer;
    }

    int status = pclose(pipe);
    if (status == -1) {
        result.exitCode = -1;
        result.stderr_ = "pclose failed";
        return result;
    }

    if (WIFEXITED(status)) {
        result.exitCode = WEXITSTATUS(status);
    } else {
        result.exitCode = -1;
        result.stderr_ = "Process did not exit normally";
    }

    // Trim trailing whitespace
    while (!result.stdout_.empty() &&
           (result.stdout_.back() == '\n' || result.stdout_.back() == '\r')) {
        result.stdout_.pop_back();
    }

    return result;
}

#endif

// ---------------------------------------------------------------------------
// GitWorker
// ---------------------------------------------------------------------------

GitWorker::GitWorker(const std::string& repoRoot)
    : repoRoot_(repoRoot) {
    if (repoRoot_.empty()) {
        throw std::invalid_argument("repoRoot must not be empty");
    }
    // Normalize path separators
    std::replace(repoRoot_.begin(), repoRoot_.end(), '/',
#ifdef _WIN32
        '\\'
#else
        '/'
#endif
    );
}

GitWorker::ProcessResult GitWorker::runCommand(
    const std::vector<std::string>& args, int timeoutSec)
{
    // Build full command: "git arg1 arg2 ..."
    std::vector<std::string> fullArgs = {"git"};
    fullArgs.insert(fullArgs.end(), args.begin(), args.end());

#ifdef _WIN32
    std::string cmdLine = buildCommandLine(fullArgs);
    return runProcessWin32(cmdLine, timeoutSec);
#else
    // Build shell-escaped command for popen
    std::ostringstream oss;
    for (size_t i = 0; i < fullArgs.size(); ++i) {
        if (i > 0) oss << " ";
        // Simple shell escaping: wrap in single quotes, escape inner quotes
        std::string arg = fullArgs[i];
        for (auto& ch : arg) {
            if (ch == '\'') {
                oss << "'\\''";
            } else {
                oss << ch;
            }
        }
    }
    // Set cwd via cd in subshell
    std::string cmd = "cd '" + repoRoot_ + "' && " + oss.str();
    return runProcessPosix(cmd);
#endif
}

std::optional<std::string> GitWorker::createWorktree(
    const std::string& objectiveId, const std::string& title)
{
    // Build slug from title
    std::string slug;
    slug.reserve(title.size());
    for (char ch : title) {
        if (std::isalnum(static_cast<unsigned char>(ch)) || ch == '-') {
            slug += static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
        } else if (ch == ' ') {
            slug += '-';
        }
    }
    if (slug.size() > 50) slug = slug.substr(0, 50);

    std::string branchName = "obj/" + objectiveId + "-" + slug;

    // Worktree path relative to repo root
    std::string worktreePath = repoRoot_ +
#ifdef _WIN32
        "\\worktrees\\" + objectiveId;
#else
        "/worktrees/" + objectiveId;
#endif

    // Create worktrees directory if needed
    std::error_code ec;
    fs::create_directories(
        repoRoot_ +
#ifdef _WIN32
            "\\worktrees",
#else
            "/worktrees",
#endif
        ec);

    // First try: create branch and worktree
    auto res = runCommand({"worktree", "add", "-b", branchName, worktreePath},
                           DEFAULT_TIMEOUT_SEC);
    if (res.exitCode == 0) {
        return branchName;
    }

    // Handle "already exists" — prune and retry
    if (res.stderr_.find("already exists") != std::string::npos ||
        res.stderr_.find("Already on") != std::string::npos) {
        // Prune stale worktrees
        runCommand({"worktree", "prune"}, 10);

        // Force remove stale worktree
        runCommand({"worktree", "remove", "--force", worktreePath}, 10);

        // Retry
        res = runCommand({"worktree", "add", "-b", branchName, worktreePath},
                          DEFAULT_TIMEOUT_SEC);
        if (res.exitCode == 0) {
            return branchName;
        }
    }

    return std::nullopt;
}

bool GitWorker::cleanupWorktree(const std::string& objectiveId) {
    std::string worktreePath = repoRoot_ +
#ifdef _WIN32
        "\\worktrees\\" + objectiveId;
#else
        "/worktrees/" + objectiveId;
#endif

    // Try without --force first
    auto res = runCommand({"worktree", "remove", worktreePath}, DEFAULT_TIMEOUT_SEC);
    if (res.exitCode == 0) return true;

    // Fallback with --force
    res = runCommand({"worktree", "remove", "--force", worktreePath},
                      DEFAULT_TIMEOUT_SEC);
    return res.exitCode == 0;
}

std::vector<std::string> GitWorker::cleanupAllStaleWorktrees() {
    std::vector<std::string> removedBranches;

    // List all worktrees in porcelain format
    auto res = runCommand({"worktree", "list", "--porcelain"}, DEFAULT_TIMEOUT_SEC);
    if (res.exitCode != 0) {
        return removedBranches;
    }

    std::string worktreesDir = repoRoot_ +
#ifdef _WIN32
        "\\worktrees";
#else
        "/worktrees";
#endif

    // Parse porcelain output
    std::istringstream stream(res.stdout_);
    std::string line;
    std::string currentPath;
    std::string currentBranch;

    auto maybeAdd = [&]() {
        if (!currentPath.empty() && !currentBranch.empty() &&
            currentBranch.substr(0, 4) == "obj/") {
            // Check if path is within our worktrees directory
            std::string normalizedPath = currentPath;
#ifdef _WIN32
            std::replace(normalizedPath.begin(), normalizedPath.end(), '\\', '/');
            std::string normalizedDir = worktreesDir;
            std::replace(normalizedDir.begin(), normalizedDir.end(), '\\', '/');
            if (normalizedPath.find(normalizedDir) != std::string::npos) {
#else
            if (currentPath.find(worktreesDir) == 0) {
#endif
                // Remove worktree
                runCommand({"worktree", "remove", "--force", currentPath},
                            DEFAULT_TIMEOUT_SEC);
                // Delete branch
                runCommand({"branch", "-D", currentBranch}, 10);
                removedBranches.push_back(currentBranch);
            }
        }
    };

    while (std::getline(stream, line)) {
        // Remove trailing \r on Windows
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }

        if (line.substr(0, 9) == "worktree ") {
            maybeAdd();
            currentPath = line.substr(9);
            currentBranch.clear();
        } else if (line.substr(0, 7) == "branch ") {
            std::string branchRef = line.substr(7);
            auto pos = branchRef.rfind("refs/heads/");
            if (pos != std::string::npos) {
                currentBranch = branchRef.substr(pos + 11);
            } else {
                currentBranch = branchRef;
            }
        }
    }
    maybeAdd();

    // Also delete obj/* branches with no associated worktree
    res = runCommand({"branch", "--list", "obj/*"}, 10);
    if (res.exitCode == 0) {
        std::istringstream branchStream(res.stdout_);
        while (std::getline(branchStream, line)) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            // Remove leading "* " for current branch marker
            if (line.size() >= 2 && line[0] == '*' && line[1] == ' ') {
                line = line.substr(2);
            }
            if (!line.empty()) {
                runCommand({"branch", "-D", line}, 10);
                removedBranches.push_back(line);
            }
        }
    }

    return removedBranches;
}

std::vector<std::string> GitWorker::detectChangedFiles(
    const std::string& branch, const std::string& baseBranch)
{
    std::vector<std::string> files;

    auto res = runCommand({"diff", "--name-only", baseBranch + ".." + branch},
                           DEFAULT_TIMEOUT_SEC);
    if (res.exitCode != 0) {
        return files;
    }

    std::istringstream stream(res.stdout_);
    std::string line;
    while (std::getline(stream, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (!line.empty()) {
            files.push_back(line);
        }
    }

    return files;
}

bool GitWorker::rollbackBranch(const std::string& branch) {
    // Stash any uncommitted changes
    runCommand({"stash", "push", "-m", "Rollback stash"}, 10);

    // Checkout the target branch first
    auto checkoutRes = runCommand({"checkout", branch}, 10);
    if (checkoutRes.exitCode != 0) {
        return false;
    }

    // Reset to HEAD to discard all changes on the branch
    auto res = runCommand({"reset", "--hard", "HEAD"}, 10);
    return res.exitCode == 0;
}

std::string GitWorker::getUserInfo() {
    // Try git config user.name
    auto nameResult = runCommand({"config", "user.name"}, 5);
    std::string name = (nameResult.exitCode == 0 && !nameResult.stdout_.empty())
        ? nameResult.stdout_ : "GAIA Orchestrator";

    // Try git config user.email
    auto emailResult = runCommand({"config", "user.email"}, 5);
    std::string email = (emailResult.exitCode == 0 && !emailResult.stdout_.empty())
        ? emailResult.stdout_ : "gaia-orchestrator@local";

    return name + " <" + email + ">";
}

} // namespace gaia
