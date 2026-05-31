"""
Personal-project provisioning.

When a teammate signs up via an invite token, they get a personal git project
folder bound to them — a private workspace they own from day one. This module
turns an invite's display_name (+ optional folder_name) into:

  1. a collision-safe folder under the projects base,
  2. a fresh git repo with `main` checked out + one empty seed commit (so agent
     worktrees can branch from `main` immediately — see worktree.py),
  3. a `projects` row stamped with `created_by = <user_id>` (ownership), and
  4. a `user_project_access` binding so the user can see + dispatch into it.

Self-contained on purpose: the register request path must not import the heavy
`mcp_external` module (it pulls in mcp.server + mission_watcher). The tiny
slug/base helpers are duplicated here rather than imported.
"""

import asyncio
import logging
import os
import re
import shutil
import uuid

import db
from auth import grant_project_access

log = logging.getLogger("devfleet.provisioning")


async def _run(cmd: list[str], cwd: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()


def _projects_base() -> str:
    base = os.environ.get("DEVFLEET_PROJECTS_DIR")
    if not base:
        devfleet_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        base = os.path.join(devfleet_root, "projects")
    return base


def _slugify(text: str, max_len: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower().strip())[:max_len].strip("-")


def _safe_slug(display_name: str, folder_seed: str, user_id: str) -> str:
    """Slug from folder_seed (preferred) or display_name. Falls back to a
    guaranteed-safe identity slug when the name slugifies to empty — e.g. it was
    all punctuation, `..`/`.`, or non-Latin script that `_slugify` strips out."""
    seed = (folder_seed or "").strip() or (display_name or "").strip()
    slug = _slugify(seed)
    if not slug:
        slug = f"user-{user_id[:8]}"
    return slug


async def _unique_project_path(base_real: str, slug: str) -> tuple[str, str]:
    """Return (final_slug, abs_path) for a folder under `base_real` that collides
    with neither an on-disk directory nor an existing `projects.path`. Appends
    -2, -3, ... until free."""
    conn = await db.get_db()
    try:
        candidate = slug
        n = 1
        while True:
            path = os.path.join(base_real, candidate)
            on_disk = os.path.exists(path)
            rows = await conn.execute_fetchall(
                "SELECT 1 FROM projects WHERE path=?", (path,)
            )
            if not on_disk and not rows:
                return candidate, path
            n += 1
            candidate = f"{slug}-{n}"
    finally:
        await conn.close()


async def _git_init_main(path: str, who: str) -> None:
    """Init a repo with `main` as the initial branch + one empty seed commit so
    agent worktrees can branch from `main` right away (worktree.py needs a ref).

    The seed commit is authored as the workspace owner (`who`) via inline `-c`
    flags — no global-config writes, and never any AI/automation attribution.
    worktree.py later overrides author identity per-worktree from the operator's
    GitHub PAT, so this is only the baseline.
    """
    # `git init -b main` needs git >= 2.28; fall back for older gits.
    code, _, err = await _run(["git", "init", "-b", "main"], path)
    if code != 0:
        code, _, err = await _run(["git", "init"], path)
        if code != 0:
            raise RuntimeError(f"git init failed: {err}")
        # No commits yet, so repointing HEAD lands the first commit on `main`.
        await _run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], path)

    code, _, err = await _run(
        [
            "git",
            "-c", f"user.name={who}",
            "-c", "user.email=noreply@devfleet.local",
            "commit", "--allow-empty", "-m", f"Initialize personal project for {who}",
        ],
        path,
    )
    if code != 0:
        raise RuntimeError(f"git seed commit failed: {err}")


async def provision_personal_project(
    user_id: str, display_name: str, folder_seed: str = ""
) -> dict:
    """Create + bind a personal project folder for a freshly-registered user.

    Returns {project_id, name, path, slug}. On any failure this rolls back its
    OWN partial state (the folder + the projects row) and re-raises — the caller
    (register) is then responsible only for rolling back the user + invite token.
    """
    base = _projects_base()
    os.makedirs(base, exist_ok=True)
    base_real = os.path.realpath(base)

    slug = _safe_slug(display_name, folder_seed, user_id)
    final_slug, path = await _unique_project_path(base_real, slug)

    # Defence-in-depth: `_slugify` already strips path separators, but confirm the
    # resolved path can't escape the projects base before we makedirs anything.
    resolved = os.path.realpath(path)
    if os.path.commonpath([base_real, resolved]) != base_real:
        final_slug = f"user-{user_id[:8]}"
        path = os.path.join(base_real, final_slug)

    name = display_name.strip() or final_slug
    project_name = f"{name}'s Workspace"
    description = f"Personal project for {name}"
    project_id = str(uuid.uuid4())

    created_dir = False
    inserted = False
    try:
        # exist_ok=False: _unique_project_path picked a free slug, but a concurrent
        # same-slug register can still win the race here — that surfaces as a
        # retryable 500, never corruption.
        os.makedirs(path)
        created_dir = True

        await _git_init_main(path, name)

        conn = await db.get_db()
        try:
            await conn.execute(
                "INSERT INTO projects (id, name, path, description, created_by) "
                "VALUES (?,?,?,?,?)",
                (project_id, project_name, path, description, user_id),
            )
            await conn.commit()
            inserted = True
        finally:
            await conn.close()

        await grant_project_access(user_id, project_id, granted_by=user_id)

        log.info(
            "Provisioned personal project %s (%s) for user %s",
            project_id, path, user_id,
        )
        return {
            "project_id": project_id,
            "name": project_name,
            "path": path,
            "slug": final_slug,
        }
    except Exception:
        log.exception(
            "Personal-project provisioning failed for user %s — rolling back", user_id
        )
        if inserted:
            try:
                conn = await db.get_db()
                try:
                    await conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
                    await conn.commit()
                finally:
                    await conn.close()
            except Exception:
                log.exception("Rollback: failed to delete project row %s", project_id)
        if created_dir:
            shutil.rmtree(path, ignore_errors=True)
        raise
