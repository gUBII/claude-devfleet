"""Schema/migration tests for the persona chat + RBAC feature.

Verifies that init_db() lands the v12 columns and tables, and that the
plaintext → encrypted github_token data migration runs idempotently.
"""

from __future__ import annotations

import aiosqlite
import pytest


@pytest.mark.asyncio
async def test_v12_users_columns_added(tmp_db):
    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(users)")
        cols = {row[1] for row in await cur.fetchall()}
    assert "github_token" in cols
    assert "github_token_encrypted" in cols
    assert "github_username" in cols


@pytest.mark.asyncio
async def test_v12_chat_history_columns_added(tmp_db):
    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(project_bot_history)")
        cols = {row[1] for row in await cur.fetchall()}
    assert "user_id" in cols
    assert "persona" in cols


@pytest.mark.asyncio
async def test_v12_is_chat_turn_added(tmp_db):
    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(missions)")
        cols = {row[1] for row in await cur.fetchall()}
    assert "is_chat_turn" in cols


@pytest.mark.asyncio
async def test_v12_chat_actions_table(tmp_db):
    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(chat_actions)")
        cols = {row[1] for row in await cur.fetchall()}
    expected = {
        "id", "project_id", "user_id", "persona", "intent",
        "command", "status", "data", "session_id", "created_at",
    }
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


@pytest.mark.asyncio
async def test_v12_chat_actions_indexes(tmp_db):
    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='chat_actions'"
        )
        idx_names = {row[0] for row in await cur.fetchall()}
    assert "idx_chat_actions_project" in idx_names
    assert "idx_chat_actions_user" in idx_names


@pytest.mark.asyncio
async def test_v12_chat_summaries_table(tmp_db):
    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(chat_summaries)")
        cols = {row[1] for row in await cur.fetchall()}
        expected = {"id", "project_id", "summary_date", "summary",
                    "message_count", "action_count", "created_at"}
        assert expected.issubset(cols)

        # UNIQUE(project_id, summary_date)
        cur = await conn.execute("PRAGMA index_list(chat_summaries)")
        idx_rows = await cur.fetchall()
        unique_count = sum(1 for row in idx_rows if row[2] == 1)
        assert unique_count >= 1, "chat_summaries needs a UNIQUE constraint"


@pytest.mark.asyncio
async def test_v12_user_permissions_table(tmp_db):
    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(user_permissions)")
        rows = await cur.fetchall()
    cols = {row[1] for row in rows}
    expected = {"user_id", "permission", "granted_by", "granted_at"}
    assert expected.issubset(cols)
    # Composite PK on (user_id, permission)
    pk_cols = {row[1] for row in rows if row[5] > 0}
    assert pk_cols == {"user_id", "permission"}


@pytest.mark.asyncio
async def test_github_token_encryption_migration_is_idempotent(tmp_db):
    """A plaintext github_token row should be encrypted on init; re-running
    init_db must not re-encrypt (which would mutate the ciphertext)."""
    import db
    import crypto

    async with aiosqlite.connect(tmp_db) as conn:
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, github_token) "
            "VALUES ('u1', 'a@b.c', 'h', 'ghp_legacy_plaintext_value')"
        )
        await conn.commit()

    # First init_db pass — should encrypt the plaintext row.
    await db.init_db()
    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute(
            "SELECT github_token, github_token_encrypted FROM users WHERE id='u1'"
        )
        plain1, enc1 = await cur.fetchone()
    assert enc1, "github_token_encrypted should be populated after first init_db"
    assert crypto.decrypt(enc1) == "ghp_legacy_plaintext_value"

    # Second init_db pass — must be a no-op for this row.
    await db.init_db()
    async with aiosqlite.connect(tmp_db) as conn:
        cur = await conn.execute(
            "SELECT github_token, github_token_encrypted FROM users WHERE id='u1'"
        )
        plain2, enc2 = await cur.fetchone()
    assert enc1 == enc2, "Re-running init_db must not re-encrypt the same row"
    assert plain2 == "ghp_legacy_plaintext_value", "Plaintext column preserved for rollback"
