"""
Claude DevFleet MCP Server — External integration endpoint.

Exposes Claude DevFleet as an MCP server so any MCP-compatible client
(Claude Code, Cursor, Windsurf, Cline, custom agents) can:
  - Plan projects from natural language
  - Create projects and missions
  - Dispatch agents
  - Check mission status and read reports
  - List and browse projects/missions

Mount via SSE transport at /mcp on the FastAPI app.
"""

import asyncio
import json
import logging
import os
import re
import uuid

from mcp.server import Server
import mcp.types as types

import db
import mission_watcher

log = logging.getLogger("devfleet.mcp-external")

server = Server("devfleet")


# ── Structured error envelope ──
# Unexpected tool failures surface a typed envelope instead of a bare
# {"error": str(e)} so MCP clients can branch on a stable `code` and back off
# on `retry_after_ms`. Codes: INVALID_PARAMS, RATE_LIMITED, INTERNAL,
# SCOPE_DENIED. Successful results stay the raw handler dict (back-compat), and
# the legacy domain errors handlers return on purpose ({"error": ...},
# {"state": ...}) are unchanged. The envelope is produced in two places: the
# call_tool exception path (via _classify_exception) and the scope gate
# (_enforce_scope, which returns a SCOPE_DENIED envelope directly).

def _error_envelope(code: str, message: str, retry_after_ms: int | None = None) -> dict:
    return {
        "ok": False,
        "error": {"code": code, "message": message, "retry_after_ms": retry_after_ms},
    }


def _classify_exception(exc: Exception) -> dict:
    if isinstance(exc, KeyError):
        field = exc.args[0] if exc.args else "?"
        return _error_envelope("INVALID_PARAMS", f"Missing required field: {field}")
    if isinstance(exc, (ValueError, TypeError)):
        return _error_envelope("INVALID_PARAMS", str(exc))
    return _error_envelope("INTERNAL", str(exc))


async def _enforce_scope(tool: str, args: dict, project_id: str | None) -> dict | None:
    """Project-scope gate for the mutating MCP tools (Task 11).

    Resolve the acting user from `acting_user_email` (or the legacy
    `created_by_email`) and refuse the call when that user is not bound to
    `project_id`. Returns a SCOPE_DENIED envelope to hand straight back to the
    caller, or None when the call is allowed. Never raises — MCP handlers return
    JSON dicts, and a raise would collapse to the generic INTERNAL envelope.

    The trust model here differs from the sdk_engine dispatch gate, so the
    fallback rules differ too:
      - Missing email → admin-equivalent fallback + one deprecation log. This is
        back-compat for callers that pre-date scope bindings; Phase II will
        require the email and drop the fallback.
      - Unknown email → DENIED. `acting_user_email` at this boundary is arbitrary
        caller-supplied input; an explicit-but-unresolvable email must not be
        silently upgraded to admin (a typo'd email getting admin access would be
        a real privilege escalation).
    """
    acting_email = (
        args.get("acting_user_email") or args.get("created_by_email") or ""
    ).strip()
    if not acting_email:
        log.warning(
            "MCP external '%s' called without acting_user_email — admin-equivalent "
            "fallback. Set acting_user_email to enable scope enforcement.",
            tool,
        )
        return None

    import auth as _auth

    user = await _auth.get_user_by_email(acting_email)
    if user is None:
        log.warning("MCP external '%s' denied: unknown user %s", tool, acting_email)
        return _error_envelope("SCOPE_DENIED", f"Unknown DevFleet user: {acting_email}")

    if project_id and not await _auth.user_has_project_access(user["id"], project_id):
        log.warning(
            "MCP external '%s' denied: %s not bound to project %s",
            tool, acting_email, project_id,
        )
        return _error_envelope(
            "SCOPE_DENIED",
            f"{acting_email} is not bound to project {project_id}",
        )
    return None


# Clients MUST send a fresh JSON-RPC `id` per request within a session.
# Concurrent requests with the same id (e.g. a polling loop hardcoded to id=42
# plus an interactive call) collide and the underlying MCP library responds
# with the opaque `{"code": -32602, "message": "Invalid request parameters",
# "data": ""}` — see #4 in the DX feedback triage. Use a UUID, monotonic
# counter, or `random.randint(1, 1_000_000)`.


# ── Helper: resolve projects dir ──

def _projects_base() -> str:
    base = os.environ.get("DEVFLEET_PROJECTS_DIR")
    if not base:
        devfleet_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        base = os.path.join(devfleet_root, "projects")
    return base


def _slugify(text: str, max_len: int = 40) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower().strip())[:max_len].strip('-')


# ── Tool Definitions ──

TOOLS = [
    types.Tool(
        name="plan_project",
        description=(
            "Plan a project from a natural language description. "
            "AI breaks the prompt into a project with chained missions, "
            "dependencies, and auto-dispatch. Returns project ID and mission list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Natural language description of what to build"
                },
                "project_path": {
                    "type": "string",
                    "description": "Optional filesystem path for the project. Auto-generated if not provided."
                },
                "created_by_email": {
                    "type": "string",
                    "description": (
                        "Your DevFleet account email (e.g. hasan@devfleet.local). "
                        "Agents will commit under your git identity and use your saved GitHub PAT."
                    ),
                },
            },
            "required": ["prompt"],
        },
    ),
    types.Tool(
        name="create_project",
        description="Create a new Claude DevFleet project manually.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name"},
                "path": {"type": "string", "description": "Filesystem path for the project. Auto-generated if not provided."},
                "description": {"type": "string", "description": "Project description"},
            },
            "required": ["name"],
        },
    ),
    types.Tool(
        name="create_mission",
        description=(
            "Create a mission (task) in an existing project. "
            "Supports dependencies, auto-dispatch, priority, and lane routing. "
            "Use `lane` to target a specialist (reviewer, security, e2e, etc.) — "
            "without it the mission lands on the default coder lane regardless of intent."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "ID of the project"},
                "title": {"type": "string", "description": "Mission title"},
                "prompt": {"type": "string", "description": "Detailed prompt / instructions for the agent"},
                "acceptance_criteria": {"type": "string", "description": "What counts as done"},
                "depends_on": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of mission IDs this depends on"
                },
                "auto_dispatch": {"type": "boolean", "description": "Auto-dispatch when dependencies complete"},
                "skip_quality_gates": {"type": "boolean", "description": "Skip spawning REV-/TEST- quality-gate sub-missions and go directly to submit_report"},
                "priority": {"type": "integer", "description": "Priority (0=normal, 1=high, 2=critical)"},
                "model": {"type": "string", "description": "Model to use (default: claude-sonnet-4-6)"},
                "mission_type": {
                    "type": "string",
                    "enum": [
                        "implement", "fix", "full", "review", "security", "test",
                        "e2e", "qa", "dynamic_test", "explore", "planner",
                        "orchestrator", "research",
                    ],
                    "description": (
                        "Mission intent. Determines tool preset AND default lane "
                        "(implement→coder, review→reviewer, security→security, test→tester, "
                        "e2e→e2e, qa→qa, research→researcher, explore→explorer, planner→orchestrator). "
                        "Override the lane mapping with the `lane` field."
                    ),
                },
                "lane": {
                    "type": "string",
                    "enum": [
                        "coder", "reviewer", "tester", "e2e", "security", "qa",
                        "dynamic_tester", "researcher", "explorer", "orchestrator",
                    ],
                    "description": (
                        "Scheduling lane override. Each lane has its own concurrency cap, model, "
                        "and tool preset. If omitted, derived from mission_type. Use get_dashboard "
                        "to inspect lane capacity before dispatching to a full one."
                    ),
                },
                "created_by_email": {
                    "type": "string",
                    "description": (
                        "Your DevFleet account email (e.g. hasan@devfleet.local). "
                        "Required for the agent to commit under your git identity and "
                        "use your saved GitHub PAT. Without this the agent uses the "
                        "machine-level git config."
                    ),
                },
                "idempotency_key": {
                    "type": "string",
                    "description": (
                        "Optional client-supplied key to make retries safe. A second "
                        "create_mission with the same key returns the original mission "
                        "(idempotent_replay=true) instead of creating a duplicate; new "
                        "args are ignored on replay."
                    ),
                },
            },
            "required": ["project_id", "title", "prompt"],
        },
    ),
    types.Tool(
        name="dispatch_mission",
        description="Dispatch an agent to work on a mission. The agent runs asynchronously.",
        inputSchema={
            "type": "object",
            "properties": {
                "mission_id": {"type": "string", "description": "ID of the mission to dispatch"},
                "model": {"type": "string", "description": "Override model for this dispatch"},
                "max_turns": {"type": "integer", "description": "Max conversation turns"},
                "acting_user_email": {
                    "type": "string",
                    "description": (
                        "Your DevFleet account email. Scope-checked against the "
                        "mission's project — dispatch is denied (SCOPE_DENIED) if you "
                        "are not bound to that project. Omit only for trusted "
                        "system/admin callers (admin-equivalent fallback)."
                    ),
                },
                "idempotency_key": {
                    "type": "string",
                    "description": (
                        "Optional client-supplied key to make retries safe. A second "
                        "dispatch_mission with the same key returns the original session "
                        "(success or failure) without spawning a second agent. Use a "
                        "fresh key to force a new attempt."
                    ),
                },
            },
            "required": ["mission_id"],
        },
    ),
    types.Tool(
        name="get_mission_status",
        description=(
            "Get current status and details of a mission including its latest session and report."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "mission_id": {"type": "string", "description": "Mission ID"},
            },
            "required": ["mission_id"],
        },
    ),
    types.Tool(
        name="get_report",
        description=(
            "Get the structured report from a completed mission — "
            "what was done, tested, untested, files changed, errors, and next steps."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "mission_id": {"type": "string", "description": "Mission ID"},
            },
            "required": ["mission_id"],
        },
    ),
    types.Tool(
        name="list_projects",
        description="List all Claude DevFleet projects.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    types.Tool(
        name="list_missions",
        description="List missions in a project, optionally filtered by status.",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "status": {
                    "type": "string",
                    "description": "Filter by status (draft, running, completed, failed)",
                    "enum": ["draft", "running", "completed", "failed"],
                },
            },
            "required": ["project_id"],
        },
    ),
    types.Tool(
        name="cancel_mission",
        description="Cancel a running mission and stop its agent.",
        inputSchema={
            "type": "object",
            "properties": {
                "mission_id": {"type": "string", "description": "Mission ID to cancel"},
                "acting_user_email": {
                    "type": "string",
                    "description": (
                        "Your DevFleet account email. Scope-checked against the "
                        "mission's project — cancel is denied (SCOPE_DENIED) if you "
                        "are not bound to that project."
                    ),
                },
            },
            "required": ["mission_id"],
        },
    ),
    types.Tool(
        name="update_mission",
        description=(
            "Update fields on a mission that hasn't started yet. "
            "Use for fixing typos, changing prompts, re-targeting depends_on, or flipping "
            "auto_dispatch before the watcher picks it up. Refuses to edit running missions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "mission_id": {"type": "string", "description": "Mission ID to update"},
                "title": {"type": "string"},
                "prompt": {"type": "string", "description": "Replaces detailed_prompt"},
                "acceptance_criteria": {"type": "string"},
                "depends_on": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Replaces the dependency list entirely",
                },
                "auto_dispatch": {"type": "boolean"},
                "priority": {"type": "integer"},
                "model": {"type": "string"},
                "mission_type": {"type": "string"},
                "lane": {"type": "string"},
                "acting_user_email": {
                    "type": "string",
                    "description": (
                        "Your DevFleet account email. Scope-checked against the "
                        "mission's project — update is denied (SCOPE_DENIED) if you "
                        "are not bound to that project."
                    ),
                },
            },
            "required": ["mission_id"],
        },
    ),
    types.Tool(
        name="delete_mission",
        description=(
            "Delete a draft/pending mission. Refuses to delete running missions "
            "(cancel them first). Also refuses if other missions depend on it."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "mission_id": {"type": "string", "description": "Mission ID to delete"},
                "acting_user_email": {
                    "type": "string",
                    "description": (
                        "Your DevFleet account email. Scope-checked against the "
                        "mission's project — delete is denied (SCOPE_DENIED) if you "
                        "are not bound to that project."
                    ),
                },
            },
            "required": ["mission_id"],
        },
    ),
    types.Tool(
        name="wait_for_mission",
        description=(
            "Wait for a mission to complete and return its final status and report. "
            "Polls every 5 seconds. Use after dispatch_mission to block until done. "
            "Caller note: if you have other concurrent calls in the same MCP session "
            "(monitor, status checks), give every request a unique JSON-RPC `id` "
            "(UUID or random int). Duplicate ids cause an opaque -32602."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "mission_id": {"type": "string", "description": "Mission ID to wait for"},
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Max seconds to wait (default: 600, max: 1800)",
                },
            },
            "required": ["mission_id"],
        },
    ),
    types.Tool(
        name="get_dashboard",
        description=(
            "Get a high-level dashboard of Claude DevFleet: running agents, "
            "project count, mission stats, and recent activity."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    from plugins import registry
    return TOOLS + registry.tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        # Check plugin tools first
        from plugins import registry
        if name in registry.tool_handlers:
            result = await registry.tool_handlers[name](arguments)
        else:
            result = await _handle_tool(name, arguments)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    except Exception as e:
        log.exception(f"MCP tool {name} failed")
        return [types.TextContent(
            type="text",
            text=json.dumps(_classify_exception(e), indent=2, default=str),
        )]


async def _handle_tool(name: str, args: dict) -> dict:
    conn = await db.get_db()
    try:
        if name == "plan_project":
            return await _plan_project(args, conn)
        elif name == "create_project":
            return await _create_project(args, conn)
        elif name == "create_mission":
            return await _create_mission(args, conn)
        elif name == "dispatch_mission":
            return await _dispatch_mission(args, conn)
        elif name == "get_mission_status":
            return await _get_mission_status(args, conn)
        elif name == "get_report":
            return await _get_report(args, conn)
        elif name == "list_projects":
            return await _list_projects(conn)
        elif name == "list_missions":
            return await _list_missions(args, conn)
        elif name == "cancel_mission":
            return await _cancel_mission(args, conn)
        elif name == "update_mission":
            return await _update_mission(args, conn)
        elif name == "delete_mission":
            return await _delete_mission(args, conn)
        elif name == "wait_for_mission":
            return await _wait_for_mission(args)
        elif name == "get_dashboard":
            return await _get_dashboard(conn)
        else:
            return {"error": f"Unknown tool: {name}"}
    finally:
        await conn.close()


# ── Tool Implementations ──

async def _plan_project(args: dict, conn) -> dict:
    from planner import plan_project

    prompt = args["prompt"]
    project_path = args.get("project_path")
    if not project_path:
        slug = _slugify(prompt)
        project_path = os.path.join(_projects_base(), slug)

    created_by_email = (args.get("created_by_email") or "").strip() or None
    result = await plan_project(prompt, project_path, created_by_email=created_by_email)
    return {
        "project_id": result["project"]["id"],
        "project_name": result["project"]["name"],
        "project_path": project_path,
        "missions": [
            {
                "id": m["id"],
                "number": m["mission_number"],
                "title": m["title"],
                "depends_on": m["depends_on"],
                "auto_dispatch": m["auto_dispatch"],
            }
            for m in result["missions"]
        ],
        "hint": "Dispatch the first mission to start the chain. The rest auto-dispatch as dependencies complete.",
    }


async def _create_project(args: dict, conn) -> dict:
    pid = str(uuid.uuid4())
    name = args["name"]
    path = args.get("path") or os.path.join(_projects_base(), _slugify(name))
    description = args.get("description", "")

    os.makedirs(path, exist_ok=True)

    await conn.execute(
        "INSERT INTO projects (id, name, path, description) VALUES (?, ?, ?, ?)",
        (pid, name, path, description),
    )
    await conn.commit()

    return {"id": pid, "name": name, "path": path, "description": description}


async def _create_mission(args: dict, conn) -> dict:
    mid = str(uuid.uuid4())

    # Verify project exists
    row = await conn.execute("SELECT id FROM projects WHERE id = ?", (args["project_id"],))
    if not await row.fetchone():
        return {"error": f"Project {args['project_id']} not found"}

    denied = await _enforce_scope("create_mission", args, args["project_id"])
    if denied:
        return denied

    # Idempotency replay: a retry with the same key returns the original mission
    # (re-derived from the live row so the shape matches a fresh create) instead
    # of creating a duplicate. New args on a replay are ignored by design — the
    # key identifies one logical create. Runs AFTER the scope gate so the key
    # can't be used to bypass project scope.
    idem_key = (args.get("idempotency_key") or "").strip() or None
    if idem_key:
        cur = await conn.execute(
            "SELECT id, mission_number, title, project_id, mission_type, lane, "
            "auto_dispatch, depends_on FROM missions WHERE idempotency_key = ?",
            (idem_key,),
        )
        existing = await cur.fetchone()
        if existing:
            existing = dict(existing)
            return {
                "id": existing["id"],
                "mission_number": existing["mission_number"],
                "title": existing["title"],
                "project_id": existing["project_id"],
                "mission_type": existing["mission_type"],
                "lane": existing["lane"],
                "auto_dispatch": bool(existing["auto_dispatch"]),
                "depends_on": json.loads(existing["depends_on"] or "[]"),
                "idempotent_replay": True,
            }

    # Get next mission number
    cur = await conn.execute(
        "SELECT COALESCE(MAX(mission_number), 0) + 1 FROM missions WHERE project_id = ?",
        (args["project_id"],),
    )
    next_num = (await cur.fetchone())[0]

    depends_on = json.dumps(args.get("depends_on", []))
    auto_dispatch = 1 if args.get("auto_dispatch", False) else 0
    skip_quality_gates = 1 if args.get("skip_quality_gates", False) else 0

    created_by_email = (args.get("created_by_email") or "").strip()

    # mission_type defaults to 'implement'; lane derives from it unless explicitly set.
    # Keep this mapping in sync with MISSION_TYPE_TO_LANE in models.py.
    mission_type = (args.get("mission_type") or "implement").strip()
    lane = (args.get("lane") or "").strip()
    if not lane:
        from models import MISSION_TYPE_TO_LANE
        lane = MISSION_TYPE_TO_LANE.get(mission_type, "coder")

    # Scope gate: a project-owned lane can't be bound to another project's mission.
    # (REST create_mission enforces the same; this is the direct-DB MCP path.)
    from lanes import assert_lane_in_scope, LaneValidationError as _LaneScopeErr
    try:
        await assert_lane_in_scope(lane, args["project_id"])
    except _LaneScopeErr as _exc:
        return {"error": str(_exc)}

    await conn.execute(
        """INSERT INTO missions
           (id, project_id, title, detailed_prompt, acceptance_criteria,
            depends_on, auto_dispatch, priority, model, mission_number,
            created_by_email, mission_type, lane, skip_quality_gates,
            idempotency_key)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            mid,
            args["project_id"],
            args["title"],
            args["prompt"],
            args.get("acceptance_criteria", ""),
            depends_on,
            auto_dispatch,
            args.get("priority", 0),
            args.get("model", "claude-sonnet-4-6"),
            next_num,
            created_by_email or None,
            mission_type,
            lane,
            skip_quality_gates,
            idem_key,
        ),
    )
    await conn.commit()

    # Nudge the watcher so an auto_dispatch mission created via MCP goes out
    # sub-second instead of waiting for the fallback heartbeat — parity with the
    # REST create path. No-op for auto_dispatch=0 or before the watcher starts.
    mission_watcher.wake()

    return {
        "id": mid,
        "mission_number": next_num,
        "title": args["title"],
        "project_id": args["project_id"],
        "mission_type": mission_type,
        "lane": lane,
        "auto_dispatch": bool(auto_dispatch),
        "depends_on": args.get("depends_on", []),
        "idempotent_replay": False,
    }


async def _dispatch_mission(args: dict, conn) -> dict:
    import uuid as _uuid
    from datetime import datetime, timezone

    mid = args["mission_id"]

    # Fetch mission with project path (needed by dispatch engine)
    cur = await conn.execute(
        "SELECT m.*, p.path AS project_path FROM missions m "
        "JOIN projects p ON p.id = m.project_id WHERE m.id = ?",
        (mid,),
    )
    mission = await cur.fetchone()
    if not mission:
        return {"error": f"Mission {mid} not found"}

    mission = dict(mission)

    # Scope gate before any side-effects (session row, status flip) so an unbound
    # caller fails fast and leaves no half-dispatched state behind.
    denied = await _enforce_scope("dispatch_mission", args, mission.get("project_id"))
    if denied:
        return denied

    # Idempotency replay: a retry with the same key returns the original session
    # (success OR failure) and never spawns a second agent. Must run BEFORE the
    # "already running" check so retrying an in-flight dispatch returns the
    # session rather than the error. New attempts need a fresh key.
    idem_key = (args.get("idempotency_key") or "").strip() or None
    if idem_key:
        cur = await conn.execute(
            "SELECT id, status, model FROM agent_sessions WHERE idempotency_key = ?",
            (idem_key,),
        )
        existing = await cur.fetchone()
        if existing:
            existing = dict(existing)
            return {
                "session_id": existing["id"],
                "mission_id": mid,
                "status": "dispatched",
                "session_status": existing["status"],
                "model": existing["model"],
                "idempotent_replay": True,
                "hint": "Replayed an existing dispatch for this idempotency_key — no new agent spawned. Use a fresh key to retry.",
            }

    if mission["status"] == "running":
        return {"error": "Mission is already running"}

    # Check per-lane capacity first, then global ceiling
    from lanes import check_slot
    from app import running_tasks, MAX_CONCURRENT_AGENTS

    ok, reason = await check_slot(mission)
    if not ok:
        return {"error": f"Dispatch blocked: {reason}"}

    running_count = sum(1 for t in running_tasks.values() if not t.done())
    if MAX_CONCURRENT_AGENTS > 0 and running_count >= MAX_CONCURRENT_AGENTS:
        return {"error": f"Global agent ceiling reached ({running_count}/{MAX_CONCURRENT_AGENTS}). Wait for a slot to free."}

    # Get last report for context (matches app.py flow)
    cur = await conn.execute(
        "SELECT * FROM reports WHERE mission_id = ? ORDER BY created_at DESC LIMIT 1",
        (mid,),
    )
    report_row = await cur.fetchone()
    last_report = dict(report_row) if report_row else None

    # Create session in DB (matches app.py flow)
    session_id = str(_uuid.uuid4())
    model_used = args.get("model") or mission.get("model") or "claude-sonnet-4-6"
    await conn.execute(
        "INSERT INTO agent_sessions (id, mission_id, model, idempotency_key) VALUES (?, ?, ?, ?)",
        (session_id, mid, model_used, idem_key),
    )
    await conn.execute(
        "UPDATE missions SET status='running', updated_at=? WHERE id=?",
        (datetime.now(timezone.utc).isoformat(), mid),
    )
    await conn.commit()

    # Import and dispatch
    USE_SDK = os.environ.get("DEVFLEET_ENGINE", "sdk").lower() == "sdk"
    if USE_SDK:
        from sdk_engine import dispatch_mission
    else:
        from dispatcher import dispatch_mission

    # Build opts from args
    from models import DispatchOptions

    opts_kwargs = {}
    if args.get("model"):
        opts_kwargs["model"] = args["model"]
    if args.get("max_turns"):
        opts_kwargs["max_turns"] = args["max_turns"]
    opts = DispatchOptions(**opts_kwargs) if opts_kwargs else None

    # Dispatch asynchronously (matches app.py flow)
    import asyncio

    task = asyncio.create_task(
        dispatch_mission(session_id, mission, last_report, opts=opts)
    )
    running_tasks[session_id] = task

    return {
        "session_id": session_id,
        "mission_id": mid,
        "status": "dispatched",
        "model": model_used,
        "idempotent_replay": False,
        "hint": "Mission is now running. Use get_mission_status to check progress.",
    }


async def _get_mission_status(args: dict, conn) -> dict:
    mid = args["mission_id"]

    cur = await conn.execute("SELECT * FROM missions WHERE id = ?", (mid,))
    mission = await cur.fetchone()
    if not mission:
        return {"error": f"Mission {mid} not found"}
    mission = dict(mission)

    # Get latest session
    cur = await conn.execute(
        "SELECT * FROM agent_sessions WHERE mission_id = ? ORDER BY started_at DESC LIMIT 1",
        (mid,),
    )
    session = await cur.fetchone()

    result = {
        "id": mission["id"],
        "title": mission["title"],
        "status": mission["status"],
        "mission_number": mission["mission_number"],
        "depends_on": json.loads(mission["depends_on"] or "[]"),
        "auto_dispatch": bool(mission["auto_dispatch"]),
    }

    if session:
        session = dict(session)
        result["session"] = {
            "id": session["id"],
            "status": session["status"],
            "started_at": session["started_at"],
            "ended_at": session["ended_at"],
            "total_cost_usd": session["total_cost_usd"],
            "total_tokens": session["total_tokens"],
        }

    return result


async def _get_report(args: dict, conn) -> dict:
    """Return a structured report or a precise state explaining why one isn't available.

    A 'no report' result has four real causes — collapsing them all to a single
    generic 404 made root-causing painful. Distinguish them so callers know
    whether to wait, re-dispatch, or accept the agent never submitted one.
    """
    mid = args["mission_id"]

    cur = await conn.execute(
        "SELECT id, status FROM missions WHERE id = ?",
        (mid,),
    )
    mission = await cur.fetchone()
    if not mission:
        return {"error": f"Mission {mid} not found", "state": "not_found"}
    mission = dict(mission)

    cur = await conn.execute(
        "SELECT * FROM reports WHERE mission_id = ? ORDER BY created_at DESC LIMIT 1",
        (mid,),
    )
    report = await cur.fetchone()
    if report:
        report = dict(report)
        return {
            "mission_id": mid,
            "state": "found",
            "mission_status": mission["status"],
            "files_changed": report["files_changed"],
            "what_done": report["what_done"],
            "what_open": report["what_open"],
            "what_tested": report["what_tested"],
            "what_untested": report["what_untested"],
            "next_steps": report["next_steps"],
            "errors_encountered": report["errors_encountered"],
            "created_at": report["created_at"],
        }

    # No report yet — classify why.
    cur = await conn.execute(
        "SELECT id, status, started_at, ended_at FROM agent_sessions "
        "WHERE mission_id = ? ORDER BY started_at DESC LIMIT 1",
        (mid,),
    )
    session = await cur.fetchone()

    if mission["status"] in ("draft", "pending"):
        return {
            "mission_id": mid,
            "state": "pending",
            "mission_status": mission["status"],
            "hint": "Mission has not been dispatched. Use dispatch_mission, or set auto_dispatch + satisfy depends_on.",
        }
    if mission["status"] == "running":
        return {
            "mission_id": mid,
            "state": "running",
            "mission_status": "running",
            "session_id": dict(session)["id"] if session else None,
            "hint": "Agent is still working. Reports are written when the agent calls submit_report at the end of its run.",
        }
    if mission["status"] in ("completed", "failed") and session:
        sess = dict(session)
        return {
            "mission_id": mid,
            "state": "no_report_submitted",
            "mission_status": mission["status"],
            "session_id": sess["id"],
            "session_status": sess["status"],
            "session_ended_at": sess["ended_at"],
            "hint": (
                "Agent finished without calling submit_report. The commits may have "
                "landed via auto-merge but no structured report was produced. "
                "Inspect the worktree branch or session output_log via REST."
            ),
        }
    return {
        "mission_id": mid,
        "state": "unknown",
        "mission_status": mission["status"],
        "hint": "No session and no report — mission may have been created but never dispatched.",
    }


async def _list_projects(conn) -> dict:
    cur = await conn.execute("SELECT id, name, path, description, created_at FROM projects ORDER BY created_at DESC")
    rows = await cur.fetchall()
    return {
        "projects": [dict(r) for r in rows],
        "count": len(rows),
    }


async def _list_missions(args: dict, conn) -> dict:
    pid = args["project_id"]
    status = args.get("status")

    if status:
        cur = await conn.execute(
            "SELECT id, title, status, mission_number, depends_on, auto_dispatch, priority, created_at "
            "FROM missions WHERE project_id = ? AND status = ? ORDER BY mission_number",
            (pid, status),
        )
    else:
        cur = await conn.execute(
            "SELECT id, title, status, mission_number, depends_on, auto_dispatch, priority, created_at "
            "FROM missions WHERE project_id = ? ORDER BY mission_number",
            (pid,),
        )

    rows = await cur.fetchall()
    missions = []
    for r in rows:
        m = dict(r)
        m["depends_on"] = json.loads(m["depends_on"] or "[]")
        m["auto_dispatch"] = bool(m["auto_dispatch"])
        missions.append(m)

    return {"missions": missions, "count": len(missions)}


async def _cancel_mission(args: dict, conn) -> dict:
    mid = args["mission_id"]

    # Resolve the mission's project for the scope gate (and to 404 cleanly).
    cur = await conn.execute("SELECT project_id FROM missions WHERE id = ?", (mid,))
    mission_row = await cur.fetchone()
    if not mission_row:
        return {"error": f"Mission {mid} not found"}

    denied = await _enforce_scope("cancel_mission", args, dict(mission_row)["project_id"])
    if denied:
        return denied

    # Find running session. The SDK engine runs in-process and has no OS pid to track,
    # so we identify the session by id alone and rely on sdk_engine.cancel_session for
    # the cooperative shutdown signal.
    cur = await conn.execute(
        "SELECT id FROM agent_sessions WHERE mission_id = ? AND status = 'running' "
        "ORDER BY started_at DESC LIMIT 1",
        (mid,),
    )
    session = await cur.fetchone()
    if not session:
        return {"error": f"No running session for mission {mid}"}

    sid = dict(session)["id"]

    # Cooperative cancel — SDK iterator exits on next yield once status is flipped to
    # cancelled. Any exception here still falls through to the DB updates so the
    # mission and session aren't left in 'running' on a transient failure.
    try:
        from sdk_engine import cancel_session
        await cancel_session(sid)
    except Exception as exc:
        log.warning("cancel_session failed for %s: %s", sid, exc)

    await conn.execute("UPDATE agent_sessions SET status = 'cancelled' WHERE id = ?", (sid,))
    await conn.execute("UPDATE missions SET status = 'failed' WHERE id = ?", (mid,))
    await conn.commit()

    return {"mission_id": mid, "session_id": sid, "status": "cancelled"}


async def _update_mission(args: dict, conn) -> dict:
    mid = args["mission_id"]

    cur = await conn.execute("SELECT status, project_id FROM missions WHERE id = ?", (mid,))
    row = await cur.fetchone()
    if not row:
        return {"error": f"Mission {mid} not found"}

    denied = await _enforce_scope("update_mission", args, dict(row)["project_id"])
    if denied:
        return denied

    if row["status"] == "running":
        return {"error": "Mission is running — cancel it first before editing"}

    # Map external field name (prompt) → DB column (detailed_prompt).
    field_map = {
        "title": "title",
        "prompt": "detailed_prompt",
        "acceptance_criteria": "acceptance_criteria",
        "priority": "priority",
        "model": "model",
        "mission_type": "mission_type",
        "lane": "lane",
    }
    sets: list[str] = []
    params: list = []
    updated: dict = {}
    for ext_name, col in field_map.items():
        if ext_name in args and args[ext_name] is not None:
            sets.append(f"{col} = ?")
            params.append(args[ext_name])
            updated[ext_name] = args[ext_name]

    if "depends_on" in args and args["depends_on"] is not None:
        sets.append("depends_on = ?")
        params.append(json.dumps(args["depends_on"]))
        updated["depends_on"] = args["depends_on"]

    if "auto_dispatch" in args and args["auto_dispatch"] is not None:
        sets.append("auto_dispatch = ?")
        params.append(1 if args["auto_dispatch"] else 0)
        updated["auto_dispatch"] = bool(args["auto_dispatch"])

    if not sets:
        return {"error": "No fields to update"}

    from datetime import datetime, timezone
    sets.append("updated_at = ?")
    params.append(datetime.now(timezone.utc).isoformat())
    params.append(mid)

    await conn.execute(
        f"UPDATE missions SET {', '.join(sets)} WHERE id = ?",
        params,
    )
    await conn.commit()

    return {"id": mid, "updated": updated}


async def _delete_mission(args: dict, conn) -> dict:
    mid = args["mission_id"]

    cur = await conn.execute("SELECT status, project_id FROM missions WHERE id = ?", (mid,))
    row = await cur.fetchone()
    if not row:
        return {"error": f"Mission {mid} not found"}

    denied = await _enforce_scope("delete_mission", args, dict(row)["project_id"])
    if denied:
        return denied

    if row["status"] == "running":
        return {"error": "Mission is running — cancel it first before deleting"}

    # Block delete when other missions list this one in depends_on. SQLite's
    # json_each lets us filter without loading every row into Python.
    cur = await conn.execute(
        "SELECT m.id, m.title FROM missions m, json_each(m.depends_on) j "
        "WHERE j.value = ?",
        (mid,),
    )
    blockers = [dict(r) for r in await cur.fetchall()]
    if blockers:
        return {
            "error": f"Cannot delete — {len(blockers)} mission(s) depend on this one",
            "blocked_by": blockers,
            "hint": "Update those missions to drop this dependency first.",
        }

    # Cascade to reports + agent_sessions so we don't leak orphans.
    await conn.execute("DELETE FROM reports WHERE mission_id = ?", (mid,))
    await conn.execute("DELETE FROM agent_sessions WHERE mission_id = ?", (mid,))
    await conn.execute("DELETE FROM missions WHERE id = ?", (mid,))
    await conn.commit()

    return {"id": mid, "deleted": True}


async def _wait_for_mission(args: dict) -> dict:
    mid = args["mission_id"]
    timeout = min(args.get("timeout_seconds", 600), 1800)  # cap at 30 min
    elapsed = 0
    poll_interval = 5

    while elapsed < timeout:
        conn = await db.get_db()
        try:
            cur = await conn.execute("SELECT status FROM missions WHERE id = ?", (mid,))
            row = await cur.fetchone()
            if not row:
                return {"error": f"Mission {mid} not found"}

            status = row["status"]
            if status in ("completed", "failed"):
                # Get report if available
                result = await _get_mission_status({"mission_id": mid}, conn)
                report_cur = await conn.execute(
                    "SELECT * FROM reports WHERE mission_id = ? ORDER BY created_at DESC LIMIT 1",
                    (mid,),
                )
                report = await report_cur.fetchone()
                if report:
                    report = dict(report)
                    result["report"] = {
                        "what_done": report["what_done"],
                        "what_tested": report["what_tested"],
                        "what_untested": report["what_untested"],
                        "files_changed": report["files_changed"],
                        "errors_encountered": report["errors_encountered"],
                        "next_steps": report["next_steps"],
                    }
                return result
        finally:
            await conn.close()

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    return {"mission_id": mid, "status": "timeout", "error": f"Mission did not complete within {timeout}s"}


async def _get_dashboard(conn) -> dict:
    # Project count
    cur = await conn.execute("SELECT COUNT(*) FROM projects")
    project_count = (await cur.fetchone())[0]

    # Mission stats
    cur = await conn.execute(
        "SELECT status, COUNT(*) as cnt FROM missions GROUP BY status"
    )
    mission_stats = {row["status"]: row["cnt"] for row in await cur.fetchall()}

    # Running agents (include lane info)
    cur = await conn.execute(
        "SELECT s.id, s.mission_id, m.title, m.lane, m.mission_type FROM agent_sessions s "
        "JOIN missions m ON s.mission_id = m.id WHERE s.status = 'running'"
    )
    running = [dict(r) for r in await cur.fetchall()]

    # Recent completions (last 5)
    cur = await conn.execute(
        "SELECT m.id, m.title, m.status, s.ended_at, s.total_cost_usd "
        "FROM missions m LEFT JOIN agent_sessions s ON m.id = s.mission_id "
        "WHERE m.status IN ('completed', 'failed') "
        "ORDER BY s.ended_at DESC LIMIT 5"
    )
    recent = [dict(r) for r in await cur.fetchall()]

    # Full lane topology — authoritative fleet shape
    from lanes import snapshot as lane_snapshot, total_capacity
    lane_data = await lane_snapshot()
    total_slots = total_capacity()

    return {
        "projects": project_count,
        "missions": mission_stats,
        "running_agents": running,
        "agent_slots": f"{len(running)}/{total_slots}",
        "lanes": lane_data,
        "recent_activity": recent,
    }
