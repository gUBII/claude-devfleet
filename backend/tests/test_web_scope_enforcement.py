"""Web-route project-scope enforcement — the REST-surface parallel to
test_mcp_scope_enforcement.py.

The MCP boundary has long been scope-gated; the equivalent website routes
(POST /api/missions, POST /api/missions/{id}/dispatch) were auth-only until the
`_enforce_project_access` gates were added. These tests lock that contract so a
future refactor that drops the gate fails loudly.

Two layers:
- unit tests of the `_enforce_project_access` primitive (incl. the create-vs-
  dispatch `allow_localhost` difference), and
- integration tests driving the two gated routes through a TestClient.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException


def _fake_request(user=None, host="testclient"):
    """Minimal stand-in for a Starlette Request: only .state.user and
    .client.host are read by _enforce_project_access / _is_localhost."""
    return SimpleNamespace(
        state=SimpleNamespace(user=user),
        client=SimpleNamespace(host=host),
    )


# ── _enforce_project_access primitive (mirrors the MCP _enforce_scope unit tests) ──


@pytest.mark.asyncio
async def test_bound_or_admin_user_allowed(monkeypatch):
    import app
    import auth

    async def _has(uid, pid):
        return True

    monkeypatch.setattr(auth, "user_has_project_access", _has)
    # No raise == allowed.
    await app._enforce_project_access(
        _fake_request(user={"sub": "u1"}), "p1", allow_localhost=False
    )


@pytest.mark.asyncio
async def test_unbound_user_gets_404_not_403(monkeypatch):
    import app
    import auth

    async def _has(uid, pid):
        return False

    monkeypatch.setattr(auth, "user_has_project_access", _has)
    with pytest.raises(HTTPException) as exc:
        await app._enforce_project_access(
            _fake_request(user={"sub": "u1"}), "p1", allow_localhost=False
        )
    # 404 (not 403) so an unbound user can't even confirm the resource exists.
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_localhost_bypass_when_allowed_create_semantics():
    import app

    # create_mission passes allow_localhost=True so the in-process stdio MCP
    # server (create_sub_mission) can post unauthenticated over loopback.
    await app._enforce_project_access(
        _fake_request(user=None, host="127.0.0.1"), "p1", allow_localhost=True
    )


@pytest.mark.asyncio
async def test_no_localhost_bypass_dispatch_semantics():
    import app

    # dispatch passes allow_localhost=False: even a loopback unauthenticated call
    # is rejected, because nothing internal hits the dispatch REST route.
    with pytest.raises(HTTPException) as exc:
        await app._enforce_project_access(
            _fake_request(user=None, host="127.0.0.1"), "p1", allow_localhost=False
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_non_localhost_always_401():
    import app

    # allow_localhost=True still 401s a non-loopback unauthenticated caller.
    with pytest.raises(HTTPException) as exc:
        await app._enforce_project_access(
            _fake_request(user=None, host="203.0.113.7"), "p1", allow_localhost=True
        )
    assert exc.value.status_code == 401


# ── Integration: the two gated routes through a TestClient ──


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFLEET_FERNET_KEY", "__X8JO5yCVC_-lOwTC1a9Zn2QTsraiyp0mEY9WOjxcU=")
    monkeypatch.setenv("DEVFLEET_JWT_SECRET", "test-secret-for-pytest-only")

    import db as _db

    p = str(tmp_path / "web_scope_test.db")
    monkeypatch.setattr(_db, "DB_PATH", p)
    await _db.init_db()

    import app as _app_mod

    importlib.reload(_app_mod)

    from fastapi.testclient import TestClient

    client = TestClient(_app_mod.app)
    yield client
    client.close()


async def _login(client, email: str, role: str = "user", password: str = "Test1234!") -> str:
    import auth

    await auth.create_user(email=email, password=password, role=role)
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


async def _seed_project(pid: str = "p1", name: str = "proj", path: str = "/tmp/proj") -> None:
    import db

    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT INTO projects (id, name, path) VALUES (?, ?, ?)", (pid, name, path)
        )
        await conn.commit()
    finally:
        await conn.close()


async def _seed_draft_mission(mid: str = "m1", pid: str = "p1") -> None:
    import db

    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT INTO missions (id, project_id, title, detailed_prompt, status) "
            "VALUES (?, ?, ?, ?, 'draft')",
            (mid, pid, "Seed mission", "do the thing"),
        )
        await conn.commit()
    finally:
        await conn.close()


CREATE_BODY = {"project_id": "p1", "title": "New task", "detailed_prompt": "do it"}


@pytest.mark.asyncio
async def test_create_mission_unbound_user_404(app_client):
    await _seed_project()
    tok = await _login(app_client, "unbound@x.local")
    res = app_client.post(
        "/api/missions", json=CREATE_BODY, headers={"Authorization": f"Bearer {tok}"}
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_create_mission_bound_user_201(app_client):
    import auth

    await _seed_project()
    tok = await _login(app_client, "bound@x.local")
    user = await auth.get_user_by_email("bound@x.local")
    await auth.grant_project_access(user["id"], "p1", granted_by="test")

    res = app_client.post(
        "/api/missions", json=CREATE_BODY, headers={"Authorization": f"Bearer {tok}"}
    )
    assert res.status_code == 201
    assert res.json()["project_id"] == "p1"


@pytest.mark.asyncio
async def test_create_mission_admin_201(app_client):
    await _seed_project()
    tok = await _login(app_client, "admin@x.local", role="admin")
    res = app_client.post(
        "/api/missions", json=CREATE_BODY, headers={"Authorization": f"Bearer {tok}"}
    )
    assert res.status_code == 201


@pytest.mark.asyncio
async def test_create_mission_no_auth_401(app_client):
    await _seed_project()
    res = app_client.post("/api/missions", json=CREATE_BODY)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_dispatch_unbound_user_404_no_side_effects(app_client):
    await _seed_project()
    await _seed_draft_mission()
    tok = await _login(app_client, "unbound@x.local")

    res = app_client.post(
        "/api/missions/m1/dispatch", headers={"Authorization": f"Bearer {tok}"}
    )
    assert res.status_code == 404

    # Gate fires before any side-effect: no session row, mission still draft.
    import db

    conn = await db.get_db()
    try:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM agent_sessions WHERE mission_id='m1'"
        )
        assert (await cur.fetchone())[0] == 0
        cur = await conn.execute("SELECT status FROM missions WHERE id='m1'")
        assert (await cur.fetchone())[0] == "draft"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_dispatch_no_auth_401(app_client):
    await _seed_project()
    await _seed_draft_mission()
    res = app_client.post("/api/missions/m1/dispatch")
    assert res.status_code == 401
