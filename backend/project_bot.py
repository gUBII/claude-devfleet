"""Per-project chat — routes operator messages to one of three personas.

The streaming endpoint owned by app.py calls `stream_bot_response()` here;
this module is the dispatcher that:

  1. Classifies the message via `chat_router.classify` (slash command >
     force_persona > legacy planner_mode > keyword heuristic > researcher).
  2. Emits a leading `persona` SSE event so the frontend can render the
     badge before any text streams.
  3. Performs RBAC via `auth.has_permission`. Denied turns audit-log and
     return a user-safe error — they never reach the persona.
  4. Dispatches:
       - researcher / architect → `chat_personas.run_inline_persona` (direct
         SDK call, streams text events).
       - git_operator → `chat_personas.start_git_operator_turn` (synthetic
         agent_session via the existing dispatch pipeline). Emits a
         `session_handoff` event; the frontend opens a second EventSource on
         `/api/sessions/{sid}/stream` to watch tool_use / hitl events.
  5. Persists the assistant reply to `project_bot_history` with `user_id` +
     `persona` attribution. `is_plan=1` only for architect plans (not quick
     patches) so context compaction works the same as the old planner_mode.

Audit responsibility split:
  - Permission denials + missing-precondition errors are logged here.
  - Persona success / failure rows are logged inside `chat_personas`.
  - No double-logging.

Backward compatibility:
  - `planner_mode=True` from the legacy chat client maps to forced architect.
  - Existing `text`, `error`, `done`, `plan_meta` SSE event types preserved.
  - New event types added: `persona`, `session_handoff` (git_operator only).
"""

import json
import logging

log = logging.getLogger("devfleet.project_bot")


async def stream_bot_response(
    pid: str,
    project: dict,
    message: str,
    user: dict,
    planner_mode: bool = False,
    force_persona: str | None = None,
):
    """Async generator yielding SSE `data: <json>\\n\\n` lines."""
    import auth
    import chat_audit
    import chat_personas
    import chat_router
    import db

    user_id = (user or {}).get("sub") or (user or {}).get("id") or ""
    project_id = project.get("id") or pid

    persona, intent, requires_confirm, required_permission = chat_router.classify(
        message,
        force_persona=force_persona,
        legacy_planner_mode=planner_mode,
    )
    clean_message = chat_router.strip_slash_prefix(message)

    yield (
        "data: "
        + json.dumps(
            {
                "type": "persona",
                "persona": persona,
                "intent": intent,
                "requires_confirm": requires_confirm,
            }
        )
        + "\n\n"
    )

    if required_permission and not await auth.has_permission(user_id, required_permission):
        await chat_audit.log_action(
            project_id,
            user_id,
            persona,
            intent,
            status="permission_denied",
            data={
                "permission": required_permission,
                "message_preview": (message or "")[:200],
            },
        )
        yield (
            "data: "
            + json.dumps(
                {
                    "type": "error",
                    "text": f"Permission denied: requires {required_permission}",
                }
            )
            + "\n\n"
        )
        yield "data: " + json.dumps({"type": "done"}) + "\n\n"
        return

    conn = await db.get_db()
    try:
        history_rows = await conn.execute_fetchall(
            "SELECT role, content, is_plan, plan_title FROM project_bot_history "
            "WHERE project_id=? ORDER BY created_at DESC LIMIT 20",
            (pid,),
        )
        mission_rows = await conn.execute_fetchall(
            "SELECT title, status FROM missions WHERE project_id=? "
            "AND COALESCE(is_chat_turn, 0) = 0 "
            "ORDER BY created_at DESC LIMIT 10",
            (pid,),
        )
    finally:
        await conn.close()

    history = list(reversed([dict(r) for r in history_rows]))
    missions_text = "\n".join(
        f"- [{m['status']}] {m['title']}" for m in mission_rows
    )
    missions_context = (
        f"Recent missions:\n{missions_text}" if missions_text else ""
    )

    if persona == "git_operator":
        token_row = await auth.get_github_token(user_id)
        if not token_row:
            await chat_audit.log_action(
                project_id,
                user_id,
                persona,
                intent,
                status="precondition_missing",
                data={
                    "reason": "no_github_token",
                    "message_preview": clean_message[:200],
                },
            )
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "error",
                        "text": (
                            "I need your GitHub token to run git operations. "
                            "Paste your PAT (starts with `ghp_…` or "
                            "`github_pat_…`) in this chat — I'll save it "
                            "encrypted and scrub it from the history "
                            "immediately. Generate one at "
                            "https://github.com/settings/tokens (scopes: "
                            "repo, workflow)."
                        ),
                    }
                )
                + "\n\n"
            )
            yield "data: " + json.dumps({"type": "done"}) + "\n\n"
            return
        gh_token, _gh_username = token_row

        try:
            result = await chat_personas.start_git_operator_turn(
                project,
                user,
                clean_message,
                intent,
                github_token=gh_token,
                requires_confirm=requires_confirm,
            )
        except Exception:
            log.exception(
                "Failed to start git_operator turn for project %s", project_id
            )
            await chat_audit.log_action(
                project_id,
                user_id,
                persona,
                intent,
                status="failed",
                data={"reason": "dispatch_setup_failed"},
            )
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "error",
                        "text": "Failed to start git operator — try again.",
                    }
                )
                + "\n\n"
            )
            yield "data: " + json.dumps({"type": "done"}) + "\n\n"
            return

        placeholder = (
            f"[git_operator handoff → session {result['session_id']}]"
        )
        conn = await db.get_db()
        try:
            await conn.execute(
                "INSERT INTO project_bot_history "
                "(project_id, role, content, user_id, persona, handoff_session_id) "
                "VALUES (?, 'assistant', ?, ?, 'git_operator', ?)",
                (pid, placeholder, user_id, result["session_id"]),
            )
            await conn.commit()
        finally:
            await conn.close()

        yield (
            "data: "
            + json.dumps(
                {
                    "type": "session_handoff",
                    "session_id": result["session_id"],
                    "mission_id": result["mission_id"],
                    "persona": "git_operator",
                }
            )
            + "\n\n"
        )
        yield "data: " + json.dumps({"type": "done"}) + "\n\n"
        return

    reply_chunks: list[str] = []
    try:
        async for event in chat_personas.run_inline_persona(
            persona,
            project,
            user,
            clean_message,
            history,
            intent=intent,
            extra_context=missions_context,
        ):
            if event.get("type") == "text":
                reply_chunks.append(event.get("text", ""))
            yield "data: " + json.dumps(event) + "\n\n"
    except Exception:
        log.exception("Inline persona %s failed for project %s", persona, project_id)
        yield (
            "data: "
            + json.dumps(
                {
                    "type": "error",
                    "text": "Persona stream error — please try again.",
                }
            )
            + "\n\n"
        )

    full_reply = "".join(reply_chunks)
    plan_row_id: int | None = None
    plan_title: str | None = None
    if full_reply:
        is_plan = 1 if persona == "architect" and intent == "plan" else 0
        if is_plan:
            first_line = (full_reply.splitlines() or [""])[0]
            plan_title = first_line.lstrip("# ").strip()[:200] or "Untitled plan"
        conn = await db.get_db()
        try:
            cur = await conn.execute(
                "INSERT INTO project_bot_history "
                "(project_id, role, content, is_plan, plan_title, user_id, persona) "
                "VALUES (?, 'assistant', ?, ?, ?, ?, ?)",
                (
                    pid,
                    full_reply,
                    is_plan,
                    plan_title or "",
                    user_id,
                    persona,
                ),
            )
            if is_plan:
                plan_row_id = cur.lastrowid
            await conn.commit()
        finally:
            await conn.close()

    if plan_row_id is not None:
        yield (
            "data: "
            + json.dumps(
                {"type": "plan_meta", "id": plan_row_id, "title": plan_title}
            )
            + "\n\n"
        )

    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
