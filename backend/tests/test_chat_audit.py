"""Tests for backend/chat_audit.py — append-only audit + token redaction."""

from __future__ import annotations

import aiosqlite
import pytest


async def _seed_project_user(db_path: str) -> tuple[str, str]:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO projects (id, name, path) VALUES ('p1', 'demo', '/tmp/demo')"
        )
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, role) "
            "VALUES ('u1', 'a@b.c', 'h', 'user')"
        )
        await conn.commit()
    return "p1", "u1"


# ─── Basic insert + retrieve ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_action_inserts_row(tmp_db):
    import chat_audit

    pid, uid = await _seed_project_user(tmp_db)
    rid = await chat_audit.log_action(
        pid, uid, "researcher", "read", command="", status="completed",
    )
    assert rid > 0

    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("SELECT * FROM chat_actions WHERE id=?", (rid,))
        row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_list_actions_returns_most_recent_first(tmp_db):
    import chat_audit

    pid, uid = await _seed_project_user(tmp_db)
    await chat_audit.log_action(pid, uid, "researcher", "read", command="first")
    await chat_audit.log_action(pid, uid, "git_operator", "pr_merge", command="second")
    rows = await chat_audit.list_actions_for_project(pid)
    assert len(rows) == 2
    assert rows[0]["command"] == "second"
    assert rows[1]["command"] == "first"


@pytest.mark.asyncio
async def test_list_actions_data_field_is_dict(tmp_db):
    """The data JSON blob should round-trip back to a dict on read."""
    import chat_audit

    pid, uid = await _seed_project_user(tmp_db)
    await chat_audit.log_action(
        pid, uid, "git_operator", "pr_merge",
        data={"pr_number": 42, "diff_summary": "+10 -5"},
    )
    rows = await chat_audit.list_actions_for_project(pid)
    assert rows[0]["data"] == {"pr_number": 42, "diff_summary": "+10 -5"}


@pytest.mark.asyncio
async def test_list_actions_for_user_scopes_by_user(tmp_db):
    import chat_audit

    pid, uid = await _seed_project_user(tmp_db)
    # Second user
    async with aiosqlite.connect(tmp_db) as conn:
        await conn.execute(
            "INSERT INTO users (id, email, password_hash) VALUES ('u2', 'b@c.d', 'h')"
        )
        await conn.commit()
    await chat_audit.log_action(pid, uid, "researcher", "read", command="u1-msg")
    await chat_audit.log_action(pid, "u2", "researcher", "read", command="u2-msg")
    u1_rows = await chat_audit.list_actions_for_user(uid)
    assert len(u1_rows) == 1
    assert u1_rows[0]["command"] == "u1-msg"


# ─── Token redaction ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redacts_classic_github_pat(tmp_db):
    import chat_audit

    pid, uid = await _seed_project_user(tmp_db)
    await chat_audit.log_action(
        pid, uid, "git_operator", "git_other",
        command="gh auth login --with-token ghp_aaaaaaaaaaaaaaaaaaaaaaaa",
    )
    rows = await chat_audit.list_actions_for_project(pid)
    assert "ghp_" not in rows[0]["command"]
    assert "<REDACTED>" in rows[0]["command"]


@pytest.mark.asyncio
async def test_redacts_fine_grained_pat(tmp_db):
    import chat_audit

    pid, uid = await _seed_project_user(tmp_db)
    await chat_audit.log_action(
        pid, uid, "git_operator", "git_other",
        command="curl -H 'auth: github_pat_aaaaaaaaaaaaaaaaaaaaaa'",
    )
    rows = await chat_audit.list_actions_for_project(pid)
    assert "github_pat_" not in rows[0]["command"]


@pytest.mark.asyncio
async def test_redacts_bearer_header(tmp_db):
    import chat_audit

    pid, uid = await _seed_project_user(tmp_db)
    await chat_audit.log_action(
        pid, uid, "git_operator", "git_other",
        command="curl -H 'Authorization: Bearer abcd1234efgh5678ijkl9012'",
    )
    rows = await chat_audit.list_actions_for_project(pid)
    assert "Bearer abcd" not in rows[0]["command"]


@pytest.mark.asyncio
async def test_redacts_gh_token_env(tmp_db):
    import chat_audit

    pid, uid = await _seed_project_user(tmp_db)
    await chat_audit.log_action(
        pid, uid, "git_operator", "git_other",
        command="GH_TOKEN=ghp_aaaaaaaaaaaaaaaaaaaaaa gh pr list",
    )
    rows = await chat_audit.list_actions_for_project(pid)
    assert "ghp_" not in rows[0]["command"]
    assert "GH_TOKEN=" not in rows[0]["command"]


@pytest.mark.asyncio
async def test_redacts_anthropic_key(tmp_db):
    import chat_audit

    pid, uid = await _seed_project_user(tmp_db)
    await chat_audit.log_action(
        pid, uid, "git_operator", "git_other",
        command="ANTHROPIC_API_KEY=sk-ant-aaaaaaaaaaaaaaaaaaaaaaaa run",
    )
    rows = await chat_audit.list_actions_for_project(pid)
    assert "sk-ant-" not in rows[0]["command"]


@pytest.mark.asyncio
async def test_non_secret_text_preserved(tmp_db):
    """Commands without recognizable secret formats stay intact."""
    import chat_audit

    pid, uid = await _seed_project_user(tmp_db)
    await chat_audit.log_action(
        pid, uid, "git_operator", "pr_merge",
        command="gh pr merge 42 --squash",
    )
    rows = await chat_audit.list_actions_for_project(pid)
    assert rows[0]["command"] == "gh pr merge 42 --squash"


# ─── Status validation ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_status_coerced_to_completed(tmp_db):
    import chat_audit

    pid, uid = await _seed_project_user(tmp_db)
    rid = await chat_audit.log_action(
        pid, uid, "researcher", "read", status="bogus_value",
    )
    rows = await chat_audit.list_actions_for_project(pid)
    assert rows[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_all_valid_statuses_accepted(tmp_db):
    import chat_audit

    pid, uid = await _seed_project_user(tmp_db)
    for status in chat_audit.VALID_STATUSES:
        rid = await chat_audit.log_action(pid, uid, "researcher", "read", status=status)
        assert rid > 0


# ─── Error tolerance ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unserializable_data_does_not_crash(tmp_db):
    """If `data` contains a non-JSON-serializable object, we should still
    write the row — default=str picks it up."""
    import chat_audit

    pid, uid = await _seed_project_user(tmp_db)

    class WeirdObj:
        def __str__(self):
            return "stringified"

    rid = await chat_audit.log_action(
        pid, uid, "researcher", "read", data={"thing": WeirdObj()},
    )
    assert rid > 0
    rows = await chat_audit.list_actions_for_project(pid)
    assert rows[0]["data"]["thing"] == "stringified"


@pytest.mark.asyncio
async def test_log_action_does_not_raise_on_unknown_user(tmp_db):
    """Audit must never crash a chat turn even if the user_id is unrecognised.
    chat_actions has no FK constraint enforced — we just log."""
    import chat_audit

    pid, _ = await _seed_project_user(tmp_db)
    # Must not raise even with phantom user_id (no FK enforcement in chat_actions)
    rid = await chat_audit.log_action(pid, "phantom_user", "researcher", "read")
    assert rid > 0
