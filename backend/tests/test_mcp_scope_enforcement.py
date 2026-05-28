"""Tests for Task 11 — MCP-external project-scope enforcement.

Covers `_enforce_scope`, the gate the mutating MCP tools (create_mission,
dispatch_mission, cancel_mission) call before touching a project. It resolves
`acting_user_email` / `created_by_email` and returns a SCOPE_DENIED envelope
when the acting user is not bound to the target project.

The unit tests monkeypatch the auth lookups so the gate logic is exercised in
isolation. One integration test drives `_dispatch_mission` against an in-memory
DB to prove the gate fires *before* any session row / status flip side-effect.
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

import auth
from mcp_external import _enforce_scope, _dispatch_mission


@pytest.fixture
def patch_auth(monkeypatch):
    """Controllable auth stubs. Mutate the returned dict per-test:
    `users` maps email→user dict (absent = unknown email); `access` maps
    (user_id, project_id)→bool."""
    state = {"users": {}, "access": {}}

    async def fake_get_user_by_email(email):
        return state["users"].get(email)

    async def fake_user_has_project_access(user_id, project_id):
        return state["access"].get((user_id, project_id), False)

    monkeypatch.setattr(auth, "get_user_by_email", fake_get_user_by_email)
    monkeypatch.setattr(auth, "user_has_project_access", fake_user_has_project_access)
    return state


# ── _enforce_scope unit tests ──

async def test_missing_email_allows_admin_equivalent(patch_auth):
    # No email at all → back-compat admin-equivalent fallback, allowed.
    assert await _enforce_scope("dispatch_mission", {}, "p1") is None


async def test_unknown_email_denied(patch_auth):
    # Explicit but unresolvable email must NOT be silently upgraded to admin.
    env = await _enforce_scope(
        "dispatch_mission", {"acting_user_email": "ghost@devfleet.local"}, "p1"
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "SCOPE_DENIED"
    assert "ghost@devfleet.local" in env["error"]["message"]


async def test_bound_user_allowed(patch_auth):
    patch_auth["users"]["hasan@devfleet.local"] = {"id": "u-hasan", "role": "user"}
    patch_auth["access"][("u-hasan", "p1")] = True
    assert (
        await _enforce_scope(
            "create_mission", {"created_by_email": "hasan@devfleet.local"}, "p1"
        )
        is None
    )


async def test_unbound_user_denied(patch_auth):
    patch_auth["users"]["hasan@devfleet.local"] = {"id": "u-hasan", "role": "user"}
    patch_auth["access"][("u-hasan", "p1")] = False
    env = await _enforce_scope(
        "create_mission", {"created_by_email": "hasan@devfleet.local"}, "p1"
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "SCOPE_DENIED"
    assert "hasan@devfleet.local" in env["error"]["message"]
    assert "p1" in env["error"]["message"]


async def test_acting_user_email_takes_precedence(patch_auth):
    # acting_user_email wins over created_by_email when both are present.
    patch_auth["users"]["adil@devfleet.local"] = {"id": "u-adil", "role": "user"}
    patch_auth["access"][("u-adil", "p1")] = False
    env = await _enforce_scope(
        "dispatch_mission",
        {
            "acting_user_email": "adil@devfleet.local",
            "created_by_email": "someone-bound@devfleet.local",
        },
        "p1",
    )
    assert env["error"]["code"] == "SCOPE_DENIED"
    assert "adil@devfleet.local" in env["error"]["message"]


async def test_no_project_id_skips_access_check(patch_auth):
    # Known user but no project to check against → allowed. (Unknown-email
    # denial still fires before this, see test_unknown_email_denied.)
    patch_auth["users"]["hasan@devfleet.local"] = {"id": "u-hasan", "role": "user"}
    assert (
        await _enforce_scope(
            "create_mission", {"created_by_email": "hasan@devfleet.local"}, None
        )
        is None
    )


# ── Integration: gate fires before side-effects in _dispatch_mission ──

@pytest_asyncio.fixture
async def seeded_db():
    """In-memory DB with one project and one draft mission."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    import db as _db

    await conn.executescript(_db.SCHEMA)
    await conn.execute(
        "INSERT INTO projects (id, name, path) VALUES (?, ?, ?)",
        ("p1", "test-project", "/tmp/test-project"),
    )
    await conn.execute(
        "INSERT INTO missions (id, project_id, title, detailed_prompt, status) "
        "VALUES (?, ?, ?, ?, ?)",
        ("m1", "p1", "Test mission", "do the thing", "draft"),
    )
    await conn.commit()
    yield conn
    await conn.close()


async def test_dispatch_denied_creates_no_session(patch_auth, seeded_db):
    # hasan is a real user but not bound to p1 → dispatch must be denied and
    # leave no agent_sessions row and the mission still 'draft'.
    patch_auth["users"]["hasan@devfleet.local"] = {"id": "u-hasan", "role": "user"}
    patch_auth["access"][("u-hasan", "p1")] = False

    result = await _dispatch_mission(
        {"mission_id": "m1", "acting_user_email": "hasan@devfleet.local"}, seeded_db
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "SCOPE_DENIED"

    cur = await seeded_db.execute("SELECT COUNT(*) AS c FROM agent_sessions WHERE mission_id = 'm1'")
    assert (await cur.fetchone())["c"] == 0
    cur = await seeded_db.execute("SELECT status FROM missions WHERE id = 'm1'")
    assert (await cur.fetchone())["status"] == "draft"
