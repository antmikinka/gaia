# GAIA V2 - User Interaction Guide

**Document Type:** User Experience Documentation
**Version:** 1.0
**Date:** March 23, 2026
**Author:** Anthony Mikinka

---

## Quick Start - 30 Seconds

```bash
# Install
pip install gaia

# Run your first pipeline
gaia-start "Build a REST API with authentication"

# That's it. GAIA handles the rest.
```

---

## Table of Contents

1. [Who Uses GAIA?](#1-who-uses-gaia)
2. [Getting Started](#2-getting-started)
3. [Commands Reference](#3-commands-reference)
4. [User Journeys](#4-user-journeys)
5. [Understanding Output](#5-understanding-output)
6. [Troubleshooting](#6-troubleshooting)
7. [Best Practices](#7-best-practices)

---

## 1. Who Uses GAIA?

### 5 User Personas

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PERSONA 1: Enterprise Dev Lead                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  WHO: Technical manager, 10+ years experience                               │
│  GOAL: Ship features faster, maintain quality                               │
│  PAIN: Team bandwidth, code review backlog                                  │
│                                                                             │
│  HOW THEY USE GAIA:                                                         │
│  ├── Template: ENTERPRISE (95/100 threshold)                               │
│  ├── Use case: Production features                                          │
│  ├── Command: `gaia-start --template=enterprise "Build X"`                 │
│  └── Output: Production-ready code, tests, docs, audit trail               │
│                                                                             │
│  WHAT THEY SEE:                                                             │
│  "Pipeline starting... Loop 1: Planning (2 min) → Development (6 min) →    │
│   Quality (4 min) → Score 82/100, looping back... Loop 2: Score 91/100,    │
│   looping back... Loop 3: Score 97/100 ✓ SHIPPED"                          │
│                                                                             │
│  TIME TO VALUE: 40-50 minutes for enterprise-grade feature                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ PERSONA 2: Startup Founder / Non-Technical                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  WHO: Entrepreneur, limited coding experience                               │
│  GOAL: Build MVP fast to validate idea                                      │
│  PAIN: Can't code, can't afford developers                                  │
│                                                                             │
│  HOW THEY USE GAIA:                                                         │
│  ├── Template: RAPID (75/100 threshold)                                    │
│  ├── Use case: Prototype, MVP                                               │
│  ├── Command: `gaia-start --template=rapid "MVP for dating app"`           │
│  └── Output: Working prototype in hours                                     │
│                                                                             │
│  WHAT THEY SEE:                                                             │
│  "Pipeline starting... Loop 1: Planning (1 min) → Development (3 min) →    │
│   Quality (2 min) → Score 72/100, looping back... Loop 2: Score 78/100     │
│   ✓ SHIPPED - Your MVP is ready!"                                          │
│                                                                             │
│  TIME TO VALUE: 15-20 minutes for working prototype                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ PERSONA 3: Senior Developer                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  WHO: Experienced developer, 5+ years                                       │
│  GOAL: Focus on complex problems, automate routine work                     │
│  PAIN: Context switching, repetitive tasks                                  │
│                                                                             │
│  HOW THEY USE GAIA:                                                         │
│  ├── Template: STANDARD (90/100 threshold)                                 │
│  ├── Use case: APIs, features, refactoring                                  │
│  ├── Command: `gaia-start "Refactor auth module to use JWT"`               │
│  └── Output: Production code with tests                                     │
│                                                                             │
│  WHAT THEY SEE:                                                             │
│  "Pipeline starting... Loop 1: Score 85/100, looping back... Loop 2:       │
│   Score 92/100 ✓ SHIPPED - 12 files created, 34 tests passing"             │
│                                                                             │
│  TIME TO VALUE: 30-40 minutes for production feature                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ PERSONA 4: Product Manager                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  WHO: Non-technical, manages roadmap                                        │
│  GOAL: Features shipped on time                                             │
│  PAIN: Development delays, scope creep                                      │
│                                                                             │
│  HOW THEY USE GAIA:                                                         │
│  ├── Template: STANDARD (via developer or directly)                        │
│  ├── Use case: Feature specifications                                       │
│  ├── Command: `gaia-start "User profile page with avatar upload"`          │
│  └── Output: spec + working implementation                                  │
│                                                                             │
│  WHAT THEY SEE:                                                             │
│  Clear progress bar, plain English status updates, ETA display             │
│  "Building user profile page... 75% complete (Loop 2/3)... 15 min left"    │
│                                                                             │
│  TIME TO VALUE: 30-40 minutes                                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ PERSONA 5: QA Engineer                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  WHO: Quality assurance professional                                        │
│  GOAL: Comprehensive test coverage                                          │
│  PAIN: Catching regressions, manual testing                                 │
│                                                                             │
│  HOW THEY USE GAIA:                                                         │
│  ├── Template: TESTING (90/100 threshold)                                  │
│  ├── Use case: Test generation                                              │
│  ├── Command: `gaia-start --template=testing "Test suite for auth module"` │
│  └── Output: Comprehensive test suite with 90%+ coverage                   │
│                                                                             │
│  WHAT THEY SEE:                                                             │
│  "Generating tests... Unit tests: 24 created, Integration tests: 8 created │
│   Coverage: 92.3% ✓ PASSED"                                                │
│                                                                             │
│  TIME TO VALUE: 20-30 minutes                                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Getting Started

### 2.1 Installation

```bash
# Option 1: pip install
pip install gaia

# Option 2: from source
git clone https://github.com/antmikinka/gaia.git
cd gaia
pip install -e .

# Verify installation
gaia --version
# Output: GAIA V2.0.0
```

### 2.2 First Run

```bash
# Simplest command
gaia-start "Build a todo API"

# What happens:
# 1. GAIA asks clarifying questions (if needed)
# 2. Selects appropriate template
# 3. Runs pipeline (planning → development → quality → decision)
# 4. Loops until quality threshold met
# 5. Ships code
```

### 2.3 What You Get

After pipeline completes, you'll have:

```
my-project/
├── src/
│   ├── routes/          # API routes
│   ├── controllers/     # Business logic
│   ├── services/        # Data operations
│   ├── models/          # Data models
│   └── middleware/      # Auth, validation, etc.
├── tests/
│   ├── unit/           # Unit tests
│   └── integration/    # Integration tests
├── docs/
│   ├── api.md         # API documentation
│   └── setup.md       # Setup guide
├── .env.example       # Environment variables
├── README.md          # Project documentation
└── CHANGELOG.md       # What was built
```

---

## 3. Commands Reference

### 3.1 Core Commands

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ gaia-start                                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DESCRIPTION: Start a new GAIA pipeline                                     │
│                                                                             │
│  USAGE:                                                                     │
│  gaia-start [OPTIONS] "YOUR GOAL"                                           │
│                                                                             │
│  OPTIONS:                                                                   │
│  ├── --template <NAME>        Pipeline template (default: STANDARD)        │
│  │                        Templates: rapid, standard, enterprise,          │
│  │                                   documentation, testing,                │
│  │                                   frontend, backend, data-ml            │
│  │                                                                         │
│  ├── --output <DIR>           Output directory (default: current dir)      │
│  │                                                                         │
│  ├── --verbose                Show detailed output                         │
│  │                                                                         │
│  ├── --dry-run                Show what would happen without running       │
│  │                                                                         │
│  └── --interactive            Ask clarifying questions                     │
│                                                                             │
│  EXAMPLES:                                                                  │
│  ├── gaia-start "Build a REST API with authentication"                     │
│  ├── gaia-start --template=enterprise "Build payment processing"           │
│  ├── gaia-start --template=rapid --interactive "MVP for my idea"           │
│  └── gaia-start --dry-run "Refactor user module"                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ gaia-status                                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DESCRIPTION: Check status of running or completed pipelines               │
│                                                                             │
│  USAGE:                                                                     │
│  gaia-status [OPTIONS] [PIPELINE_ID]                                        │
│                                                                             │
│  OPTIONS:                                                                   │
│  ├── --all                    Show all pipelines                           │
│  ├── --running                Show only running pipelines                  │
│  ├── --completed              Show only completed pipelines                │
│  └── --json                   Output as JSON                               │
│                                                                             │
│  EXAMPLES:                                                                  │
│  ├── gaia-status                                                          │
│  │   Output: Current pipeline status with progress bar                     │
│  │   "auth-api-001: Loop 2/3 - Quality phase (75% complete)"               │
│  │                                                                         │
│  ├── gaia-status --all                                                    │
│  │   Output: List of all pipelines with status                             │
│  │   "auth-api-001: SHIPPED (97/100)"                                      │
│  │   "payment-002: RUNNING (Loop 1/3)"                                     │
│  │                                                                         │
│  └── gaia-status auth-api-001                                             │
│      Output: Detailed status for specific pipeline                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ gaia-logs                                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DESCRIPTION: View pipeline execution logs                                  │
│                                                                             │
│  USAGE:                                                                     │
│  gaia-logs [OPTIONS] PIPELINE_ID                                            │
│                                                                             │
│  OPTIONS:                                                                   │
│  ├── --loop <N>               Show specific loop                           │
│  ├── --phase <NAME>           Show specific phase (planning, dev, quality) │
│  ├── --defects                Show only defect reports                     │
│  └── --json                   Output as JSON                               │
│                                                                             │
│  EXAMPLES:                                                                  │
│  ├── gaia-logs auth-api-001                                               │
│  │   Output: Full execution log                                            │
│  │                                                                         │
│  ├── gaia-logs auth-api-001 --loop 1                                      │
│  │   Output: Only Loop 1 details                                           │
│  │                                                                         │
│  └── gaia-logs auth-api-001 --defects                                     │
│      Output: Only defects found and fixes applied                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ gaia-config                                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DESCRIPTION: View or modify GAIA configuration                            │
│                                                                             │
│  USAGE:                                                                     │
│  gaia-config [OPTIONS] [KEY] [VALUE]                                        │
│                                                                             │
│  OPTIONS:                                                                   │
│  ├── --list                   Show all configuration                       │
│  ├── --reset                  Reset to defaults                            │
│  └── --validate               Validate configuration                       │
│                                                                             │
│  CONFIGURABLE SETTINGS:                                                     │
│  ├── default_template         Default template (rapid/standard/enterprise) │
│  ├── output_dir               Default output directory                     │
│  ├── quality_threshold        Override template threshold                  │
│  ├── max_loops                Maximum loops (default: unlimited)           │
│  ├── verbose                  Default verbosity                            │
│  └── api_key                  LLM API key (if using cloud)                 │
│                                                                             │
│  EXAMPLES:                                                                  │
│  ├── gaia-config --list                                                   │
│  │   Output: All configuration values                                      │
│  │                                                                         │
│  ├── gaia-config default_template enterprise                              │
│  │   Output: Set default template to enterprise                            │
│  │                                                                         │
│  └── gaia-config --reset                                                  │
│      Output: Reset all settings to defaults                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Command Quick Reference

| Command | What It Does | When to Use |
|---------|--------------|-------------|
| `gaia-start "goal"` | Start a new pipeline | Building something new |
| `gaia-start --template=rapid` | Quick prototype | MVP, experiments |
| `gaia-start --template=enterprise` | Production code | Features for users |
| `gaia-status` | Check progress | Waiting for pipeline |
| `gaia-logs <id>` | View execution details | Debugging, learning |
| `gaia-config --list` | Show settings | Checking configuration |

---

## 4. User Journeys

### 4.1 Journey 1: Enterprise Dev Lead

**Scenario:** Build user authentication API

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: Start Pipeline                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  USER TYPES:                                                                │
│  $ gaia-start --template=enterprise "Build user authentication API with    │
│     JWT tokens, password reset, and rate limiting"                          │
│                                                                             │
│  WHAT USER SEES:                                                            │
│  ╔════════════════════════════════════════════════════════════════════╗    │
│  ║  GAIA Pipeline Starting...                                         ║    │
│  ╠════════════════════════════════════════════════════════════════════╣    │
│  ║  Pipeline ID: auth-api-20260323-001                                ║    │
│  ║  Template: ENTERPRISE (95/100 threshold)                           ║    │
│  ║  Goal: Build user authentication API...                            ║    │
│  ║                                                                    ║    │
│  ║  Starting Loop 1...                                                ║    │
│  ╚════════════════════════════════════════════════════════════════════╝    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 2: Watch Progress                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  WHAT USER SEES (REAL-TIME):                                                │
│                                                                             │
│  ╔════════════════════════════════════════════════════════════════════╗    │
│  ║  LOOP 1/∞                                                           ║    │
│  ║  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   ║    │
│  ║                                                                    ║    │
│  ║  [✓] PLANNING       (2m 34s) - planning-analysis-strategist        ║    │
│  ║  [✓] DEVELOPMENT    (6m 10s) - senior-developer                    ║    │
│  ║  [▶] QUALITY        (running 2m) - quality-reviewer                ║    │
│  ║  [ ] DECISION                                                       ║    │
│  ║                                                                    ║    │
│  ║  ETA: 8 minutes remaining                                          ║    │
│  ╚════════════════════════════════════════════════════════════════════╝    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 3: Loop Back (Quality Below Threshold)                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  WHAT USER SEES:                                                            │
│                                                                             │
│  ╔════════════════════════════════════════════════════════════════════╗    │
│  ║  LOOP 1 COMPLETE                                                    ║    │
│  ╠════════════════════════════════════════════════════════════════════╣    │
│  ║  Quality Score: 82.4/100                                            ║    │
│  ║  Threshold: 95.0/100                                                ║    │
│  ║  Result: BELOW_THRESHOLD - Looping back                             ║    │
│  ║                                                                    ║    │
│  ║  Defects Found (6):                                                 ║    │
│  ║  ├── CRITICAL: Rate limiter uses memory store (SECURITY)           ║    │
│  ║  ├── CRITICAL: Missing password reset tests (TESTING)              ║    │
│  ║  ├── HIGH: No email validation (SECURITY)                          ║    │
│  ║  ├── HIGH: Generic error messages (ERROR_HANDLING)                 ║    │
│  ║  ├── MEDIUM: No rate limit tests (TESTING)                         ║    │
│  ║  └── MEDIUM: No concurrent registration handling (EDGE_CASES)      ║    │
│  ║                                                                    ║    │
│  ║  Starting Loop 2 - Focusing on: Security and testing defects       ║    │
│  ╚════════════════════════════════════════════════════════════════════╝    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ STEP 4: Pipeline Complete                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  WHAT USER SEES:                                                            │
│                                                                             │
│  ╔════════════════════════════════════════════════════════════════════╗    │
│  ║  ✓ PIPELINE COMPLETE                                                ║    │
│  ╠════════════════════════════════════════════════════════════════════╣    │
│  ║  Pipeline ID: auth-api-20260323-001                                ║    │
│  ║  Status: SHIPPED                                                   ║    │
│  ║  Final Score: 96.8/100                                             ║    │
│  ║  Total Loops: 3                                                    ║    │
│  ║  Total Time: 40m 24s                                               ║    │
│  ║                                                                    ║    │
│  ║  Deliverables:                                                     ║    │
│  ║  ├── 18 files created                                              ║    │
│  ║  ├── 1,247 lines of code                                           ║    │
│  ║  ├── 34 tests (92.3% coverage)                                     ║    │
│  ║  └── Complete documentation                                        ║    │
│  ║                                                                    ║    │
│  ║  Files:                                                            ║    │
│  ║  ├── src/routes/auth.routes.ts                                     ║    │
│  ║  ├── src/controllers/auth.controller.ts                            ║    │
│  ║  ├── src/services/auth.service.ts                                  ║    │
│  ║  ├── tests/auth.test.ts                                            ║    │
│  ║  ├── README.md                                                     ║    │
│  ║  └── [13 more files...]                                            ║    │
│  ║                                                                    ║    │
│  ║  Next Steps:                                                       ║    │
│  ║  1. Review code in ./src                                           ║    │
│  ║  2. Run tests: npm test                                            ║    │
│  ║  3. Configure .env from .env.example                               ║    │
│  ║  4. Deploy: npm run deploy                                         ║    │
│  ╚════════════════════════════════════════════════════════════════════╝    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Journey 2: Startup Founder (Non-Technical)

**Scenario:** Build MVP for a task management app

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SIMPLIFIED VIEW (NON-TECHNICAL USER)                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  USER TYPES:                                                                │
│  $ gaia-start --template=rapid "Task management app where users can        │
│     create projects, add tasks, set deadlines, and collaborate"             │
│                                                                             │
│  WHAT USER SEES (SIMPLIFIED):                                               │
│                                                                             │
│  ╔════════════════════════════════════════════════════════════════════╗    │
│  ║  Building your MVP...                                              ║    │
│  ║  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 67%                     ║    │
│  ║                                                                    ║    │
│  ║  Current: Building features (2 of 3 complete)                      ║    │
│  ║  Next: Testing and quality checks                                  ║    │
│  ║  Time remaining: ~8 minutes                                        ║    │
│  ╚════════════════════════════════════════════════════════════════════╝    │
│                                                                             │
│  [After completion]                                                         │
│                                                                             │
│  ╔════════════════════════════════════════════════════════════════════╗    │
│  ║  ✓ Your MVP is ready!                                              ║    │
│  ╠════════════════════════════════════════════════════════════════════╣    │
│  ║  What was built:                                                    ║    │
│  ║  ├── User authentication (login/signup)                            ║    │
│  ║  ├── Project creation and management                               ║    │
│  ║  ├── Task creation with deadlines                                  ║    │
│  ║  └── Basic collaboration features                                  ║    │
│  ║                                                                    ║    │
│  ║  To run your app:                                                   ║    │
│  ║  1. Open terminal in this folder                                   ║    │
│  ║  2. Type: npm install                                              ║    │
│  ║  3. Type: npm start                                                ║    │
│  ║  4. Open browser to: http://localhost:3000                         ║    │
│  ║                                                                    ║    │
│  ║  Documentation: See README.md for full instructions                ║    │
│  ╚════════════════════════════════════════════════════════════════════╝    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Understanding Output

### 5.1 Success Output

```
╔════════════════════════════════════════════════════════════════════╗
║  ✓ PIPELINE COMPLETE                                                ║
╠════════════════════════════════════════════════════════════════════╣
║  Summary                                                           ║
║  ───────────────────────────────────────────────────────────────── ║
║  Pipeline:     auth-api-20260323-001                               ║
║  Status:       SHIPPED ✓                                           ║
║  Quality:      96.8/100 (threshold: 95.0)                          ║
║  Loops:        3                                                   ║
║  Duration:     40m 24s                                             ║
║                                                                    ║
║  What Changed                                                      ║
║  ───────────────────────────────────────────────────────────────── ║
║  Files Created:   18                                               ║
║  Files Modified:  0                                                ║
║  Lines Added:     1,247                                            ║
║  Tests Created:   34                                               ║
║  Test Coverage:   92.3%                                            ║
║                                                                    ║
║  Quality Breakdown                                                 ║
║  ───────────────────────────────────────────────────────────────── ║
║  Code Quality:        94/100  ✓                                    ║
║  Requirements:        98/100  ✓                                    ║
║  Testing:             95/100  ✓                                    ║
║  Documentation:       99/100  ✓                                    ║
║  Best Practices:      98/100  ✓                                    ║
║                                                                    ║
║  Files                                                           ║
║  ───────────────────────────────────────────────────────────────── ║
║  src/                                                            ║
║  ├── routes/auth.routes.ts                                       ║
║  ├── controllers/auth.controller.ts                              ║
║  ├── services/auth.service.ts                                    ║
║  ├── middleware/auth.middleware.ts                               ║
║  ├── middleware/rateLimit.middleware.ts                          ║
║  ├── middleware/validation.middleware.ts                         ║
║  ├── models/user.model.ts                                        ║
║  ├── utils/jwt.util.ts                                           ║
║  └── utils/email.util.ts                                         ║
║  tests/                                                          ║
║  ├── auth.test.ts                                                ║
║  └── rateLimit.test.ts                                           ║
║  docs/                                                           ║
║  ├── api.md                                                      ║
║  └── security.md                                                 ║
║  root/                                                           ║
║  ├── .env.example                                                ║
║  ├── README.md                                                   ║
║  ├── CHANGELOG.md                                                ║
║  └── package.json                                                ║
║                                                                    ║
║  Next Steps                                                      ║
║  ───────────────────────────────────────────────────────────────── ║
║  1. Review the code                                                ║
║     $ code ./src                                                  ║
║                                                                    ║
║  2. Install dependencies                                           ║
║     $ npm install                                                 ║
║                                                                    ║
║  3. Configure environment                                          ║
║     $ cp .env.example .env                                        ║
║     $ # Edit .env with your values                                ║
║                                                                    ║
║  4. Run tests                                                      ║
║     $ npm test                                                    ║
║     Expected: 34 tests passing                                    ║
║                                                                    ║
║  5. Start development server                                       ║
║     $ npm run dev                                                 ║
║     Server: http://localhost:3000                                 ║
║                                                                    ║
║  6. View API documentation                                         ║
║     $ open docs/api.md                                            ║
║                                                                    ║
║  Full execution log: logs/auth-api-20260323-001.log               ║
╚════════════════════════════════════════════════════════════════════╝
```

### 5.2 Progress Output (During Execution)

```
╔════════════════════════════════════════════════════════════════════╗
║  GAIA Pipeline - Loop 2/∞                                          ║
║  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 67%                              ║
╠════════════════════════════════════════════════════════════════════╣
║  Current Phase: DEVELOPMENT                                        ║
║  Agent: senior-developer                                           ║
║  Working on: Implementing security fixes (DEF-001, DEF-003)        ║
║  Progress: [████████████░░░░░░░░░░░░] 45%                         ║
║  ETA: 4 minutes remaining                                          ║
╠════════════════════════════════════════════════════════════════════╣
║  Loop History                                                      ║
║  ───────────────────────────────────────────────────────────────── ║
║  Loop 1: Score 82.4/100 - Defects: 6 (6 fixed)                     ║
║  Loop 2: IN PROGRESS                                               ║
╚════════════════════════════════════════════════════════════════════╝

[Real-time updates appear here as work progresses]
```

### 5.3 Error Output

```
╔════════════════════════════════════════════════════════════════════╗
║  ⚠ PIPELINE PAUSED                                                 ║
╠════════════════════════════════════════════════════════════════════╣
║  Error: Missing API Key                                            ║
║                                                                    ║
║  GAIA needs an API key to access the AI model.                     ║
║                                                                    ║
║  To fix this, choose ONE option:                                   ║
║                                                                    ║
║  Option 1: Set environment variable                                ║
║  $ export ANTHROPIC_API_KEY=your-key-here                          ║
║                                                                    ║
║  Option 2: Configure in GAIA                                       ║
║  $ gaia-config api_key your-key-here                               ║
║                                                                    ║
║  Option 3: Use local model (requires Ollama)                       ║
║  $ gaia-start --local "your goal"                                  ║
║                                                                    ║
║  Need help? Run: gaia-start --help                                 ║
║  Documentation: https://gaia.dev/docs/setup                        ║
╚════════════════════════════════════════════════════════════════════╝
```

### 5.4 Defect Report Output

```
╔════════════════════════════════════════════════════════════════════╗
║  Defect Report - Loop 1                                            ║
╠════════════════════════════════════════════════════════════════════╣
║  CRITICAL (Must Fix)                                               ║
║  ───────────────────────────────────────────────────────────────── ║
║                                                                    ║
║  DEF-001: Rate limiter uses in-memory store                        ║
║  Location: src/middleware/rateLimit.middleware.ts:23               ║
║  Category: SECURITY                                                ║
║  Issue: MemoryStore doesn't work in production                     ║
║  Fix: Use RedisStore with rate-limit-redis package                 ║
║                                                                    ║
║  DEF-002: Missing password reset tests                             ║
║  Location: tests/auth.test.ts                                      ║
║  Category: TESTING                                                 ║
║  Issue: No tests for POST /reset-password endpoint                 ║
║  Fix: Add tests for valid email, invalid token, rate limiting      ║
║                                                                    ║
║  HIGH (Should Fix)                                                 ║
║  ───────────────────────────────────────────────────────────────── ║
║                                                                    ║
║  DEF-003: No email validation                                      ║
║  Location: src/controllers/auth.controller.ts:45                   ║
║  Category: SECURITY                                                ║
║  Issue: Email passed directly to database without validation       ║
║  Fix: Add express-validator middleware                             ║
║                                                                    ║
║  DEF-004: Generic error messages                                   ║
║  Location: src/services/auth.service.ts:67                         ║
║  Category: ERROR_HANDLING                                          ║
║  Issue: Database errors exposed to API consumer                    ║
║  Fix: Implement structured error responses                         ║
║                                                                    ║
║  MEDIUM (Recommended)                                              ║
║  ───────────────────────────────────────────────────────────────── ║
║                                                                    ║
║  DEF-005: No rate limit integration tests                          ║
║  DEF-006: No concurrent registration handling                      ║
║                                                                    ║
║  ════════════════════════════════════════════════════════════════ ║
║  Summary: 6 defects found (2 critical, 2 high, 2 medium)           ║
║  Action: Looping back to fix defects                               ║
╚════════════════════════════════════════════════════════════════════╝
```

---

## 6. Troubleshooting

### 6.1 Common Issues

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ISSUE: "Pipeline stuck on Loop 1"                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  LIKELY CAUSE: Quality threshold too high for initial implementation       │
│                                                                             │
│  SOLUTIONS:                                                                 │
│  ├── Wait - Loop 2 should address defects                                  │
│  ├── Check logs: gaia-logs <pipeline-id>                                   │
│  └── Try lower threshold: gaia-start --threshold=85 "goal"                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ISSUE: "API key error"                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  CAUSE: Missing or invalid API key                                         │
│                                                                             │
│  SOLUTIONS:                                                                 │
│  ├── Set env: export ANTHROPIC_API_KEY=sk-...                              │
│  ├── Or configure: gaia-config api_key sk-...                              │
│  └── Or use local: gaia-start --local "goal"                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ISSUE: "Tests failing after pipeline completes"                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  CAUSE: Environment not configured correctly                                 │
│                                                                             │
│  SOLUTIONS:                                                                 │
│  ├── Copy example: cp .env.example .env                                    │
│  ├── Edit .env with correct values                                         │
│  ├── Install deps: npm install                                             │
│  └── Re-run tests: npm test                                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ ISSUE: "Pipeline runs but no files created"                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  CAUSE: Output directory not writable or wrong path                        │
│                                                                             │
│  SOLUTIONS:                                                                 │
│  ├── Check permissions: ls -la                                             │
│  ├── Specify output: gaia-start --output ./my-project "goal"               │
│  └── Check disk space: df -h                                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Getting Help

```bash
# View all commands
gaia --help

# View command-specific help
gaia-start --help

# View execution logs
gaia-logs <pipeline-id>

# Check status
gaia-status

# Report bug
gaia bug-report "Description of issue"
```

---

## 7. Best Practices

### 7.1 Writing Good Goals

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ BAD GOALS (Too Vague)                                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ❌ "Build an app"                                                          │
│  ❌ "Make something cool"                                                   │
│  ❌ "Fix the code"                                                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ GOOD GOALS (Specific, Actionable)                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ✅ "Build a REST API for user authentication with JWT tokens"              │
│  ✅ "Create a React component for user profile with avatar upload"          │
│  ✅ "Add unit tests for the payment processing module"                      │
│  ✅ "Refactor the database layer to use PostgreSQL"                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ GREAT GOALS (Include Constraints)                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ✅ "Build REST API with JWT auth, rate limiting (100/hour),                │
│      PostgreSQL database, 90% test coverage"                                │
│                                                                             │
│  ✅ "Create React dashboard with real-time charts using D3,                 │
│      dark mode support, responsive design"                                  │
│                                                                             │
│  ✅ "Migrate user authentication from sessions to JWT tokens,                │
│      maintain backward compatibility, zero downtime deployment"             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Choosing Templates

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ TEMPLATE SELECTION GUIDE                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  USE RAPID (75/100) WHEN:                                                   │
│  ├── You need a quick prototype                                             │
│  ├── Testing an idea                                                        │
│  ├── Building MVP for validation                                            │
│  └── Speed is more important than quality                                   │
│                                                                             │
│  USE STANDARD (90/100) WHEN:                                                │
│  ├── Building production features                                           │
│  ├── Default choice for most work                                           │
│  ├── Need good balance of speed and quality                                 │
│  └── Standard business requirements                                         │
│                                                                             │
│  USE ENTERPRISE (95/100) WHEN:                                              │
│  ├── Mission-critical features                                              │
│  ├── Security-sensitive (auth, payments)                                    │
│  ├── Compliance required (HIPAA, SOC2)                                      │
│  └── High-traffic systems                                                   │
│                                                                             │
│  USE DOCUMENTATION (85/100) WHEN:                                           │
│  ├── Generating API documentation                                           │
│  ├── Writing user guides                                                    │
│  └── Creating technical specs                                               │
│                                                                             │
│  USE TESTING (90/100) WHEN:                                                 │
│  ├── Adding test coverage                                                   │
│  ├── Writing integration tests                                              │
│  └── Quality assurance tasks                                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.3 Workflow Tips

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ TIP 1: Use Interactive Mode for Complex Tasks                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  $ gaia-start --interactive "Build e-commerce platform"                    │
│                                                                             │
│  GAIA will ask clarifying questions:                                        │
│  - What payment processors to support?                                      │
│  - Need inventory management?                                               │
│  - User roles (admin, customer, vendor)?                                    │
│  - Preferred tech stack?                                                    │
│                                                                             │
│  This produces better results for complex projects.                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ TIP 2: Review Defects Before Each Loop                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  After each loop, GAIA shows defects found. Review them to understand:      │
│  - What needs improvement                                                   │
│  - Why quality score was below threshold                                    │
│  - How the next loop will improve things                                    │
│                                                                             │
│  $ gaia-logs <pipeline-id> --defects                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ TIP 3: Use Dry Run for Expensive Operations                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Before running a large pipeline, use dry-run to see what will happen:      │
│                                                                             │
│  $ gaia-start --dry-run "Build complete e-commerce platform"               │
│                                                                             │
│  Output shows:                                                              │
│  - Estimated duration                                                       │
│  - Expected files                                                           │
│  - API calls required                                                       │
│  - Estimated cost (if using paid API)                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ TIP 4: Save Configurations for Common Tasks                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Create config files for recurring pipeline types:                          │
│                                                                             │
│  # api-project.yaml                                                         │
│  template: standard                                                         │
│  output: ./api-projects                                                     │
│  quality_threshold: 0.90                                                    │
│  agents:                                                                    │
│    - api-designer                                                           │
│    - backend-specialist                                                     │
│                                                                             │
│  $ gaia-start --config api-project.yaml "New user API"                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ GAIA QUICK REFERENCE                                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  BASIC COMMANDS                                                             │
│  ─────────────────                                                          │
│  gaia-start "goal"                    Start pipeline                        │
│  gaia-start --template=rapid "goal"   Quick prototype                       │
│  gaia-start --template=enterprise     Production code                       │
│  gaia-status                          Check progress                        │
│  gaia-logs <id>                       View logs                             │
│  gaia-config --list                   Show settings                         │
│                                                                             │
│  TEMPLATES                                                                  │
│  ───────────────                                                            │
│  rapid         75/100    Prototype, MVP (15-20 min)                         │
│  standard      90/100    Production features (30-40 min)                    │
│  enterprise    95/100    Mission-critical (40-60 min)                       │
│  testing       90/100    Test generation (20-30 min)                        │
│  docs          85/100    Documentation (15-25 min)                          │
│                                                                             │
│  OUTPUT FILES                                                               │
│  ─────────────                                                              │
│  src/           Source code                                                  │
│  tests/         Test suite                                                   │
│  docs/          Documentation                                                │
│  README.md      Setup instructions                                           │
│  .env.example   Environment template                                         │
│                                                                             │
│  QUALITY THRESHOLDS                                                         │
│  ──────────────────                                                         │
│  75/100    MVP quality - core features work                                 │
│  85/100    Good quality - minor issues OK                                   │
│  90/100    Production quality - ready for users                             │
│  95/100    Enterprise quality - compliance ready                            │
│                                                                             │
│  GETTING HELP                                                               │
│  ───────────────                                                            │
│  gaia --help                          All commands                          │
│  gaia-start --help                    Start command help                    │
│  gaia-logs <id> --defects             View defects only                     │
│  gaia bug-report "issue"              Report a problem                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Conclusion

GAIA is designed to be **simple for beginners, powerful for experts**:

- **Beginners**: Use `gaia-start "goal"` and get production code
- **Experts**: Configure templates, hooks, and custom agents

The key insight: **GAIA handles the complexity so you don't have to.**

### What Users Get

| User Type | Time Saved | Quality Improvement | Outcome |
|-----------|------------|---------------------|---------|
| Enterprise Dev | 12x faster | Consistent 95/100 | Compliance-ready code |
| Startup Founder | Days → minutes | Working MVP | Validated idea |
| Senior Developer | 10x output | Focus on hard problems | More impact |
| Product Manager | 2 weeks → 2 days | Predictable delivery | Happy customers |
| QA Engineer | Hours → minutes | 90%+ coverage | Confidence |

**Remember:** The goal is not to replace humans - it's to amplify human capability.
