"""Tests for the persona-chat auth helpers added to backend/auth.py:
RBAC (has_permission, grant, revoke, list) + per-user encrypted GitHub PAT."""

from __future__ import annotations

import aiosqlite
import pytest


async def _seed_user(db_path: str, user_id: str, role: str = "user", **extra) -> None:
    cols = ["id", "email", "password_hash", "role"]
    vals = [user_id, f"{user_id}@test", "hash", role]
    for k, v in extra.items():
        cols.append(k)
        vals.append(v)
    placeholders = ",".join("?" for _ in cols)
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            f"INSERT INTO users ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        await conn.commit()


# ─── Permissions ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_has_all_permissions(tmp_db):
    import auth

    await _seed_user(tmp_db, "admin1", role="admin")
    assert await auth.has_permission("admin1", "git.pr.merge")
    assert await auth.has_permission("admin1", "anything.invented")


@pytest.mark.asyncio
async def test_user_without_grant_denied(tmp_db):
    import auth

    await _seed_user(tmp_db, "u1")
    assert not await auth.has_permission("u1", "git.pr.merge")


@pytest.mark.asyncio
async def test_grant_then_check_passes(tmp_db):
    import auth

    await _seed_user(tmp_db, "u1")
    await _seed_user(tmp_db, "admin1", role="admin")
    await auth.grant_permission("u1", "git.pr.merge", "admin1")
    assert await auth.has_permission("u1", "git.pr.merge")


@pytest.mark.asyncio
async def test_grant_is_idempotent(tmp_db):
    import auth

    await _seed_user(tmp_db, "u1")
    await _seed_user(tmp_db, "admin1", role="admin")
    await auth.grant_permission("u1", "git.push", "admin1")
    await auth.grant_permission("u1", "git.push", "admin1")
    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM user_permissions WHERE user_id='u1' AND permission='git.push'"
        )
        count = (await cur.fetchone())[0]
    assert count == 1


@pytest.mark.asyncio
async def test_revoke_removes_grant(tmp_db):
    import auth

    await _seed_user(tmp_db, "u1")
    await _seed_user(tmp_db, "admin1", role="admin")
    await auth.grant_permission("u1", "git.push", "admin1")
    await auth.revoke_permission("u1", "git.push")
    assert not await auth.has_permission("u1", "git.push")


@pytest.mark.asyncio
async def test_revoke_missing_is_noop(tmp_db):
    import auth

    await _seed_user(tmp_db, "u1")
    # Must not raise.
    await auth.revoke_permission("u1", "git.push")


@pytest.mark.asyncio
async def test_list_permissions_excludes_admin_bypass(tmp_db):
    """Admins implicitly hold all perms, but list_permissions returns only
    their explicit grants — the UI checks admin via the role column."""
    import auth

    await _seed_user(tmp_db, "admin1", role="admin")
    perms = await auth.list_permissions("admin1")
    assert perms == []  # No explicit rows


@pytest.mark.asyncio
async def test_list_permissions_returns_grants(tmp_db):
    import auth

    await _seed_user(tmp_db, "u1")
    await _seed_user(tmp_db, "admin1", role="admin")
    await auth.grant_permission("u1", "git.push", "admin1")
    await auth.grant_permission("u1", "git.pr.create", "admin1")
    perms = await auth.list_permissions("u1")
    assert set(perms) == {"git.push", "git.pr.create"}


# ─── GitHub token storage ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_then_get_round_trips(tmp_db):
    import auth

    await _seed_user(tmp_db, "u1")
    await auth.set_github_token("u1", "ghp_secrettoken12345", "octocat")
    got = await auth.get_github_token("u1")
    assert got == ("ghp_secrettoken12345", "octocat")


@pytest.mark.asyncio
async def test_set_clears_plaintext_column(tmp_db):
    """Setting a token through the API path must leave github_token empty so
    we never have both an encrypted and a plaintext copy on disk."""
    import auth

    await _seed_user(tmp_db, "u1", github_token="ghp_oldplaintext_should_be_cleared")
    await auth.set_github_token("u1", "ghp_newone", "octocat")
    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute(
            "SELECT github_token, github_token_encrypted FROM users WHERE id='u1'"
        )
        plain, enc = await cur.fetchone()
    assert plain == ""
    assert enc, "Encrypted column should be populated"


@pytest.mark.asyncio
async def test_get_returns_none_when_no_token(tmp_db):
    import auth

    await _seed_user(tmp_db, "u1")
    assert await auth.get_github_token("u1") is None


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_user(tmp_db):
    import auth

    assert await auth.get_github_token("does-not-exist") is None


@pytest.mark.asyncio
async def test_clear_removes_both_columns(tmp_db):
    import auth

    await _seed_user(tmp_db, "u1")
    await auth.set_github_token("u1", "ghp_value", "octocat")
    await auth.clear_github_token("u1")
    assert await auth.get_github_token("u1") is None


@pytest.mark.asyncio
async def test_get_falls_back_to_plaintext_with_warning(tmp_db, caplog):
    """If encryption migration never ran for a row, get_github_token returns
    the plaintext and logs a warning so deployment can be fixed."""
    import auth
    import logging

    # Insert directly to bypass set_github_token (which would encrypt).
    async with aiosqlite.connect(tmp_db) as conn:
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, role, github_token, github_username) "
            "VALUES ('u1', 'a@b', 'h', 'user', 'ghp_orphaned_plaintext', 'octocat')"
        )
        await conn.commit()

    with caplog.at_level(logging.WARNING, logger="devfleet"):
        result = await auth.get_github_token("u1")
    assert result == ("ghp_orphaned_plaintext", "octocat")
    assert any("unencrypted" in rec.message.lower() for rec in caplog.records)
