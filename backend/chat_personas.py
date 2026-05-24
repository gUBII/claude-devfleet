"""Persona executors — one entry point per persona.

Two distinct execution shapes:

  • **Inline personas** (researcher, architect) → `run_inline_persona()` is an
    async generator that streams SSE event dicts straight back to the chat
    endpoint. Read-only, no mission row, no worktree, no `ask_human`. Same
    pattern as the existing `project_bot.stream_bot_response()`.

  • **Git operator persona** → `start_git_operator_turn()` creates a synthetic
    `agent_sessions` row + a hidden mission (`is_chat_turn=1`), dispatches it
    through `sdk_engine.dispatch_mission()`, and returns `{session_id}`. The
    frontend then opens a second EventSource on the agent session's existing
    SSE endpoint to stream tool_use/text/hitl events. (Advisor option b —
    handoff. Simpler than proxying through the chat SSE.)

Why this split:
  • Inline avoids worktree / mission / dispatch overhead for read-only turns.
  • git_operator inherits the full dispatch pipeline for free: worktree
    isolation, GH_TOKEN env injection, `ask_human` blocking the SDK natively,
    `total_cost_usd` heartbeat-flush, branch-name tracking, and `mission_events`
    audit. No code duplication.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import AsyncGenerator

import chat_audit
import db
from models import CHAT_PERSONAS, ChatPersona

log = logging.getLogger("devfleet.chat_personas")


# ─── Inline personas (researcher, architect) ─────────────────────────────


def _build_inline_system_prompt(
    persona: ChatPersona,
    project: dict,
    history: list[dict],
    extra_context: str = "",
) -> str:
    """System prompt for read-only inline personas. Combines:
      - project name / path / description (Moofasa scope rules apply)
      - persona-specific extras from CHAT_PERSONAS
      - optional caller-supplied extra context (e.g. recent missions board)
      - the last ~10 turns of project_bot_history for context
    """
    policy = CHAT_PERSONAS[persona]

    history_text = ""
    for msg in (history or [])[-10:]:
        if msg.get("is_plan"):
            history_text += f"[earlier plan: {msg.get('plan_title') or 'untitled'}]\n"
        else:
            prefix = "Human" if msg.get("role") == "user" else "Assistant"
            content = (msg.get("content") or "")[:500]
            history_text += f"{prefix}: {content}\n"

    extra_block = f"\n{extra_context}\n" if extra_context else ""

    return (
        f"You are the DevFleet chat assistant for project: {project.get('name', '')}\n"
        f"Project path: {project.get('path', '')}\n"
        f"Project description: {project.get('description') or 'No description'}\n\n"
        f"{policy['system_prompt_extra']}\n\n"
        "SCOPE RULES (hard limits):\n"
        "1. You ONLY help with this project. Refuse cross-project requests.\n"
        "2. Keep responses concise and actionable.\n"
        f"{extra_block}"
        + (f"\nRecent conversation:\n{history_text}\n" if history_text else "")
    )


async def run_inline_persona(
    persona: ChatPersona,
    project: dict,
    user: dict,
    message: str,
    history: list[dict],
    *,
    intent: str = "read",
    extra_context: str = "",
) -> AsyncGenerator[dict, None]:
    """Stream SSE event dicts for a read-only persona turn.

    Yields events with shape `{type: ..., ...}`. Caller is responsible for:
      - serializing to `data: <json>\\n\\n` SSE wire format,
      - persisting the assembled reply to project_bot_history,
      - emitting any final `done` event.

    Audit log is written here (not in the caller) so the guardrail is
    unconditional — no caller can forget. One row at start (`status='started'`),
    one row at end (`status='completed'` or `'failed'`).

    Event types emitted:
      - `text`     — model output chunk (forward to client)
      - `error`    — non-fatal stream error (forward, then return)
    """
    # Lazy import — SDK is heavy and chat_personas is imported at app boot.
    from claude_code_sdk import query as sdk_query, ClaudeCodeOptions
    from claude_code_sdk.types import TextBlock

    if persona not in {"researcher", "architect"}:
        raise ValueError(f"run_inline_persona doesn't handle {persona!r}")

    policy = CHAT_PERSONAS[persona]
    cwd = (
        project["path"]
        if project.get("path") and os.path.isdir(project["path"])
        else "/tmp"
    )

    user_id = (user or {}).get("sub") or (user or {}).get("id") or ""
    project_id = project.get("id", "")

    await chat_audit.log_action(
        project_id, user_id, persona, intent,
        status="started",
        data={"message_preview": (message or "")[:200]},
    )

    system_prompt = _build_inline_system_prompt(
        persona, project, history, extra_context=extra_context
    )
    full_prompt = f"{system_prompt}\n\nHuman: {message}\n\nAssistant:"

    options = ClaudeCodeOptions(
        model=policy["model"],
        permission_mode=policy["permission_mode"],
        allowed_tools=list(policy["allowed_tools"]),
        max_turns=policy["max_turns"],
        cwd=cwd,
    )

    char_count = 0
    failed = False
    saw_text_block = False
    try:
        async for msg in sdk_query(prompt=full_prompt, options=options):
            if msg is None:
                continue
            if hasattr(msg, "content"):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        saw_text_block = True
                        char_count += len(block.text)
                        yield {"type": "text", "text": block.text}
            elif hasattr(msg, "result") and msg.result and not saw_text_block:
                char_count += len(msg.result)
                yield {"type": "text", "text": msg.result}
    except Exception:
        failed = True
        log.exception(
            "Inline persona %s stream error for project %s",
            persona, project_id,
        )
        yield {"type": "error", "text": "Persona stream error — please try again"}

    await chat_audit.log_action(
        project_id, user_id, persona, intent,
        status="failed" if failed else "completed",
        data={"reply_chars": char_count},
    )


# ─── Git operator (synthetic session via dispatch_mission) ────────────────


async def start_git_operator_turn(
    project: dict,
    user: dict,
    message: str,
    intent: str,
    *,
    github_token: str,
    requires_confirm: bool,
) -> dict:
    """Create a synthetic agent_session and dispatch via the SDK engine.

    The synthetic mission carries `is_chat_turn=1` so the mission watcher and
    operator-facing mission board both filter it out. The session_id is the
    handle the frontend uses to open a second EventSource on the existing
    `/api/sessions/{sid}/stream` endpoint and watch live tool_use / text /
    hitl_question events.

    Returns: `{"session_id": str, "mission_id": str}`.
    Raises: any underlying DB / dispatch error (caller decides surface).

    Notes for callers:
      - `github_token` MUST be a usable PAT — caller is responsible for the
        permission check and the get_github_token lookup beforehand.
      - The synthetic mission's `detailed_prompt` includes the persona's
        system_prompt_extra AND a one-liner instructing the agent to call
        `ask_human` before destructive ops. This is enforcement at the prompt
        layer — the audit log + the MCP-blocking-tool semantics together
        make bypass extremely hard.
    """
    from sdk_engine import dispatch_mission
    from app import running_tasks  # lazy — avoids circular import at module load
    from models import DispatchOptions

    policy = CHAT_PERSONAS["git_operator"]
    mission_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    detailed_prompt = (
        f"{policy['system_prompt_extra']}\n\n"
        f"Operator request:\n{message}"
    )
    if requires_confirm:
        detailed_prompt += (
            "\n\nThis request appears destructive. You MUST call the `ask_human` "
            "MCP tool BEFORE executing the command. Format:\n"
            "  ask_human(question=\"Approve running: <exact command>?\", "
            "options=[\"approve\", \"deny\"])\n"
            "Only run the command if the human replies 'approve' (case-insensitive)."
        )

    title = f"Chat: {message.strip()[:80]}"
    creator_email = (user or {}).get("email", "")
    creator_name = creator_email.split("@")[0] if creator_email else ""

    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT INTO missions "
            "(id, project_id, title, detailed_prompt, status, model, "
            "mission_type, lane, auto_dispatch, is_chat_turn, "
            "allowed_tools, created_by_email, created_by_name) "
            "VALUES (?, ?, ?, ?, 'running', ?, 'chat_op', 'coder', 0, 1, ?, ?, ?)",
            (
                mission_id, project["id"], title, detailed_prompt,
                policy["model"],
                ",".join(policy["allowed_tools"]),
                creator_email, creator_name,
            ),
        )
        await conn.execute(
            "INSERT INTO agent_sessions (id, mission_id, status, model) "
            "VALUES (?, ?, 'running', ?)",
            (session_id, mission_id, policy["model"]),
        )
        await conn.commit()

        # Fetch the full mission record back — dispatch_mission requires
        # project_path joined in.
        rows = await conn.execute_fetchall(
            "SELECT m.*, p.path AS project_path FROM missions m "
            "JOIN projects p ON p.id = m.project_id WHERE m.id = ?",
            (mission_id,),
        )
        if not rows:
            raise RuntimeError(f"synthetic mission {mission_id} vanished post-insert")
        mission_record = dict(rows[0])
    finally:
        await conn.close()

    opts = DispatchOptions(
        model=policy["model"], max_turns=policy["max_turns"]
    )

    # Audit BEFORE dispatch so the row exists even if dispatch crashes inside
    # the background task. The wrapper below augments status on terminal events.
    user_id = (user or {}).get("sub") or (user or {}).get("id") or ""
    await chat_audit.log_action(
        project["id"], user_id, "git_operator", intent,
        command=f"<chat-turn-message:{message[:120]}>",
        status="started",
        data={"requires_confirm": requires_confirm,
              "title": title, "mission_id": mission_id},
        session_id=session_id,
    )

    async def _dispatch_with_failsafe():
        """Wrap dispatch_mission so any exception flips session+mission to
        failed and audit-logs. Without this, a crash before _run_agent's own
        cleanup runs would leave both rows stuck at 'running'."""
        try:
            await dispatch_mission(
                session_id, mission_record, None,
                opts=opts, github_token=github_token,
            )
        except Exception:
            log.exception(
                "Chat git_operator dispatch crashed — session=%s mission=%s",
                session_id, mission_id,
            )
            try:
                _conn = await db.get_db()
                try:
                    await _conn.execute(
                        "UPDATE agent_sessions SET status='failed', "
                        "ended_at=datetime('now') WHERE id=? AND status='running'",
                        (session_id,),
                    )
                    await _conn.execute(
                        "UPDATE missions SET status='failed' WHERE id=? "
                        "AND status='running'",
                        (mission_id,),
                    )
                    await _conn.commit()
                finally:
                    await _conn.close()
            except Exception:
                log.exception("Also failed to mark session/mission failed")
            await chat_audit.log_action(
                project["id"], user_id, "git_operator", intent,
                status="failed", session_id=session_id,
                data={"reason": "dispatch_exception", "mission_id": mission_id},
            )

    task = asyncio.create_task(_dispatch_with_failsafe())
    running_tasks[session_id] = task

    log.info(
        "Started git_operator chat turn — session=%s mission=%s intent=%s confirm=%s",
        session_id, mission_id, intent, requires_confirm,
    )

    return {"session_id": session_id, "mission_id": mission_id}
