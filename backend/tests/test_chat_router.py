"""Tests for backend/chat_router.py — heuristic intent classifier."""

from __future__ import annotations

import pytest


# ─── Slash command precedence ─────────────────────────────────────────────


def test_slash_haiku_routes_to_researcher():
    from chat_router import classify

    persona, intent, confirm, perm = classify("/haiku what's the latest commit?")
    assert persona == "researcher"
    assert intent == "read"
    assert confirm is False
    assert perm is None


def test_slash_sonnet_routes_to_git_operator():
    from chat_router import classify

    persona, _, _, _ = classify("/sonnet show me PR status")
    assert persona == "git_operator"


def test_slash_opus_routes_to_architect():
    from chat_router import classify

    persona, _, _, _ = classify("/opus plan a refactor")
    assert persona == "architect"


def test_slash_must_be_first_token():
    """Discussing /sonnet in prose shouldn't route to git_operator."""
    from chat_router import classify

    persona, _, _, _ = classify("Should we use /sonnet for this kind of question?")
    assert persona == "researcher"  # falls back to default


def test_slash_overrides_keywords():
    """`/haiku merge PR 42` stays researcher — slash beats heuristic."""
    from chat_router import classify

    persona, intent, confirm, _ = classify("/haiku merge PR 42")
    assert persona == "researcher"
    assert intent == "read"
    assert confirm is False


def test_slash_case_insensitive():
    from chat_router import classify

    persona, _, _, _ = classify("/SONNET merge PR 1")
    assert persona == "git_operator"


def test_slash_with_leading_whitespace():
    from chat_router import classify

    persona, _, _, _ = classify("   /opus plan something")
    assert persona == "architect"


def test_strip_slash_prefix_removes_routing():
    from chat_router import strip_slash_prefix

    assert strip_slash_prefix("/sonnet merge PR 42") == "merge PR 42"
    assert strip_slash_prefix("/haiku explain mission_watcher") == "explain mission_watcher"
    assert strip_slash_prefix("no slash here") == "no slash here"


# ─── force_persona ─────────────────────────────────────────────────────────


def test_force_persona_when_no_slash():
    from chat_router import classify

    persona, _, _, _ = classify("merge PR 42", force_persona="researcher")
    assert persona == "researcher"


def test_force_persona_unknown_value_ignored():
    """An invalid force_persona falls through to heuristic — never crashes."""
    from chat_router import classify

    persona, _, _, _ = classify("merge PR 42", force_persona="cthulhu")
    # Heuristic picks git_operator on "merge"
    assert persona == "git_operator"


# ─── legacy planner_mode ──────────────────────────────────────────────────


def test_legacy_planner_mode_routes_to_architect():
    from chat_router import classify

    persona, intent, _, _ = classify("refactor the watcher", legacy_planner_mode=True)
    assert persona == "architect"
    assert intent == "plan"


def test_slash_beats_legacy_planner_mode():
    from chat_router import classify

    persona, _, _, _ = classify("/sonnet do the thing", legacy_planner_mode=True)
    assert persona == "git_operator"


# ─── Keyword heuristics ───────────────────────────────────────────────────


def test_git_keyword_merge_picks_git_operator():
    from chat_router import classify

    persona, intent, confirm, perm = classify("merge PR 42 please")
    assert persona == "git_operator"
    assert intent == "pr_merge"
    assert confirm is True  # destructive verb "merge"
    assert perm == "git.pr.merge"


def test_git_keyword_push_picks_git_operator_with_confirm():
    from chat_router import classify

    persona, intent, confirm, perm = classify("push the branch upstream")
    assert persona == "git_operator"
    assert intent == "push"
    assert confirm is True
    assert perm == "git.push"


def test_git_keyword_commit_no_destructive_confirm():
    """`commit` is not in DESTRUCTIVE_VERBS — should NOT trigger confirm."""
    from chat_router import classify

    persona, intent, confirm, perm = classify("commit the staged changes")
    assert persona == "git_operator"
    assert intent == "commit"
    assert confirm is False
    assert perm == "git.commit"


def test_plan_keyword_picks_architect():
    from chat_router import classify

    persona, intent, _, _ = classify("plan a migration to PostgreSQL")
    assert persona == "architect"
    assert intent == "plan"


def test_patch_keyword_picks_architect_quickpatch():
    from chat_router import classify

    persona, intent, _, _ = classify("quick patch for the null check")
    assert persona == "architect"
    assert intent == "quick_patch"


def test_default_is_researcher():
    from chat_router import classify

    persona, intent, confirm, perm = classify("hey, how are you")
    assert persona == "researcher"
    assert intent == "read"
    assert confirm is False
    assert perm is None


def test_git_beats_plan_when_both_keywords_present():
    """Action verbs (git) outrank plan verbs because they're more specific."""
    from chat_router import classify

    persona, _, _, _ = classify("plan a merge of PR 42")
    assert persona == "git_operator"


# ─── Destructive-verb detection ────────────────────────────────────────────


def test_force_push_triggers_confirm():
    from chat_router import classify

    _, _, confirm, _ = classify("force push to origin/feat-x")
    assert confirm is True


def test_reset_hard_triggers_confirm():
    from chat_router import classify

    _, _, confirm, _ = classify("git reset --hard HEAD~2")
    assert confirm is True


def test_pr_question_not_destructive():
    """Asking about PRs (not acting on them) shouldn't trigger confirm."""
    from chat_router import classify

    persona, intent, confirm, _ = classify("show me PR list")
    assert persona == "git_operator"
    # intent could be pr_create due to "show", but should not require confirm
    assert confirm is False


def test_intent_for_pr_create():
    from chat_router import classify

    persona, intent, _, perm = classify("open a PR from this branch")
    assert persona == "git_operator"
    assert intent == "pr_create"
    assert perm == "git.pr.create"


# ─── Read intents need no permission ──────────────────────────────────────


def test_read_intent_no_permission_required():
    from chat_router import classify

    _, intent, _, perm = classify("what does mission_watcher do?")
    assert intent == "read"
    assert perm is None


def test_plan_intent_no_permission_required():
    from chat_router import classify

    _, intent, _, perm = classify("design a migration plan")
    assert intent == "plan"
    assert perm is None
