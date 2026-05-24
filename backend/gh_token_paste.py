"""Detect and handle inline GitHub PAT pastes in project chat.

Why this module: there is no separate frontend UI for installing a
per-user PAT. Non-Farhan users self-onboard by pasting their token into
the chat — we detect it, save it Fernet-encrypted via
`auth.set_github_token`, and scrub the plaintext from the persisted
message before it ever reaches `project_bot_history`.

Recognised formats — the ones GitHub's Settings → Developer settings
actually issues for a human operator:
  - Classic PAT:      ghp_[A-Za-z0-9]{36}        (40 chars total)
  - Fine-grained PAT: github_pat_[A-Za-z0-9_]{82,}

OAuth (gho_), user-to-server (ghu_) and server-to-server (ghs_) tokens
are intentionally NOT matched. Operators won't be pasting those, and
matching them would risk eating an unrelated string that happened to
share the prefix.
"""

from __future__ import annotations

import re

TOKEN_RE = re.compile(
    r"\b(ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82,})"
)

REDACTED = "[GitHub token redacted]"


def find_token(message: str) -> str | None:
    """Return the first PAT-shaped substring in `message`, else None."""
    if not message:
        return None
    m = TOKEN_RE.search(message)
    return m.group(1) if m else None


def redact(message: str) -> str:
    """Replace every PAT-shaped substring with REDACTED. Idempotent."""
    if not message:
        return message
    return TOKEN_RE.sub(REDACTED, message)
