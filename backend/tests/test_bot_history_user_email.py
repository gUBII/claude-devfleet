"""GET /api/projects/{pid}/bot-history must include user_email per row.

Shared project chat (multiple users posting into the same project) needs
per-row attribution. The endpoint LEFT JOINs users so legacy rows with a
NULL user_id still come back with user_email=''.
"""

import aiosqlite
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch):
    import db as _db
    db_path = str(tmp_path / "app_test.db")
    monkeypatch.setattr(_db, "DB_PATH", db_path)
    await _db.init_db()

    import importlib
    import app as _app_mod
    importlib.reload(_app_mod)

    from fastapi.testclient import TestClient
    client = TestClient(_app_mod.app)
    yield client, db_path
    client.close()


@pytest.mark.asyncio
async def test_bot_history_returns_user_email_per_row(app_client):
    client, db_path = app_client
    import auth as _auth

    # Two users so we can verify per-row attribution
    farhan = await _auth.create_user(email="farhan@devfleet.local", password="Test1234!", role="admin")
    hasan = await _auth.create_user(email="hasan@devfleet.local", password="Test1234!", role="user")

    # Seed a project and a few chat rows directly
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO projects (id, name, path) VALUES ('p1', 'Shared', '/tmp')"
        )
        await conn.execute(
            "INSERT INTO project_bot_history "
            "(project_id, role, content, user_id, persona) VALUES "
            "('p1', 'user', 'hello from farhan', ?, 'user')",
            (farhan["id"],),
        )
        await conn.execute(
            "INSERT INTO project_bot_history "
            "(project_id, role, content, user_id, persona) VALUES "
            "('p1', 'assistant', 'reply 1', ?, 'researcher')",
            (farhan["id"],),
        )
        await conn.execute(
            "INSERT INTO project_bot_history "
            "(project_id, role, content, user_id, persona) VALUES "
            "('p1', 'user', 'hello from hasan', ?, 'user')",
            (hasan["id"],),
        )
        # Legacy row with NULL user_id (pre-RBAC) — must still come back
        await conn.execute(
            "INSERT INTO project_bot_history "
            "(project_id, role, content, user_id, persona) VALUES "
            "('p1', 'assistant', 'pre-RBAC row', NULL, 'researcher')"
        )
        await conn.commit()

    # Login as farhan to get a real Bearer token
    res = client.post(
        "/api/auth/login",
        json={"email": "farhan@devfleet.local", "password": "Test1234!"},
    )
    assert res.status_code == 200
    token = res.json()["access_token"]

    res = client.get(
        "/api/projects/p1/bot-history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert len(rows) == 4

    by_content = {r["content"]: r for r in rows}
    assert by_content["hello from farhan"]["user_email"] == "farhan@devfleet.local"
    assert by_content["hello from hasan"]["user_email"] == "hasan@devfleet.local"
    # Legacy NULL user_id row → empty string, not missing key
    assert by_content["pre-RBAC row"]["user_email"] == ""
    # Every row must carry the field (so the frontend can rely on it)
    for r in rows:
        assert "user_email" in r
        assert "user_id" in r
        assert "github_login" in r


@pytest.mark.asyncio
async def test_bot_history_returns_github_login_when_populated(app_client):
    client, db_path = app_client
    import auth as _auth

    user = await _auth.create_user(
        email="adil@devfleet.local", password="Test1234!", role="user",
    )

    # Seed identity columns directly — gh_identity fetch is mocked elsewhere.
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "UPDATE users SET github_login=?, github_name=?, github_noreply_email=? "
            "WHERE id=?",
            ("adil-mug", "Adil M",
             "1234567+adil-mug@users.noreply.github.com", user["id"]),
        )
        await conn.execute(
            "INSERT INTO projects (id, name, path) VALUES ('p2', 'Shared', '/tmp')"
        )
        await conn.execute(
            "INSERT INTO project_bot_history "
            "(project_id, role, content, user_id, persona) VALUES "
            "('p2', 'user', 'wired', ?, 'user')",
            (user["id"],),
        )
        await conn.commit()

    res = client.post(
        "/api/auth/login",
        json={"email": "adil@devfleet.local", "password": "Test1234!"},
    )
    assert res.status_code == 200
    token = res.json()["access_token"]

    res = client.get(
        "/api/projects/p2/bot-history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["github_login"] == "adil-mug"
    assert rows[0]["user_email"] == "adil@devfleet.local"
