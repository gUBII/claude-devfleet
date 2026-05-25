"""GitHub identity fetch.

Calls GET https://api.github.com/user with the user's PAT and returns the
fields we persist for per-user git attribution: login, name, and the noreply
email built from the numeric user id (which works even when the user's primary
email is private).

Failure is always non-fatal at the call site — if GitHub is down or the PAT
lacks `read:user`, we return None and the worktree falls back to repo-level
git config (likely Farhan's machine identity). The persona prompt will then
nudge the user to refresh their PAT.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("devfleet.gh_identity")

_GITHUB_USER_URL = "https://api.github.com/user"
_NOREPLY_DOMAIN = "users.noreply.github.com"


@dataclass(frozen=True)
class GitHubIdentity:
    login: str
    name: str
    noreply_email: str


async def fetch_github_identity(token: str, *, timeout: float = 5.0) -> GitHubIdentity | None:
    """Return identity for the PAT holder, or None on any failure.

    The noreply_email format is `<numeric_id>+<login>@users.noreply.github.com`,
    matching what GitHub itself sets when "Keep my email address private" is on.
    """
    if not token:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(_GITHUB_USER_URL, headers=headers)
    except Exception as exc:
        log.warning("GitHub /user fetch failed: %s", exc)
        return None

    if resp.status_code != 200:
        log.warning(
            "GitHub /user returned %d (body: %s)",
            resp.status_code,
            resp.text[:200],
        )
        return None

    try:
        data = resp.json()
    except ValueError as exc:
        log.warning("GitHub /user returned non-JSON: %s", exc)
        return None

    login = (data.get("login") or "").strip()
    user_id = data.get("id")
    if not login or not isinstance(user_id, int):
        log.warning("GitHub /user missing login or id: keys=%s", list(data.keys()))
        return None

    name = (data.get("name") or "").strip() or login
    noreply_email = f"{user_id}+{login}@{_NOREPLY_DOMAIN}"

    return GitHubIdentity(login=login, name=name, noreply_email=noreply_email)
