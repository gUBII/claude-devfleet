"""Integration tests for POST /api/auth/me/change-password.

Verifies:
  - Happy path: correct current password updates the hash, new password
    is usable for login, old password is no longer accepted.
  - Wrong current password returns 403.
  - Missing JWT returns 401.
  - New password exceeding bcrypt's 72-byte hard limit returns 400, not 500.
"""

from __future__ import annotations

import os
import sys

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch):
    import db as _db
    db_path = str(tmp_path / "pw_test.db")
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
async def auth_token(app_client):
    """Create a user, login, return (client, headers, email, current_pw)."""
    import auth as _auth
    email = "pwtest@example.com"
    current_pw = "OriginalPass1!"
    await _auth.create_user(email=email, password=current_pw, role="user")
    res = app_client.post(
        "/api/auth/login", json={"email": email, "password": current_pw}
    )
    assert res.status_code == 200
    tok = res.json()["access_token"]
    return app_client, {"Authorization": f"Bearer {tok}"}, email, current_pw


@pytest.mark.integration
@pytest.mark.asyncio
async def test_change_password_happy_path(auth_token):
    client, headers, email, current_pw = auth_token
    new_pw = "BrandNewPass2!"

    res = client.post(
        "/api/auth/me/change-password",
        json={"current_password": current_pw, "new_password": new_pw},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    # Old password no longer works.
    res2 = client.post("/api/auth/login", json={"email": email, "password": current_pw})
    assert res2.status_code == 401

    # New password works.
    res3 = client.post("/api/auth/login", json={"email": email, "password": new_pw})
    assert res3.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_change_password_wrong_current_returns_403(auth_token):
    client, headers, _email, _current_pw = auth_token
    res = client.post(
        "/api/auth/me/change-password",
        json={"current_password": "WRONG", "new_password": "NewPass1!"},
        headers=headers,
    )
    assert res.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_change_password_requires_auth(app_client):
    res = app_client.post(
        "/api/auth/me/change-password",
        json={"current_password": "a", "new_password": "b"},
    )
    assert res.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_change_password_over_72_bytes_returns_400(auth_token):
    """bcrypt rejects >72-byte passwords; the route must surface that as
    a 400, never a 500."""
    client, headers, _email, current_pw = auth_token
    # 73-char ASCII string — exceeds 72-byte bcrypt limit.
    too_long = "a" * 73
    res = client.post(
        "/api/auth/me/change-password",
        json={"current_password": current_pw, "new_password": too_long},
        headers=headers,
    )
    # Pydantic max_length=72 catches it before the route — 422 is also fine.
    assert res.status_code in (400, 422)
