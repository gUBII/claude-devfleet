"""Regression tests for the dispatch base-race (T3.1).

The defect: create_worktree fetched origin/main and based every worktree off it,
but cleanup_worktree merges completed agent work into LOCAL main and never pushes.
So origin/main lags local main, and new dispatches branched off stale state — silently
dropping prior agents' merged work ("v2 scaffolding lost, worktree landed on v1").

Invariant under test: a new worktree's base must never be BEHIND local `main`.
It may jump forward to origin/main when the remote is genuinely ahead.

These use real git repos (worktree.py shells out to git); no DB / env needed.
test_base_does_not_regress_below_local_main is the headline regression — it must
go RED on the pre-fix code and GREEN after.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from worktree import create_worktree


# ─── git helpers (sync; create_worktree is the only async bit) ───────────────


def _git(repo: str, *args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=check
    ).stdout.strip()


def _init_repo(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", path], check=True, capture_output=True)
    _git(path, "config", "user.email", "t@t.local")
    _git(path, "config", "user.name", "Test")
    return path


def _commit(repo: str, fname: str, content: str, msg: str) -> str:
    with open(os.path.join(repo, fname), "w") as f:
        f.write(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _clone(origin: str, dest: str, email: str = "t@t.local", name: str = "Test") -> str:
    subprocess.run(["git", "clone", origin, dest], check=True, capture_output=True)
    _git(dest, "config", "user.email", email)
    _git(dest, "config", "user.name", name)
    return dest


def _setup_clone_with_origin(tmp_path) -> tuple[str, str, str]:
    """Bare origin @ v1 + a working clone. Returns (local_path, origin_path, v1_sha)."""
    origin = str(tmp_path / "origin.git")
    subprocess.run(["git", "init", "--bare", "-b", "main", origin], check=True, capture_output=True)
    seed = _init_repo(str(tmp_path / "seed"))
    v1 = _commit(seed, "f.txt", "v1", "v1")
    _git(seed, "remote", "add", "origin", origin)
    _git(seed, "push", "origin", "main")
    local = _clone(origin, str(tmp_path / "local"))
    return local, origin, v1


def _wt_head(wt_path: str) -> str:
    return _git(wt_path, "rev-parse", "HEAD")


# ─── the headline regression ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_base_does_not_regress_below_local_main(tmp_path):
    """origin/main lags at v1; local main has merged v2 (not pushed). The worktree
    MUST base off v2, not the stale origin/main v1. RED on pre-fix code."""
    local, _origin, v1 = _setup_clone_with_origin(tmp_path)
    v2 = _commit(local, "f.txt", "v2", "v2 — merged agent work, not pushed")
    assert v2 != v1

    wt_path, branch = await create_worktree(local, "sess1234")
    assert wt_path is not None, "worktree creation must succeed"
    assert _wt_head(wt_path) == v2, "must base off local main (v2), not stale origin/main (v1)"


@pytest.mark.asyncio
async def test_sequential_dispatches_both_see_latest(tmp_path):
    """Two dispatches in sequence; local main advances between them. Neither may
    regress to a stale base (guards the 'second dispatch lands on stale' path)."""
    local, _origin, _v1 = _setup_clone_with_origin(tmp_path)
    v2 = _commit(local, "f.txt", "v2", "v2")
    wt1, _ = await create_worktree(local, "sessaaaa")
    assert _wt_head(wt1) == v2

    v3 = _commit(local, "f.txt", "v3", "v3 — second agent's merged work")
    wt2, _ = await create_worktree(local, "sessbbbb")
    assert _wt_head(wt2) == v3, "second dispatch must see v3, not stale v2/origin"


# ─── forward jumps + edge shapes ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_base_jumps_forward_to_origin_when_remote_ahead(tmp_path):
    """Remote genuinely ahead (someone pushed v2); local still v1. The fetch brings
    origin/main=v2 and the worktree should pick it up."""
    local, origin, _v1 = _setup_clone_with_origin(tmp_path)
    pusher = _clone(origin, str(tmp_path / "pusher"), email="p@p.local", name="P")
    v2 = _commit(pusher, "f.txt", "v2", "v2 pushed remotely")
    _git(pusher, "push", "origin", "main")

    wt_path, _ = await create_worktree(local, "sess2222")
    assert _wt_head(wt_path) == v2, "must jump forward to genuinely-newer origin/main"


@pytest.mark.asyncio
async def test_base_prefers_local_main_on_divergence(tmp_path):
    """Both sides have unique commits (origin: c_o, local: c_l). Base off local main
    to preserve locally-merged work; the remote-only commit must NOT be in history."""
    local, origin, _v1 = _setup_clone_with_origin(tmp_path)
    pusher = _clone(origin, str(tmp_path / "pusher"), email="p@p.local", name="P")
    c_o = _commit(pusher, "remote.txt", "remote", "c_o remote-only")
    _git(pusher, "push", "origin", "main")

    c_l = _commit(local, "local.txt", "local", "c_l local-only merged work")

    wt_path, _ = await create_worktree(local, "sess3333")
    assert _wt_head(wt_path) == c_l, "diverged → local main wins (preserve merged work)"
    # c_o (remote-only) must be unreachable from the worktree HEAD.
    reachable = subprocess.run(
        ["git", "merge-base", "--is-ancestor", c_o, "HEAD"],
        cwd=wt_path, capture_output=True,
    ).returncode
    assert reachable != 0, "remote-only commit must not be in the diverged base"


@pytest.mark.asyncio
async def test_base_uses_local_main_when_no_remote(tmp_path):
    """Personal folder (provisioning.py: git init -b main, no origin). The fetch
    fails quietly and the worktree bases off local main's tip."""
    local = _init_repo(str(tmp_path / "personal"))
    _commit(local, "f.txt", "v1", "seed")
    v2 = _commit(local, "f.txt", "v2", "more")

    wt_path, _ = await create_worktree(local, "sess4444")
    assert wt_path is not None
    assert _wt_head(wt_path) == v2
