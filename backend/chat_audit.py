"""Chat audit log — append-only record of every operator-issued chat action.

Every code path that triggers a state change (or a permission denial, or a
pending confirmation) MUST call `log_action`. Read-only persona invocations
are also recorded for traceability, at a lower volume.

Pattern mirrors backend/mission_watcher.py:88 — single INSERT, JSON blob in
the data column, no joins. Idempotent appends only — never updates a row.

The `_redact` step strips well-known secret formats from the persisted
`command` column. Tokens should not arrive here in the first place (operators
should use the dedicated PUT /api/auth/me/github-token endpoint), but if an
operator ever pastes a PAT into chat the audit row must not retain it.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import db

log = logging.getLogger("devfleet.chat_audit")

# Patterns extended over time as new secret formats appear. Substring matches
# are not enough — we use full token regexes (no captures) and replace inline.
_TOKEN_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"ghu_[A-Za-z0-9]{20,}"),
    re.compile(r"ghs_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),                  # OpenAI keys
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),              # Anthropic keys
    re.compile(r"AKIA[0-9A-Z]{16}"),                        # AWS access key id
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}", re.IGNORECASE),
    re.compile(r"GH_TOKEN=\S+"),
    re.compile(r"GITHUB_TOKEN=\S+"),
]


def _redact(text: str) -> str:
    """Replace every recognized token pattern in `text` with <REDACTED>."""
    if not text:
        return text
    for pat in _TOKEN_PATTERNS:
        text = pat.sub("<REDACTED>", text)
    return text


# Valid status values. Defined here so callers don't pass typos.
VALID_STATUSES = frozenset({
    "pending",            # confirm awaited
    "approved",           # confirm received, command about to run
    "denied",             # user rejected the confirm
    "timeout",            # confirm window elapsed
    "completed",          # command ran to completion
    "failed",             # command ran but errored
    "permission_denied",  # RBAC blocked execution
    "precondition_missing",  # e.g. no github_token set
    "started",            # turn started (researcher / architect)
})


async def log_action(
    project_id: str,
    user_id: str,
    persona: str,
    intent: str,
    *,
    command: str = "",
    status: str = "completed",
    data: Optional[dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> int:
    """Append a chat_actions row. Returns the inserted row id.

    Args:
        project_id: project this action belongs to (FK).
        user_id: user who triggered the action (FK).
        persona: researcher | git_operator | architect.
        intent: a CHAT_PERMISSIONS-known intent name (read, pr_merge, …).
        command: exact shell command run, or empty for non-shell intents.
            Redacted of well-known secret formats before persistence.
        status: see VALID_STATUSES.
        data: JSON-serializable dict with extra context (diff_summary,
            exit_code, stdout_excerpt, etc.).
        session_id: agent_sessions.id for git_operator turns; None for
            researcher / architect.

    Never raises on invalid inputs — audit is best-effort. A failure here
    must not break the chat turn. Errors are logged but swallowed.
    """
    if status not in VALID_STATUSES:
        log.warning("Unknown chat_actions status %r — coercing to 'completed'", status)
        status = "completed"

    redacted_command = _redact(command)
    try:
        data_json = json.dumps(data or {}, default=str)
    except Exception as exc:
        log.warning("chat_audit: data serialization failed (%s); using {}", exc)
        data_json = "{}"

    try:
        conn = await db.get_db()
        try:
            cur = await conn.execute(
                "INSERT INTO chat_actions "
                "(project_id, user_id, persona, intent, command, status, data, session_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    project_id, user_id, persona, intent,
                    redacted_command, status, data_json, session_id,
                ),
            )
            await conn.commit()
            return cur.lastrowid or 0
        finally:
            await conn.close()
    except Exception:
        log.exception("chat_audit: failed to record action persona=%s intent=%s status=%s",
                      persona, intent, status)
        return 0


async def list_actions_for_project(
    project_id: str, *, limit: int = 100
) -> list[dict[str, Any]]:
    """Return the most-recent chat_actions for a project. Used by the UI."""
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT id, project_id, user_id, persona, intent, command, status, "
            "data, session_id, created_at FROM chat_actions "
            "WHERE project_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            try:
                d["data"] = json.loads(d.get("data") or "{}")
            except json.JSONDecodeError:
                pass
            result.append(d)
        return result
    finally:
        await conn.close()


async def list_actions_for_user(
    user_id: str, *, limit: int = 100
) -> list[dict[str, Any]]:
    """Return the most-recent chat_actions for a user across all projects."""
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT id, project_id, user_id, persona, intent, command, status, "
            "data, session_id, created_at FROM chat_actions "
            "WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT ?",
            (user_id, limit),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            try:
                d["data"] = json.loads(d.get("data") or "{}")
            except json.JSONDecodeError:
                pass
            result.append(d)
        return result
    finally:
        await conn.close()
