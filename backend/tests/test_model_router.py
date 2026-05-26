"""Tests for model_router — the /model-route heuristic in Python."""

from __future__ import annotations

import pytest

from model_router import (
    route_model,
    route_missions,
    estimate_savings_vs_sonnet,
)


# ─── route_model classification ────────────────────────────────────────────


def test_route_haiku_for_mechanical_rename():
    d = route_model("Rename utility function for clarity")
    assert d.tier == "haiku"
    assert "rename" in d.reason.lower()


def test_route_haiku_for_lint_fix():
    d = route_model("Run prettier and fix linting violations across src/")
    assert d.tier == "haiku"


def test_route_opus_for_architecture():
    d = route_model("Design system for multi-tenant data isolation")
    assert d.tier == "opus"


def test_route_opus_for_ambiguous_research():
    d = route_model("Investigate root cause of intermittent test failures")
    assert d.tier == "opus"


def test_route_sonnet_for_default_implementation():
    d = route_model("Implement REST endpoint for creating users")
    assert d.tier == "sonnet"


def test_route_sonnet_for_empty_text():
    d = route_model("")
    assert d.tier == "sonnet"


def test_route_sonnet_for_none_text():
    d = route_model(None)  # type: ignore[arg-type]
    assert d.tier == "sonnet"


def test_route_opus_wins_over_haiku_when_both_present():
    """Architecture trumps mechanical — 'rename' shouldn't downgrade an arch task."""
    d = route_model("Architect the multi-tenant rename strategy")
    assert d.tier == "opus"


def test_route_is_case_insensitive():
    d = route_model("RENAME the controller")
    assert d.tier == "haiku"


# ─── model ID mapping ──────────────────────────────────────────────────────


def test_haiku_decision_uses_canonical_model_id():
    d = route_model("Fix typos in README")
    assert d.model == "claude-haiku-4-5-20251001"


def test_sonnet_decision_uses_canonical_model_id():
    d = route_model("Add caching layer")
    assert d.model == "claude-sonnet-4-6"


def test_opus_decision_uses_canonical_model_id():
    d = route_model("System design for event bus")
    assert d.model == "claude-opus-4-7"


# ─── savings math ──────────────────────────────────────────────────────────


def test_savings_positive_when_haiku_replaces_sonnet():
    decisions = [route_model("Fix typos"), route_model("Lint check")]
    saved = estimate_savings_vs_sonnet(decisions)
    assert saved > 0


def test_savings_clamped_to_zero_when_opus_dominates():
    """Opus is more expensive than Sonnet — we never report negative savings."""
    decisions = [route_model("Architect the system"), route_model("Architect data model")]
    saved = estimate_savings_vs_sonnet(decisions)
    assert saved == 0.0


def test_savings_zero_for_all_sonnet():
    decisions = [route_model("Implement feature A"), route_model("Implement feature B")]
    saved = estimate_savings_vs_sonnet(decisions)
    assert saved == 0.0


# ─── batch helper ──────────────────────────────────────────────────────────


def test_route_missions_returns_decision_per_input():
    missions = [
        {"title": "Rename module", "detailed_prompt": ""},
        {"title": "Architect API", "detailed_prompt": ""},
        {"title": "Add tests", "detailed_prompt": ""},
    ]
    decisions, saved = route_missions(missions)
    assert len(decisions) == 3
    tiers = [d.tier for d in decisions]
    assert tiers == ["haiku", "opus", "sonnet"]


def test_route_missions_concatenates_title_and_prompt():
    """Keywords in the detailed_prompt should still classify, not just the title."""
    missions = [{"title": "Phase 1", "detailed_prompt": "Run prettier on all files"}]
    decisions, _ = route_missions(missions)
    assert decisions[0].tier == "haiku"
