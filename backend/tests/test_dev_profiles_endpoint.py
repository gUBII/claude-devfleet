"""Tests for GET /api/dev-profiles — public leaderboard endpoint."""

from __future__ import annotations

import importlib

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFLEET_FERNET_KEY", "LB3EdGLPlPohv-pv9m1f-BYRve1oS7_36Db1xaRs7N0=")
    monkeypatch.setenv("DEVFLEET_JWT_SECRET", "test-secret-for-pytest-only")

    import db as _db
    p = str(tmp_path / "dev_profiles_test.db")
    monkeypatch.setattr(_db, "DB_PATH", p)
    await _db.init_db()

    import app as _app_mod
    importlib.reload(_app_mod)

    from fastapi.testclient import TestClient
    client = TestClient(_app_mod.app)
    yield client, p
    client.close()


async def _login(client, email: str, password: str = "Test1234!", role: str = "user") -> str:
    import auth as _auth
    await _auth.create_user(email=email, password=password, role=role)
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


# ─── Auth gate ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dev_profiles_requires_auth(app_client):
    client, _ = app_client
    res = client.get("/api/dev-profiles")
    assert res.status_code == 401


# ─── Admin exclusion ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dev_profiles_excludes_admins(app_client):
    client, _ = app_client
    admin_tok = await _login(client, "boss@x.local", role="admin")
    _ = await _login(client, "dev@x.local")

    res = client.get(
        "/api/dev-profiles",
        headers={"Authorization": f"Bearer {admin_tok}"},
    )
    assert res.status_code == 200
    emails = {p["email"] for p in res.json()}
    assert "boss@x.local" not in emails
    assert "dev@x.local" in emails


# ─── Ordering ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dev_profiles_sorted_by_likeness_desc(app_client):
    client, _ = app_client
    _ = await _login(client, "low@x.local")
    high_tok = await _login(client, "high@x.local")

    import dev_metrics
    import auth as _auth
    low = await _auth.get_user_by_email("low@x.local")
    high = await _auth.get_user_by_email("high@x.local")
    await dev_metrics.increment_likeness(low["id"], 2)
    await dev_metrics.increment_likeness(high["id"], 20)

    res = client.get(
        "/api/dev-profiles",
        headers={"Authorization": f"Bearer {high_tok}"},
    )
    assert res.status_code == 200
    rows = res.json()
    assert rows[0]["email"] == "high@x.local"
    assert rows[1]["email"] == "low@x.local"


# ─── Avatar derivation ─────────────────────────────────────────────────────


def test_avatar_url_from_noreply_email():
    from app import _derive_avatar_url
    url = _derive_avatar_url("262498766+genesisprime01@users.noreply.github.com")
    assert url == "https://avatars.githubusercontent.com/u/262498766"


def test_avatar_url_blank_for_missing_or_malformed():
    from app import _derive_avatar_url
    assert _derive_avatar_url("") == ""
    assert _derive_avatar_url("plain@example.com") == ""
    assert _derive_avatar_url("notnumeric+x@users.noreply.github.com") == ""


# ─── Payload shape ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dev_profiles_payload_shape(app_client):
    client, _ = app_client
    tok = await _login(client, "dev@x.local")
    res = client.get(
        "/api/dev-profiles",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    row = body[0]
    expected_keys = {
        "user_id", "email", "display_name", "github_login", "github_name", "avatar_url",
        "likeness_points", "pr_merges_clean", "pr_merges_total",
        "dollars_saved_routing", "current_clean_streak", "longest_clean_streak",
    }
    assert set(row.keys()) == expected_keys
    # New user with no events → all zeroed
    assert row["likeness_points"] == 0
    assert row["dollars_saved_routing"] == 0
    # No invite display name set → empty string, not null
    assert row["display_name"] == ""
