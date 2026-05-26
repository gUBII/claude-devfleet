"""Dev metrics — Likeness points + behaviour tracking for non-admin users.

Admin users are deliberately skipped so they never appear on the public
DevProfiles dashboard (per product spec: "admin profiles don't appear on the
public board"). Every helper is a no-op when called against an admin row, so
callers can blindly increment without role-checking first.

All writes are upserts (INSERT ... ON CONFLICT) — the row is created lazily on
the user's first qualifying event. Callers MUST pass a valid user_id that
references users.id, otherwise the FK constraint will raise.
"""

from __future__ import annotations

import logging
from typing import Optional

import aiosqlite

from db import get_db

logger = logging.getLogger("devfleet.dev_metrics")


async def _is_admin(db: aiosqlite.Connection, user_id: str) -> bool:
    """Returns True for admin rows (skip tracking) or unknown user_ids (defensive)."""
    async with db.execute("SELECT role FROM users WHERE id=?", (user_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        return True  # unknown user — refuse to create orphan dev_metrics row
    return (row[0] or "").lower() == "admin"


async def _ensure_row(db: aiosqlite.Connection, user_id: str) -> None:
    """Lazy upsert. Safe to call repeatedly — INSERT OR IGNORE."""
    await db.execute(
        "INSERT OR IGNORE INTO dev_metrics (user_id) VALUES (?)",
        (user_id,),
    )


async def increment_likeness(user_id: str, points: int, reason: str = "") -> bool:
    """Add `points` to user's likeness. No-op for admins or unknown users.

    Returns True if the row was updated, False if skipped (admin/unknown).
    """
    if points == 0:
        return False
    db = await get_db()
    try:
        if await _is_admin(db, user_id):
            return False
        await _ensure_row(db, user_id)
        await db.execute(
            "UPDATE dev_metrics SET likeness_points = likeness_points + ?, "
            "updated_at = datetime('now') WHERE user_id=?",
            (points, user_id),
        )
        await db.commit()
        logger.info(
            "dev_metrics: +%d likeness for %s (reason=%s)",
            points, user_id, reason or "unspecified",
        )
        return True
    finally:
        await db.close()


async def record_pr_merge(user_id: str, *, clean: bool, likeness: int = 5) -> bool:
    """Increment total + clean PR counters; clean merges award likeness and
    extend the clean streak. Non-clean merges reset the streak.

    A "clean" merge means: no force-push, no `reset --hard`, no amend of
    landed commits during the merge process. The detection lives in the
    caller (chat_personas.py — see PR merge protocol).
    """
    db = await get_db()
    try:
        if await _is_admin(db, user_id):
            return False
        await _ensure_row(db, user_id)
        if clean:
            await db.execute(
                "UPDATE dev_metrics SET "
                "pr_merges_total = pr_merges_total + 1, "
                "pr_merges_clean = pr_merges_clean + 1, "
                "likeness_points = likeness_points + ?, "
                "current_clean_streak = current_clean_streak + 1, "
                "longest_clean_streak = MAX(longest_clean_streak, current_clean_streak + 1), "
                "updated_at = datetime('now') "
                "WHERE user_id=?",
                (likeness, user_id),
            )
        else:
            await db.execute(
                "UPDATE dev_metrics SET "
                "pr_merges_total = pr_merges_total + 1, "
                "current_clean_streak = 0, "
                "updated_at = datetime('now') "
                "WHERE user_id=?",
                (user_id,),
            )
        await db.commit()
        logger.info(
            "dev_metrics: PR merge for %s (clean=%s, +%d likeness)",
            user_id, clean, likeness if clean else 0,
        )
        return True
    finally:
        await db.close()


async def record_routing_savings(
    user_id: str,
    dollars_saved: float,
    *,
    likeness_per_dollar: int = 1,
    likeness_cap: int = 10,
) -> bool:
    """Credit a dev for choosing model routing. Likeness scaled to dollars
    saved on this run, capped so a single big plan can't dominate the board.

    Uses ceil() so any positive saving awards at least 1 point — flooring would
    silently zero out small wins (e.g. a $0.40 save would credit 0 points).
    """
    if dollars_saved <= 0:
        return False
    import math
    db = await get_db()
    try:
        if await _is_admin(db, user_id):
            return False
        await _ensure_row(db, user_id)
        likeness = min(math.ceil(dollars_saved * likeness_per_dollar), likeness_cap)
        await db.execute(
            "UPDATE dev_metrics SET "
            "dollars_saved_routing = dollars_saved_routing + ?, "
            "likeness_points = likeness_points + ?, "
            "updated_at = datetime('now') "
            "WHERE user_id=?",
            (dollars_saved, likeness, user_id),
        )
        await db.commit()
        logger.info(
            "dev_metrics: routing saved $%.4f for %s (+%d likeness)",
            dollars_saved, user_id, likeness,
        )
        return True
    finally:
        await db.close()


async def get_metrics(user_id: str) -> Optional[dict]:
    """Returns the user's current metrics row, or None if absent (admin or no events yet)."""
    db = await get_db()
    try:
        async with db.execute(
            "SELECT user_id, likeness_points, pr_merges_clean, pr_merges_total, "
            "dollars_saved_routing, current_clean_streak, longest_clean_streak, updated_at "
            "FROM dev_metrics WHERE user_id=?",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        await db.close()


async def credit_chat_pr_merge_if_eligible(
    session_id: str,
    *,
    succeeded: bool,
    output_log: str = "",
) -> bool:
    """Inspect the chat_actions row for `session_id` and credit a PR merge.

    Fires from sdk_engine at session end. No-op when:
      - no chat_actions row exists for this session (not a chat turn)
      - the action intent isn't 'pr_merge'
      - the action wasn't tied to a user (anon / system)
      - the user is admin

    Cleanness heuristic: a merge is "clean" only if it succeeded AND the
    agent's output_log shows no force-push markers ("--force", "push -f",
    "reset --hard"). Failed sessions reset the clean streak.
    """
    db = await get_db()
    try:
        async with db.execute(
            "SELECT user_id, intent FROM chat_actions WHERE session_id=? "
            "ORDER BY id DESC LIMIT 1",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return False
        user_id, intent = row[0], row[1]
        if intent != "pr_merge" or not user_id:
            return False
    finally:
        await db.close()

    lo = (output_log or "").lower()
    force_markers = ("--force", "push -f", "reset --hard")
    has_dirty_marker = any(m in lo for m in force_markers)
    clean = succeeded and not has_dirty_marker
    return await record_pr_merge(user_id, clean=clean)


async def list_public_profiles() -> list[dict]:
    """Returns non-admin users with their metrics, joined to identity fields.

    Sort: likeness_points DESC, then longest_clean_streak DESC.
    Admins are excluded outright — they aren't on the leaderboard at all,
    even if a dev_metrics row was created for them by an earlier bug.
    """
    db = await get_db()
    try:
        async with db.execute(
            "SELECT u.id, u.email, "
            "COALESCE(u.github_login, '') AS github_login, "
            "COALESCE(u.github_name, '') AS github_name, "
            "COALESCE(u.github_noreply_email, '') AS github_noreply_email, "
            "COALESCE(m.likeness_points, 0) AS likeness_points, "
            "COALESCE(m.pr_merges_clean, 0) AS pr_merges_clean, "
            "COALESCE(m.pr_merges_total, 0) AS pr_merges_total, "
            "COALESCE(m.dollars_saved_routing, 0) AS dollars_saved_routing, "
            "COALESCE(m.current_clean_streak, 0) AS current_clean_streak, "
            "COALESCE(m.longest_clean_streak, 0) AS longest_clean_streak "
            "FROM users u LEFT JOIN dev_metrics m ON m.user_id = u.id "
            "WHERE LOWER(COALESCE(u.role, 'user')) != 'admin' "
            "ORDER BY likeness_points DESC, longest_clean_streak DESC, u.email ASC"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()
