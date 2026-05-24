"""Daily chat compactor — condenses each project's chat history into a single
summary row per day and deletes the raw messages.

Runs from the scheduler at the time set in `DEVFLEET_CHAT_COMPACT_CRON`
(default `0 3 * * *` = 3am UTC daily). Also exposed as an admin-trigger
endpoint at POST /api/projects/{pid}/chat/compact.

Why this exists:
  - Chat is multi-user (Moofasa + Adil + Farhan) and append-only; without
    compaction the history table grows unbounded.
  - Daily summaries give the team a reviewable rollup ("yesterday Adil
    merged 3 PRs, Farhan asked 5 questions about the watcher").
  - Deleting raw rows after summarization keeps PII / token surface small;
    the chat_actions audit table is the durable, never-compacted record.

Design choices:
  - **Deterministic format** (no LLM). The audit value of the rollup lives
    in structured counts + per-turn metadata; natural-language synthesis is
    a v2 upgrade. Deterministic also keeps tests fast and free.
  - **Idempotent**: the (project_id, summary_date) UNIQUE constraint on
    chat_summaries means re-running for the same date is a no-op.
  - **Single transaction**: select → insert → delete all in one connection;
    if anything fails the raw rows survive for the next run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import db

log = logging.getLogger("devfleet.chat_compactor")


def _yesterday_iso() -> str:
    """Return yesterday's date in ISO format (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def _render_summary(
    messages: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> str:
    """Build a deterministic markdown summary of one day's chat activity.

    Structure (sections only emitted when non-empty):
      - Header with date + counts
      - Per-persona turn breakdown
      - Action audit (intent, status, who) — chat_actions rows
      - Per-turn timeline (compact, role + persona + 80-char content preview)
    """
    persona_counts: dict[str, int] = {}
    user_counts: dict[str, int] = {}
    for msg in messages:
        p = (msg.get("persona") or "user").strip() or "user"
        persona_counts[p] = persona_counts.get(p, 0) + 1
        uid = (msg.get("user_id") or "").strip() or "(anonymous)"
        user_counts[uid] = user_counts.get(uid, 0) + 1

    status_counts: dict[str, int] = {}
    intent_counts: dict[str, int] = {}
    for action in actions:
        s = (action.get("status") or "").strip()
        status_counts[s] = status_counts.get(s, 0) + 1
        i = (action.get("intent") or "").strip()
        intent_counts[i] = intent_counts.get(i, 0) + 1

    lines: list[str] = []
    lines.append("## Daily chat summary")
    lines.append(f"- Messages: {len(messages)}")
    lines.append(f"- Actions:  {len(actions)}")

    if persona_counts:
        lines.append("")
        lines.append("### Personas")
        for p in sorted(persona_counts):
            lines.append(f"- {p}: {persona_counts[p]}")

    if user_counts:
        lines.append("")
        lines.append("### Participants")
        for u in sorted(user_counts):
            lines.append(f"- {u[:8]}…: {user_counts[u]}")

    if intent_counts or status_counts:
        lines.append("")
        lines.append("### Actions")
        if intent_counts:
            for i in sorted(intent_counts):
                lines.append(f"- intent {i or '(none)'}: {intent_counts[i]}")
        if status_counts:
            for s in sorted(status_counts):
                lines.append(f"- status {s or '(none)'}: {status_counts[s]}")

    if messages:
        lines.append("")
        lines.append("### Timeline")
        for msg in messages:
            role = msg.get("role") or ""
            persona = msg.get("persona") or ""
            created = (msg.get("created_at") or "")[:16].replace("T", " ")
            preview = (msg.get("content") or "").splitlines()[0:1]
            preview_text = (preview[0] if preview else "")[:80]
            tag = f"{role}/{persona}" if persona else role
            lines.append(f"- {created} [{tag}] {preview_text}")

    return "\n".join(lines).strip() + "\n"


async def compact_yesterday(project_id: str) -> dict[str, Any]:
    """Compact one day of chat for a project. Idempotent.

    Returns: dict with keys:
        - status: 'compacted' | 'skipped' | 'no_messages'
        - summary_date: ISO date string
        - message_count, action_count: counts (0 if skipped)

    Behavior:
      - If a chat_summaries row already exists for (project_id, yesterday),
        return status='skipped'.
      - If no project_bot_history rows exist for yesterday, return
        status='no_messages' (don't create an empty summary).
      - Otherwise: render summary → insert → delete raw rows → commit.
        Returns status='compacted'.
    """
    summary_date = _yesterday_iso()

    conn = await db.get_db()
    try:
        existing = await conn.execute_fetchall(
            "SELECT id FROM chat_summaries WHERE project_id=? AND summary_date=?",
            (project_id, summary_date),
        )
        if existing:
            log.info(
                "Chat compaction skipped for project=%s date=%s — already summarized",
                project_id, summary_date,
            )
            return {
                "status": "skipped",
                "summary_date": summary_date,
                "message_count": 0,
                "action_count": 0,
            }

        msg_rows = await conn.execute_fetchall(
            "SELECT id, role, content, user_id, persona, is_plan, plan_title, created_at "
            "FROM project_bot_history "
            "WHERE project_id=? AND date(created_at)=? "
            "ORDER BY created_at, id",
            (project_id, summary_date),
        )
        if not msg_rows:
            log.info(
                "Chat compaction: no messages for project=%s date=%s — nothing to do",
                project_id, summary_date,
            )
            return {
                "status": "no_messages",
                "summary_date": summary_date,
                "message_count": 0,
                "action_count": 0,
            }

        action_rows = await conn.execute_fetchall(
            "SELECT intent, status, persona, user_id "
            "FROM chat_actions "
            "WHERE project_id=? AND date(created_at)=?",
            (project_id, summary_date),
        )

        messages = [dict(r) for r in msg_rows]
        actions = [dict(r) for r in action_rows]
        summary = _render_summary(messages, actions)

        await conn.execute(
            "INSERT INTO chat_summaries "
            "(project_id, summary_date, summary, message_count, action_count) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, summary_date, summary, len(messages), len(actions)),
        )
        await conn.execute(
            "DELETE FROM project_bot_history "
            "WHERE project_id=? AND date(created_at)=?",
            (project_id, summary_date),
        )
        await conn.commit()

        log.info(
            "Chat compaction: project=%s date=%s messages=%d actions=%d",
            project_id, summary_date, len(messages), len(actions),
        )
        return {
            "status": "compacted",
            "summary_date": summary_date,
            "message_count": len(messages),
            "action_count": len(actions),
        }
    finally:
        await conn.close()


async def compact_all_projects() -> list[dict[str, Any]]:
    """Run compact_yesterday for every project. Used by the scheduler tick.

    One DB error in one project shouldn't take down the loop — exceptions
    are caught, logged, and the remaining projects continue. Returns the
    list of result dicts (one per project, including failures with
    status='error').
    """
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall("SELECT id FROM projects")
    finally:
        await conn.close()

    results: list[dict[str, Any]] = []
    for row in rows:
        pid = dict(row)["id"]
        try:
            res = await compact_yesterday(pid)
            res["project_id"] = pid
            results.append(res)
        except Exception as exc:
            log.exception("Chat compaction failed for project %s", pid)
            results.append(
                {
                    "project_id": pid,
                    "status": "error",
                    "summary_date": _yesterday_iso(),
                    "error": str(exc),
                }
            )
    return results
