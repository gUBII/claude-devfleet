"""Moofasa — per-project chat assistant that drafts missions (and plans).

Streams SSE chunks to the caller. Moofasa is hard-scoped to one project and
can produce two output shapes:

- Mission drafts (default, Haiku): short single-mission JSON in a ```mission
  code fence.
- Full plans (planner mode, Opus): structured markdown plans saved with
  is_plan=1 so subsequent chat history is context-compacted.

Tools are read-only (Read/Glob/Grep) under permission_mode="default" — Moofasa
can crawl the project to understand context, but cannot write or execute.
"""

import json
import logging
import os

log = logging.getLogger("devfleet.project_bot")

_BOT_SYSTEM = """You are Moofasa, the Nexis365 DevFleet assistant for the project: {project_name}
Project path: {project_path}
Project description: {description}

You help the team draft coding missions for their Claude agents. You can read
files in this project to understand the codebase before drafting.

SCOPE RULES (hard limits — never violate):
1. You ONLY help with this project. Politely refuse requests about other projects.
2. You cannot execute code, dispatch agents, or modify files directly — you only have READ tools.
3. You can: read the codebase, answer questions, give advice, and produce MISSION DRAFTS.
4. When producing a mission draft, format it exactly like this:
   ```mission
   {{"title": "...", "detailed_prompt": "...", "acceptance_criteria": "..."}}
   ```
5. The user reviews the draft and creates the mission manually.

Recent project context:
{context}

Keep responses concise and actionable."""


_PLANNER_APPEND = """

The user has requested a FULL PLAN (Planner mode, Opus). Produce a single
markdown document with these sections, in order:

# <Plan Title — one short imperative sentence>

## Context
Why this plan exists; what problem it addresses.

## Phases
Numbered phases (Phase 1, Phase 2, …) each with concrete steps the team or
agents will execute. Phases must be self-contained enough that a fresh agent
could pick one up cold.

## Acceptance Criteria
A bulleted list of mechanically-checkable conditions — what "done" looks like.

## Risks
What could go wrong, with mitigations.

## Files Touched
Table or list of paths that will change, with one-line "what changes" notes.

In Planner mode, do NOT emit ```mission code fences — this output is a roadmap,
not a single mission. The user will save the plan and may extract specific
phases into missions later.
"""


async def stream_bot_response(
    pid: str,
    project: dict,
    message: str,
    user: dict,
    planner_mode: bool = False,
):
    """Async generator yielding SSE data lines. Saves assistant reply to DB on completion.

    In planner_mode, uses Opus + a longer plan-shaped system prompt and persists
    the reply with is_plan=1 so subsequent chats compact it.
    """
    import db
    from claude_code_sdk import query as sdk_query, ClaudeCodeOptions
    from claude_code_sdk.types import TextBlock

    conn = await db.get_db()
    try:
        history_rows = await conn.execute_fetchall(
            "SELECT role, content, is_plan, plan_title FROM project_bot_history "
            "WHERE project_id=? ORDER BY created_at DESC LIMIT 20",
            (pid,),
        )
        mission_rows = await conn.execute_fetchall(
            "SELECT title, status FROM missions WHERE project_id=? ORDER BY created_at DESC LIMIT 10",
            (pid,),
        )
    finally:
        await conn.close()

    history = list(reversed([dict(r) for r in history_rows]))
    missions_text = "\n".join(f"- [{m['status']}] {m['title']}" for m in mission_rows)
    context = f"Recent missions:\n{missions_text or 'No missions yet.'}"

    system_prompt = _BOT_SYSTEM.format(
        project_name=project["name"],
        project_path=project["path"],
        description=project.get("description") or "No description",
        context=context,
    )
    if planner_mode:
        system_prompt += _PLANNER_APPEND

    # Context compaction: collapse prior plan rows to a one-liner so they
    # don't blow the prompt window on the next chat turn.
    history_text = ""
    for msg in history[:-1]:  # last entry is the user message we just saved
        if msg.get("is_plan"):
            history_text += (
                f"Assistant: [earlier: drafted plan \"{msg.get('plan_title') or 'Untitled'}\"]\n\n"
            )
        else:
            prefix = "Human" if msg["role"] == "user" else "Assistant"
            history_text += f"{prefix}: {msg['content']}\n\n"

    full_prompt = f"{system_prompt}\n\n{history_text}Human: {message}\n\nAssistant:"

    cwd = project["path"] if project.get("path") and os.path.isdir(project["path"]) else "/tmp"

    if planner_mode:
        model = os.environ.get("DEVFLEET_PLANNER_MODEL", "claude-opus-4-7")
        max_turns = 8
    else:
        model = os.environ.get("DEVFLEET_BOT_MODEL", "claude-haiku-4-5-20251001")
        max_turns = 4

    options = ClaudeCodeOptions(
        model=model,
        permission_mode="default",
        allowed_tools=["Read", "Glob", "Grep"],
        max_turns=max_turns,
        cwd=cwd,
    )

    reply_chunks: list[str] = []
    try:
        async for msg in sdk_query(prompt=full_prompt, options=options):
            if msg is None:
                continue
            if hasattr(msg, "content"):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        reply_chunks.append(block.text)
                        yield f"data: {json.dumps({'type': 'text', 'text': block.text})}\n\n"
            elif hasattr(msg, "result") and msg.result:
                reply_chunks.append(msg.result)
                yield f"data: {json.dumps({'type': 'text', 'text': msg.result})}\n\n"
    except Exception as exc:
        log.error("Bot stream error for project %s: %s", pid, exc)
        yield f"data: {json.dumps({'type': 'error', 'text': 'Bot error — please try again'})}\n\n"
        return

    full_reply = "".join(reply_chunks)
    plan_row_id = None
    plan_title = None
    if full_reply:
        if planner_mode:
            # Use first heading or first line as title.
            first_line = (full_reply.splitlines() or [""])[0]
            plan_title = first_line.lstrip("# ").strip()[:200] or "Untitled plan"
            conn = await db.get_db()
            try:
                cur = await conn.execute(
                    "INSERT INTO project_bot_history (project_id, role, content, is_plan, plan_title) "
                    "VALUES (?, 'assistant', ?, 1, ?)",
                    (pid, full_reply, plan_title),
                )
                plan_row_id = cur.lastrowid
                await conn.commit()
            finally:
                await conn.close()
        else:
            conn = await db.get_db()
            try:
                await conn.execute(
                    "INSERT INTO project_bot_history (project_id, role, content) VALUES (?, 'assistant', ?)",
                    (pid, full_reply),
                )
                await conn.commit()
            finally:
                await conn.close()

    if planner_mode and plan_row_id is not None:
        yield f"data: {json.dumps({'type': 'plan_meta', 'id': plan_row_id, 'title': plan_title})}\n\n"

    yield f"data: {json.dumps({'type': 'done'})}\n\n"
