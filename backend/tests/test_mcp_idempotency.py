"""Tests for Task #20 — idempotency keys on create_mission / dispatch_mission.

A client-supplied `idempotency_key` makes a retry safe: a second call with the
same key returns the original resource (success OR failure) instead of creating
a duplicate mission or spawning a second agent. New args are ignored on replay —
the key identifies one logical operation. The partial unique index is the
backstop against a concurrent double-create/double-spawn.
"""

import os
import sys

import pytest
import pytest_asyncio
import aiosqlite

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("DEVFLEET_JWT_SECRET", "test-secret-do-not-use-in-prod-only-for-pytest")
os.environ.setdefault("DEVFLEET_ALLOWED_ORIGINS", "*")
os.environ.setdefault(
    "DEVFLEET_FERNET_KEY", "__X8JO5yCVC_-lOwTC1a9Zn2QTsraiyp0mEY9WOjxcU="
)

from mcp_external import _create_mission, _dispatch_mission


@pytest_asyncio.fixture
async def db_conn():
    """In-memory DB with the v18 idempotency columns/indexes + one project and mission."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    import db as _db

    await conn.executescript(_db.SCHEMA)
    for stmt in (
        "ALTER TABLE missions ADD COLUMN skip_quality_gates INTEGER DEFAULT 0",
        "ALTER TABLE missions ADD COLUMN idempotency_key TEXT",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_missions_idempotency_key "
        "ON missions(idempotency_key) WHERE idempotency_key IS NOT NULL",
        "ALTER TABLE agent_sessions ADD COLUMN idempotency_key TEXT",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_idempotency_key "
        "ON agent_sessions(idempotency_key) WHERE idempotency_key IS NOT NULL",
    ):
        await conn.execute(stmt)
    await conn.execute(
        "INSERT INTO projects (id, name, path) VALUES (?, ?, ?)",
        ("p1", "proj", "/tmp/proj"),
    )
    await conn.execute(
        "INSERT INTO missions (id, project_id, title, detailed_prompt, status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("m1", "p1", "seed mission", "do it", "draft"),
    )
    await conn.commit()
    yield conn
    await conn.close()


async def _mission_count(conn, project_id="p1"):
    cur = await conn.execute(
        "SELECT COUNT(*) AS c FROM missions WHERE project_id = ?", (project_id,)
    )
    return (await cur.fetchone())["c"]


async def _session_count(conn, mission_id="m1"):
    cur = await conn.execute(
        "SELECT COUNT(*) AS c FROM agent_sessions WHERE mission_id = ?", (mission_id,)
    )
    return (await cur.fetchone())["c"]


# ── create_mission ──

async def test_create_without_key_allows_duplicates(db_conn):
    base = await _mission_count(db_conn)
    a = await _create_mission({"project_id": "p1", "title": "T", "prompt": "p"}, db_conn)
    b = await _create_mission({"project_id": "p1", "title": "T", "prompt": "p"}, db_conn)
    assert a["id"] != b["id"]
    assert a["idempotent_replay"] is False
    assert b["idempotent_replay"] is False
    assert await _mission_count(db_conn) == base + 2


async def test_create_same_key_returns_original(db_conn):
    base = await _mission_count(db_conn)
    a = await _create_mission(
        {"project_id": "p1", "title": "T", "prompt": "p", "idempotency_key": "k1"}, db_conn
    )
    b = await _create_mission(
        {"project_id": "p1", "title": "T", "prompt": "p", "idempotency_key": "k1"}, db_conn
    )
    assert a["idempotent_replay"] is False
    assert b["idempotent_replay"] is True
    assert b["id"] == a["id"]
    assert await _mission_count(db_conn) == base + 1  # only one created


async def test_create_replay_ignores_new_args(db_conn):
    a = await _create_mission(
        {"project_id": "p1", "title": "original", "prompt": "p", "idempotency_key": "k2"},
        db_conn,
    )
    b = await _create_mission(
        {"project_id": "p1", "title": "hijacked", "prompt": "p", "idempotency_key": "k2"},
        db_conn,
    )
    assert b["id"] == a["id"]
    assert b["title"] == "original"  # new title discarded on replay


async def test_create_replay_shape_matches_fresh(db_conn):
    a = await _create_mission(
        {
            "project_id": "p1",
            "title": "T",
            "prompt": "p",
            "lane": "reviewer",
            "idempotency_key": "k3",
        },
        db_conn,
    )
    b = await _create_mission(
        {"project_id": "p1", "title": "T", "prompt": "p", "idempotency_key": "k3"}, db_conn
    )
    assert set(a.keys()) == set(b.keys())  # replay re-derives the full shape
    assert b["lane"] == "reviewer"
    assert b["mission_number"] == a["mission_number"]


async def test_create_empty_key_is_treated_as_no_key(db_conn):
    base = await _mission_count(db_conn)
    a = await _create_mission(
        {"project_id": "p1", "title": "T", "prompt": "p", "idempotency_key": "  "}, db_conn
    )
    b = await _create_mission(
        {"project_id": "p1", "title": "T", "prompt": "p", "idempotency_key": ""}, db_conn
    )
    assert a["id"] != b["id"]
    assert await _mission_count(db_conn) == base + 2


async def test_unique_index_blocks_duplicate_mission_key(db_conn):
    # The partial unique index is the backstop for a concurrent double-create
    # that slips past the SELECT-then-insert check.
    await _create_mission(
        {"project_id": "p1", "title": "T", "prompt": "p", "idempotency_key": "u1"}, db_conn
    )
    with pytest.raises(aiosqlite.IntegrityError):
        await db_conn.execute(
            "INSERT INTO missions (id, project_id, title, detailed_prompt, idempotency_key) "
            "VALUES (?, ?, ?, ?, ?)",
            ("dup", "p1", "T", "p", "u1"),
        )


# ── dispatch_mission ──

async def _seed_session(conn, sid, status, key, model="claude-sonnet-4-6"):
    await conn.execute(
        "INSERT INTO agent_sessions (id, mission_id, status, model, idempotency_key) "
        "VALUES (?, ?, ?, ?, ?)",
        (sid, "m1", status, model, key),
    )
    await conn.commit()


async def test_dispatch_replay_returns_existing_running_session(db_conn):
    await _seed_session(db_conn, "s-running", "running", "d1")
    result = await _dispatch_mission({"mission_id": "m1", "idempotency_key": "d1"}, db_conn)
    assert result["idempotent_replay"] is True
    assert result["session_id"] == "s-running"
    assert result["session_status"] == "running"
    assert await _session_count(db_conn) == 1  # no new session spawned


async def test_dispatch_replay_returns_failed_session(db_conn):
    # Stripe-style contract: replay of a failed dispatch returns the failure; it
    # does NOT silently re-dispatch. A fresh key is required to retry.
    await _seed_session(db_conn, "s-failed", "failed", "d2")
    result = await _dispatch_mission({"mission_id": "m1", "idempotency_key": "d2"}, db_conn)
    assert result["idempotent_replay"] is True
    assert result["session_id"] == "s-failed"
    assert result["session_status"] == "failed"
    assert await _session_count(db_conn) == 1  # no re-dispatch
