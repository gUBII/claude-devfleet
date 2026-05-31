"""
Git Worktree Isolation

Each agent session gets its own git worktree so it can't break the main codebase.
After the session, the worktree can be merged (if successful) or discarded.

Structure:
  project_root/
    .devfleet-worktrees/
      session-{id}/   (worktree checkout on branch devfleet/{id})
"""

import asyncio
import logging
import os
import shutil

log = logging.getLogger("devfleet.worktree")


async def _run(
    cmd: list[str], cwd: str, env: dict[str, str] | None = None
) -> tuple[int, str, str]:
    kwargs = dict(
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if env is not None:
        kwargs["env"] = env
    proc = await asyncio.create_subprocess_exec(*cmd, **kwargs)
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode().strip(), stderr.decode().strip()


async def is_git_repo(path: str) -> bool:
    code, _, _ = await _run(["git", "rev-parse", "--is-inside-work-tree"], path)
    return code == 0


async def create_worktree(
    project_path: str,
    session_id: str,
    mission: dict | None = None,
    git_identity: dict | None = None,
) -> tuple[str | None, str | None]:
    """Create an isolated git worktree. Returns (worktree_path, branch_name) or (None, None).

    If `git_identity` is provided as `{"login", "name", "noreply_email"}`, set
    `git config user.name`/`user.email` inside the worktree so commits the
    agent makes are attributed to the human operator (not the machine
    default). Missing identity is non-fatal — git falls back to repo/global
    config and the persona prompt will flag it.
    """
    if not await is_git_repo(project_path):
        log.info("Project %s is not a git repo — skipping worktree isolation", project_path)
        return None, None

    short_id = session_id[:8]
    if mission:
        lane = (mission.get("lane") or "").strip() or "coder"
        mission_num = mission.get("mission_number") or 0
        branch_name = f"devfleet/{lane}/{mission_num}-{short_id}"
    else:
        branch_name = f"devfleet/{short_id}"
    worktree_dir = os.path.join(project_path, ".devfleet-worktrees")
    worktree_path = os.path.join(worktree_dir, f"session-{short_id}")

    os.makedirs(worktree_dir, exist_ok=True)

    # Refresh origin/main when there's a remote — main is the canonical baseline
    # (pseudo-prod). Best-effort: a local-only project (e.g. an auto-provisioned
    # personal folder) has no `origin`, so this just fails quietly.
    await _run(["git", "fetch", "origin", "main"], project_path)

    # Pick the base ref with graceful fallback: origin/main (synced remote) →
    # local main → HEAD. A personal folder created by provisioning.py has only a
    # local `main`, so hard-requiring origin/main would fail every dispatch.
    base_ref = None
    for candidate in ("origin/main", "main", "HEAD"):
        code, _, _ = await _run(
            ["git", "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"],
            project_path,
        )
        if code == 0:
            base_ref = candidate
            break
    if base_ref is None:
        log.error("No usable base ref (origin/main|main|HEAD) in %s", project_path)
        return None, None

    # Branch from the resolved baseline so agent work is grounded in current state
    code, out, err = await _run(
        ["git", "worktree", "add", "-b", branch_name, worktree_path, base_ref],
        project_path,
    )
    if code != 0:
        log.error("Failed to create worktree: %s", err)
        return None, None
    if base_ref != "origin/main":
        log.info("Worktree based on %s (origin/main unavailable) in %s", base_ref, project_path)

    log.info("Created worktree at %s on branch %s", worktree_path, branch_name)

    # Per-user git author identity + HTTPS credential helper, written to
    # PER-WORKTREE config (`extensions.worktreeConfig` + `git config --worktree`)
    # so they never leak into the shared common config. A plain `git config
    # --local` from inside a worktree targets the SHARED config, which poisons
    # the main checkout — e.g. the scheduler's `git fetch` inheriting a
    # GH_TOKEN-based helper it can't satisfy, failing auth every cycle. Failure
    # is non-fatal: git falls back to repo/global config.
    if git_identity:
        # Enable per-worktree config before any --worktree write (idempotent;
        # honored on git >= 2.20 regardless of core.repositoryformatversion).
        await _run(
            ["git", "config", "extensions.worktreeConfig", "true"], worktree_path
        )
        gi_name = (git_identity.get("name") or git_identity.get("login") or "").strip()
        gi_email = (git_identity.get("noreply_email") or "").strip()
        if gi_name:
            code, _, gerr = await _run(
                ["git", "config", "--worktree", "user.name", gi_name], worktree_path
            )
            if code != 0:
                log.warning("git config user.name failed: %s", gerr)
        if gi_email:
            code, _, gerr = await _run(
                ["git", "config", "--worktree", "user.email", gi_email], worktree_path
            )
            if code != 0:
                log.warning("git config user.email failed: %s", gerr)
        if gi_name and gi_email:
            log.info(
                "Worktree git identity set: %s <%s>", gi_name, gi_email
            )

        # Credential helper for HTTPS remotes. SSH remotes ignore this entirely.
        # GH_TOKEN is read from the agent process env at the moment `git push`
        # runs — set by sdk_engine when dispatching with a per-user PAT.
        # Scoped to https://github.com so other helpers (e.g. macOS keychain
        # for unrelated hosts) keep working. --worktree keeps it out of the
        # shared config so the scheduler's main-checkout fetch is unaffected.
        _, _, _ = await _run(
            ["git", "config", "--worktree", "credential.https://github.com.helper", ""],
            worktree_path,
        )
        await _run(
            ["git", "config", "--worktree", "--add",
             "credential.https://github.com.helper",
             "!f() { echo username=x-access-token; echo \"password=${GH_TOKEN:-}\"; }; f"],
            worktree_path,
        )

    # Pre-warm node_modules so the agent doesn't OOM during install inside the session.
    # pnpm install runs here (pre-agent) where a failure is cheap and clearly scoped.
    lock_file = os.path.join(worktree_path, "pnpm-lock.yaml")
    if os.path.exists(lock_file):
        pnpm_cmd = shutil.which("pnpm") or "pnpm"
        pnpm_env = {**os.environ, "NODE_OPTIONS": "--max-old-space-size=3072"}
        log.info("Pre-warming pnpm install in worktree %s…", worktree_path)
        pw_code, _, pw_err = await _run(
            [pnpm_cmd, "install", "--frozen-lockfile", "--prefer-offline"],
            worktree_path,
            env=pnpm_env,
        )
        if pw_code != 0:
            log.warning("pnpm pre-warm failed (exit %d): %s — agent will proceed anyway", pw_code, pw_err[:300])

    # Add .devfleet-worktrees to .gitignore if not already there
    gitignore_path = os.path.join(project_path, ".gitignore")
    marker = ".devfleet-worktrees"
    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r") as f:
            if marker not in f.read():
                with open(gitignore_path, "a") as f2:
                    f2.write(f"\n{marker}/\n")
    else:
        with open(gitignore_path, "w") as f:
            f.write(f"{marker}/\n")

    return worktree_path, branch_name


async def cleanup_worktree(
    project_path: str,
    session_id: str,
    merge: bool = False,
    branch_name: str | None = None,
) -> bool:
    """Remove a worktree. Optionally safe-merge its branch first.

    Safe-merge protocol:
    1. Check for new commits on the branch.
    2. Attempt merge with --no-commit --no-ff (dry run).
    3. If conflicts detected → abort, preserve worktree, return False.
    4. If clean → complete the merge with a descriptive commit message.
    5. Verify no conflict markers leaked into tracked files.
    """
    short_id = session_id[:8]
    # Use provided branch_name (lane-aware naming) or fall back to legacy format
    if not branch_name:
        branch_name = f"devfleet/{short_id}"
    worktree_path = os.path.join(project_path, ".devfleet-worktrees", f"session-{short_id}")

    if merge:
        # Step 1: any commits to merge?
        code, out, _ = await _run(
            ["git", "log", f"HEAD..{branch_name}", "--oneline"],
            project_path,
        )
        if code == 0 and out.strip():
            # Step 2: dry-run merge — detect conflicts without committing
            code, _, err = await _run(
                ["git", "merge", "--no-commit", "--no-ff", branch_name],
                project_path,
            )

            # Step 3: check for unmerged paths (conflict markers)
            _, unmerged, _ = await _run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                project_path,
            )

            if unmerged.strip():
                # Conflicts — abort and preserve worktree for human/orchestrator resolution
                await _run(["git", "merge", "--abort"], project_path)
                log.warning(
                    "Safe-merge CONFLICT for session %s — conflicts in: %s. "
                    "Worktree preserved at %s for resolution.",
                    short_id, unmerged.strip().replace("\n", ", "), worktree_path,
                )
                return False

            # Step 4: also verify no stray conflict markers in any tracked file
            _, marker_files, _ = await _run(
                ["git", "grep", "-l", "<<<<<<", "--cached"],
                project_path,
            )
            if marker_files.strip():
                await _run(["git", "merge", "--abort"], project_path)
                log.warning(
                    "Safe-merge MARKER check failed for session %s — conflict markers in: %s.",
                    short_id, marker_files.strip().replace("\n", ", "),
                )
                return False

            # Step 5: clean — finalise the merge
            code, _, err = await _run(
                ["git", "commit", "--no-edit", "-m",
                 f"Farhanmerge(devfleet): integrate session {short_id}"],
                project_path,
            )
            if code != 0:
                log.warning("Merge commit failed for session %s: %s", short_id, err)
                await _run(["git", "merge", "--abort"], project_path)
                return False

            log.info("Safe-merge completed for session %s", short_id)

    # Remove worktree
    code, _, err = await _run(["git", "worktree", "remove", "--force", worktree_path], project_path)
    if code != 0:
        log.warning("Failed to remove worktree %s: %s", worktree_path, err)
        if os.path.exists(worktree_path):
            shutil.rmtree(worktree_path, ignore_errors=True)

    # Delete the branch
    await _run(["git", "branch", "-D", branch_name], project_path)

    log.info("Cleaned up worktree for session %s (merge=%s)", short_id, merge)
    return True
