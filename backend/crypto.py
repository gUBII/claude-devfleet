"""Fernet symmetric encryption for at-rest credentials.

Currently used by: per-user GitHub PATs (users.github_token_encrypted).

The key is loaded from DEVFLEET_FERNET_KEY at import time. The process refuses
to start without it — there is no runtime key generation or fallback by design.
Tokens encrypted under one key can only be decrypted with the same key; key
rotation requires re-encrypting all stored ciphertexts.

Generate a fresh key with:
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

_KEY_ENV = "DEVFLEET_FERNET_KEY"
_KEY_MISSING_MSG = (
    f"{_KEY_ENV} env var is required for at-rest credential encryption. "
    "Generate one with: "
    'python3 -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"'
)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Lazy Fernet — module import must not crash when no encrypted tokens
    are in play yet (e.g. fresh install, prod backend under launchd that
    hasn't had the key added to its plist). The error surfaces the moment
    encrypt/decrypt is actually called."""
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.environ.get(_KEY_ENV)
    if not key:
        raise RuntimeError(_KEY_MISSING_MSG)
    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string. Returns an ASCII Fernet token."""
    if not isinstance(plaintext, str):
        raise TypeError(f"encrypt expects str, got {type(plaintext).__name__}")
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token. Raises ValueError on invalid/tampered input."""
    if not isinstance(ciphertext, str):
        raise TypeError(f"decrypt expects str, got {type(ciphertext).__name__}")
    try:
        return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Invalid or tampered ciphertext") from exc
