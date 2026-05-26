"""Tests for dev_metrics module — Likeness points + behaviour tracking.

Covers:
  - schema exists after init_db
  - increment_likeness happy path + admin skip + unknown user skip
  - record_pr_merge clean vs non-clean + streak math
  - record_routing_savings dollars + likeness cap
  - list_public_profiles excludes admins, orders correctly
"""

from __future__ import annotations

import aiosqlite
import pytest


async def _seed_user(db_path: str, email: str, role: str = "user") -> str:
    """Insert a user directly via aiosqlite and return their id."""
    import uuid
    uid = str(uuid.uuid4())
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO users (id, email, password_hash, role) VALUES (?,?,?,?)",
            (uid, email, "fake-hash", role),
        )
        await db.commit()
    return uid


# ─── Schema ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dev_metrics_table_exists(tmp_db):
    async with aiosqlite.connect(tmp_db) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='dev_metrics'"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        # Verify all expected columns
        async with db.execute("PRAGMA table_info(dev_metrics)") as cur:
            cols = {r[1] for r in await cur.fetchall()}
        expected = {
            "user_id", "likeness_points", "pr_merges_clean", "pr_merges_total",
            "dollars_saved_routing", "current_clean_streak", "longest_clean_streak",
            "updated_at",
        }
        assert expected.issubset(cols), f"missing columns: {expected - cols}"


# ─── increment_likeness ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_increment_likeness_creates_row_lazily(tmp_db):
    import dev_metrics

    uid = await _seed_user(tmp_db, "dev@x.local")
    ok = await dev_metrics.increment_likeness(uid, 5, reason="test")
    assert ok is True

    metrics = await dev_metrics.get_metrics(uid)
    assert metrics is not None
    assert metrics["likeness_points"] == 5


@pytest.mark.asyncio
async def test_increment_likeness_accumulates(tmp_db):
    import dev_metrics

    uid = await _seed_user(tmp_db, "dev@x.local")
    await dev_metrics.increment_likeness(uid, 3)
    await dev_metrics.increment_likeness(uid, 7)

    metrics = await dev_metrics.get_metrics(uid)
    assert metrics["likeness_points"] == 10


@pytest.mark.asyncio
async def test_increment_likeness_skips_admin(tmp_db):
    import dev_metrics

    admin = await _seed_user(tmp_db, "boss@x.local", role="admin")
    ok = await dev_metrics.increment_likeness(admin, 100)
    assert ok is False
    assert await dev_metrics.get_metrics(admin) is None


@pytest.mark.asyncio
async def test_increment_likeness_skips_unknown_user(tmp_db):
    import dev_metrics

    ok = await dev_metrics.increment_likeness("does-not-exist", 5)
    assert ok is False


@pytest.mark.asyncio
async def test_increment_likeness_zero_noop(tmp_db):
    import dev_metrics

    uid = await _seed_user(tmp_db, "dev@x.local")
    ok = await dev_metrics.increment_likeness(uid, 0)
    assert ok is False
    assert await dev_metrics.get_metrics(uid) is None


# ─── record_pr_merge ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_pr_merge_clean_extends_streak_and_awards(tmp_db):
    import dev_metrics

    uid = await _seed_user(tmp_db, "dev@x.local")
    await dev_metrics.record_pr_merge(uid, clean=True)
    await dev_metrics.record_pr_merge(uid, clean=True)
    await dev_metrics.record_pr_merge(uid, clean=True)

    m = await dev_metrics.get_metrics(uid)
    assert m["pr_merges_clean"] == 3
    assert m["pr_merges_total"] == 3
    assert m["current_clean_streak"] == 3
    assert m["longest_clean_streak"] == 3
    assert m["likeness_points"] == 15  # 5 * 3


@pytest.mark.asyncio
async def test_record_pr_merge_dirty_resets_streak(tmp_db):
    import dev_metrics

    uid = await _seed_user(tmp_db, "dev@x.local")
    await dev_metrics.record_pr_merge(uid, clean=True)
    await dev_metrics.record_pr_merge(uid, clean=True)  # streak = 2
    await dev_metrics.record_pr_merge(uid, clean=False)  # streak → 0, longest stays 2

    m = await dev_metrics.get_metrics(uid)
    assert m["pr_merges_clean"] == 2
    assert m["pr_merges_total"] == 3
    assert m["current_clean_streak"] == 0
    assert m["longest_clean_streak"] == 2
    assert m["likeness_points"] == 10  # 5 * 2; dirty merge awards 0


# ─── record_routing_savings ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_routing_savings_credits_dollars_and_likeness(tmp_db):
    import dev_metrics

    uid = await _seed_user(tmp_db, "dev@x.local")
    await dev_metrics.record_routing_savings(uid, 3.50)

    m = await dev_metrics.get_metrics(uid)
    assert abs(m["dollars_saved_routing"] - 3.50) < 1e-9
    assert m["likeness_points"] == 4  # ceil(3.50 * 1)


@pytest.mark.asyncio
async def test_record_routing_savings_awards_one_point_for_tiny_save(tmp_db):
    """Sub-dollar savings still award 1 likeness via ceil(), not 0 via floor()."""
    import dev_metrics

    uid = await _seed_user(tmp_db, "dev@x.local")
    await dev_metrics.record_routing_savings(uid, 0.40)

    m = await dev_metrics.get_metrics(uid)
    assert m["likeness_points"] == 1


@pytest.mark.asyncio
async def test_record_routing_savings_caps_likeness(tmp_db):
    import dev_metrics

    uid = await _seed_user(tmp_db, "dev@x.local")
    await dev_metrics.record_routing_savings(uid, 99.0)  # huge single run

    m = await dev_metrics.get_metrics(uid)
    assert m["likeness_points"] == 10  # cap, not 99


@pytest.mark.asyncio
async def test_record_routing_savings_ignores_zero_or_negative(tmp_db):
    import dev_metrics

    uid = await _seed_user(tmp_db, "dev@x.local")
    assert await dev_metrics.record_routing_savings(uid, 0) is False
    assert await dev_metrics.record_routing_savings(uid, -1.0) is False
    assert await dev_metrics.get_metrics(uid) is None


# ─── list_public_profiles ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_public_profiles_excludes_admins(tmp_db):
    import dev_metrics

    dev = await _seed_user(tmp_db, "dev@x.local")
    admin = await _seed_user(tmp_db, "boss@x.local", role="admin")
    await dev_metrics.increment_likeness(dev, 5)
    # Admin should never appear, even if a row was manually inserted
    async with aiosqlite.connect(tmp_db) as db:
        await db.execute(
            "INSERT INTO dev_metrics (user_id, likeness_points) VALUES (?, 999)",
            (admin,),
        )
        await db.commit()

    profiles = await dev_metrics.list_public_profiles()
    emails = {p["email"] for p in profiles}
    assert "dev@x.local" in emails
    assert "boss@x.local" not in emails


@pytest.mark.asyncio
async def test_list_public_profiles_orders_by_likeness_desc(tmp_db):
    import dev_metrics

    low = await _seed_user(tmp_db, "low@x.local")
    high = await _seed_user(tmp_db, "high@x.local")
    await dev_metrics.increment_likeness(low, 1)
    await dev_metrics.increment_likeness(high, 50)

    profiles = await dev_metrics.list_public_profiles()
    assert profiles[0]["email"] == "high@x.local"
    assert profiles[1]["email"] == "low@x.local"


@pytest.mark.asyncio
async def test_credit_chat_pr_merge_clean_path(tmp_db):
    import dev_metrics

    uid = await _seed_user(tmp_db, "dev@x.local")
    sid = "session-1"
    async with aiosqlite.connect(tmp_db) as db:
        await db.execute(
            "INSERT INTO chat_actions (project_id, user_id, persona, intent, "
            "status, session_id) VALUES (?, ?, 'git_operator', 'pr_merge', "
            "'started', ?)",
            ("proj-1", uid, sid),
        )
        await db.commit()

    ok = await dev_metrics.credit_chat_pr_merge_if_eligible(
        sid, succeeded=True, output_log="merging into main",
    )
    assert ok is True

    m = await dev_metrics.get_metrics(uid)
    assert m["pr_merges_clean"] == 1
    assert m["current_clean_streak"] == 1
    assert m["likeness_points"] == 5


@pytest.mark.asyncio
async def test_credit_chat_pr_merge_force_push_marks_dirty(tmp_db):
    """A successful session that force-pushed is NOT clean — resets streak."""
    import dev_metrics

    uid = await _seed_user(tmp_db, "dev@x.local")
    await dev_metrics.record_pr_merge(uid, clean=True)  # streak = 1

    sid = "session-2"
    async with aiosqlite.connect(tmp_db) as db:
        await db.execute(
            "INSERT INTO chat_actions (project_id, user_id, persona, intent, "
            "status, session_id) VALUES (?, ?, 'git_operator', 'pr_merge', "
            "'started', ?)",
            ("proj-1", uid, sid),
        )
        await db.commit()

    ok = await dev_metrics.credit_chat_pr_merge_if_eligible(
        sid, succeeded=True, output_log="ran: git push --force-with-lease",
    )
    assert ok is True

    m = await dev_metrics.get_metrics(uid)
    # Dirty merge → streak resets to 0, longest stays 1
    assert m["current_clean_streak"] == 0
    assert m["longest_clean_streak"] == 1


@pytest.mark.asyncio
async def test_credit_chat_pr_merge_skips_non_merge_intent(tmp_db):
    """A chat git turn that wasn't a PR merge shouldn't award merge points."""
    import dev_metrics

    uid = await _seed_user(tmp_db, "dev@x.local")
    sid = "session-3"
    async with aiosqlite.connect(tmp_db) as db:
        await db.execute(
            "INSERT INTO chat_actions (project_id, user_id, persona, intent, "
            "status, session_id) VALUES (?, ?, 'git_operator', 'commit', "
            "'started', ?)",
            ("proj-1", uid, sid),
        )
        await db.commit()

    ok = await dev_metrics.credit_chat_pr_merge_if_eligible(
        sid, succeeded=True,
    )
    assert ok is False
    assert await dev_metrics.get_metrics(uid) is None


@pytest.mark.asyncio
async def test_credit_chat_pr_merge_skips_when_no_action_row(tmp_db):
    import dev_metrics

    ok = await dev_metrics.credit_chat_pr_merge_if_eligible(
        "no-such-session", succeeded=True,
    )
    assert ok is False


@pytest.mark.asyncio
async def test_credit_chat_pr_merge_failed_resets_streak(tmp_db):
    """A session that failed mid-merge → clean=False (resets streak)."""
    import dev_metrics

    uid = await _seed_user(tmp_db, "dev@x.local")
    await dev_metrics.record_pr_merge(uid, clean=True)
    await dev_metrics.record_pr_merge(uid, clean=True)  # streak = 2

    sid = "session-4"
    async with aiosqlite.connect(tmp_db) as db:
        await db.execute(
            "INSERT INTO chat_actions (project_id, user_id, persona, intent, "
            "status, session_id) VALUES (?, ?, 'git_operator', 'pr_merge', "
            "'started', ?)",
            ("proj-1", uid, sid),
        )
        await db.commit()

    await dev_metrics.credit_chat_pr_merge_if_eligible(sid, succeeded=False)

    m = await dev_metrics.get_metrics(uid)
    assert m["current_clean_streak"] == 0
    assert m["longest_clean_streak"] == 2


@pytest.mark.asyncio
async def test_list_public_profiles_includes_users_without_metrics_row(tmp_db):
    """Devs who haven't earned any points yet should still show on the board
    with zeroed counters — otherwise the leaderboard only shows winners."""
    import dev_metrics

    await _seed_user(tmp_db, "newbie@x.local")
    profiles = await dev_metrics.list_public_profiles()
    by_email = {p["email"]: p for p in profiles}
    assert "newbie@x.local" in by_email
    assert by_email["newbie@x.local"]["likeness_points"] == 0
