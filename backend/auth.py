"""JWT auth utilities for DevFleet online."""
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt, JWTError
from passlib.context import CryptContext

import db

log = logging.getLogger("devfleet")

SECRET_KEY = os.environ.get("DEVFLEET_JWT_SECRET")
if not SECRET_KEY:
    raise RuntimeError(
        "DEVFLEET_JWT_SECRET must be set — refusing to start without a secret key. "
        "Generate one with: openssl rand -hex 32"
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Precomputed at startup so login timing is constant whether the email exists or not.
# Used by verify_password when the user lookup returns None.
DUMMY_HASH = _pwd.hash("__devfleet_dummy_password_for_constant_time__")


def hash_password(plain: str) -> str:
    if len(plain.encode("utf-8")) > 72:
        raise ValueError("Password must be 72 bytes or fewer (bcrypt limit)")
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    """Verify a password. If hashed is None/empty, runs bcrypt against a dummy
    hash to preserve constant-time behavior, then returns False."""
    if not hashed:
        _pwd.verify(plain, DUMMY_HASH)
        return False
    return _pwd.verify(plain, hashed)


def create_access_token(user_id: str, email: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": user_id, "email": email, "role": role, "exp": expire},
        SECRET_KEY, algorithm=ALGORITHM,
    )


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises JWTError on invalid/expired."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


async def get_user_by_email(email: str) -> dict | None:
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall("SELECT * FROM users WHERE email=?", (email,))
        return dict(rows[0]) if rows else None
    finally:
        await conn.close()


async def get_user_by_id(user_id: str) -> dict | None:
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall("SELECT * FROM users WHERE id=?", (user_id,))
        return dict(rows[0]) if rows else None
    finally:
        await conn.close()


async def create_user(
    email: str, password: str, role: str = "user", display_name: str = ""
) -> dict:
    user_id = str(uuid.uuid4())
    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, role, display_name) VALUES (?,?,?,?,?)",
            (user_id, email, hash_password(password), role, display_name),
        )
        await conn.commit()
        return {"id": user_id, "email": email, "role": role, "display_name": display_name}
    finally:
        await conn.close()


async def set_user_display_name(user_id: str, display_name: str) -> None:
    """Patch a user's display name. Used by register after the invite token
    (which carries the admin-entered name) is consumed."""
    conn = await db.get_db()
    try:
        await conn.execute(
            "UPDATE users SET display_name=? WHERE id=?", (display_name, user_id)
        )
        await conn.commit()
    finally:
        await conn.close()


async def create_invite_token(
    created_by: str, display_name: str = "", folder_name: str = ""
) -> str:
    """Mint an invite token. `display_name` is the teammate's name (shown on the
    leaderboard + seeds their personal folder); `folder_name` optionally overrides
    the folder slug. Both ride the token row admin→signup."""
    token = str(uuid.uuid4())
    expire = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT INTO invite_tokens (token, created_by, expires_at, display_name, folder_name) "
            "VALUES (?,?,?,?,?)",
            (token, created_by, expire, display_name, folder_name),
        )
        await conn.commit()
        return token
    finally:
        await conn.close()


async def consume_invite_token(token: str, used_by: str) -> dict | None:
    """Atomically mark the token used and return its row (incl. display_name /
    folder_name). Returns None if invalid/expired/already-used.

    The UPDATE is guarded by `used_by IS NULL` and we check the affected
    rowcount, so two concurrent registers racing on the same token can't both
    win — the loser sees rowcount 0 and gets None.
    """
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT token, created_by, display_name, folder_name, expires_at "
            "FROM invite_tokens WHERE token=? AND used_by IS NULL "
            "AND expires_at > datetime('now')",
            (token,),
        )
        if not rows:
            return None
        cur = await conn.execute(
            "UPDATE invite_tokens SET used_by=?, used_at=datetime('now') "
            "WHERE token=? AND used_by IS NULL AND expires_at > datetime('now')",
            (used_by, token),
        )
        if cur.rowcount == 0:
            # Lost the race — another register consumed it, or it expired between
            # the SELECT and the UPDATE.
            await conn.rollback()
            return None
        await conn.commit()
        return dict(rows[0])
    finally:
        await conn.close()


async def release_invite_token(token: str) -> None:
    """Un-consume a token so its invite link works again. Called by register's
    saga rollback when personal-project provisioning fails after the token was
    already marked used — the admin's link stays valid for a retry."""
    conn = await db.get_db()
    try:
        await conn.execute(
            "UPDATE invite_tokens SET used_by=NULL, used_at=NULL WHERE token=?",
            (token,),
        )
        await conn.commit()
    finally:
        await conn.close()


# ──────────────────────────────────────────────────────────────────────────
# Persona chat — RBAC + per-user GitHub PAT (Fernet-encrypted at rest)
# ──────────────────────────────────────────────────────────────────────────


async def has_permission(user_id: str, permission: str) -> bool:
    """Return True if the user has the given chat permission.

    Admins implicitly hold every permission — this keeps the matrix small and
    avoids accidental admin lockout when a new permission is introduced.
    Non-admins need an explicit row in user_permissions.
    """
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT role FROM users WHERE id=?", (user_id,)
        )
        if rows and dict(rows[0]).get("role") == "admin":
            return True
        rows = await conn.execute_fetchall(
            "SELECT 1 FROM user_permissions WHERE user_id=? AND permission=?",
            (user_id, permission),
        )
        return bool(rows)
    finally:
        await conn.close()


async def grant_permission(user_id: str, permission: str, granted_by: str) -> None:
    """Idempotently grant a permission."""
    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT OR IGNORE INTO user_permissions "
            "(user_id, permission, granted_by) VALUES (?, ?, ?)",
            (user_id, permission, granted_by),
        )
        await conn.commit()
    finally:
        await conn.close()


async def revoke_permission(user_id: str, permission: str) -> None:
    """Revoke a permission. Idempotent — revoking an absent grant is a no-op."""
    conn = await db.get_db()
    try:
        await conn.execute(
            "DELETE FROM user_permissions WHERE user_id=? AND permission=?",
            (user_id, permission),
        )
        await conn.commit()
    finally:
        await conn.close()


async def list_permissions(user_id: str) -> list[str]:
    """Return the user's explicit permission grants. Admins do NOT short-circuit
    here — this surface backs the permissions UI, where admins should see their
    role from the role column rather than every-permission-checked."""
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT permission FROM user_permissions WHERE user_id=? ORDER BY permission",
            (user_id,),
        )
        return [dict(r)["permission"] for r in rows]
    finally:
        await conn.close()


# ──────────────────────────────────────────────────────────────────────────
# Project-scope bindings — which folders/projects a non-admin user may see and
# dispatch into. Admins are implicitly bound to every project (mirrors the
# has_permission admin short-circuit above).
# ──────────────────────────────────────────────────────────────────────────


async def user_has_project_access(user_id: str, project_id: str) -> bool:
    """Admin → always True. Non-admin → row must exist in user_project_access."""
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT role FROM users WHERE id=?", (user_id,)
        )
        if rows and dict(rows[0]).get("role") == "admin":
            return True
        rows = await conn.execute_fetchall(
            "SELECT 1 FROM user_project_access WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        )
        return bool(rows)
    finally:
        await conn.close()


async def is_project_owner_or_admin(user_id: str, project_id: str) -> bool:
    """True if the user is an admin OR the project's creator (`projects.created_by`).

    Authority gate for peer-sharing: only an owner (or admin) may grant/revoke
    other users' access to a project, or clone its workers elsewhere. Plain
    `user_has_project_access` is NOT enough — a shared-in collaborator can use the
    project but must not be able to re-share it."""
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT role FROM users WHERE id=?", (user_id,)
        )
        if rows and dict(rows[0]).get("role") == "admin":
            return True
        rows = await conn.execute_fetchall(
            "SELECT 1 FROM projects WHERE id=? AND created_by=?",
            (project_id, user_id),
        )
        return bool(rows)
    finally:
        await conn.close()


async def list_project_shares(project_id: str) -> list[dict]:
    """Return [{user_id, email, display_name, granted_at, granted_by}] for every
    user bound to the project, newest grant first."""
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT upa.user_id, u.email, COALESCE(u.display_name,'') AS display_name, "
            "upa.granted_at, upa.granted_by "
            "FROM user_project_access upa JOIN users u ON u.id = upa.user_id "
            "WHERE upa.project_id=? ORDER BY upa.granted_at DESC",
            (project_id,),
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def list_accessible_project_ids(user_id: str) -> list[str] | None:
    """Return None for admins (sentinel: caller must NOT filter). For non-admins
    return the explicit list of bound project IDs (possibly empty)."""
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT role FROM users WHERE id=?", (user_id,)
        )
        if rows and dict(rows[0]).get("role") == "admin":
            return None
        rows = await conn.execute_fetchall(
            "SELECT project_id FROM user_project_access WHERE user_id=? "
            "ORDER BY granted_at",
            (user_id,),
        )
        return [dict(r)["project_id"] for r in rows]
    finally:
        await conn.close()


async def grant_project_access(
    user_id: str, project_id: str, granted_by: str
) -> None:
    """Idempotently bind a user to a project."""
    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT OR IGNORE INTO user_project_access "
            "(user_id, project_id, granted_by) VALUES (?, ?, ?)",
            (user_id, project_id, granted_by),
        )
        await conn.commit()
    finally:
        await conn.close()


async def revoke_project_access(user_id: str, project_id: str) -> None:
    """Revoke a binding. Idempotent — revoking an absent binding is a no-op."""
    conn = await db.get_db()
    try:
        await conn.execute(
            "DELETE FROM user_project_access WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        )
        await conn.commit()
    finally:
        await conn.close()


async def list_user_project_bindings(user_id: str) -> list[dict]:
    """Return [{project_id, project_name, project_path, granted_at, granted_by}]
    for the user's bound projects, newest grant first."""
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT upa.project_id, p.name AS project_name, p.path AS project_path, "
            "upa.granted_at, upa.granted_by "
            "FROM user_project_access upa "
            "JOIN projects p ON p.id = upa.project_id "
            "WHERE upa.user_id=? ORDER BY upa.granted_at DESC",
            (user_id,),
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def set_github_token(
    user_id: str, token: str, github_username: str = ""
) -> None:
    """Store the user's GitHub PAT, encrypted at rest. The legacy plaintext
    `github_token` column is cleared so we never have both copies on disk.

    After persisting the token, attempt to fetch the user's GitHub identity
    (login + name + noreply email) and cache it on the row. Network failure
    here is non-fatal — the token is already saved; the identity columns
    just stay empty and worktree git config will fall back to the repo
    default (which the persona prompt will flag).
    """
    import crypto
    from gh_identity import fetch_github_identity

    enc = crypto.encrypt(token)
    conn = await db.get_db()
    try:
        await conn.execute(
            "UPDATE users SET github_token_encrypted=?, github_username=?, github_token='' "
            "WHERE id=?",
            (enc, github_username, user_id),
        )
        await conn.commit()
    finally:
        await conn.close()

    identity = await fetch_github_identity(token)
    if identity is None:
        log.warning(
            "GitHub identity fetch failed for user %s — git author fields stay empty",
            user_id,
        )
        return

    conn = await db.get_db()
    try:
        await conn.execute(
            "UPDATE users SET github_login=?, github_name=?, github_noreply_email=? "
            "WHERE id=?",
            (identity.login, identity.name, identity.noreply_email, user_id),
        )
        await conn.commit()
    finally:
        await conn.close()


async def get_github_identity(user_id: str) -> dict | None:
    """Return cached {login, name, noreply_email} or None if not populated.

    Used by the dispatcher to set `git config user.name/user.email` inside
    the worktree so commits land under the operator's identity rather than
    Farhan's machine identity.
    """
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT github_login, github_name, github_noreply_email "
            "FROM users WHERE id=?",
            (user_id,),
        )
    finally:
        await conn.close()
    if not rows:
        return None
    row = dict(rows[0])
    login = (row.get("github_login") or "").strip()
    if not login:
        return None
    return {
        "login": login,
        "name": (row.get("github_name") or "").strip() or login,
        "noreply_email": (row.get("github_noreply_email") or "").strip(),
    }


async def get_github_token(user_id: str) -> tuple[str, str] | None:
    """Decrypt and return (token, github_username) or None.

    Falls back to the legacy plaintext `github_token` column for rows that
    pre-date encryption AND failed to encrypt at boot (e.g. Fernet key was
    missing during init_db). Returning plaintext beats failing dispatch, but
    log.warning so the operator can fix the deployment.
    """
    import crypto

    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT github_token, github_token_encrypted, github_username FROM users WHERE id=?",
            (user_id,),
        )
        if not rows:
            return None
        row = dict(rows[0])
    finally:
        await conn.close()

    enc = (row.get("github_token_encrypted") or "").strip()
    username = (row.get("github_username") or "").strip()
    if enc:
        try:
            return crypto.decrypt(enc), username
        except ValueError as exc:
            log.warning("Failed to decrypt github_token for user %s: %s", user_id, exc)
            return None

    plain = (row.get("github_token") or "").strip()
    if plain:
        log.warning(
            "Returning unencrypted github_token for user %s — encryption migration "
            "did not run for this row. Set DEVFLEET_FERNET_KEY and restart.",
            user_id,
        )
        return plain, username
    return None


async def clear_github_token(user_id: str) -> None:
    """Wipe both token columns + the username for the user."""
    conn = await db.get_db()
    try:
        await conn.execute(
            "UPDATE users SET github_token='', github_token_encrypted='', github_username='', "
            "github_login='', github_name='', github_noreply_email='' "
            "WHERE id=?",
            (user_id,),
        )
        await conn.commit()
    finally:
        await conn.close()
