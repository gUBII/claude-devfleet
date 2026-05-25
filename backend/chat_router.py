"""Chat intent classifier.

Turns a free-form operator message into a routing decision used by the chat
endpoint to pick a persona executor and apply RBAC.

Routing precedence (highest first):
  1. Slash prefix in the message: `/haiku`, `/gitsheba` (or legacy `/sonnet`),
     `/opus` → direct map.
  2. Explicit `force_persona` from the API body (ProjectChatRequest).
  3. Legacy `planner_mode=True` → architect.
  4. Keyword heuristic on the message text.
  5. Default → researcher (read-only is always the safe fallback).

Why heuristic instead of an LLM classifier:
  - Chat is streaming-first; adding ~200ms classifier latency per turn is
    user-visible. The slash command + the audit log + the persona system
    prompts together absorb misclassification — getting routed to the wrong
    persona at worst means a wrong tool, never a wrong action.
  - Deterministic + zero-cost is easier to test and reason about.
"""

from __future__ import annotations

import logging
import re

from models import (
    CHAT_PERSONAS,
    DESTRUCTIVE_VERBS,
    INTENT_PERMISSIONS,
    ChatPersona,
)

log = logging.getLogger("devfleet.chat_router")

# Slash prefix must be the FIRST token; otherwise discussing "/gitsheba" in
# prose wouldn't accidentally route the message. `/sonnet` is retained as a
# legacy alias — drop it once telemetry shows zero usage.
_SLASH_RE = re.compile(r"^\s*/(haiku|gitsheba|sonnet|opus)\b", re.IGNORECASE)

_SLASH_TO_PERSONA: dict[str, ChatPersona] = {
    "haiku": "researcher",
    "gitsheba": "git_operator",
    "sonnet": "git_operator",  # legacy alias
    "opus": "architect",
}

# Two heuristic vocabularies, matched against the lowercased message.
_GIT_KEYWORDS = re.compile(
    r"\b(merge|rebase|push|pull request|pr\b|branch|commit|gh\b|git\b|cherry-pick|squash)",
    re.IGNORECASE,
)
_PLAN_KEYWORDS = re.compile(
    r"\b(plan|architect|design|roadmap|spec|patch|fix\b|refactor|propose)",
    re.IGNORECASE,
)


def strip_slash_prefix(message: str) -> str:
    """Return the message with any leading `/persona` prefix removed.

    Used by persona executors so the operator's actual question reaches the
    SDK without the routing slash. `/sonnet merge PR 42` → `merge PR 42`.
    """
    return _SLASH_RE.sub("", message, count=1).lstrip()


def _detect_intent(message: str, persona: ChatPersona) -> str:
    """Map (persona, message) → a coarse INTENT_PERMISSIONS key.

    Read-personas always emit `read` / `plan` / `quick_patch`. Git operator
    inspects the message for the most specific git verb in order of
    destructiveness; falls back to `git_other` for unrecognized commands.
    """
    lo = message.lower()
    if persona == "researcher":
        return "read"
    if persona == "architect":
        if "patch" in lo or "fix" in lo:
            return "quick_patch"
        return "plan"
    # git_operator from here on
    if "merge" in lo and ("pr" in lo or "pull request" in lo):
        return "pr_merge"
    if ("create" in lo or "open" in lo) and ("pr" in lo or "pull request" in lo):
        return "pr_create"
    if "push" in lo:
        return "push"
    if "commit" in lo:
        return "commit"
    return "git_other"


def _detect_destructive(message: str) -> bool:
    lo = message.lower()
    return any(verb in lo for verb in DESTRUCTIVE_VERBS)


def classify(
    message: str,
    *,
    force_persona: str | None = None,
    legacy_planner_mode: bool = False,
) -> tuple[ChatPersona, str, bool, str | None]:
    """Classify a chat message.

    Returns:
        persona: one of {"researcher", "git_operator", "architect"}.
        intent: a coarse intent name in INTENT_PERMISSIONS.
        requires_confirm: True if the persona is confirm-required AND a
            destructive verb was matched. False otherwise.
        required_permission: the CHAT_PERMISSIONS string required for this
            intent, or None for read/plan/quick_patch.
    """
    # 1. Slash command — first token wins, overrides everything else.
    slash = _SLASH_RE.match(message)
    if slash:
        persona: ChatPersona = _SLASH_TO_PERSONA[slash.group(1).lower()]
    elif force_persona in CHAT_PERSONAS:
        persona = force_persona  # type: ignore[assignment]
    elif legacy_planner_mode:
        persona = "architect"
    else:
        # 2. Keyword heuristic. Git verbs beat plan verbs because they're
        #    more action-specific; ambiguous messages fall to researcher.
        if _GIT_KEYWORDS.search(message):
            persona = "git_operator"
        elif _PLAN_KEYWORDS.search(message):
            persona = "architect"
        else:
            persona = "researcher"

    intent = _detect_intent(message, persona)
    requires_confirm = bool(
        CHAT_PERSONAS[persona]["requires_confirm"] and _detect_destructive(message)
    )
    required_permission = INTENT_PERMISSIONS.get(intent)

    log.debug(
        "classify(message=%r) → persona=%s intent=%s confirm=%s perm=%s",
        message[:80], persona, intent, requires_confirm, required_permission,
    )
    return persona, intent, requires_confirm, required_permission
