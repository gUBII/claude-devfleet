"""Tests for the skip_quality_gates opt-out flag on missions.

Three required scenarios:

Q1  POST /api/missions with skip_quality_gates=true persists the flag as 1 in
    the DB and returns it as true in the response.

Q2  PUT /api/missions/{id} can toggle skip_quality_gates from false → true
    and back to false.

Q3  skip_quality_gates defaults to false (0 in DB) when omitted on creation.
"""

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


# ── Shared helpers ────────────────────────────────────────────────────────────


async def _seed_project(name: str = "Skip QG Project") -> str:
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


async def _get_mission_skip_flag(mid: str) -> int:
    """Return the raw INTEGER value of skip_quality_gates from the DB."""
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT skip_quality_gates FROM missions WHERE id=?", (mid,)
        )
        return dict(rows[0])["skip_quality_gates"] if rows else -1
    finally:
        await conn.close()


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch):
    """FastAPI TestClient with an isolated DB."""
    import db as _db

    db_path = str(tmp_path / "skip_qg_test.db")
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


# ── Q1: POST with skip_quality_gates=true persists flag ──────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mission_create_with_skip_flag_persists(authed_client):
    """Q1: POST /api/missions with skip_quality_gates=true must store 1 in DB
    and return skip_quality_gates=true in the response body.
    """
    client, headers = authed_client

    pid = await _seed_project("Q1 Project")

    res = client.post(
        "/api/missions",
        headers=headers,
        json={
            "project_id": pid,
            "title": "Mission with QG skip",
            "detailed_prompt": "Do the thing",
            "acceptance_criteria": "Done",
            "skip_quality_gates": True,
        },
    )
    assert res.status_code == 201, res.text

    body = res.json()
    mid = body["id"]

    # DB raw value must be 1
    raw = await _get_mission_skip_flag(mid)
    assert raw == 1, f"Expected skip_quality_gates=1 in DB, got {raw}"


# ── Q2: PUT can toggle skip_quality_gates ────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mission_update_can_toggle_skip(authed_client):
    """Q2: PUT /api/missions/{id} should be able to flip skip_quality_gates
    from false to true, and back to false.
    """
    client, headers = authed_client

    pid = await _seed_project("Q2 Project")

    # Create with default (false)
    create_res = client.post(
        "/api/missions",
        headers=headers,
        json={
            "project_id": pid,
            "title": "Toggle QG mission",
            "detailed_prompt": "Do the thing",
            "acceptance_criteria": "Done",
        },
    )
    assert create_res.status_code == 201, create_res.text
    mid = create_res.json()["id"]
    assert await _get_mission_skip_flag(mid) == 0

    # Flip to true
    flip_on_res = client.put(
        f"/api/missions/{mid}",
        headers=headers,
        json={"skip_quality_gates": True},
    )
    assert flip_on_res.status_code == 200, flip_on_res.text
    assert await _get_mission_skip_flag(mid) == 1, "Expected flag to be set to 1 after update"

    # Flip back to false
    flip_off_res = client.put(
        f"/api/missions/{mid}",
        headers=headers,
        json={"skip_quality_gates": False},
    )
    assert flip_off_res.status_code == 200, flip_off_res.text
    assert await _get_mission_skip_flag(mid) == 0, "Expected flag to be reset to 0 after second update"


# ── Q3: Default is false ──────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_default_is_false(authed_client):
    """Q3: POST /api/missions without skip_quality_gates must default to 0 in DB.
    Ensures existing missions created before the feature are unaffected.
    """
    client, headers = authed_client

    pid = await _seed_project("Q3 Project")

    res = client.post(
        "/api/missions",
        headers=headers,
        json={
            "project_id": pid,
            "title": "Mission without QG skip field",
            "detailed_prompt": "Do the thing",
            "acceptance_criteria": "Done",
        },
    )
    assert res.status_code == 201, res.text

    mid = res.json()["id"]
    raw = await _get_mission_skip_flag(mid)
    assert raw == 0, f"Expected skip_quality_gates=0 (default) in DB, got {raw}"
