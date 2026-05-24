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


async def create_user(email: str, password: str, role: str = "user") -> dict:
    user_id = str(uuid.uuid4())
    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, role) VALUES (?,?,?,?)",
            (user_id, email, hash_password(password), role),
        )
        await conn.commit()
        return {"id": user_id, "email": email, "role": role}
    finally:
        await conn.close()


async def create_invite_token(created_by: str) -> str:
    token = str(uuid.uuid4())
    expire = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    conn = await db.get_db()
    try:
        await conn.execute(
            "INSERT INTO invite_tokens (token, created_by, expires_at) VALUES (?,?,?)",
            (token, created_by, expire),
        )
        await conn.commit()
        return token
    finally:
        await conn.close()


async def consume_invite_token(token: str, used_by: str) -> bool:
    """Mark token used. Returns False if invalid/expired/already-used."""
    conn = await db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT token FROM invite_tokens WHERE token=? AND used_by IS NULL AND expires_at > datetime('now')",
            (token,),
        )
        if not rows:
            return False
        await conn.execute(
            "UPDATE invite_tokens SET used_by=?, used_at=datetime('now') WHERE token=?",
            (used_by, token),
        )
        await conn.commit()
        return True
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


async def set_github_token(
    user_id: str, token: str, github_username: str = ""
) -> None:
    """Store the user's GitHub PAT, encrypted at rest. The legacy plaintext
    `github_token` column is cleared so we never have both copies on disk."""
    import crypto

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
            "UPDATE users SET github_token='', github_token_encrypted='', github_username='' "
            "WHERE id=?",
            (user_id,),
        )
        await conn.commit()
    finally:
        await conn.close()
