"""Tests for the invite-onboarding feature (named invite → personal folder →
leaderboard identity → peer sharing).

Phase coverage:
  P1  invite token carries display_name + folder_name end-to-end
  P2  register auto-provisions an owned, bound personal git folder; the saga
      rolls back user + releases the token when provisioning fails
  P2  provision_personal_project: slug collision, empty-slug fallback,
      path-traversal containment, git `main` + seed commit
  P3  leaderboard (/api/dev-profiles) surfaces the display_name
  P4  peer project sharing — owner-or-admin authority, owner non-removable
  P5  worker (lane) clone — field/tool fidelity, source guard, name collision,
      target-authority gate

Fixture runs the REAL db.init_db() so new migration columns (users.display_name,
invite_tokens.display_name/folder_name, projects.created_by) appear automatically
— no hand-rolled schema to drift (see test-fixture-migration-drift).
"""

from __future__ import annotations

import importlib
import os

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFLEET_FERNET_KEY", "LB3EdGLPlPohv-pv9m1f-BYRve1oS7_36Db1xaRs7N0=")
    monkeypatch.setenv("DEVFLEET_JWT_SECRET", "test-secret-for-pytest-only")
    # Sandbox every personal folder provisioning does real git+fs work in.
    projects_dir = str(tmp_path / "projects")
    monkeypatch.setenv("DEVFLEET_PROJECTS_DIR", projects_dir)

    import db as _db
    p = str(tmp_path / "invite_onboarding_test.db")
    monkeypatch.setattr(_db, "DB_PATH", p)
    await _db.init_db()

    # Lane cache is a module global — clear it so state can't leak across tests.
    import lanes as _lanes
    await _lanes.reload_cache()

    import app as _app_mod
    importlib.reload(_app_mod)

    from fastapi.testclient import TestClient
    client = TestClient(_app_mod.app)
    yield client, p, projects_dir
    client.close()


# ─── helpers ───────────────────────────────────────────────────────────────


async def _mk_user(email: str, role: str = "user", password: str = "Test1234!") -> dict:
    import auth as _auth
    return await _auth.create_user(email=email, password=password, role=role)


def _login(client, email: str, password: str = "Test1234!") -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


async def _token(client, email: str, role: str = "user", password: str = "Test1234!") -> str:
    await _mk_user(email, role=role, password=password)
    return _login(client, email, password)


async def _mk_project(pid: str, name: str | None = None, created_by: str = "") -> None:
    import db as _db
    conn = await _db.get_db()
    try:
        await conn.execute(
            "INSERT INTO projects (id, name, path, created_by) VALUES (?, ?, ?, ?)",
            (pid, name or pid, f"/tmp/{pid}", created_by),
        )
        await conn.commit()
    finally:
        await conn.close()


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════════════
# P1 — invite carries the name
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_invite_token_carries_name_and_folder(app_client):
    """create_invite_token persists display_name + folder_name; consume returns them."""
    import auth as _auth
    admin = await _mk_user("admin@x.local", role="admin")

    token = await _auth.create_invite_token(
        admin["id"], display_name="Alice Wong", folder_name="alice-ws"
    )
    consumer = await _mk_user("alice@x.local")
    row = await _auth.consume_invite_token(token, consumer["id"])

    assert row is not None
    assert row["display_name"] == "Alice Wong"
    assert row["folder_name"] == "alice-ws"


@pytest.mark.asyncio
async def test_admin_invite_endpoint_requires_admin(app_client):
    client, _, _ = app_client
    user_tok = await _token(client, "plain@x.local")
    res = client.post(
        "/api/auth/invite",
        json={"display_name": "Nope"},
        headers=_auth_header(user_tok),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_admin_invite_endpoint_returns_relative_path(app_client):
    client, _, _ = app_client
    admin_tok = await _token(client, "admin@x.local", role="admin")
    res = client.post(
        "/api/auth/invite",
        json={"display_name": "Bob Lee", "folder_name": "bob"},
        headers=_auth_header(admin_tok),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["display_name"] == "Bob Lee"
    # Relative path only — the SPA composes the absolute URL from its own origin.
    assert body["invite_path"] == f"/?invite={body['invite_token']}"
    assert body["invite_path"].startswith("/?invite=")


@pytest.mark.asyncio
async def test_invite_strips_control_chars_from_name(app_client):
    """InviteCreate scrubs Unicode control/format chars (newlines, NUL, zero-width,
    RTL override) from display_name + folder_name so they can't poison the
    leaderboard or the git metadata provisioning writes."""
    client, _, _ = app_client
    import auth as _auth
    admin_tok = await _token(client, "admin@x.local", role="admin")

    dirty_name = "Mal​ici‮ous\nName\x00"
    res = client.post(
        "/api/auth/invite",
        json={"display_name": dirty_name, "folder_name": "fold\ter\x07"},
        headers=_auth_header(admin_tok),
    )
    assert res.status_code == 200, res.text
    # Visible glyphs survive; all control/format chars are gone.
    assert res.json()["display_name"] == "MaliciousName"

    token = res.json()["invite_token"]
    consumer = await _mk_user("consumer@x.local")
    row = await _auth.consume_invite_token(token, consumer["id"])
    assert row["display_name"] == "MaliciousName"
    assert row["folder_name"] == "folder"

    # A name that is ALL control chars has no visible content → rejected (422).
    rejected = client.post(
        "/api/auth/invite",
        json={"display_name": "\n\t\x00"},
        headers=_auth_header(admin_tok),
    )
    assert rejected.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# P2 — register auto-provisions folder + binding + display_name
# ═══════════════════════════════════════════════════════════════════════════


def _mint_invite(client, admin_tok: str, display_name: str, folder_name: str = "") -> str:
    payload = {"display_name": display_name}
    if folder_name:
        payload["folder_name"] = folder_name
    res = client.post("/api/auth/invite", json=payload, headers=_auth_header(admin_tok))
    assert res.status_code == 200, res.text
    return res.json()["invite_token"]


@pytest.mark.asyncio
async def test_register_provisions_owned_bound_folder(app_client):
    client, _, projects_dir = app_client
    import auth as _auth

    admin_tok = await _token(client, "admin@x.local", role="admin")
    invite = _mint_invite(client, admin_tok, "Carol Diaz", "carol")

    res = client.post(
        "/api/auth/register",
        json={"email": "carol@x.local", "password": "Test1234!", "invite_token": invite},
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["user"]["display_name"] == "Carol Diaz"
    uid = payload["user"]["id"]

    # display_name stamped on the user row
    user = await _auth.get_user_by_id(uid)
    assert user["display_name"] == "Carol Diaz"

    # A personal project exists, owned by the user, and bound to them.
    bindings = await _auth.list_user_project_bindings(uid)
    assert len(bindings) == 1
    proj = await _project_row(bindings[0]["project_id"])
    assert proj["created_by"] == uid
    assert proj["name"] == "Carol Diaz's Workspace"
    # Folder lives under the sandboxed projects base and is a git repo on `main`.
    assert proj["path"].startswith(os.path.realpath(projects_dir))
    assert os.path.isdir(os.path.join(proj["path"], ".git"))
    branch = _git(proj["path"], "rev-parse", "--abbrev-ref", "HEAD")
    assert branch == "main"
    count = _git(proj["path"], "rev-list", "--count", "HEAD")
    assert count == "1"  # exactly one seed commit


@pytest.mark.asyncio
async def test_register_saga_rolls_back_and_releases_token(app_client):
    """When provisioning fails, register must delete the user AND release the
    invite token — so the same link (and email) works on a retry."""
    client, _, _ = app_client
    import auth as _auth
    import provisioning as _prov

    admin_tok = await _token(client, "admin@x.local", role="admin")
    invite = _mint_invite(client, admin_tok, "Dan Frost", "dan")

    # Fail the FIRST provisioning attempt only; the retry uses the real one.
    real = _prov.provision_personal_project
    calls = {"n": 0}

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk full")
        return await real(*a, **k)

    # register does `from provisioning import provision_personal_project` per call,
    # so patching the module attribute is picked up on each invocation.
    import app as _app_mod
    monkey = pytest.MonkeyPatch()
    monkey.setattr(_prov, "provision_personal_project", flaky)
    try:
        fail = client.post(
            "/api/auth/register",
            json={"email": "dan@x.local", "password": "Test1234!", "invite_token": invite},
        )
        assert fail.status_code == 500, fail.text
        # User rolled back — email is free again.
        assert await _auth.get_user_by_email("dan@x.local") is None

        # Retry with the SAME token + email now succeeds → token was released and
        # the orphaned user was cleaned up.
        ok = client.post(
            "/api/auth/register",
            json={"email": "dan@x.local", "password": "Test1234!", "invite_token": invite},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["user"]["display_name"] == "Dan Frost"
    finally:
        monkey.undo()


@pytest.mark.asyncio
async def test_register_rolls_back_when_display_name_stamp_fails(app_client):
    """The name stamp lives inside the saga try, so if it fails the whole register
    rolls back — user deleted, token released — exactly like a provisioning fault.
    Guards against the name-stamp drifting back outside the rollback boundary."""
    client, _, _ = app_client
    import auth as _auth

    admin_tok = await _token(client, "admin@x.local", role="admin")
    invite = _mint_invite(client, admin_tok, "Erin Stamp", "erin")

    real = _auth.set_user_display_name
    calls = {"n": 0}

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("write failed")
        return await real(*a, **k)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(_auth, "set_user_display_name", flaky)
    try:
        fail = client.post(
            "/api/auth/register",
            json={"email": "erin@x.local", "password": "Test1234!", "invite_token": invite},
        )
        assert fail.status_code == 500, fail.text
        # User rolled back even though create_user already succeeded.
        assert await _auth.get_user_by_email("erin@x.local") is None
        # Token was released — same link + email succeeds on retry.
        ok = client.post(
            "/api/auth/register",
            json={"email": "erin@x.local", "password": "Test1234!", "invite_token": invite},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["user"]["display_name"] == "Erin Stamp"
    finally:
        monkey.undo()


@pytest.mark.asyncio
async def test_register_rollback_tolerates_a_failing_cleanup_step(app_client):
    """Fault-tolerant rollback: if a cleanup step (release_invite_token) itself
    throws, register must still (a) return the clean 500 — the cleanup exception
    must not mask it — and (b) still ATTEMPT the user delete. The orphan is NOT
    guaranteed gone when release fails (the FK then blocks the delete); the point
    is the endpoint degrades gracefully instead of crashing on the masking error.
    Under the pre-fix code, release's RuntimeError propagated unhandled and the
    user delete was skipped entirely."""
    client, _, _ = app_client
    import auth as _auth
    import provisioning as _prov
    import app as _app_mod

    admin_tok = await _token(client, "admin@x.local", role="admin")
    invite = _mint_invite(client, admin_tok, "Gail Toss", "gail")

    async def boom_provision(*a, **k):
        raise RuntimeError("disk full")

    async def boom_release(*a, **k):
        raise RuntimeError("db locked during rollback")

    delete_calls = {"n": 0}

    async def spy_delete(user_id):
        delete_calls["n"] += 1  # record the attempt; no-op so the FK can't interfere

    monkey = pytest.MonkeyPatch()
    monkey.setattr(_prov, "provision_personal_project", boom_provision)
    monkey.setattr(_auth, "release_invite_token", boom_release)
    monkey.setattr(_app_mod, "_delete_user", spy_delete)
    try:
        res = client.post(
            "/api/auth/register",
            json={"email": "gail@x.local", "password": "Test1234!", "invite_token": invite},
        )
        # Clean 500 carrying our detail — proves the release exception was caught,
        # not re-raised as a masking unhandled 500.
        assert res.status_code == 500, res.text
        assert res.json()["detail"] == "Registration failed — please try again"
        # The user delete was still attempted even though release threw first.
        assert delete_calls["n"] == 1
    finally:
        monkey.undo()


@pytest.mark.asyncio
async def test_register_invalid_token_creates_no_orphan(app_client):
    client, _, _ = app_client
    import auth as _auth
    res = client.post(
        "/api/auth/register",
        json={"email": "ghost@x.local", "password": "Test1234!", "invite_token": "bogus"},
    )
    assert res.status_code == 400
    # No half-created account left behind.
    assert await _auth.get_user_by_email("ghost@x.local") is None


# ─── provisioning unit behaviour ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provision_collision_suffixes_folder(app_client):
    import provisioning as _prov
    u1 = await _mk_user("p1@x.local")
    u2 = await _mk_user("p2@x.local")

    a = await _prov.provision_personal_project(u1["id"], "Same Name")
    b = await _prov.provision_personal_project(u2["id"], "Same Name")

    assert a["slug"] == "same-name"
    assert b["slug"] == "same-name-2"
    assert a["path"] != b["path"]
    assert os.path.isdir(a["path"]) and os.path.isdir(b["path"])


@pytest.mark.asyncio
async def test_provision_empty_slug_falls_back_to_user_id(app_client):
    """A name that slugifies to empty (all punctuation / non-Latin) must still
    yield a safe, unique folder keyed off the user id — never a path escape."""
    import provisioning as _prov
    u = await _mk_user("dots@x.local")
    res = await _prov.provision_personal_project(u["id"], "...")
    assert res["slug"] == f"user-{u['id'][:8]}"
    assert os.path.isdir(res["path"])


@pytest.mark.asyncio
async def test_provision_path_traversal_is_contained(app_client):
    import provisioning as _prov
    u = await _mk_user("eve@x.local")
    res = await _prov.provision_personal_project(u["id"], "../../etc/evil")
    base = os.path.realpath(os.environ["DEVFLEET_PROJECTS_DIR"])
    # Resolved folder never escapes the projects base.
    assert os.path.commonpath([base, os.path.realpath(res["path"])]) == base


# ═══════════════════════════════════════════════════════════════════════════
# P3 — leaderboard shows the name
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_leaderboard_surfaces_display_name(app_client):
    client, _, _ = app_client
    import auth as _auth

    tok = await _token(client, "dev@x.local")
    user = await _auth.get_user_by_email("dev@x.local")
    await _auth.set_user_display_name(user["id"], "Display Dev")

    res = client.get("/api/dev-profiles", headers=_auth_header(tok))
    assert res.status_code == 200
    rows = res.json()
    mine = next(r for r in rows if r["email"] == "dev@x.local")
    assert mine["display_name"] == "Display Dev"


# ═══════════════════════════════════════════════════════════════════════════
# P4 — peer project sharing
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_owner_can_share_and_list_peers(app_client):
    client, _, _ = app_client
    import auth as _auth

    owner = await _mk_user("owner@x.local")
    peer = await _mk_user("peer@x.local")
    owner_tok = _login(client, "owner@x.local")
    await _mk_project("proj-own", "Owned", created_by=owner["id"])
    # Owner is bound to their own project (mirrors provisioning's grant).
    await _auth.grant_project_access(owner["id"], "proj-own", granted_by=owner["id"])

    res = client.post(
        "/api/projects/proj-own/share",
        json={"user_id": peer["id"]},
        headers=_auth_header(owner_tok),
    )
    assert res.status_code == 201, res.text

    listed = client.get("/api/projects/proj-own/share", headers=_auth_header(owner_tok))
    assert listed.status_code == 200
    ids = {s["user_id"] for s in listed.json()}
    assert owner["id"] in ids and peer["id"] in ids


@pytest.mark.asyncio
async def test_shared_in_collaborator_cannot_reshare(app_client):
    """A user who was shared INTO a project can use it but is not owner-or-admin,
    so the sharing endpoints must 403 for them."""
    client, _, _ = app_client
    import auth as _auth

    owner = await _mk_user("owner@x.local")
    peer = await _mk_user("peer@x.local")
    third = await _mk_user("third@x.local")
    await _mk_project("proj-own", "Owned", created_by=owner["id"])
    # Peer is granted access (shared in) but does NOT own the project.
    await _auth.grant_project_access(peer["id"], "proj-own", granted_by=owner["id"])
    peer_tok = _login(client, "peer@x.local")

    # Can't even list shares.
    assert client.get(
        "/api/projects/proj-own/share", headers=_auth_header(peer_tok)
    ).status_code == 403
    # Can't re-share to a third party.
    assert client.post(
        "/api/projects/proj-own/share",
        json={"user_id": third["id"]},
        headers=_auth_header(peer_tok),
    ).status_code == 403


@pytest.mark.asyncio
async def test_admin_can_share_project_they_dont_own(app_client):
    client, _, _ = app_client
    owner = await _mk_user("owner@x.local")
    peer = await _mk_user("peer@x.local")
    admin_tok = await _token(client, "admin@x.local", role="admin")
    await _mk_project("proj-own", "Owned", created_by=owner["id"])

    res = client.post(
        "/api/projects/proj-own/share",
        json={"user_id": peer["id"]},
        headers=_auth_header(admin_tok),
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_unshare_revokes_but_owner_is_protected(app_client):
    client, _, _ = app_client
    import auth as _auth

    owner = await _mk_user("owner@x.local")
    peer = await _mk_user("peer@x.local")
    owner_tok = _login(client, "owner@x.local")
    await _mk_project("proj-own", "Owned", created_by=owner["id"])
    await _auth.grant_project_access(owner["id"], "proj-own", granted_by=owner["id"])
    await _auth.grant_project_access(peer["id"], "proj-own", granted_by=owner["id"])

    # Revoking the peer works (204) and removes the binding.
    revoke = client.request(
        "DELETE",
        "/api/projects/proj-own/share",
        json={"user_id": peer["id"]},
        headers=_auth_header(owner_tok),
    )
    assert revoke.status_code == 204, revoke.text
    assert await _auth.user_has_project_access(peer["id"], "proj-own") is False

    # Revoking the OWNER is refused — it would hide their own project from them.
    protect = client.request(
        "DELETE",
        "/api/projects/proj-own/share",
        json={"user_id": owner["id"]},
        headers=_auth_header(owner_tok),
    )
    assert protect.status_code == 400
    assert await _auth.user_has_project_access(owner["id"], "proj-own") is True


@pytest.mark.asyncio
async def test_share_unknown_user_and_project_404(app_client):
    client, _, _ = app_client
    owner = await _mk_user("owner@x.local")
    owner_tok = _login(client, "owner@x.local")
    await _mk_project("proj-own", "Owned", created_by=owner["id"])

    # Unknown target user → 404.
    bad_user = client.post(
        "/api/projects/proj-own/share",
        json={"user_id": "no-such-user"},
        headers=_auth_header(owner_tok),
    )
    assert bad_user.status_code == 404
    # Unknown project → 404 (resolved before the authority check).
    bad_proj = client.get(
        "/api/projects/no-such-project/share", headers=_auth_header(owner_tok)
    )
    assert bad_proj.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# P5 — peer worker (lane) sharing
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_clone_worker_copies_fields_and_tools(app_client):
    import lanes as _lanes
    await _mk_project("src", "Source")
    await _mk_project("dst", "Dest Project")

    await _lanes.create_lane(name="docs_writer", project_id="src", max_agents=2, color="#abcdef")
    await _lanes.update_lane("docs_writer", {"append_prompt": "Write great docs."})
    await _lanes.upsert_lane_mcp_tool("docs_writer", "devfleet-tools", "submit_report", True, "always")

    cloned = await _lanes.clone_lane_to_project("docs_writer", "src", "dst", "Dest Project")
    cname = cloned["name"]

    assert cname.startswith("docs_writer__")
    assert len(cname) <= 31
    assert cloned["project_id"] == "dst"
    assert cloned["max_agents"] == 2
    # append_prompt survives — create_lane drops it, the clone's direct INSERT keeps it.
    assert cloned["append_prompt"] == "Write great docs."
    tools = await _lanes.get_lane_mcp_tools(cname)
    assert any(
        t["server_name"] == "devfleet-tools" and t["tool_name"] == "submit_report"
        for t in tools
    )


@pytest.mark.asyncio
async def test_clone_rejects_non_source_worker(app_client):
    import lanes as _lanes
    await _mk_project("src", "Source")
    await _mk_project("dst", "Dest")
    await _lanes.create_lane(name="docs_writer", project_id="src")

    # docs_writer belongs to src, not dst → cloning "from dst" must be refused.
    with pytest.raises(_lanes.LaneValidationError):
        await _lanes.clone_lane_to_project("docs_writer", "dst", "src", "Source")


@pytest.mark.asyncio
async def test_clone_name_collision_suffixes(app_client):
    import lanes as _lanes
    await _mk_project("src", "Source")
    await _mk_project("dst", "Dest Project")
    await _lanes.create_lane(name="docs_writer", project_id="src")

    first = await _lanes.clone_lane_to_project("docs_writer", "src", "dst", "Dest Project")
    second = await _lanes.clone_lane_to_project("docs_writer", "src", "dst", "Dest Project")
    assert first["name"] != second["name"]
    assert len(second["name"]) <= 31


@pytest.mark.asyncio
async def test_share_worker_http_happy_path_admin(app_client):
    client, _, _ = app_client
    import lanes as _lanes
    admin_tok = await _token(client, "admin@x.local", role="admin")
    await _mk_project("src", "Source")
    await _mk_project("dst", "Dest")
    await _lanes.create_lane(name="reviewer_bot", project_id="src")

    res = client.post(
        "/api/projects/src/share-worker",
        json={"lane_name": "reviewer_bot", "target_project_id": "dst"},
        headers=_auth_header(admin_tok),
    )
    assert res.status_code == 201, res.text
    assert res.json()["cloned_lane"].startswith("reviewer_bot__")


@pytest.mark.asyncio
async def test_share_worker_requires_target_authority(app_client):
    """Has source access, but does NOT own-or-admin the target → 403."""
    client, _, _ = app_client
    import auth as _auth
    import lanes as _lanes

    u = await _mk_user("dev@x.local")
    other = await _mk_user("other@x.local")
    tok = _login(client, "dev@x.local")
    await _mk_project("src", "Source", created_by=u["id"])
    await _mk_project("dst", "Dest", created_by=other["id"])
    # u has access to source (owner + bound) but no authority over target.
    await _auth.grant_project_access(u["id"], "src", granted_by=u["id"])
    await _lanes.create_lane(name="helper_bot", project_id="src")

    res = client.post(
        "/api/projects/src/share-worker",
        json={"lane_name": "helper_bot", "target_project_id": "dst"},
        headers=_auth_header(tok),
    )
    assert res.status_code == 403


# ─── small DB/git helpers (kept at the bottom; used above) ───────────────────


async def _project_row(pid: str) -> dict:
    import db as _db
    conn = await _db.get_db()
    try:
        rows = await conn.execute_fetchall("SELECT * FROM projects WHERE id=?", (pid,))
        return dict(rows[0])
    finally:
        await conn.close()


def _git(repo: str, *args: str) -> str:
    import subprocess
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
