"""
DevFleet Context Model — MCP Server

A stdio MCP server that provides contextual intelligence to every agent.
Auto-attached to all agent dispatches, giving agents awareness of:
- Project structure and conventions
- Current mission requirements
- Past session history and reports
- Other agents' progress on the same project

Runs as a subprocess spawned by the SDK via McpStdioServerConfig.
Connects to the DevFleet API (localhost) to fetch context.
"""

import asyncio
import json
import os
import sys

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

DEVFLEET_API = os.environ.get("DEVFLEET_API_URL", "http://localhost:18801")
# These are passed as env vars when spawning the MCP server
MISSION_ID = os.environ.get("DEVFLEET_MISSION_ID", "")
PROJECT_ID = os.environ.get("DEVFLEET_PROJECT_ID", "")
SESSION_ID = os.environ.get("DEVFLEET_SESSION_ID", "")

server = Server("devfleet-context")


async def _api_get(path: str) -> dict | list | None:
    """Call the DevFleet API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{DEVFLEET_API}{path}")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────
# Resources — URI-addressable read-only context.
# Industry convention (philschmid, Speakeasy, Zuplo): Resources for data the
# client should KNOW, Tools for what the client can DO. Read-only context fits
# Resources; we keep the equivalent Tools in place for back-compat so clients
# that don't query resources still work.
# ──────────────────────────────────────────────


@server.list_resources()
async def list_resources() -> list[types.Resource]:
    res: list[types.Resource] = []
    if MISSION_ID:
        res.append(types.Resource(
            uri=f"devfleet://mission/{MISSION_ID}/context",
            name=f"Current mission context ({MISSION_ID[:8]})",
            description="Requirements, acceptance criteria, status of the current mission.",
            mimeType="application/json",
        ))
        res.append(types.Resource(
            uri=f"devfleet://mission/{MISSION_ID}/session-history",
            name="Previous session reports for this mission",
            description="Reports from prior agents that worked on this mission (continuity).",
            mimeType="application/json",
        ))
    if PROJECT_ID:
        res.append(types.Resource(
            uri=f"devfleet://project/{PROJECT_ID}/context",
            name="Current project context",
            description="Project info + recent mission history.",
            mimeType="application/json",
        ))
    res.append(types.Resource(
        uri="devfleet://fleet/team-context",
        name="Team context (other running agents)",
        description="What other agents are currently working on, fleet-wide.",
        mimeType="application/json",
    ))
    res.append(types.Resource(
        uri="devfleet://fleet/shape",
        name="Fleet shape — all lane capacity",
        description="Full lane topology: max_agents, running, free, model per lane.",
        mimeType="application/json",
    ))
    return res


@server.read_resource()
async def read_resource(uri) -> str:
    # uri arrives as a pydantic AnyUrl object in mcp>=1.0; coerce to str.
    s = str(uri)
    if s.startswith("devfleet://mission/") and s.endswith("/context"):
        mid = s.split("/")[3]
        # Reuse the same fetch logic the Tool uses; emit pure JSON for Resources
        # (Resources are data; no human-prose wrapper).
        data = await _api_get(f"/api/missions/{mid}")
        if not data:
            return json.dumps({"error": f"Mission {mid} not found"})
        return json.dumps({
            "mission_id": data["id"],
            "title": data["title"],
            "detailed_prompt": data["detailed_prompt"],
            "acceptance_criteria": data.get("acceptance_criteria", ""),
            "status": data["status"],
            "mission_type": data.get("mission_type", "implement"),
            "model": data.get("model", ""),
            "latest_report": data.get("latest_report"),
        }, indent=2)
    if s.startswith("devfleet://mission/") and s.endswith("/session-history"):
        mid = s.split("/")[3]
        reports = await _api_get(f"/api/reports?mission_id={mid}") or []
        return json.dumps([
            {
                "created_at": r.get("created_at", ""),
                "what_done": r.get("what_done", ""),
                "what_open": r.get("what_open", ""),
                "next_steps": r.get("next_steps", ""),
                "errors_encountered": r.get("errors_encountered", ""),
            }
            for r in reports[:5]
        ], indent=2)
    if s.startswith("devfleet://project/") and s.endswith("/context"):
        pid = s.split("/")[3]
        data = await _api_get(f"/api/projects/{pid}")
        if not data:
            return json.dumps({"error": f"Project {pid} not found"})
        missions = data.get("missions", [])
        return json.dumps({
            "project_name": data["name"],
            "project_path": data["path"],
            "description": data.get("description", ""),
            "total_missions": len(missions),
            "recent_missions": [
                {"id": m["id"], "title": m["title"], "status": m["status"], "type": m.get("mission_type", "")}
                for m in missions[:10]
            ],
        }, indent=2)
    if s == "devfleet://fleet/team-context":
        sessions = await _api_get("/api/sessions?status=running") or []
        team = [
            {
                "session_id": x["id"],
                "mission_title": x.get("mission_title", ""),
                "project_name": x.get("project_name", ""),
                "status": x["status"],
                "started_at": x.get("started_at", ""),
            }
            for x in sessions if x["id"] != SESSION_ID
        ]
        return json.dumps(team, indent=2)
    if s == "devfleet://fleet/shape":
        lanes = await _api_get("/api/lanes") or []
        total_slots = sum(l.get("max_agents", 0) for l in lanes)
        total_free = sum(l.get("free", 0) for l in lanes)
        return json.dumps({
            "total_slots": total_slots,
            "total_free": total_free,
            "lanes": [
                {
                    "name": l["name"],
                    "icon": l.get("icon", ""),
                    "max_agents": l.get("max_agents", 0),
                    "running": l.get("running", 0),
                    "free": l.get("free", 0),
                    "model": l.get("default_model", ""),
                }
                for l in lanes
            ],
        }, indent=2)
    return json.dumps({"error": f"Unknown resource URI: {s}"})


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_mission_context",
            description="Get the current mission's requirements, acceptance criteria, and status",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        types.Tool(
            name="get_project_context",
            description="Get project information and recent mission history",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        types.Tool(
            name="get_session_history",
            description="Get reports from previous sessions on this mission for continuity",
            inputSchema={
                "type": "object",
                "properties": {
                    "mission_id": {
                        "type": "string",
                        "description": "Mission ID (defaults to current mission)",
                    },
                },
            },
        ),
        types.Tool(
            name="get_team_context",
            description="See what other agents are currently working on in this project",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        types.Tool(
            name="read_past_reports",
            description="Read detailed reports from any mission in this project",
            inputSchema={
                "type": "object",
                "properties": {
                    "mission_id": {
                        "type": "string",
                        "description": "Specific mission ID to get reports for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max reports to return (default 5)",
                    },
                },
                "required": ["mission_id"],
            },
        ),
        types.Tool(
            name="get_fleet_shape",
            description=(
                "Returns the full DevFleet lane topology — all 10 lanes with their max agent slots, "
                "currently running count, free slots, default model, and role icon. "
                "Call this BEFORE proposing any DAG parallelism so you plan against actual capacity, "
                "not assumed defaults. The fleet has 18 total slots across 10 specialised lanes."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "get_mission_context":
        return await _get_mission_context()
    elif name == "get_project_context":
        return await _get_project_context()
    elif name == "get_session_history":
        mid = arguments.get("mission_id", MISSION_ID)
        return await _get_session_history(mid)
    elif name == "get_team_context":
        return await _get_team_context()
    elif name == "read_past_reports":
        mid = arguments["mission_id"]
        limit = arguments.get("limit", 5)
        return await _read_past_reports(mid, limit)
    elif name == "get_fleet_shape":
        return await _get_fleet_shape()
    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def _get_mission_context() -> list[types.TextContent]:
    if not MISSION_ID:
        return [types.TextContent(type="text", text="No mission context available (DEVFLEET_MISSION_ID not set)")]

    data = await _api_get(f"/api/missions/{MISSION_ID}")
    if not data:
        return [types.TextContent(type="text", text=f"Mission {MISSION_ID} not found")]

    context = {
        "mission_id": data["id"],
        "title": data["title"],
        "detailed_prompt": data["detailed_prompt"],
        "acceptance_criteria": data.get("acceptance_criteria", ""),
        "status": data["status"],
        "mission_type": data.get("mission_type", "implement"),
        "model": data.get("model", ""),
        "latest_report": data.get("latest_report"),
    }
    return [types.TextContent(type="text", text=json.dumps(context, indent=2))]


async def _get_project_context() -> list[types.TextContent]:
    if not PROJECT_ID:
        return [types.TextContent(type="text", text="No project context available (DEVFLEET_PROJECT_ID not set)")]

    data = await _api_get(f"/api/projects/{PROJECT_ID}")
    if not data:
        return [types.TextContent(type="text", text=f"Project {PROJECT_ID} not found")]

    missions = data.get("missions", [])
    context = {
        "project_name": data["name"],
        "project_path": data["path"],
        "description": data.get("description", ""),
        "total_missions": len(missions),
        "recent_missions": [
            {
                "id": m["id"],
                "title": m["title"],
                "status": m["status"],
                "type": m.get("mission_type", ""),
            }
            for m in missions[:10]
        ],
    }
    return [types.TextContent(type="text", text=json.dumps(context, indent=2))]


async def _get_session_history(mission_id: str) -> list[types.TextContent]:
    mid = mission_id or MISSION_ID
    if not mid:
        return [types.TextContent(type="text", text="No mission ID provided")]

    reports = await _api_get(f"/api/reports?mission_id={mid}")
    if not reports:
        return [types.TextContent(type="text", text="No previous session reports found")]

    history = []
    for r in reports[:5]:
        history.append({
            "created_at": r.get("created_at", ""),
            "what_done": r.get("what_done", ""),
            "what_open": r.get("what_open", ""),
            "next_steps": r.get("next_steps", ""),
            "errors_encountered": r.get("errors_encountered", ""),
        })
    return [types.TextContent(type="text", text=json.dumps(history, indent=2))]


async def _get_team_context() -> list[types.TextContent]:
    sessions = await _api_get("/api/sessions?status=running")
    if not sessions:
        return [types.TextContent(type="text", text="No other agents currently running")]

    # Filter to same project if possible
    team = []
    for s in sessions:
        if s["id"] == SESSION_ID:
            continue  # Skip self
        team.append({
            "session_id": s["id"],
            "mission_title": s.get("mission_title", ""),
            "project_name": s.get("project_name", ""),
            "status": s["status"],
            "started_at": s.get("started_at", ""),
        })

    if not team:
        return [types.TextContent(type="text", text="No other agents currently running")]

    return [types.TextContent(type="text", text=json.dumps(team, indent=2))]


async def _read_past_reports(mission_id: str, limit: int) -> list[types.TextContent]:
    reports = await _api_get(f"/api/reports?mission_id={mission_id}")
    if not reports:
        return [types.TextContent(type="text", text=f"No reports found for mission {mission_id}")]

    results = []
    for r in reports[:limit]:
        results.append({
            "created_at": r.get("created_at", ""),
            "files_changed": r.get("files_changed", ""),
            "what_done": r.get("what_done", ""),
            "what_open": r.get("what_open", ""),
            "what_tested": r.get("what_tested", ""),
            "what_untested": r.get("what_untested", ""),
            "next_steps": r.get("next_steps", ""),
            "errors_encountered": r.get("errors_encountered", ""),
        })
    return [types.TextContent(type="text", text=json.dumps(results, indent=2))]


async def _get_fleet_shape() -> list[types.TextContent]:
    """Return full lane topology via the DevFleet API."""
    lanes = await _api_get("/api/lanes")
    if not lanes:
        return [types.TextContent(type="text", text="Fleet shape unavailable — DevFleet API not responding")]

    total_slots = sum(l.get("max_agents", 0) for l in lanes)
    total_free = sum(l.get("free", 0) for l in lanes)

    result = {
        "total_slots": total_slots,
        "total_free": total_free,
        "lanes": [
            {
                "name": l["name"],
                "icon": l.get("icon", ""),
                "max_agents": l.get("max_agents", 0),
                "running": l.get("running", 0),
                "free": l.get("free", 0),
                "model": l.get("default_model", ""),
            }
            for l in lanes
        ],
    }
    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
