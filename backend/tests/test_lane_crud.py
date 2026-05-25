"""Tests for user-created lanes (Fleet Config '+ New Lane' button).

Covers:
  - create_lane() validation: name format, built-in collision, duplicate
  - delete_lane() refuses built-ins regardless of user_created flag
  - init_db's disable-on-startup logic leaves user_created lanes alone
  - POST/DELETE endpoints enforce admin role
"""

from __future__ import annotations

import aiosqlite
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFLEET_FERNET_KEY", "LB3EdGLPlPohv-pv9m1f-BYRve1oS7_36Db1xaRs7N0=")
    monkeypatch.setenv("DEVFLEET_JWT_SECRET", "test-secret-for-pytest-only")

    import db as _db
    p = str(tmp_path / "lane_crud_test.db")
    monkeypatch.setattr(_db, "DB_PATH", p)
    await _db.init_db()

    import importlib
    import app as _app_mod
    importlib.reload(_app_mod)

    from fastapi.testclient import TestClient
    client = TestClient(_app_mod.app)
    yield client, p
    client.close()


# ─── Validation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_lane_happy_path(app_client):
    import lanes as _lanes

    row = await _lanes.create_lane(
        name="docs_writer", icon="📝", max_agents=2,
        default_model="claude-haiku-4-5-20251001",
    )
    assert row["name"] == "docs_writer"
    assert row["max_agents"] == 2
    assert row["icon"] == "📝"
    assert row["user_created"] == 1
    assert row["enabled"] == 1
    assert row["append_prompt"] == ""  # blank — Prompt Studio is the next step


@pytest.mark.asyncio
async def test_create_lane_rejects_built_in_name(app_client):
    import lanes as _lanes

    with pytest.raises(_lanes.LaneValidationError, match="built-in"):
        await _lanes.create_lane(name="coder")


@pytest.mark.asyncio
async def test_create_lane_rejects_bad_format(app_client):
    import lanes as _lanes

    bad_names = ["Has-Dash", "has space", "1starts_digit", "x", "a" * 40, ""]
    for bad in bad_names:
        with pytest.raises(_lanes.LaneValidationError):
            await _lanes.create_lane(name=bad)


@pytest.mark.asyncio
async def test_create_lane_refuses_duplicate(app_client):
    import lanes as _lanes

    await _lanes.create_lane(name="dup_lane")
    with pytest.raises(_lanes.LaneValidationError, match="already exists"):
        await _lanes.create_lane(name="dup_lane")


@pytest.mark.asyncio
async def test_create_lane_validates_max_agents(app_client):
    import lanes as _lanes

    with pytest.raises(_lanes.LaneValidationError, match="max_agents"):
        await _lanes.create_lane(name="zero_cap", max_agents=0)
    with pytest.raises(_lanes.LaneValidationError, match="max_agents"):
        await _lanes.create_lane(name="too_many", max_agents=100)


# ─── Deletion protection ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_lane_protects_builtins(app_client):
    import lanes as _lanes

    ok, reason = await _lanes.delete_lane("coder")
    assert ok is False
    assert "built-in" in reason


@pytest.mark.asyncio
async def test_delete_lane_user_created_succeeds(app_client):
    import lanes as _lanes

    await _lanes.create_lane(name="ephemeral")
    ok, reason = await _lanes.delete_lane("ephemeral")
    assert ok is True
    assert reason == ""
    assert (await _lanes.get_one_lane("ephemeral")) is None


@pytest.mark.asyncio
async def test_delete_lane_missing_returns_false(app_client):
    import lanes as _lanes

    ok, reason = await _lanes.delete_lane("never_existed")
    assert ok is False
    assert "not found" in reason


# ─── Restart safety ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_lane_survives_init_db_reseed(app_client, tmp_path, monkeypatch):
    """init_db's disable query must skip user_created lanes — otherwise every
    backend restart would silently disable everything Fleet Config created."""
    import lanes as _lanes
    import db as _db

    await _lanes.create_lane(name="restart_proof")
    # Re-run init_db on the same DB
    await _db.init_db()

    row = await _lanes.get_one_lane("restart_proof")
    assert row is not None
    assert row["enabled"] == 1
    assert row["user_created"] == 1


# ─── HTTP endpoints + admin gate ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_lanes_requires_admin(app_client):
    client, _ = app_client
    import auth as _auth

    # Non-admin user
    await _auth.create_user(email="u@x.local", password="Test1234!", role="user")
    res = client.post("/api/auth/login", json={"email": "u@x.local", "password": "Test1234!"})
    token = res.json()["access_token"]

    res = client.post(
        "/api/lanes",
        json={"name": "should_fail", "max_agents": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    assert "admin" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_post_lanes_admin_creates_lane(app_client):
    client, _ = app_client
    import auth as _auth

    await _auth.create_user(email="a@x.local", password="Test1234!", role="admin")
    res = client.post("/api/auth/login", json={"email": "a@x.local", "password": "Test1234!"})
    token = res.json()["access_token"]

    res = client.post(
        "/api/lanes",
        json={"name": "doc_lane", "max_agents": 2, "icon": "📚"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "doc_lane"
    assert body["user_created"] == 1


@pytest.mark.asyncio
async def test_delete_lane_endpoint_blocks_builtins(app_client):
    client, _ = app_client
    import auth as _auth

    await _auth.create_user(email="a@x.local", password="Test1234!", role="admin")
    res = client.post("/api/auth/login", json={"email": "a@x.local", "password": "Test1234!"})
    token = res.json()["access_token"]

    res = client.delete("/api/lanes/coder", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 409
    assert "built-in" in res.json()["detail"]
