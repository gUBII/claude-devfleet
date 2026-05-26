from pydantic import BaseModel, Field
from typing import Literal, Optional, List


class ProjectCreate(BaseModel):
    name: str
    path: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None
    description: Optional[str] = None


# ── Dispatch Configuration ──
# Controls how the Claude CLI agent is spawned per mission

TOOL_PRESETS = {
    "full":         ["Read", "Write", "Edit", "Bash", "Grep", "Glob", "WebFetch", "WebSearch"],
    "implement":    ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
    "review":       ["Read", "Grep", "Glob", "Bash(git diff *)", "Bash(git log *)", "Bash(git blame *)"],
    "security":     ["Read", "Grep", "Glob", "Bash(git diff *)", "Bash(grep *)"],
    "test":         ["Read", "Write", "Edit", "Bash(npm test *)", "Bash(pytest *)", "Bash(cargo test *)", "Bash(npx playwright *)", "Grep", "Glob"],
    "e2e":          ["Read", "Bash(npx playwright *)", "Bash(curl *)", "Bash(npm run *)", "Grep", "Glob"],
    "qa":           ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
    "explore":      ["Read", "Grep", "Glob", "Bash(git *)", "Bash(ls *)", "Bash(find *)"],
    "fix":          ["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
    "orchestrator": ["Read", "Grep", "Glob", "WebFetch", "WebSearch"],
    "researcher":   ["Read", "Grep", "Glob", "WebFetch", "WebSearch"],
}

_GLOBAL_ECC = "~/.claude"  # injected into every agent via add_dirs

# ── Lane definitions ──────────────────────────────────────────────────────────
# Scheduling dimension — independent of mission_type tool presets.
# Each lane has its own concurrency cap, default model, tools, and role prompt.
# Total concurrent agents = sum of all max_agents values.
LANE_DEFAULTS: dict[str, dict] = {

    # ── Orchestrators (3 slots) — plan, coordinate, decompose ────────────────
    "orchestrator": {
        "max_agents": 3,
        "default_model": "claude-opus-4-7",
        "tool_preset": "orchestrator",
        "append_prompt": (
            # ── ROLE ────────────────────────────────────────────────────────────
            "## ROLE — DevFleet Orchestrator\n"
            "You are the planning and coordination layer of the DevFleet. "
            "You do NOT write production code directly. Your output is a DAG of sub-missions "
            "dispatched to specialist lanes. Every decision you make shapes what other "
            "agent slots do next. Think in parallel tracks, gate every track, and never "
            "guess on architecture — call the advisor tool at every real fork.\n\n"

            # ── INFRA CONTEXT ────────────────────────────────────────────────────
            "## INFRASTRUCTURE CONTEXT\n"
            "Fleet: 18 total slots across 10 lanes — "
            "orchestrator×3 · coder×3 · reviewer×2 · security×1 · tester×2 · "
            "e2e×2 · qa×1 · dynamic_tester×1 · researcher×2 · explorer×1.\n"
            "Backend: FastAPI + SQLite (uvicorn --reload). Frontend: React 19 + Vite.\n"
            "Each project has its own repo, stack, branch model, and commit convention. "
            "Discover the project's rules from its own files (`docs/CI_CD_PIPELINE.md`, "
            "`AGENTS.md`, `.devfleet/PROTOCOL.md`, `CONTRIBUTING.md`, or `CLAUDE.md`) — "
            "never assume defaults from another project. If no protocol doc exists, infer "
            "from `git log --oneline -20` and `git symbolic-ref refs/remotes/origin/HEAD`, "
            "then surface a `DECISION NEEDED` line asking the owner to add one.\n"
            "Commit attribution: NEVER add Co-Authored-By, Generated-By, or any AI-tool "
            "trailer. Match whatever owner-prefix or Conventional Commits style the repo "
            "history already uses.\n\n"

            # ── MANDATORY STARTUP SEQUENCE ───────────────────────────────────────
            "## MANDATORY STARTUP SEQUENCE (always run in this order)\n"
            "1. `mcp__devfleet-context__get_fleet_shape` — live slot counts per lane. "
            "Shape your DAG to 'free' counts, not assumed defaults.\n"
            "2. `mcp__devfleet-tools__list_project_missions` — see existing work; "
            "never duplicate a mission that is already pending or running.\n"
            "3. Read the project's protocol doc + `CLAUDE.md` (if present) and check "
            "`git log --oneline -10` before decomposing — understand what just shipped "
            "and how this repo wants work delivered.\n\n"

            # ── HOTSPOT FILES RULE ───────────────────────────────────────────────
            "## HOTSPOT FILES RULE\n"
            "Hotspot files (schema.prisma, package.json, db.py, migration files, "
            "route index files, any shared config) may only be edited by ONE mission per batch. "
            "Assign ownership explicitly in each sub-mission prompt: "
            "'You are the sole editor of <file> in this batch.' "
            "Non-owning missions must introduce new files that get imported — not touch the hotspot.\n\n"

            # ── QUALITY GATES ────────────────────────────────────────────────────
            "## QUALITY GATES — required in every DAG\n"
            "Every coder mission must have downstream gate missions. Gate assignments by work type:\n"
            "• API / backend changes → tester mission (unit + integration tests)\n"
            "• UI / React / React Native → e2e mission (Playwright or Detox)\n"
            "• Async, polling, streaming logic → dynamic_tester mission\n"
            "• Auth, permissions, payments, secrets → security mission (mandatory, not optional)\n"
            "• PR ready to merge → reviewer mission (reads diff, checks conventions, approves)\n"
            "• Final release gate → qa mission (smoke test across all changed surfaces)\n\n"
            "DAG pattern: coder → [reviewer + tester] → next_coder. "
            "Never chain two coders on shared files without a reviewer gate between them. "
            "If capacity is full in a gate lane, set auto_dispatch=true and depends_on — "
            "the mission watcher will dispatch when a slot opens.\n\n"

            # ── FAILURE & RECOVERY ───────────────────────────────────────────────
            "## FAILURE & RECOVERY RULES\n"
            "If a sub-mission is interrupted or failed: read its last report via "
            "`mcp__devfleet-context__read_past_reports`, then create a resume mission "
            "(lane: coder, depends_on: [], detailed_prompt references the interrupted session ID). "
            "Do NOT re-run the full feature from scratch — resume from last checkpoint.\n"
            "If a reviewer returns BLOCK (critical issue): create a fix mission in coder lane "
            "that depends_on the reviewer, then a new reviewer that depends_on the fix.\n\n"

            # ── PLANNING TOOLS ───────────────────────────────────────────────────
            "## PLANNING TOOLS\n"
            "Use /prp-plan to produce phased implementation plans before dispatching. "
            "Use /prompt-optimizer to sharpen each sub-mission prompt before creation. "
            "Use the advisor tool at architectural forks — especially for: DB schema changes, "
            "auth changes, monorepo dependency upgrades, and anything touching shared infra."
        ),
        "color": "#b44ff7",
        "icon": "🧠",
    },

    # ── Coders (3 slots) — land features ─────────────────────────────────────
    "coder": {
        "max_agents": 3,
        "default_model": "claude-sonnet-4-6",
        "tool_preset": "implement",
        "append_prompt": (
            "You are a DevFleet **Coder**. Your role is implementation.\n"
            "Follow the /prp-implement plan exactly. Write atomic commits. Use /tdd.\n"
            "Context limit: when approaching 199k tokens, run /compact immediately.\n\n"
            "PROJECT CI/CD PROTOCOL — read the project's protocol doc FIRST:\n"
            "Look for `docs/CI_CD_PIPELINE.md`, `AGENTS.md`, `.devfleet/PROTOCOL.md`,\n"
            "`CONTRIBUTING.md`, or `CLAUDE.md`. That file owns branch, rebase, commit,\n"
            "and validation rules. If none exists, infer base branch via\n"
            "`git symbolic-ref refs/remotes/origin/HEAD` and commit style via\n"
            "`git log --oneline -20`, then flag `DECISION NEEDED` for the owner.\n\n"
            "REBASE BEFORE YOU START AND BEFORE YOU PUSH:\n"
            "  git fetch origin && git rebase origin/<base-branch>\n"
            "Run this twice — once before touching any file, once just before committing.\n"
            "If rebase conflicts: git rebase --abort, report conflict in errors_encountered, stop.\n"
            "Never force-push. Never self-merge on conflict.\n\n"
            "VALIDATION ORDER:\n"
            "1. Commit your code first, then typecheck.\n"
            "2. Scope typecheck to the package you modified — never the full monorepo.\n"
            "   In pnpm workspaces: `pnpm --filter <package-name> exec tsc --noEmit`\n"
            "3. If your platform has `timeout`/`gtimeout`, wrap long-running commands\n"
            "   (e.g. `timeout 300 …`). Otherwise watch the wall clock and kill at 5 min.\n"
            "4. If validation stalls, commit anyway, report the timeout, stop cleanly.\n\n"
            "COMMIT FORMAT (non-negotiable):\n"
            "Match the prefix style the repo already uses. Confirm via `git log --oneline -20`.\n"
            "Many repos here use an owner-prefix convention: {Owner}feat/fix/update/refactor/test/chore(scope):.\n"
            "Body must describe what changed — function names, endpoints, behaviour. No vague messages.\n"
            "ZERO attribution trailers — no Co-Authored-By, no Claude, no AI tool mentions. Ever.\n\n"
            "QUALITY GATE — MANDATORY AFTER EVERY IMPLEMENTATION:\n"
            "When your implementation is committed and ready, call `mcp__devfleet-tools__create_sub_mission` "
            "to spawn quality-gate sub-missions. Do this BEFORE calling submit_report.\n"
            "Rules:\n"
            "  1. ALWAYS spawn a reviewer sub-mission:\n"
            "     title: 'REV-[your mission title]'\n"
            "     mission_type: 'review', lane: 'reviewer'\n"
            "     depends_on: [your current mission id — get it from mcp__devfleet-context__get_mission_context]\n"
            "     auto_dispatch: true\n"
            "  2. SPAWN a tester sub-mission based on what you built:\n"
            "     - UI components with user interaction → lane: 'e2e', mission_type: 'e2e'\n"
            "     - Polling/real-time/async state → lane: 'dynamic_tester', mission_type: 'dynamic_test'\n"
            "     - API endpoints + business logic → lane: 'tester', mission_type: 'test'\n"
            "     - Pure refactors with no new behaviour → skip tester, reviewer only\n"
            "  3. Use wait_for_me=false — sub-missions run after you finish, not blocking you.\n"
            "  4. Write the reviewer prompt to focus on YOUR specific code — not generic boilerplate.\n"
            "     Include: what files changed, what the key logic is, what edge cases to check.\n"
            "This is how the fleet self-improves. Every coder spawns its own quality gates."
        ),
        "color": "#4f8ef7",
        "icon": "🛠",
    },

    # ── Code Reviewer (2 slots) ───────────────────────────────────────────────
    "reviewer": {
        "max_agents": 2,
        "default_model": "claude-sonnet-4-6",
        "tool_preset": "review",
        "append_prompt": (
            "You are a DevFleet **Code Reviewer**. Read-only analysis only.\n"
            "Check: naming, patterns, error handling, test coverage, git hygiene.\n"
            "Score each dimension 0-10. Fail anything below 7. Be specific with line numbers.\n"
            "Use the code-reviewer ECC skill for systematic review.\n\n"
            "CRITICAL — multi-agent verification rule: NEVER re-read a file to confirm your own "
            "change looks correct. `Read` returns combined working-tree state including patches "
            "from other agents that may have already fixed the bug you're reviewing. "
            "To verify a specific commit, use: `git diff <baseline>..HEAD -- <file>` where "
            "<baseline> is the parent mission's commit SHA if available, or "
            "`git merge-base HEAD origin/main` as a fallback. "
            "Use `git show <commit-sha> -- <file>` to inspect what a commit actually wrote in "
            "isolation. When two reviewers work overlapping files, each must diff against their "
            "own baseline, not against HEAD."
        ),
        "color": "#f7a84f",
        "icon": "🔍",
    },

    # ── Security Reviewer (1 slot) ────────────────────────────────────────────
    "security": {
        "max_agents": 1,
        "default_model": "claude-sonnet-4-6",
        "tool_preset": "security",
        "append_prompt": (
            "You are a DevFleet **Security Reviewer**. Hunt vulnerabilities only.\n"
            "Check: OWASP Top 10, hardcoded secrets, injection, auth bypasses, unsafe deps.\n"
            "Use the security-reviewer ECC skill. Flag CRITICAL/HIGH/MEDIUM/LOW.\n"
            "BLOCK merge on any CRITICAL finding."
        ),
        "color": "#f74f4f",
        "icon": "🔒",
    },

    # ── Unit/Integration Tester (2 slots) ─────────────────────────────────────
    "tester": {
        "max_agents": 2,
        "default_model": "claude-haiku-4-5-20251001",
        "tool_preset": "test",
        "append_prompt": (
            "You are a DevFleet **Tester**. Write and run unit + integration tests.\n"
            "Minimum 80% coverage. Use /tdd — write test first, fail, implement, pass.\n"
            "Use the python-testing or tdd-workflow ECC skill.\n"
            "All tests must pass before submitting report."
        ),
        "color": "#4fc97b",
        "icon": "🧪",
    },

    # ── E2E Verifier (2 slots) ────────────────────────────────────────────────
    "e2e": {
        "max_agents": 2,
        "default_model": "claude-sonnet-4-6",
        "tool_preset": "e2e",
        "append_prompt": (
            "You are a DevFleet **E2E Verifier**. Run end-to-end and acceptance tests.\n"
            "Use Playwright for web, curl for APIs, runtime execution for CLI tools.\n"
            "Use the e2e-testing ECC skill. Capture screenshots on failure.\n"
            "Verify the golden path AND 3 edge cases minimum."
        ),
        "color": "#4ff7e8",
        "icon": "🌐",
    },

    # ── QA Agent (1 slot) ─────────────────────────────────────────────────────
    "qa": {
        "max_agents": 1,
        "default_model": "claude-sonnet-4-6",
        "tool_preset": "qa",
        "append_prompt": (
            "You are a DevFleet **QA Agent**. Holistic quality gatekeeper.\n"
            "Check: UX flows, accessibility, performance budgets, error messaging, docs accuracy.\n"
            "Run /verify. Score release readiness 0-100. Below 80 = not shippable."
        ),
        "color": "#f7d44f",
        "icon": "✅",
    },

    # ── Dynamic Tester (1 slot) ───────────────────────────────────────────────
    "dynamic_tester": {
        "max_agents": 1,
        "default_model": "claude-sonnet-4-6",
        "tool_preset": "test",
        "append_prompt": (
            "You are a DevFleet **Dynamic Tester**. Runtime and chaos testing.\n"
            "Inject failures: bad inputs, race conditions, resource exhaustion, network timeouts.\n"
            "Verify graceful degradation and error recovery in all cases.\n"
            "Use the ai-regression-testing ECC skill."
        ),
        "color": "#f7974f",
        "icon": "⚡",
    },

    # ── Researcher (2 slots) — feasibility + sustainability ───────────────────
    "researcher": {
        "max_agents": 2,
        "default_model": "claude-opus-4-7",
        "tool_preset": "researcher",
        "append_prompt": (
            "You are a DevFleet **Researcher**. Feasibility and sustainability analysis.\n"
            "Investigate: library alternatives, dependency risks, license compliance, long-term maintenance cost.\n"
            "Use the search-first and market-research ECC skills.\n"
            "Output: recommendation with evidence and risk rating."
        ),
        "color": "#a0a0f7",
        "icon": "🔬",
    },

    # ── Explorer (1 slot) — codebase discovery ────────────────────────────────
    "explorer": {
        "max_agents": 1,
        "default_model": "claude-sonnet-4-6",
        "tool_preset": "explore",
        "append_prompt": (
            "You are a DevFleet **Explorer**. Map the codebase and surface unknowns.\n"
            "Build dependency graphs, find dead code, identify coupling hotspots.\n"
            "Use the code-explorer ECC agent. Output structured findings for orchestrators."
        ),
        "color": "#f74f6b",
        "icon": "🔭",
    },
}

# Mapping from mission_type → default lane
MISSION_TYPE_TO_LANE: dict[str, str] = {
    "implement":    "coder",
    "fix":          "coder",
    "full":         "coder",
    "review":       "reviewer",
    "security":     "security",
    "test":         "tester",
    "e2e":          "e2e",
    "qa":           "qa",
    "dynamic_test": "dynamic_tester",
    "explore":      "explorer",
    "planner":      "orchestrator",
    "orchestrator": "orchestrator",
    "research":     "researcher",
}

MODEL_CHOICES = ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]


class DispatchOptions(BaseModel):
    """Per-dispatch overrides for Claude CLI invocation."""
    model: Optional[str] = None              # claude-opus-4-7, claude-sonnet-4-6, claude-haiku-4-5-20251001
    max_turns: Optional[int] = None          # --max-turns N
    max_budget_usd: Optional[float] = None   # --max-budget-usd N
    allowed_tools: Optional[List[str]] = None # --allowedTools list (or preset name)
    tool_preset: Optional[str] = None        # key into TOOL_PRESETS
    append_system_prompt: Optional[str] = None  # --append-system-prompt
    fork_session: bool = False               # --fork-session (for branching from resume)
    context_mode: bool = False               # attach context-mode MCP server for context savings + session continuity
    lane: Optional[str] = None               # scheduling lane override (coder/reviewer/tester/planner/explorer)


class MissionCreate(BaseModel):
    project_id: str
    title: str
    detailed_prompt: str
    acceptance_criteria: str = ""
    priority: int = 0
    tags: List[str] = []
    # Default dispatch config stored on mission
    model: str = "claude-sonnet-4-6"
    max_turns: Optional[int] = None
    max_budget_usd: Optional[float] = None
    allowed_tools: Optional[str] = None      # JSON string or preset name
    mission_type: str = "implement"          # implement, review, test, explore, fix
    lane: Optional[str] = None               # scheduling lane; derived from mission_type if absent
    # Phase 3: multi-agent, dependencies, scheduling
    parent_mission_id: Optional[str] = None  # parent mission for sub-missions
    depends_on: List[str] = []               # mission IDs that must complete first
    auto_dispatch: bool = False              # auto-dispatch when dependencies met
    schedule_cron: Optional[str] = None      # cron expression for recurring missions
    status: Optional[str] = None             # Watcher picks up status="draft"; "pending" / other values are inert until manually advanced


class MissionUpdate(BaseModel):
    title: Optional[str] = None
    detailed_prompt: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = None
    tags: Optional[List[str]] = None
    model: Optional[str] = None
    max_turns: Optional[int] = None
    max_budget_usd: Optional[float] = None
    allowed_tools: Optional[str] = None
    mission_type: Optional[str] = None
    lane: Optional[str] = None
    parent_mission_id: Optional[str] = None
    depends_on: Optional[List[str]] = None
    auto_dispatch: Optional[bool] = None
    schedule_cron: Optional[str] = None
    schedule_enabled: Optional[bool] = None


# ── Lane Configuration ──

class LaneCreate(BaseModel):
    name: str
    max_agents: int = 1
    default_model: str = "claude-sonnet-4-6"
    tool_preset: str = "implement"
    append_prompt: str = ""
    color: str = "#888888"
    icon: str = ""


class LaneUpdate(BaseModel):
    max_agents: Optional[int] = None
    default_model: Optional[str] = None
    tool_preset: Optional[str] = None
    append_prompt: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    enabled: Optional[bool] = None


class ServiceCreate(BaseModel):
    project_id: str
    name: str
    url: str
    group_name: str = "Default"
    description: str = ""
    check_interval: int = 30
    timeout_ms: int = 5000
    expected_status: int = 200


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    group_name: Optional[str] = None
    description: Optional[str] = None
    check_interval: Optional[int] = None
    timeout_ms: Optional[int] = None
    expected_status: Optional[int] = None
    enabled: Optional[bool] = None


class IncidentCreate(BaseModel):
    service_id: Optional[str] = None
    project_id: str
    title: str
    description: str = ""
    severity: str = "minor"


class IncidentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    severity: Optional[str] = None
    resolved_at: Optional[str] = None


# ── MCP Server Configuration ──

class McpServerCreate(BaseModel):
    """Configure an MCP server for a project — agents get access to its tools."""
    server_name: str                          # e.g. "github", "brave-search", "memory"
    server_type: str = "stdio"                # stdio, sse, http
    config: dict = {}                         # command, args, env, url, headers etc.


# ── Auth Models ──────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: str
    password: str
    invite_token: str

class UserLogin(BaseModel):
    email: str
    password: str

class UserOut(BaseModel):
    id: str
    email: str
    role: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── System Models ────────────────────────────────────────────────────────────

class CeilingUpdate(BaseModel):
    """Global agent concurrency ceiling update."""
    max_agents: int


# ── HITL + Project Bot ───────────────────────────────────────────────────────

class HitlAskRequest(BaseModel):
    question: str
    options: list[str] = []

class HitlReply(BaseModel):
    reply: str

class ProjectChatRequest(BaseModel):
    message: str
    planner_mode: bool = False
    # New: explicit persona override. Slash commands in the message (/haiku,
    # /sonnet, /opus) take precedence over this field. planner_mode=True still
    # maps to architect persona for backward compatibility.
    force_persona: Optional[Literal["researcher", "git_operator", "architect"]] = None


# ── Persona chat — RBAC + persona registry ──────────────────────────────────
#
# Three personas, three models. The router (backend/chat_router.py) classifies
# each chat message into one persona; permission checks gate which intents the
# user can actually execute. CHAT_PERSONAS is the single source of truth so
# Fleet Config can mutate models per persona without scattering string literals.

ChatPersona = Literal["researcher", "git_operator", "architect"]

# Permission names used in user_permissions.permission. Implicit `git.read`
# is granted to every authenticated user (no row needed) — the literal isn't
# in this list because we never check it.
CHAT_PERMISSIONS: list[str] = [
    "git.commit",
    "git.push",
    "git.pr.create",
    "git.pr.merge",
    "fleet.dispatch",
    "fleet.config",
    "chat.compact",
]

# Coarse intents the router emits. Each maps to either None (no special
# permission beyond persona baseline) or a CHAT_PERMISSIONS entry.
INTENT_PERMISSIONS: dict[str, Optional[str]] = {
    "read":         None,
    "plan":         None,
    "quick_patch":  None,
    "commit":       "git.commit",
    "push":         "git.push",
    "pr_create":    "git.pr.create",
    "pr_merge":     "git.pr.merge",
    "dispatch":     "fleet.dispatch",
    "git_other":    "git.commit",  # any other git_operator turn — minimum bar
}

# Verbs that flip a git_operator turn into confirm-required mode. Detected by
# substring match (case-insensitive) on the operator's message. Erring on the
# side of confirming an extra read-only command is much cheaper than missing
# a destructive one.
DESTRUCTIVE_VERBS: list[str] = [
    "merge", "push", "force-push", "force push",
    "delete branch", "delete remote",
    "reset --hard", "rm ", "rm -",
    "drop table", "truncate",
    "revert",
]

# Per-persona policy. `model`, `allowed_tools`, and `permission_mode` are
# passed straight to claude_code_sdk.ClaudeCodeOptions. `requires_confirm` is
# the persona-wide flag; the router still consults DESTRUCTIVE_VERBS before
# actually pausing for confirmation.
CHAT_PERSONAS: dict[str, dict] = {
    "researcher": {
        "model": "claude-haiku-4-5-20251001",
        "allowed_tools": ["Read", "Glob", "Grep"],
        "permission_mode": "default",
        "max_turns": 4,
        "requires_confirm": False,
        "baseline_permission": None,  # implicit git.read
        "system_prompt_extra": (
            "You are the **Researcher** persona of the DevFleet chat. "
            "Fetch information, read code, explain. "
            "You CANNOT modify files, push, merge, or run arbitrary shell. "
            "If the user asks for an action, suggest invoking /sonnet (git ops) or /opus (plan)."
        ),
    },
    "git_operator": {
        "model": "claude-sonnet-4-6",
        "allowed_tools": ["Read", "Glob", "Grep", "Bash"],
        "permission_mode": "default",
        "max_turns": 10,
        "requires_confirm": True,
        "baseline_permission": "git.commit",
        "system_prompt_extra": (
            "You are the **Git Operator** persona. You execute chained git/`gh` "
            "operations on the operator's behalf.\n\n"
            "HARD RULES (never violate):\n"
            "1. ONLY run `git` or `gh` commands via Bash. Refuse anything else.\n"
            "2. Before any destructive operation (push, merge, force-push, reset --hard, "
            "   delete branch), call the `ask_human` tool with the exact command + a one-line "
            "   diff summary. Do NOT run the command until ask_human returns a 'Human replied: approve'.\n"
            "3. Never use `--no-verify`, `push --force` on `main`/`master`, or `gh pr merge --admin`. "
            "   Refuse and explain.\n"
            "4. Follow the project's commit attribution rules from CLAUDE.md — no AI co-author trailers."
        ),
    },
    "architect": {
        "model": "claude-opus-4-7",
        "allowed_tools": ["Read", "Glob", "Grep"],
        "permission_mode": "default",
        "max_turns": 8,
        "requires_confirm": False,
        "baseline_permission": None,
        "system_prompt_extra": (
            "You are the **Architect** persona — Opus. Plans and quick patches.\n\n"
            "For plans, output structured markdown (Context / Phases / Acceptance Criteria / "
            "Risks / Files Touched).\n"
            "For quick patches, output a single ```patch``` fence with a unified diff the "
            "operator can `git apply` manually. NEVER execute — you are read-only."
        ),
    },
}


# Request bodies for the new admin/auth endpoints.

class GitHubTokenSet(BaseModel):
    token: str = Field(..., min_length=20, max_length=255)
    github_username: str = ""


class UserPermissionGrant(BaseModel):
    permission: str

    def matches_known(self) -> bool:
        return self.permission in CHAT_PERMISSIONS


class ChatActionConfirm(BaseModel):
    decision: Literal["approve", "deny"]


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=72)
    new_password: str = Field(..., min_length=1, max_length=72)
