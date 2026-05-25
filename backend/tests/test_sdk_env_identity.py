"""_build_sdk_options must wire per-user git identity + GH_TOKEN into the
agent process env, not just into MCP subprocess env.

Failure modes this guards against:
  - GIT_AUTHOR_EMAIL set from `mission.created_by_email` (a local-only email
    like adil@devfleet.local) overrides the worktree's noreply identity and
    commits land with an unverifiable author.
  - GH_TOKEN reaches mcp_context/mcp_devfleet but NOT the agent's Bash tool,
    so `gh pr merge` / `git push` fall back to the machine credential helper
    (Farhan's PAT), breaking per-user attribution silently.
"""

from __future__ import annotations

import pytest


def _mission(created_by_email: str = "", created_by_name: str = "") -> dict:
    return {
        "id": "m1",
        "project_id": "p1",
        "title": "Test",
        "detailed_prompt": "",
        "model": "claude-sonnet-4-6",
        "lane": "coder",
        "created_by_email": created_by_email,
        "created_by_name": created_by_name,
        "allowed_tools": "Read,Bash",
    }


@pytest.mark.asyncio
async def test_git_identity_overrides_chat_creator_email(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFLEET_FERNET_KEY", "LB3EdGLPlPohv-pv9m1f-BYRve1oS7_36Db1xaRs7N0=")
    monkeypatch.setenv("DEVFLEET_JWT_SECRET", "test-secret-for-pytest-only")

    import importlib
    import sdk_engine
    importlib.reload(sdk_engine)

    identity = {
        "login": "adil-mug",
        "name": "Adil M",
        "noreply_email": "1234567+adil-mug@users.noreply.github.com",
    }
    sdk_options = await sdk_engine._build_sdk_options(
        mission=_mission(created_by_email="adil@devfleet.local", created_by_name="adil"),
        opts=None,
        work_dir=str(tmp_path),
        github_token="ghp_fake_token_value",
        git_identity=identity,
    )

    env = sdk_options.env
    # Identity wins over chat creator
    assert env["GIT_AUTHOR_EMAIL"] == "1234567+adil-mug@users.noreply.github.com"
    assert env["GIT_COMMITTER_EMAIL"] == "1234567+adil-mug@users.noreply.github.com"
    assert env["GIT_AUTHOR_NAME"] == "Adil M"
    assert env["GIT_COMMITTER_NAME"] == "Adil M"
    # Token reaches the agent process, not just MCP subprocesses
    assert env["GH_TOKEN"] == "ghp_fake_token_value"
    assert env["GITHUB_TOKEN"] == "ghp_fake_token_value"


@pytest.mark.asyncio
async def test_chat_creator_fallback_when_no_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVFLEET_FERNET_KEY", "LB3EdGLPlPohv-pv9m1f-BYRve1oS7_36Db1xaRs7N0=")
    monkeypatch.setenv("DEVFLEET_JWT_SECRET", "test-secret-for-pytest-only")

    import importlib
    import sdk_engine
    importlib.reload(sdk_engine)

    sdk_options = await sdk_engine._build_sdk_options(
        mission=_mission(created_by_email="farhan@devfleet.local", created_by_name="Farhan"),
        opts=None,
        work_dir=str(tmp_path),
        github_token=None,
        git_identity=None,
    )
    env = sdk_options.env
    assert env["GIT_AUTHOR_EMAIL"] == "farhan@devfleet.local"
    assert env["GIT_AUTHOR_NAME"] == "Farhan"
    # No token → no GH_TOKEN injected
    assert "GH_TOKEN" not in env
    assert "GITHUB_TOKEN" not in env


@pytest.mark.asyncio
async def test_no_identity_no_creator_no_git_env(tmp_path, monkeypatch):
    """Mission with neither identity nor creator → no GIT_AUTHOR_* — git falls
    through to repo + global config."""
    monkeypatch.setenv("DEVFLEET_FERNET_KEY", "LB3EdGLPlPohv-pv9m1f-BYRve1oS7_36Db1xaRs7N0=")
    monkeypatch.setenv("DEVFLEET_JWT_SECRET", "test-secret-for-pytest-only")

    import importlib
    import sdk_engine
    importlib.reload(sdk_engine)

    sdk_options = await sdk_engine._build_sdk_options(
        mission=_mission(),  # empty creator fields
        opts=None,
        work_dir=str(tmp_path),
        github_token=None,
        git_identity=None,
    )
    env = sdk_options.env
    assert "GIT_AUTHOR_EMAIL" not in env
    assert "GIT_AUTHOR_NAME" not in env
