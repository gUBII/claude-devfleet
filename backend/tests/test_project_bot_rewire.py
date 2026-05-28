"""Tests for backend/project_bot.py — the persona dispatcher.

These tests stub out chat_personas + auth so the SDK is never reached. They
verify routing decisions, RBAC denial paths, audit-log calls, history
attribution, and SSE event emission.
"""

from __future__ import annotations

import json
import re
import uuid

import aiosqlite
import pytest


# ─── Helpers ──────────────────────────────────────────────────────────────


async def _seed(db_path: str, *, role: str = "user", grant_perms: list[str] | None = None,
                with_token: bool = False):
    """Insert a project + user. Returns (project_dict, user_dict)."""
    project_id = "proj-1"
    user_id = str(uuid.uuid4())
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO projects (id, name, path, description) "
            "VALUES (?, 'demo', '/tmp/demo-not-real', 'desc')",
            (project_id,),
        )
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, role) "
            "VALUES (?, 'u@x.test', 'h', ?)",
            (user_id, role),
        )
        if with_token:
            # Encrypted token. Use auth.set_github_token via subprocess would be
            # cleaner; for tests we encrypt inline so the row is real.
            import crypto
            enc = crypto.encrypt("ghp_testtoken_abcdef0123456789")
            await conn.execute(
                "UPDATE users SET github_token_encrypted=?, github_username='moofasa' "
                "WHERE id=?",
                (enc, user_id),
            )
        for perm in grant_perms or []:
            await conn.execute(
                "INSERT INTO user_permissions (user_id, permission, granted_by) "
                "VALUES (?, ?, 'admin')",
                (user_id, perm),
            )
        await conn.commit()
    project = {
        "id": project_id, "name": "demo", "path": "/tmp/demo-not-real",
        "description": "desc",
    }
    user = {"sub": user_id, "email": "u@x.test", "role": role}
    return project, user


def _decode(lines: list[str]) -> list[dict]:
    """Parse a list of SSE wire strings into event dicts."""
    out: list[dict] = []
    for raw in lines:
        if not raw.startswith("data: "):
            continue
        out.append(json.loads(raw[6:].strip()))
    return out


async def _collect(gen):
    return [chunk async for chunk in gen]


# ─── Persona event always emits first ─────────────────────────────────────


@pytest.mark.asyncio
async def test_persona_event_is_first(tmp_db, monkeypatch):
    """The persona SSE event must be the very first frame, before any RBAC
    check, so the frontend can render the badge even when the request is
    later denied."""
    from project_bot import stream_bot_response

    project, user = await _seed(tmp_db)

    async def fake_inline(*args, **kwargs):
        yield {"type": "text", "text": "hi"}

    monkeypatch.setattr(
        "chat_personas.run_inline_persona", fake_inline
    )

    chunks = await _collect(stream_bot_response(
        project["id"], project, "what does this repo do?", user,
    ))
    events = _decode(chunks)
    assert events[0]["type"] == "persona"
    assert events[0]["persona"] == "researcher"


# ─── Slash override beats keyword heuristic ───────────────────────────────


@pytest.mark.asyncio
async def test_slash_haiku_forces_researcher(tmp_db, monkeypatch):
    from project_bot import stream_bot_response

    project, user = await _seed(tmp_db)

    async def fake_inline(*args, **kwargs):
        yield {"type": "text", "text": "ok"}

    monkeypatch.setattr("chat_personas.run_inline_persona", fake_inline)

    chunks = await _collect(stream_bot_response(
        project["id"], project,
        "/haiku merge PR 42 please",  # git keyword that would normally route to git_operator
        user,
    ))
    events = _decode(chunks)
    persona_event = next(e for e in events if e["type"] == "persona")
    assert persona_event["persona"] == "researcher"


# ─── RBAC denial path ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pr_merge_denied_without_permission(tmp_db, monkeypatch):
    """Non-admin user without git.pr.merge permission asking for a merge gets
    a permission_denied audit row + error SSE event + done. No personas
    invoked."""
    from project_bot import stream_bot_response

    project, user = await _seed(tmp_db, role="user", with_token=True)

    inline_called = False

    async def fake_inline(*a, **kw):
        nonlocal inline_called
        inline_called = True
        yield {"type": "text", "text": "should not happen"}

    git_called = False

    async def fake_git(*a, **kw):
        nonlocal git_called
        git_called = True
        return {"session_id": "s", "mission_id": "m"}

    monkeypatch.setattr("chat_personas.run_inline_persona", fake_inline)
    monkeypatch.setattr("chat_personas.start_git_operator_turn", fake_git)

    chunks = await _collect(stream_bot_response(
        project["id"], project, "merge PR 42", user,
    ))
    events = _decode(chunks)
    types = [e["type"] for e in events]
    assert types == ["persona", "error", "done"]
    assert "Permission denied" in events[1]["text"]
    assert "git.pr.merge" in events[1]["text"]
    assert not inline_called
    assert not git_called

    # Audit row must exist with status='permission_denied'.
    async with aiosqlite.connect(tmp_db) as conn:
        rows = await (await conn.execute(
            "SELECT status, intent, persona FROM chat_actions "
            "WHERE project_id=? AND user_id=?",
            (project["id"], user["sub"]),
        )).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "permission_denied"
    assert rows[0][1] == "pr_merge"
    assert rows[0][2] == "git_operator"


# ─── Admin bypasses permission table ──────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_skips_permission_lookup(tmp_db, monkeypatch):
    """Admins implicitly hold every permission. A merge intent from admin
    should reach the git_operator path (and only fail later if no token)."""
    from project_bot import stream_bot_response

    project, user = await _seed(tmp_db, role="admin", with_token=True)

    captured = {}

    async def fake_git(project, user, message, intent, *, github_token, requires_confirm):
        captured.update(
            message=message,
            intent=intent,
            requires_confirm=requires_confirm,
            github_token_provided=bool(github_token),
        )
        return {"session_id": "sid-1", "mission_id": "mid-1"}

    monkeypatch.setattr("chat_personas.start_git_operator_turn", fake_git)

    chunks = await _collect(stream_bot_response(
        project["id"], project, "merge PR 42", user,
    ))
    events = _decode(chunks)
    types = [e["type"] for e in events]
    assert types == ["persona", "session_handoff", "done"]
    handoff = events[1]
    assert handoff["session_id"] == "sid-1"
    assert handoff["mission_id"] == "mid-1"
    assert handoff["persona"] == "git_operator"

    # The merge verb should have flipped requires_confirm=True.
    assert captured["intent"] == "pr_merge"
    assert captured["requires_confirm"] is True
    assert captured["github_token_provided"] is True


# ─── Precondition missing: no github token ────────────────────────────────


@pytest.mark.asyncio
async def test_git_operator_without_token_audits_precondition_missing(tmp_db, monkeypatch):
    """If the user has the permission but no stored token, we audit
    precondition_missing and surface a user-safe error. Dispatch never
    runs."""
    from project_bot import stream_bot_response

    project, user = await _seed(
        tmp_db, role="user", grant_perms=["git.pr.merge"], with_token=False,
    )

    git_called = False

    async def fake_git(*a, **kw):
        nonlocal git_called
        git_called = True
        return {"session_id": "s", "mission_id": "m"}

    monkeypatch.setattr("chat_personas.start_git_operator_turn", fake_git)

    chunks = await _collect(stream_bot_response(
        project["id"], project, "merge PR 42", user,
    ))
    events = _decode(chunks)
    types = [e["type"] for e in events]
    assert types == ["persona", "error", "done"]
    # New ask-for-paste copy: asks the user to paste their PAT directly
    # in chat (chat-paste self-onboarding flow). Match stable nouns.
    assert "GitHub token" in events[1]["text"]
    assert "Paste your PAT" in events[1]["text"]
    assert not git_called

    async with aiosqlite.connect(tmp_db) as conn:
        rows = await (await conn.execute(
            "SELECT status, persona FROM chat_actions "
            "WHERE project_id=? AND user_id=?",
            (project["id"], user["sub"]),
        )).fetchall()
    assert any(r[0] == "precondition_missing" and r[1] == "git_operator" for r in rows)


# ─── History persistence: user_id + persona on assistant rows ─────────────


@pytest.mark.asyncio
async def test_inline_reply_persisted_with_user_id_and_persona(tmp_db, monkeypatch):
    from project_bot import stream_bot_response

    project, user = await _seed(tmp_db)

    async def fake_inline(*a, **kw):
        yield {"type": "text", "text": "Mission watcher polls every 5s."}

    monkeypatch.setattr("chat_personas.run_inline_persona", fake_inline)

    await _collect(stream_bot_response(
        project["id"], project, "what does mission_watcher do?", user,
    ))

    async with aiosqlite.connect(tmp_db) as conn:
        rows = await (await conn.execute(
            "SELECT role, content, user_id, persona, is_plan "
            "FROM project_bot_history WHERE project_id=? ORDER BY id",
            (project["id"],),
        )).fetchall()

    # Only the assistant row is inserted here (the user-message row is owned
    # by the app.py endpoint, not stream_bot_response).
    assert len(rows) == 1
    assert rows[0][0] == "assistant"
    assert "Mission watcher" in rows[0][1]
    assert rows[0][2] == user["sub"]
    assert rows[0][3] == "researcher"
    assert rows[0][4] == 0  # not a plan


# ─── Architect plan flagging ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_architect_plan_intent_sets_is_plan_and_emits_plan_meta(tmp_db, monkeypatch):
    """Architect + intent=plan → persisted with is_plan=1 and a plan_meta event."""
    from project_bot import stream_bot_response

    project, user = await _seed(tmp_db)

    async def fake_inline(*a, **kw):
        yield {"type": "text", "text": "# Refactor plan\n\n## Phases\n1. …"}

    monkeypatch.setattr("chat_personas.run_inline_persona", fake_inline)

    chunks = await _collect(stream_bot_response(
        project["id"], project, "/opus plan the migration", user,
    ))
    events = _decode(chunks)
    persona = next(e for e in events if e["type"] == "persona")
    assert persona["persona"] == "architect"
    assert persona["intent"] == "plan"

    plan_meta = [e for e in events if e["type"] == "plan_meta"]
    assert len(plan_meta) == 1
    assert plan_meta[0]["title"] == "Refactor plan"

    async with aiosqlite.connect(tmp_db) as conn:
        rows = await (await conn.execute(
            "SELECT is_plan, plan_title, persona FROM project_bot_history "
            "WHERE project_id=? AND role='assistant'",
            (project["id"],),
        )).fetchall()
    assert rows[0][0] == 1
    assert rows[0][1] == "Refactor plan"
    assert rows[0][2] == "architect"


# ─── Legacy planner_mode=True maps to architect ───────────────────────────


@pytest.mark.asyncio
async def test_legacy_planner_mode_routes_to_architect(tmp_db, monkeypatch):
    from project_bot import stream_bot_response

    project, user = await _seed(tmp_db)

    async def fake_inline(*a, **kw):
        yield {"type": "text", "text": "# Plan"}

    monkeypatch.setattr("chat_personas.run_inline_persona", fake_inline)

    chunks = await _collect(stream_bot_response(
        project["id"], project, "draft a plan",
        user, planner_mode=True,
    ))
    events = _decode(chunks)
    persona = next(e for e in events if e["type"] == "persona")
    assert persona["persona"] == "architect"


# ─── force_persona body field is honored ──────────────────────────────────


@pytest.mark.asyncio
async def test_force_persona_overrides_keyword_heuristic(tmp_db, monkeypatch):
    """An admin force-setting persona=researcher should win over a git
    keyword in the message (because slash and force_persona are explicit
    operator intent)."""
    from project_bot import stream_bot_response

    project, user = await _seed(tmp_db, role="admin")

    async def fake_inline(*a, **kw):
        yield {"type": "text", "text": "ok"}

    monkeypatch.setattr("chat_personas.run_inline_persona", fake_inline)

    chunks = await _collect(stream_bot_response(
        project["id"], project, "merge PR 42", user,
        force_persona="researcher",
    ))
    events = _decode(chunks)
    persona = next(e for e in events if e["type"] == "persona")
    assert persona["persona"] == "researcher"


@pytest.mark.asyncio
async def test_task_creator_emits_reviewable_mission_draft(tmp_db, monkeypatch):
    """A create-task chat turn should stop at a reviewable draft card.

    It must not create a mission row or dispatch an agent; the frontend creates
    the draft only after the operator reviews/edits the card.
    """
    from project_bot import stream_bot_response

    project, user = await _seed(tmp_db)

    async def fail_inline(*a, **kw):
        raise AssertionError("task_creator must not call the SDK inline persona")
        yield {"type": "text", "text": "unreachable"}

    async def fail_git(*a, **kw):
        raise AssertionError("task_creator must not start a git_operator turn")

    monkeypatch.setattr("chat_personas.run_inline_persona", fail_inline)
    monkeypatch.setattr("chat_personas.start_git_operator_turn", fail_git)

    chunks = await _collect(stream_bot_response(
        project["id"], project, "create a task to add dark mode", user,
    ))
    events = _decode(chunks)
    assert [e["type"] for e in events] == ["persona", "text", "done"]
    assert events[0]["persona"] == "task_creator"
    assert events[0]["intent"] == "create_task"

    match = re.search(r"```mission\s*\n([\s\S]*?)\n```", events[1]["text"])
    assert match, events[1]["text"]
    draft = json.loads(match.group(1))
    assert draft["title"] == "Add dark mode"
    assert draft["mission_type"] == "implement"
    assert draft["auto_dispatch"] is False
    assert "Operator request" in draft["detailed_prompt"]

    async with aiosqlite.connect(tmp_db) as conn:
        history = await (await conn.execute(
            "SELECT role, content, user_id, persona FROM project_bot_history "
            "WHERE project_id=?",
            (project["id"],),
        )).fetchall()
        actions = await (await conn.execute(
            "SELECT status, intent, persona FROM chat_actions WHERE project_id=?",
            (project["id"],),
        )).fetchall()
        missions = await (await conn.execute(
            "SELECT COUNT(*) FROM missions WHERE project_id=?",
            (project["id"],),
        )).fetchone()

    assert len(history) == 1
    assert history[0][0] == "assistant"
    assert history[0][2] == user["sub"]
    assert history[0][3] == "task_creator"
    assert "```mission" in history[0][1]
    assert actions == [("completed", "create_task", "task_creator")]
    assert missions[0] == 0
