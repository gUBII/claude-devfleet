"""Model router — classify per-phase difficulty and pick haiku/sonnet/opus.

Ported from the `/model-route` slash command heuristic. Backend Python can't
fire a user-facing slash command (no Claude session to host it), so the rules
live here as a deterministic function — $0 cost, instant, easy to unit-test.

The router classifies based on keyword presence in the phase title +
detailed_prompt. Three buckets:

  haiku  → deterministic, low-risk mechanical work (rename, lint, typo)
  opus   → architecture, design, deep review, ambiguous requirements
  sonnet → everything else (default)

For ambiguous prompts the heuristic stays on sonnet — picking opus
unnecessarily is the costly mistake; picking haiku for ambiguous work risks
the mission failing. Sonnet is the safe middle ground.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# Keep keywords narrow — false positives on these are expensive (haiku
# attempting an architecture task) or merely wasteful (opus on a typo fix).
# Word-boundary matching via " kw " padding is good enough; we lowercase first.

_HAIKU_KEYWORDS: tuple[str, ...] = (
    "rename", "renaming",
    "typo", "typos",
    "lint", "linting",
    "format", "formatting", "reformat",
    "prettier", "ruff", "black", "eslint",
    "import order", "isort",
    "trailing whitespace",
    "spelling",
    "comment cleanup",
    "remove unused",
    "delete dead code",
    "fix indentation",
)

_OPUS_KEYWORDS: tuple[str, ...] = (
    "architect", "architecture",
    "design system", "system design",
    "deep review", "code review",
    "ambiguous", "unclear requirements",
    "research", "investigate root cause",
    "rfc",
    "data model design", "schema design",
    "security review",
    "multi-service", "distributed",
    "refactor entire", "rearchitect",
    "propose approach", "evaluate trade-offs",
)

# Rough per-mission token estimate (input-heavy due to long prompts + tool
# outputs in context). Tuned for DevFleet's typical mission shape; can be
# overridden via the `tokens` arg. Used only for the savings nudge — not for
# anything load-bearing.
_DEFAULT_TOKENS_PER_MISSION = 50_000

# Per-1M-token blended pricing (input * 0.7 + output * 0.3 — rough mix).
# Sources: Anthropic public pricing as of 2026-Q2.
#   haiku-4.5: $1 in / $5 out  → blended ≈ $2.20
#   sonnet-4.6: $3 in / $15 out → blended ≈ $6.60
#   opus-4.7:  $15 in / $75 out → blended ≈ $33.00
_BLENDED_RATE_PER_MTOK: dict[str, float] = {
    "haiku":  2.20,
    "sonnet": 6.60,
    "opus":  33.00,
}


@dataclass(frozen=True)
class RouteDecision:
    """One phase's routing result."""
    tier: str          # 'haiku' | 'sonnet' | 'opus'
    model: str         # canonical model ID for sdk_engine
    reason: str        # short explanation for the UI chip


_TIER_TO_MODEL: dict[str, str] = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-7",
}


def _any_keyword(text: str, keywords: Iterable[str]) -> str | None:
    """Return the first matching keyword (for the UI reason), or None."""
    for kw in keywords:
        if kw in text:
            return kw
    return None


def route_model(phase_text: str) -> RouteDecision:
    """Classify a phase. Default tier is sonnet; haiku/opus require keyword match.

    `phase_text` should be the mission's title + detailed_prompt concatenated.
    """
    t = (phase_text or "").lower()

    hit = _any_keyword(t, _OPUS_KEYWORDS)
    if hit is not None:
        return RouteDecision(
            tier="opus",
            model=_TIER_TO_MODEL["opus"],
            reason=f"matched '{hit}' → deep reasoning",
        )

    hit = _any_keyword(t, _HAIKU_KEYWORDS)
    if hit is not None:
        return RouteDecision(
            tier="haiku",
            model=_TIER_TO_MODEL["haiku"],
            reason=f"matched '{hit}' → mechanical work",
        )

    return RouteDecision(
        tier="sonnet",
        model=_TIER_TO_MODEL["sonnet"],
        reason="default — general implementation",
    )


def estimate_savings_vs_sonnet(
    decisions: list[RouteDecision],
    *,
    tokens_per_mission: int = _DEFAULT_TOKENS_PER_MISSION,
) -> float:
    """Estimate dollars saved by routing N phases away from the all-Sonnet
    baseline. Opus phases COST extra (negative contribution); haiku phases SAVE.

    Result is clamped at 0.0 — we never tell a dev the routing cost them
    money, even if Opus phases dominated. The nudge framing only works with
    positive numbers.
    """
    baseline_per_mission = _BLENDED_RATE_PER_MTOK["sonnet"] * (tokens_per_mission / 1_000_000)
    total_delta = 0.0
    for d in decisions:
        actual = _BLENDED_RATE_PER_MTOK[d.tier] * (tokens_per_mission / 1_000_000)
        total_delta += baseline_per_mission - actual  # +ve when actual < baseline
    return max(total_delta, 0.0)


def route_missions(missions: list[dict]) -> tuple[list[RouteDecision], float]:
    """Batch helper: classify a planner's mission list and estimate savings.

    Each mission should have at least `title` and `detailed_prompt` keys.
    Returns (decisions in order, estimated dollars saved vs all-Sonnet).
    """
    decisions = [
        route_model(f"{m.get('title', '')} {m.get('detailed_prompt', '')}")
        for m in missions
    ]
    saved = estimate_savings_vs_sonnet(decisions)
    return decisions, saved
