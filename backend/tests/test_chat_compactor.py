"""Tests for backend/chat_compactor.py."""

from __future__ import annotations

import aiosqlite
import pytest


async def _seed_project(db_path: str, pid: str = "p1") -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO projects (id, name, path, description) "
            "VALUES (?, 'demo', '/tmp', 'd')",
            (pid,),
        )
        await conn.commit()


async def _seed_history(
    db_path: str, *, pid: str, date_iso: str, count: int,
    persona: str = "researcher", user_id: str = "u-1",
) -> None:
    """Insert `count` rows with created_at = `date_iso` (date only, time is 12:00)."""
    async with aiosqlite.connect(db_path) as conn:
        for i in range(count):
            await conn.execute(
                "INSERT INTO project_bot_history "
                "(project_id, role, content, user_id, persona, created_at) "
                "VALUES (?, 'user', ?, ?, ?, ?)",
                (pid, f"message {i}", user_id, persona, f"{date_iso}T12:0{i}:00"),
            )
        await conn.commit()


async def _seed_actions(
    db_path: str, *, pid: str, date_iso: str, count: int, status: str = "completed",
    intent: str = "read", persona: str = "researcher", user_id: str = "u-1",
) -> None:
    async with aiosqlite.connect(db_path) as conn:
        for i in range(count):
            await conn.execute(
                "INSERT INTO chat_actions "
                "(project_id, user_id, persona, intent, command, status, data, created_at) "
                "VALUES (?, ?, ?, ?, '', ?, '{}', ?)",
                (pid, user_id, persona, intent, status, f"{date_iso}T12:0{i}:00"),
            )
        await conn.commit()


@pytest.mark.asyncio
async def test_render_summary_includes_counts_and_personas():
    from chat_compactor import _render_summary

    messages = [
        {"role": "user", "persona": "user", "user_id": "u1",
         "content": "hello", "created_at": "2026-05-23T10:00:00"},
        {"role": "assistant", "persona": "researcher", "user_id": "u1",
         "content": "world", "created_at": "2026-05-23T10:01:00"},
    ]
    actions = [
        {"intent": "read", "status": "completed", "persona": "researcher",
         "user_id": "u1"},
    ]
    summary = _render_summary(messages, actions)
    assert "Messages: 2" in summary
    assert "Actions:  1" in summary
    assert "researcher" in summary
    assert "intent read" in summary
    assert "status completed" in summary
    assert "hello" in summary
    assert "world" in summary


@pytest.mark.asyncio
async def test_compact_with_no_messages_returns_no_messages(tmp_db):
    from chat_compactor import compact_yesterday

    await _seed_project(tmp_db, "p1")
    result = await compact_yesterday("p1")
    assert result["status"] == "no_messages"
    assert result["message_count"] == 0


@pytest.mark.asyncio
async def test_compact_with_messages_creates_summary_and_deletes_raw(tmp_db):
    from chat_compactor import _yesterday_iso, compact_yesterday

    await _seed_project(tmp_db, "p1")
    yesterday = _yesterday_iso()
    await _seed_history(tmp_db, pid="p1", date_iso=yesterday, count=3)
    await _seed_actions(tmp_db, pid="p1", date_iso=yesterday, count=2)

    result = await compact_yesterday("p1")
    assert result["status"] == "compacted"
    assert result["message_count"] == 3
    assert result["action_count"] == 2

    async with aiosqlite.connect(tmp_db) as conn:
        # Raw rows for yesterday gone.
        raw = await (await conn.execute(
            "SELECT COUNT(*) FROM project_bot_history "
            "WHERE project_id=? AND date(created_at)=?",
            ("p1", yesterday),
        )).fetchone()
        assert raw[0] == 0

        # Summary row exists.
        sumrow = await (await conn.execute(
            "SELECT message_count, action_count, summary FROM chat_summaries "
            "WHERE project_id=? AND summary_date=?",
            ("p1", yesterday),
        )).fetchone()
        assert sumrow is not None
        assert sumrow[0] == 3
        assert sumrow[1] == 2
        assert "Messages: 3" in sumrow[2]


@pytest.mark.asyncio
async def test_compact_is_idempotent(tmp_db):
    """Second run returns 'skipped' and leaves the original summary untouched."""
    from chat_compactor import _yesterday_iso, compact_yesterday

    await _seed_project(tmp_db, "p1")
    yesterday = _yesterday_iso()
    await _seed_history(tmp_db, pid="p1", date_iso=yesterday, count=2)

    first = await compact_yesterday("p1")
    assert first["status"] == "compacted"

    # Second invocation finds the summary row, returns skipped.
    second = await compact_yesterday("p1")
    assert second["status"] == "skipped"

    # Still exactly one summary row.
    async with aiosqlite.connect(tmp_db) as conn:
        rows = await (await conn.execute(
            "SELECT COUNT(*) FROM chat_summaries WHERE project_id=?",
            ("p1",),
        )).fetchone()
    assert rows[0] == 1


@pytest.mark.asyncio
async def test_compact_preserves_other_days(tmp_db):
    """Only yesterday's rows get deleted — today + earlier days untouched."""
    from chat_compactor import _yesterday_iso, compact_yesterday

    await _seed_project(tmp_db, "p1")
    yesterday = _yesterday_iso()

    # Seed yesterday + a date 5 days ago + today.
    await _seed_history(tmp_db, pid="p1", date_iso=yesterday, count=2)
    await _seed_history(tmp_db, pid="p1", date_iso="2026-01-01", count=3)

    # "Today" — insert with no explicit created_at so it defaults to now.
    async with aiosqlite.connect(tmp_db) as conn:
        await conn.execute(
            "INSERT INTO project_bot_history "
            "(project_id, role, content, user_id, persona) "
            "VALUES ('p1', 'user', 'today msg', 'u1', 'user')"
        )
        await conn.commit()

    await compact_yesterday("p1")

    async with aiosqlite.connect(tmp_db) as conn:
        # Yesterday's rows deleted.
        y = await (await conn.execute(
            "SELECT COUNT(*) FROM project_bot_history "
            "WHERE project_id=? AND date(created_at)=?",
            ("p1", yesterday),
        )).fetchone()
        assert y[0] == 0

        # Earlier date intact.
        earlier = await (await conn.execute(
            "SELECT COUNT(*) FROM project_bot_history "
            "WHERE project_id=? AND date(created_at)='2026-01-01'",
            ("p1",),
        )).fetchone()
        assert earlier[0] == 3

        # Today's row intact.
        today = await (await conn.execute(
            "SELECT COUNT(*) FROM project_bot_history "
            "WHERE project_id=? AND content='today msg'",
            ("p1",),
        )).fetchone()
        assert today[0] == 1


@pytest.mark.asyncio
async def test_compact_all_projects_skips_failing_one(tmp_db, monkeypatch):
    """compact_all_projects must not let one project's exception kill the rest."""
    import chat_compactor

    await _seed_project(tmp_db, "p1")
    await _seed_project(tmp_db, "p2")

    seen: list[str] = []
    original = chat_compactor.compact_yesterday

    async def patched(pid: str):
        seen.append(pid)
        if pid == "p1":
            raise RuntimeError("boom")
        return await original(pid)

    monkeypatch.setattr(chat_compactor, "compact_yesterday", patched)
    results = await chat_compactor.compact_all_projects()
    assert {"p1", "p2"} <= {r["project_id"] for r in results}
    p1 = next(r for r in results if r["project_id"] == "p1")
    p2 = next(r for r in results if r["project_id"] == "p2")
    assert p1["status"] == "error"
    assert "boom" in p1["error"]
    # p2 ran cleanly (no messages, but that's a clean status — not error).
    assert p2["status"] in ("no_messages", "compacted")
