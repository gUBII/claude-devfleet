"""Tests for the persona/permission constants added to backend/models.py."""

from __future__ import annotations

import pytest


def test_three_personas_only():
    from models import CHAT_PERSONAS

    assert set(CHAT_PERSONAS.keys()) == {"researcher", "git_operator", "architect"}


def test_each_persona_resolves_to_valid_model():
    from models import CHAT_PERSONAS, MODEL_CHOICES

    for name, policy in CHAT_PERSONAS.items():
        assert policy["model"] in MODEL_CHOICES, (
            f"{name} persona model {policy['model']!r} not in MODEL_CHOICES"
        )


def test_persona_model_assignment_matches_spec():
    """Locked spec: Haiku for talk/research, Sonnet for git, Opus for plan."""
    from models import CHAT_PERSONAS

    assert "haiku" in CHAT_PERSONAS["researcher"]["model"].lower()
    assert "sonnet" in CHAT_PERSONAS["git_operator"]["model"].lower()
    assert "opus" in CHAT_PERSONAS["architect"]["model"].lower()


def test_only_git_operator_requires_confirm():
    from models import CHAT_PERSONAS

    assert CHAT_PERSONAS["researcher"]["requires_confirm"] is False
    assert CHAT_PERSONAS["git_operator"]["requires_confirm"] is True
    assert CHAT_PERSONAS["architect"]["requires_confirm"] is False


def test_only_git_operator_gets_bash():
    """Researcher + architect must NEVER have Bash — they're read-only."""
    from models import CHAT_PERSONAS

    assert "Bash" not in CHAT_PERSONAS["researcher"]["allowed_tools"]
    assert "Bash" not in CHAT_PERSONAS["architect"]["allowed_tools"]
    assert "Bash" in CHAT_PERSONAS["git_operator"]["allowed_tools"]


def test_intent_permissions_keys_match_known_intents():
    from models import INTENT_PERMISSIONS

    expected_intents = {
        "read", "plan", "quick_patch",
        "commit", "push", "pr_create", "pr_merge",
        "dispatch", "git_other",
    }
    assert expected_intents.issubset(INTENT_PERMISSIONS.keys())


def test_intent_permissions_values_are_known_or_none():
    from models import INTENT_PERMISSIONS, CHAT_PERMISSIONS

    for intent, perm in INTENT_PERMISSIONS.items():
        if perm is not None:
            assert perm in CHAT_PERMISSIONS, (
                f"Intent {intent!r} requires unknown permission {perm!r}"
            )


def test_read_and_plan_require_no_permission():
    """Researcher reads and architect plans must be free — no RBAC gate."""
    from models import INTENT_PERMISSIONS

    assert INTENT_PERMISSIONS["read"] is None
    assert INTENT_PERMISSIONS["plan"] is None
    assert INTENT_PERMISSIONS["quick_patch"] is None


def test_destructive_verbs_lowercase_and_actionable():
    from models import DESTRUCTIVE_VERBS

    assert len(DESTRUCTIVE_VERBS) >= 5
    for verb in DESTRUCTIVE_VERBS:
        # All-lowercase so case-insensitive substring match works after .lower()
        assert verb == verb.lower(), f"DESTRUCTIVE_VERBS must be lowercase: {verb!r}"
    assert "merge" in DESTRUCTIVE_VERBS
    assert "push" in DESTRUCTIVE_VERBS


def test_github_token_set_validates_min_length():
    from models import GitHubTokenSet
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        GitHubTokenSet(token="too-short")


def test_github_token_set_accepts_realistic_pat():
    from models import GitHubTokenSet

    body = GitHubTokenSet(token="ghp_aaaaaaaaaaaaaaaaaaaa", github_username="octocat")
    assert body.token.startswith("ghp_")
    assert body.github_username == "octocat"


def test_user_permission_grant_matches_known():
    from models import UserPermissionGrant

    good = UserPermissionGrant(permission="git.pr.merge")
    assert good.matches_known()

    bad = UserPermissionGrant(permission="something.invented")
    assert not bad.matches_known()


def test_chat_action_confirm_literal():
    from models import ChatActionConfirm
    import pydantic

    ChatActionConfirm(decision="approve")
    ChatActionConfirm(decision="deny")
    with pytest.raises(pydantic.ValidationError):
        ChatActionConfirm(decision="maybe")


def test_project_chat_request_force_persona_optional():
    """force_persona is optional and constrained to the three persona names."""
    from models import ProjectChatRequest
    import pydantic

    # No persona forced
    r = ProjectChatRequest(message="hi")
    assert r.force_persona is None

    # Valid forcing
    r2 = ProjectChatRequest(message="hi", force_persona="git_operator")
    assert r2.force_persona == "git_operator"

    # Invalid
    with pytest.raises(pydantic.ValidationError):
        ProjectChatRequest(message="hi", force_persona="unknown")
