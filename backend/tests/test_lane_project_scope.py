"""Tests for project-scoped lanes (Epic A).

Covers:
  - create_lane(project_id=) persists the owner; NULL = global
  - list_lanes_for_project() = globals + that project's own lanes only
  - global lanes (built-ins) visible to every project + survive init_db re-run
  - name uniqueness stays GLOBAL (can't reuse a name across projects)
  - assert_lane_in_scope(): same-project ok, global ok, unknown ok, cross-project raises
  - GET /api/lanes?project_id= filters; bare GET returns all
  - create_mission rejects (400) a lane owned by another project; allows global + same-project
  - deleting a project removes its scoped lanes (and drops them from the cache)

Fixture mirrors test_lane_crud.py — runs the REAL db.init_db() so new migration
columns appear automatically (no hand-rolled schema to drift).
"""

from __future__ import annotations

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFLEET_FERNET_KEY", "LB3EdGLPlPohv-pv9m1f-BYRve1oS7_36Db1xaRs7N0=")
    monkeypatch.setenv("DEVFLEET_JWT_SECRET", "test-secret-for-pytest-only")

    import db as _db
    p = str(tmp_path / "lane_scope_test.db")
    monkeypatch.setattr(_db, "DB_PATH", p)
    await _db.init_db()

    # Lane cache is a module global — clear it so state can't leak from a prior test.
    import lanes as _lanes
    await _lanes.reload_cache()

    import importlib
    import app as _app_mod
    importlib.reload(_app_mod)

    from fastapi.testclient import TestClient
    client = TestClient(_app_mod.app)
    yield client, p
    client.close()


async def _mk_project(pid: str, name: str | None = None) -> None:
    """Insert a bare project row so a scoped lane's FK is satisfied."""
    import db as _db
    conn = await _db.get_db()
    try:
        await conn.execute(
            "INSERT INTO projects (id, name, path) VALUES (?, ?, ?)",
            (pid, name or pid, f"/tmp/{pid}"),
        )
        await conn.commit()
    finally:
        await conn.close()


async def _admin_token(client) -> str:
    import auth as _auth
    await _auth.create_user(email="admin@x.local", password="Test1234!", role="admin")
    res = client.post("/api/auth/login", json={"email": "admin@x.local", "password": "Test1234!"})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


# ─── create + persist ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_lane_persists_project_id(app_client):
    import lanes as _lanes
    await _mk_project("p1")

    row = await _lanes.create_lane(name="shift_expert", project_id="p1", max_agents=2)
    assert row["project_id"] == "p1"
    assert row["user_created"] == 1


@pytest.mark.asyncio
async def test_create_lane_without_project_is_global(app_client):
    import lanes as _lanes
    row = await _lanes.create_lane(name="global_helper")
    assert row["project_id"] is None


# ─── visibility / filtering ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_lanes_for_project_filters(app_client):
    import lanes as _lanes
    await _mk_project("p1")
    await _mk_project("p2")
    await _lanes.create_lane(name="p1_lane", project_id="p1")
    await _lanes.create_lane(name="p2_lane", project_id="p2")

    p1_names = {l["name"] for l in await _lanes.list_lanes_for_project("p1")}
    p2_names = {l["name"] for l in await _lanes.list_lanes_for_project("p2")}

    assert "p1_lane" in p1_names
    assert "p1_lane" not in p2_names
    assert "p2_lane" in p2_names
    assert "p2_lane" not in p1_names
    # Built-in globals are visible to both
    assert "coder" in p1_names and "coder" in p2_names


@pytest.mark.asyncio
async def test_builtins_are_global_and_survive_restart(app_client):
    import lanes as _lanes
    import db as _db

    coder = await _lanes.get_one_lane("coder")
    assert coder is not None
    assert coder["project_id"] is None

    await _lanes.create_lane(name="restart_scoped", project_id=None)
    await _db.init_db()  # re-run migrations/seed on the same DB

    coder2 = await _lanes.get_one_lane("coder")
    assert coder2["project_id"] is None
    assert coder2["enabled"] == 1


@pytest.mark.asyncio
async def test_lane_name_uniqueness_is_global(app_client):
    """Names stay globally unique — a project can't reuse another's lane name."""
    import lanes as _lanes
    await _mk_project("p1")
    await _mk_project("p2")
    await _lanes.create_lane(name="dup", project_id="p1")
    with pytest.raises(_lanes.LaneValidationError, match="already exists"):
        await _lanes.create_lane(name="dup", project_id="p2")


# ─── the scope guard ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assert_lane_in_scope(app_client):
    import lanes as _lanes
    await _mk_project("p1")
    await _mk_project("p2")
    await _lanes.create_lane(name="p1_only", project_id="p1")

    # same project → ok
    await _lanes.assert_lane_in_scope("p1_only", "p1")
    # global lane → ok from any project
    await _lanes.assert_lane_in_scope("coder", "p2")
    # unknown name (derive_lane falls back to coder) → ok
    await _lanes.assert_lane_in_scope("does_not_exist", "p2")
    # empty → ok
    await _lanes.assert_lane_in_scope("", "p2")
    # cross-project → raises
    with pytest.raises(_lanes.LaneValidationError, match="another project"):
        await _lanes.assert_lane_in_scope("p1_only", "p2")


# ─── HTTP: GET filter ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_lanes_project_filter(app_client):
    import lanes as _lanes
    client, _ = app_client
    await _mk_project("p1")
    await _mk_project("p2")
    await _lanes.create_lane(name="p1_lane", project_id="p1")

    scoped = client.get("/api/lanes?project_id=p1").json()
    names = {l["name"] for l in scoped}
    assert "p1_lane" in names
    assert "coder" in names  # globals included

    other = {l["name"] for l in client.get("/api/lanes?project_id=p2").json()}
    assert "p1_lane" not in other

    all_lanes = {l["name"] for l in client.get("/api/lanes").json()}
    assert "p1_lane" in all_lanes  # bare GET returns everything


# ─── HTTP: create_mission scope enforcement ────────────────────────────────


@pytest.mark.asyncio
async def test_create_mission_rejects_foreign_project_lane(app_client):
    import lanes as _lanes
    client, _ = app_client
    token = await _admin_token(client)  # admin bypasses project-access gate
    await _mk_project("pA", "Project A")
    await _mk_project("pB", "Project B")
    await _lanes.create_lane(name="a_special", project_id="pA")

    headers = {"Authorization": f"Bearer {token}"}

    # Project B trying to use Project A's lane → 400
    res = client.post("/api/missions", json={
        "project_id": "pB", "title": "x", "detailed_prompt": "y", "lane": "a_special",
    }, headers=headers)
    assert res.status_code == 400, res.text
    assert "another project" in res.json()["detail"]

    # Same project → allowed
    ok = client.post("/api/missions", json={
        "project_id": "pA", "title": "x", "detailed_prompt": "y", "lane": "a_special",
    }, headers=headers)
    assert ok.status_code == 201, ok.text

    # Global lane from any project → allowed
    glob = client.post("/api/missions", json={
        "project_id": "pB", "title": "x", "detailed_prompt": "y", "lane": "coder",
    }, headers=headers)
    assert glob.status_code == 201, glob.text


# ─── HTTP: project delete cascades scoped lanes ────────────────────────────


@pytest.mark.asyncio
async def test_delete_project_removes_scoped_lanes(app_client):
    import lanes as _lanes
    client, _ = app_client
    token = await _admin_token(client)
    await _mk_project("pdel")
    await _lanes.create_lane(name="doomed_lane", project_id="pdel")
    assert await _lanes.get_one_lane("doomed_lane") is not None

    res = client.delete("/api/projects/pdel", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 204, res.text

    assert await _lanes.get_one_lane("doomed_lane") is None
    # And it's gone from the live cache / snapshot
    assert "doomed_lane" not in {l["name"] for l in await _lanes.snapshot()}
