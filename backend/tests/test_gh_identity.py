"""Tests for gh_identity.fetch_github_identity + auth.set_github_token wiring.

We stub httpx.AsyncClient so no network call leaves the test process. The
contract under test:

  - 200 with valid body → GitHubIdentity(login, name, noreply_email)
  - Non-200 → None
  - Network error → None
  - Empty token → None
  - set_github_token populates users.github_login/name/noreply_email
  - set_github_token failure path leaves columns empty but token persists
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db_path(tmp_path, monkeypatch):
    import db as _db
    p = str(tmp_path / "gh_identity_test.db")
    monkeypatch.setattr(_db, "DB_PATH", p)
    await _db.init_db()
    return p


def _mock_response(status_code: int, json_data: dict | None = None):
    resp = AsyncMock()
    resp.status_code = status_code
    if json_data is not None:
        resp.json = lambda: json_data
    else:
        resp.json = lambda: (_ for _ in ()).throw(ValueError("no body"))
    resp.text = "{}" if json_data else ""
    return resp


class _FakeClient:
    """Async-context-managed stand-in for httpx.AsyncClient."""

    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url: str, headers: dict[str, str] | None = None):
        return self._response


@pytest.mark.asyncio
async def test_fetch_returns_identity_on_200():
    from gh_identity import fetch_github_identity

    payload = {"login": "adil-mug", "id": 1234567, "name": "Adil M"}
    fake = _FakeClient(_mock_response(200, payload))

    with patch("gh_identity.httpx.AsyncClient", return_value=fake):
        identity = await fetch_github_identity("ghp_validtoken")

    assert identity is not None
    assert identity.login == "adil-mug"
    assert identity.name == "Adil M"
    assert identity.noreply_email == "1234567+adil-mug@users.noreply.github.com"


@pytest.mark.asyncio
async def test_fetch_falls_back_to_login_when_name_missing():
    from gh_identity import fetch_github_identity

    payload = {"login": "hasan-x", "id": 99, "name": None}
    fake = _FakeClient(_mock_response(200, payload))

    with patch("gh_identity.httpx.AsyncClient", return_value=fake):
        identity = await fetch_github_identity("ghp_token")

    assert identity is not None
    assert identity.name == "hasan-x"


@pytest.mark.asyncio
async def test_fetch_returns_none_on_non_200():
    from gh_identity import fetch_github_identity

    fake = _FakeClient(_mock_response(401, {"message": "Bad credentials"}))

    with patch("gh_identity.httpx.AsyncClient", return_value=fake):
        identity = await fetch_github_identity("ghp_bad")

    assert identity is None


@pytest.mark.asyncio
async def test_fetch_returns_none_on_network_error():
    from gh_identity import fetch_github_identity

    class _BoomClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise OSError("network down")

    with patch("gh_identity.httpx.AsyncClient", return_value=_BoomClient()):
        identity = await fetch_github_identity("ghp_token")

    assert identity is None


@pytest.mark.asyncio
async def test_fetch_returns_none_on_empty_token():
    from gh_identity import fetch_github_identity

    identity = await fetch_github_identity("")
    assert identity is None


@pytest.mark.asyncio
async def test_set_github_token_populates_identity_columns(db_path, monkeypatch):
    """Happy path: token saved + identity fields populated."""
    # crypto + auth require these env vars; gh_identity is mocked so no real call.
    monkeypatch.setenv("DEVFLEET_FERNET_KEY", "LB3EdGLPlPohv-pv9m1f-BYRve1oS7_36Db1xaRs7N0=")
    monkeypatch.setenv("DEVFLEET_JWT_SECRET", "test-secret-for-pytest-only")

    import importlib
    import auth as _auth
    import gh_identity as _gh
    importlib.reload(_gh)
    importlib.reload(_auth)

    user = await _auth.create_user(email="t@x.local", password="Test1234!", role="user")

    fake_identity = _gh.GitHubIdentity(
        login="t-login", name="T Name",
        noreply_email="42+t-login@users.noreply.github.com",
    )

    async def _fake_fetch(token: str, **kwargs):
        return fake_identity

    # auth.set_github_token does `from gh_identity import fetch_github_identity`
    # at call time, so patching the source module attribute is sufficient.
    monkeypatch.setattr("gh_identity.fetch_github_identity", _fake_fetch)

    await _auth.set_github_token(user["id"], "ghp_fakefakefakefake", "t-login")

    cached = await _auth.get_github_identity(user["id"])
    assert cached is not None
    assert cached["login"] == "t-login"
    assert cached["noreply_email"] == "42+t-login@users.noreply.github.com"


@pytest.mark.asyncio
async def test_set_github_token_failure_leaves_columns_empty(db_path, monkeypatch):
    """If GitHub /user is unreachable, token still persists; identity stays empty."""
    monkeypatch.setenv("DEVFLEET_FERNET_KEY", "LB3EdGLPlPohv-pv9m1f-BYRve1oS7_36Db1xaRs7N0=")
    monkeypatch.setenv("DEVFLEET_JWT_SECRET", "test-secret-for-pytest-only")

    import importlib
    import auth as _auth
    import gh_identity as _gh
    importlib.reload(_gh)
    importlib.reload(_auth)

    user = await _auth.create_user(email="u@x.local", password="Test1234!", role="user")

    async def _fake_fetch(token: str, **kwargs):
        return None  # simulate network/auth failure

    monkeypatch.setattr("gh_identity.fetch_github_identity", _fake_fetch)

    await _auth.set_github_token(user["id"], "ghp_fakefakefakefake", "u-login")

    # Token still stored
    tok = await _auth.get_github_token(user["id"])
    assert tok is not None
    assert tok[0] == "ghp_fakefakefakefake"

    # Identity stays empty
    assert await _auth.get_github_identity(user["id"]) is None
