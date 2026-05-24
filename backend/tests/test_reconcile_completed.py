"""Tests for POST /api/missions/{mid}/reconcile-completed — Bug 3 fix.

Three required scenarios:

R1  Happy path: endpoint flips mission + session rows, emits a 'reconciled'
    mission_event, and returns the IDs of newly-eligible child missions.

R2  Status guard: any status other than 'interrupted' → 409.  Covers the four
    cases mentioned in the spec: running, completed, failed, and draft.

R3  Watcher integration: after the reconcile DB writes complete,
    _find_eligible_missions actually surfaces the previously-blocked child.
"""

import asyncio
import json
import os
import sys
import uuid

import pytest
import pytest_asyncio

# Required env vars must be set before importing auth/app
os.environ.setdefault("DEVFLEET_JWT_SECRET", "test-secret-do-not-use-in-prod-only-for-pytest")
os.environ.setdefault("DEVFLEET_ALLOWED_ORIGINS", "*")
os.environ.setdefault(
    "DEVFLEET_FERNET_KEY", "__X8JO5yCVC_-lOwTC1a9Zn2QTsraiyp0mEY9WOjxcU="
)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import db
import mission_watcher


# ── Shared helpers ───────────────────────────────────────────────────────────


async def _seed_project(name: str = "Test Project") -> str:
    pid = str(uuid.uuid4())
    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT INTO projects (id, name, path) VALUES (?, ?, ?)",
            (pid, name, "/tmp/test"),
        )
        await conn.commit()
    finally:
        await conn.close()
    return pid


async def _seed_mission(
    project_id: str,
    status: str = "draft",
    auto_dispatch: int = 0,
    depends_on: list[str] | None = None,
    lane: str = "coder",
) -> str:
    mid = str(uuid.uuid4())
    conn = await db.get_db()
    try:
        await conn.execute(
            """INSERT INTO missions
               (id, project_id, title, detailed_prompt, status, lane, auto_dispatch, depends_on)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mid,
                project_id,
                "Test Mission",
                "Do something",
                status,
                lane,
                auto_dispatch,
                json.dumps(depends_on or []),
            ),
        )
        await conn.commit()
    finally:
        await conn.close()
    return mid


async def _seed_session(mission_id: str, status: str = "interrupted") -> str:
    sid = str(uuid.uuid4())
    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT INTO agent_sessions (id, mission_id, status) VALUES (?, ?, ?)",
            (sid, mission_id, status),
        )
        await conn.commit()
    finally:
        await conn.close()
    return sid


async def _get_mission_status(mid: str) -> str:
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT status FROM missions WHERE id=?", (mid,)
        )
        return dict(rows[0])["status"] if rows else ""
    finally:
        await conn.close()


async def _get_session(sid: str) -> dict:
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT status, exit_code, error_log FROM agent_sessions WHERE id=?", (sid,)
        )
        return dict(rows[0]) if rows else {}
    finally:
        await conn.close()


async def _get_reconcile_events(mid: str) -> list[dict]:
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT * FROM mission_events WHERE mission_id=? AND event_type='reconciled'",
            (mid,),
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


# ── R1: Happy path ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch):
    """FastAPI TestClient with an isolated DB and a pre-authenticated user."""
    import db as _db

    db_path = str(tmp_path / "reconcile_test.db")
    monkeypatch.setattr(_db, "DB_PATH", db_path)
    await _db.init_db()

    import importlib
    import app as _app_mod
    importlib.reload(_app_mod)

    from fastapi.testclient import TestClient
    client = TestClient(_app_mod.app)
    yield client
    client.close()


@pytest_asyncio.fixture
async def authed_client(app_client):
    """TestClient + Authorization header for a freshly-created admin user."""
    import auth as _auth

    email = f"admin-{uuid.uuid4().hex[:8]}@test.local"
    password = "Test1234!"
    await _auth.create_user(email=email, password=password, role="admin")
    token_data = app_client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    ).json()
    token = token_data["access_token"]
    return app_client, {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reconcile_flips_rows_emits_event_returns_children(
    authed_client,
):
    """R1: POST reconcile-completed on an interrupted mission should:
    - flip mission to 'completed'
    - flip the latest agent_session to 'completed' with the operator error_log
    - emit a 'reconciled' mission_event
    - return the IDs of newly-eligible child missions
    """
    client, headers = authed_client

    # Seed project, parent (interrupted) + its session, child (blocked)
    pid = await _seed_project("R1 Project")
    parent_id = await _seed_mission(pid, status="interrupted")
    session_id = await _seed_session(parent_id, status="interrupted")
    child_id = await _seed_mission(
        pid,
        status="draft",
        auto_dispatch=1,
        depends_on=[parent_id],
    )

    res = client.post(
        f"/api/missions/{parent_id}/reconcile-completed",
        headers=headers,
    )
    assert res.status_code == 200, res.text

    body = res.json()
    assert body["mission_id"] == parent_id
    assert body["prior_status"] == "interrupted"
    assert child_id in body["newly_eligible_children"]

    # DB: mission flipped
    assert await _get_mission_status(parent_id) == "completed"

    # DB: session flipped with correct fields
    session = await _get_session(session_id)
    assert session["status"] == "completed"
    assert session["exit_code"] == 0
    assert "Reconciled by operator" in (session["error_log"] or "")

    # DB: 'reconciled' event emitted
    events = await _get_reconcile_events(parent_id)
    assert len(events) == 1
    event_data = json.loads(events[0]["data"])
    assert event_data["prior_status"] == "interrupted"


# ── R2: Status guard ─────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_status",
    ["running", "completed", "failed", "draft"],
)
async def test_reconcile_rejects_non_interrupted_status(
    authed_client, bad_status: str
):
    """R2: Reconcile must return 409 for any status except 'interrupted'.

    Covers pending/running/completed/failed — all should be refused to prevent
    accidental progression of genuinely incomplete or already-done work.
    """
    client, headers = authed_client

    pid = await _seed_project(f"R2 Project {bad_status}")
    mid = await _seed_mission(pid, status=bad_status)

    res = client.post(
        f"/api/missions/{mid}/reconcile-completed",
        headers=headers,
    )
    assert res.status_code == 409, (
        f"Expected 409 for status='{bad_status}', got {res.status_code}: {res.text}"
    )
    detail = res.json().get("detail", "")
    assert bad_status in detail, f"Error message should mention the current status: {detail}"

    # Mission must be unchanged
    assert await _get_mission_status(mid) == bad_status


# ── R3: Watcher integration ──────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.unit
async def test_find_eligible_missions_unblocked_after_reconcile(tmp_db):
    """R3: After reconcile flips the parent to 'completed', _find_eligible_missions
    must surface the previously-blocked child mission.

    Before reconcile  → child is NOT in eligible list (parent still 'interrupted')
    After  reconcile  → child IS  in eligible list (parent now 'completed')
    """
    pid = await _seed_project("R3 Project")
    parent_id = await _seed_mission(pid, status="interrupted")
    child_id = await _seed_mission(
        pid,
        status="draft",
        auto_dispatch=1,
        depends_on=[parent_id],
        lane="coder",
    )

    # Before reconcile: parent is 'interrupted', not 'completed' → child blocked
    all_lanes_open = {"coder": 10, "reviewer": 10, "planner": 10, "default": 10}
    eligible_before = await mission_watcher._find_eligible_missions(dict(all_lanes_open))
    eligible_ids_before = [m["id"] for m in eligible_before]
    assert child_id not in eligible_ids_before, (
        "Child should be blocked while parent is 'interrupted'"
    )

    # Simulate the reconcile DB writes (what the endpoint does)
    conn = await db.get_db()
    try:
        await conn.execute(
            "UPDATE missions SET status='completed' WHERE id=?", (parent_id,)
        )
        await conn.commit()
    finally:
        await conn.close()

    # After reconcile: parent is 'completed' → child should be eligible
    eligible_after = await mission_watcher._find_eligible_missions(dict(all_lanes_open))
    eligible_ids_after = [m["id"] for m in eligible_after]
    assert child_id in eligible_ids_after, (
        "Child should be eligible once parent is 'completed'"
    )
