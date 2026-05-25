"""Tests for backend/chat_personas.py — inline + git_operator executors."""

from __future__ import annotations

import aiosqlite
import pytest


async def _seed_project(db_path: str, pid: str = "p1") -> dict:
    """Insert a project row and return it as a dict."""
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO projects (id, name, path, description) "
            "VALUES (?, 'demo', '/tmp/demo-not-real', 'A demo project')",
            (pid,),
        )
        await conn.commit()
    return {"id": pid, "name": "demo", "path": "/tmp/demo-not-real",
            "description": "A demo project"}


# ─── System prompt builder ────────────────────────────────────────────────


def test_inline_prompt_includes_project_name():
    from chat_personas import _build_inline_system_prompt

    project = {"id": "p1", "name": "myproj", "path": "/tmp", "description": "x"}
    prompt = _build_inline_system_prompt("researcher", project, [])
    assert "myproj" in prompt


def test_inline_prompt_includes_scope_rules():
    from chat_personas import _build_inline_system_prompt

    project = {"id": "p1", "name": "myproj", "path": "/tmp", "description": ""}
    prompt = _build_inline_system_prompt("researcher", project, [])
    assert "SCOPE RULES" in prompt
    assert "ONLY help with this project" in prompt


def test_inline_prompt_includes_persona_extras():
    from chat_personas import _build_inline_system_prompt

    project = {"id": "p1", "name": "myproj", "path": "/tmp", "description": ""}
    r = _build_inline_system_prompt("researcher", project, [])
    a = _build_inline_system_prompt("architect", project, [])
    assert "Researcher" in r
    assert "Architect" in a
    assert r != a  # different persona = different prompt


def test_inline_prompt_truncates_history_to_10():
    from chat_personas import _build_inline_system_prompt

    project = {"id": "p1", "name": "myproj", "path": "/tmp", "description": ""}
    history = [
        {"role": "user", "content": f"message {i}", "is_plan": False}
        for i in range(20)
    ]
    prompt = _build_inline_system_prompt("researcher", project, history)
    # Messages 0..9 should NOT be present (they're outside the last-10 window)
    assert "message 0" not in prompt
    assert "message 9" not in prompt
    # Messages 10..19 should be present
    assert "message 19" in prompt


def test_inline_prompt_handles_empty_history():
    from chat_personas import _build_inline_system_prompt

    project = {"id": "p1", "name": "x", "path": "/tmp", "description": ""}
    prompt = _build_inline_system_prompt("researcher", project, [])
    # Should not crash; should not include "Recent conversation"
    assert "Recent conversation" not in prompt


def test_inline_prompt_summarizes_plan_rows():
    from chat_personas import _build_inline_system_prompt

    project = {"id": "p1", "name": "x", "path": "/tmp", "description": ""}
    history = [
        {"role": "assistant", "content": "long plan content here", "is_plan": True,
         "plan_title": "Refactor watcher"},
    ]
    prompt = _build_inline_system_prompt("researcher", project, history)
    assert "earlier plan: Refactor watcher" in prompt
    assert "long plan content" not in prompt  # raw plan not inlined


# ─── run_inline_persona ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_inline_rejects_git_operator():
    from chat_personas import run_inline_persona

    gen = run_inline_persona(
        "git_operator",
        {"id": "p1", "name": "x", "path": "/tmp"},
        {"email": "a@b"},
        "hi", [],
    )
    with pytest.raises(ValueError, match="git_operator"):
        async for _ in gen:
            pass


@pytest.mark.asyncio
async def test_run_inline_yields_text_events(monkeypatch):
    """Stub claude_code_sdk.query so the inline persona just emits two
    text blocks. Verifies the event shape forwarded to the chat SSE."""
    from chat_personas import run_inline_persona
    import claude_code_sdk
    from claude_code_sdk.types import TextBlock

    class StubMsg:
        def __init__(self, text: str):
            self.content = [TextBlock(text=text)]

    async def fake_query(prompt, options):
        yield StubMsg("hello ")
        yield StubMsg("world")

    monkeypatch.setattr(claude_code_sdk, "query", fake_query)
    # chat_personas imports `query as sdk_query` inside the function — patch the
    # module attribute the lazy import resolves to.
    monkeypatch.setattr("claude_code_sdk.query", fake_query)

    events = []
    async for ev in run_inline_persona(
        "researcher",
        {"id": "p1", "name": "x", "path": "/tmp", "description": ""},
        {"email": "a@b"}, "say hello", [],
    ):
        events.append(ev)

    text_events = [e for e in events if e["type"] == "text"]
    assert len(text_events) == 2
    assert text_events[0]["text"] == "hello "
    assert text_events[1]["text"] == "world"


@pytest.mark.asyncio
async def test_run_inline_does_not_double_emit_via_result_message(monkeypatch):
    """SDK emits text once via AssistantMessage TextBlocks and again via the
    terminal ResultMessage.result. Inline persona must only stream the blocks;
    the final ResultMessage is metadata, not a second copy of the reply."""
    from chat_personas import run_inline_persona
    import claude_code_sdk
    from claude_code_sdk.types import TextBlock

    class AssistantStub:
        def __init__(self, text: str):
            self.content = [TextBlock(text=text)]

    class ResultStub:
        # No `content`, only `result` — mirrors the SDK's terminal message
        def __init__(self, text: str):
            self.result = text

    async def fake_query(prompt, options):
        yield AssistantStub("hello ")
        yield AssistantStub("world")
        yield ResultStub("hello world")  # full reply again — must NOT be re-yielded

    monkeypatch.setattr("claude_code_sdk.query", fake_query)

    events = []
    async for ev in run_inline_persona(
        "researcher",
        {"id": "p1", "name": "x", "path": "/tmp", "description": ""},
        {"email": "a@b"}, "say hello", [],
    ):
        events.append(ev)

    text_events = [e for e in events if e["type"] == "text"]
    assert len(text_events) == 2, (
        f"expected only the 2 TextBlocks, got {len(text_events)} "
        f"(ResultMessage.result was double-yielded)"
    )
    assert "".join(e["text"] for e in text_events) == "hello world"


@pytest.mark.asyncio
async def test_run_inline_falls_back_to_result_when_no_text_blocks(monkeypatch):
    """If the SDK happens to skip TextBlocks and only emits a ResultMessage
    (rare lightweight path), we must still surface the reply — otherwise the
    chat goes silent."""
    from chat_personas import run_inline_persona

    class ResultOnlyStub:
        def __init__(self, text: str):
            self.result = text

    async def fake_query(prompt, options):
        yield ResultOnlyStub("just the result")

    monkeypatch.setattr("claude_code_sdk.query", fake_query)

    events = []
    async for ev in run_inline_persona(
        "researcher",
        {"id": "p1", "name": "x", "path": "/tmp", "description": ""},
        {"email": "a@b"}, "hi", [],
    ):
        events.append(ev)

    text_events = [e for e in events if e["type"] == "text"]
    assert len(text_events) == 1
    assert text_events[0]["text"] == "just the result"


@pytest.mark.asyncio
async def test_run_inline_emits_error_on_exception(monkeypatch):
    """If the SDK call raises, an error event must be yielded — the chat
    stream should never hang or expose a stack trace."""
    from chat_personas import run_inline_persona

    async def boom(prompt, options):
        raise RuntimeError("SDK exploded")
        yield  # make it a generator (unreachable)

    monkeypatch.setattr("claude_code_sdk.query", boom)

    events = []
    async for ev in run_inline_persona(
        "researcher",
        {"id": "p1", "name": "x", "path": "/tmp", "description": ""},
        {"email": "a@b"}, "hi", [],
    ):
        events.append(ev)

    assert any(e["type"] == "error" for e in events)
    # Never leak the original exception message
    assert not any("SDK exploded" in str(e.get("text", "")) for e in events)


# ─── start_git_operator_turn ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_operator_creates_synthetic_mission(tmp_db, monkeypatch):
    """Verify the synthetic mission has is_chat_turn=1 and never gets picked
    up by the mission watcher's eligibility query."""
    import chat_personas
    import app

    project = await _seed_project(tmp_db)

    # Stub dispatch_mission so we don't actually spawn the SDK
    dispatched: list[tuple] = []

    async def fake_dispatch(session_id, mission, last_report, opts=None, github_token=None):
        dispatched.append((session_id, mission["id"], github_token))

    monkeypatch.setattr("sdk_engine.dispatch_mission", fake_dispatch)
    # running_tasks lives on app; provide a fresh dict for the test
    monkeypatch.setattr(app, "running_tasks", {})

    result = await chat_personas.start_git_operator_turn(
        project, {"email": "farhan@devfleet.local"},
        "merge PR 42", "pr_merge",
        github_token="ghp_testtoken1234567890",
        requires_confirm=True,
    )
    assert "session_id" in result
    assert "mission_id" in result

    # Verify the synthetic mission has the right flags
    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute(
            "SELECT mission_type, is_chat_turn, auto_dispatch, status, "
            "       created_by_email, allowed_tools "
            "FROM missions WHERE id = ?",
            (result["mission_id"],),
        )
        row = await cur.fetchone()
    assert row is not None
    mtype, is_chat, auto, status, email, tools = row
    assert mtype == "chat_op"
    assert is_chat == 1
    assert auto == 0
    assert status == "running"
    assert email == "farhan@devfleet.local"
    assert "Bash" in tools

    # Give the background task a tick to fire
    import asyncio
    await asyncio.sleep(0.05)
    assert len(dispatched) == 1
    assert dispatched[0][2] == "ghp_testtoken1234567890"  # token forwarded


@pytest.mark.asyncio
async def test_git_operator_detailed_prompt_includes_confirm_instruction(tmp_db, monkeypatch):
    """When requires_confirm=True, the detailed_prompt must instruct the agent
    to call ask_human first. This is the prompt-level guardrail."""
    import chat_personas
    import app

    project = await _seed_project(tmp_db)

    async def fake_dispatch(*a, **kw):
        pass

    monkeypatch.setattr("sdk_engine.dispatch_mission", fake_dispatch)
    monkeypatch.setattr(app, "running_tasks", {})

    result = await chat_personas.start_git_operator_turn(
        project, {"email": "a@b.c"},
        "force push to main", "push",
        github_token="ghp_x",
        requires_confirm=True,
    )

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute(
            "SELECT detailed_prompt FROM missions WHERE id = ?",
            (result["mission_id"],),
        )
        prompt = (await cur.fetchone())[0]

    assert "ask_human" in prompt
    assert "approve" in prompt.lower()


@pytest.mark.asyncio
async def test_git_operator_no_extra_confirm_block_when_safe(tmp_db, monkeypatch):
    """A non-destructive git_operator turn should NOT carry the inline
    'This request appears destructive' block — saves tokens and avoids
    nagging the agent on safe operations. (The persona's baseline system
    prompt mentions ask_human in general; this test checks the extra
    per-turn explicit instruction is absent.)"""
    import chat_personas
    import app

    project = await _seed_project(tmp_db)

    async def fake_dispatch(*a, **kw):
        pass

    monkeypatch.setattr("sdk_engine.dispatch_mission", fake_dispatch)
    monkeypatch.setattr(app, "running_tasks", {})

    safe = await chat_personas.start_git_operator_turn(
        project, {"email": "a@b.c"},
        "show me the PR list", "pr_create",
        github_token="ghp_x",
        requires_confirm=False,
    )
    risky = await chat_personas.start_git_operator_turn(
        project, {"email": "a@b.c"},
        "merge PR 99 now", "pr_merge",
        github_token="ghp_x",
        requires_confirm=True,
    )

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute(
            "SELECT id, detailed_prompt FROM missions WHERE id IN (?, ?)",
            (safe["mission_id"], risky["mission_id"]),
        )
        prompts = {row[0]: row[1] for row in await cur.fetchall()}

    # The block we add per-turn only when confirm is required
    confirm_block_marker = "This request appears destructive"
    assert confirm_block_marker not in prompts[safe["mission_id"]]
    assert confirm_block_marker in prompts[risky["mission_id"]]


@pytest.mark.asyncio
async def test_git_operator_agent_session_row_created(tmp_db, monkeypatch):
    import chat_personas
    import app

    project = await _seed_project(tmp_db)

    async def fake_dispatch(*a, **kw):
        pass

    monkeypatch.setattr("sdk_engine.dispatch_mission", fake_dispatch)
    monkeypatch.setattr(app, "running_tasks", {})

    result = await chat_personas.start_git_operator_turn(
        project, {"email": "a@b"}, "commit changes", "commit",
        github_token="ghp_x", requires_confirm=False,
    )

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute(
            "SELECT mission_id, status, model FROM agent_sessions WHERE id = ?",
            (result["session_id"],),
        )
        row = await cur.fetchone()
    assert row is not None
    mid, status, model = row
    assert mid == result["mission_id"]
    assert status == "running"
    assert "sonnet" in model.lower()


@pytest.mark.asyncio
async def test_git_operator_writes_started_audit_row(tmp_db, monkeypatch):
    """Audit must be unconditional. The 'started' row should land BEFORE
    dispatch so even a dispatch crash leaves a forensic trail."""
    import chat_personas
    import app

    project = await _seed_project(tmp_db)

    async def fake_dispatch(*a, **kw):
        pass

    monkeypatch.setattr("sdk_engine.dispatch_mission", fake_dispatch)
    monkeypatch.setattr(app, "running_tasks", {})

    await chat_personas.start_git_operator_turn(
        project, {"sub": "u1", "email": "a@b"},
        "merge PR 42", "pr_merge",
        github_token="ghp_x", requires_confirm=True,
    )

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute(
            "SELECT persona, intent, status, user_id FROM chat_actions "
            "WHERE project_id=? ORDER BY id ASC",
            (project["id"],),
        )
        rows = await cur.fetchall()
    assert len(rows) >= 1
    assert rows[0] == ("git_operator", "pr_merge", "started", "u1")


@pytest.mark.asyncio
async def test_inline_persona_writes_started_and_completed_audit(tmp_db, monkeypatch):
    """run_inline_persona must log start AND end — completed on success,
    failed on exception."""
    import chat_personas
    import claude_code_sdk
    from claude_code_sdk.types import TextBlock

    project = await _seed_project(tmp_db)

    class StubMsg:
        def __init__(self, text: str):
            self.content = [TextBlock(text=text)]

    async def fake_query(prompt, options):
        yield StubMsg("ok")

    monkeypatch.setattr("claude_code_sdk.query", fake_query)

    async for _ in chat_personas.run_inline_persona(
        "researcher", project, {"sub": "u1"}, "hi", [], intent="read",
    ):
        pass

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute(
            "SELECT status FROM chat_actions WHERE project_id=? "
            "ORDER BY id ASC",
            (project["id"],),
        )
        statuses = [row[0] for row in await cur.fetchall()]
    assert "started" in statuses
    assert "completed" in statuses


@pytest.mark.asyncio
async def test_inline_persona_failure_audited_as_failed(tmp_db, monkeypatch):
    import chat_personas

    project = await _seed_project(tmp_db)

    async def boom(prompt, options):
        raise RuntimeError("nope")
        yield  # generator stub

    monkeypatch.setattr("claude_code_sdk.query", boom)

    async for _ in chat_personas.run_inline_persona(
        "researcher", project, {"sub": "u1"}, "hi", [], intent="read",
    ):
        pass

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute(
            "SELECT status FROM chat_actions WHERE project_id=?",
            (project["id"],),
        )
        statuses = [row[0] for row in await cur.fetchall()]
    assert "failed" in statuses


@pytest.mark.asyncio
async def test_git_operator_dispatch_crash_marks_mission_failed(tmp_db, monkeypatch):
    """If dispatch_mission raises inside the failsafe wrapper, the mission
    and session must flip from 'running' to 'failed' and an audit row
    must capture status='failed'. Otherwise a crashed chat turn leaves
    stuck rows on the operator's mission board."""
    import chat_personas
    import app
    import asyncio

    project = await _seed_project(tmp_db)

    async def boom(*a, **kw):
        raise RuntimeError("dispatch went sideways")

    monkeypatch.setattr("sdk_engine.dispatch_mission", boom)
    monkeypatch.setattr(app, "running_tasks", {})

    result = await chat_personas.start_git_operator_turn(
        project, {"sub": "u1"}, "merge PR 1", "pr_merge",
        github_token="ghp_x", requires_confirm=True,
    )

    # Give the failsafe wrapper a tick
    await asyncio.sleep(0.05)

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute(
            "SELECT status FROM missions WHERE id=?",
            (result["mission_id"],),
        )
        mission_status = (await cur.fetchone())[0]
        cur = await conn.execute(
            "SELECT status FROM agent_sessions WHERE id=?",
            (result["session_id"],),
        )
        session_status = (await cur.fetchone())[0]
        cur = await conn.execute(
            "SELECT status FROM chat_actions WHERE project_id=? AND status='failed'",
            (project["id"],),
        )
        failed_audits = await cur.fetchall()

    assert mission_status == "failed"
    assert session_status == "failed"
    assert len(failed_audits) >= 1


@pytest.mark.asyncio
async def test_synthetic_mission_excluded_from_watcher_eligibility(tmp_db, monkeypatch):
    """End-to-end check: chat_personas creates a synthetic mission, and the
    mission watcher's eligibility query MUST NOT return it."""
    import chat_personas
    import app
    import mission_watcher

    project = await _seed_project(tmp_db)

    async def fake_dispatch(*a, **kw):
        pass

    monkeypatch.setattr("sdk_engine.dispatch_mission", fake_dispatch)
    monkeypatch.setattr(app, "running_tasks", {})

    result = await chat_personas.start_git_operator_turn(
        project, {"email": "a@b"}, "merge PR 1", "pr_merge",
        github_token="ghp_x", requires_confirm=True,
    )

    # Mark it auto_dispatch=1 just to test the filter — chat_personas sets
    # auto_dispatch=0 by default, so this exercises the is_chat_turn guard
    # specifically.
    async with aiosqlite.connect(tmp_db) as conn:
        await conn.execute(
            "UPDATE missions SET auto_dispatch=1, status='draft' WHERE id=?",
            (result["mission_id"],),
        )
        await conn.commit()

    # Build a lane_capacity dict the watcher expects
    lane_capacity = {
        "coder": 3, "reviewer": 1, "tester": 1, "explorer": 1,
        "orchestrator": 1, "security": 1, "e2e": 1, "qa": 1,
        "dynamic_tester": 1, "researcher": 1,
    }
    eligible = await mission_watcher._find_eligible_missions(lane_capacity)
    eligible_ids = [m["id"] for m in eligible]
    assert result["mission_id"] not in eligible_ids


# ─── PR merge protocol prompt cadence ─────────────────────────────────────


def test_git_operator_prompt_declares_pr_merge_protocol():
    """The persona prompt MUST spell out all six phases of the PR merge cadence.

    The agent's actual output cadence depends on a real SDK conversation, so we
    test the contract at the prompt layer: every required phase keyword is
    present, and the prompt forbids silent execution between fetch and merge.
    """
    from models import CHAT_PERSONAS

    prompt = CHAT_PERSONAS["git_operator"]["system_prompt_extra"]

    # Six-phase cadence labels
    assert "Phase 1" in prompt and "Fetching" in prompt
    assert "Phase 2" in prompt and "Diff:" in prompt
    assert "Phase 3" in prompt and "Proposed:" in prompt
    assert "Phase 4" in prompt and "Awaiting your confirmation" in prompt
    assert "Phase 5" in prompt and "Merging" in prompt
    assert "Phase 6" in prompt

    # Silent-execution prohibition between fetch and merge
    assert "Silent execution" in prompt or "silent execution" in prompt.lower()

    # ask_human enforcement before merge
    assert "ask_human" in prompt

    # Identity-aware: prompt must mention the worktree git config so the agent
    # refuses to commit when identity is missing
    assert "git config user.email" in prompt or "git config user.name" in prompt
