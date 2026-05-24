"""Tests for backend/crypto.py — Fernet encrypt/decrypt round-trip + tamper detection."""

from __future__ import annotations

import pytest


def test_round_trip_preserves_plaintext():
    import crypto

    secret = "ghp_examplePATvalue1234567890abcd"
    assert crypto.decrypt(crypto.encrypt(secret)) == secret


def test_round_trip_handles_unicode():
    import crypto

    secret = "tøkén-with-ünicödé-✓"
    assert crypto.decrypt(crypto.encrypt(secret)) == secret


def test_empty_string_roundtrips():
    import crypto

    assert crypto.decrypt(crypto.encrypt("")) == ""


def test_each_encrypt_produces_unique_ciphertext():
    """Fernet uses a fresh IV per encryption — the same plaintext must produce
    different ciphertexts every call. Otherwise a passive observer of the DB
    could fingerprint shared tokens."""
    import crypto

    secret = "ghp_same_value"
    a = crypto.encrypt(secret)
    b = crypto.encrypt(secret)
    assert a != b
    assert crypto.decrypt(a) == secret
    assert crypto.decrypt(b) == secret


def test_tampered_ciphertext_raises_value_error():
    import crypto

    ct = crypto.encrypt("ghp_originaltoken")
    # Flip a single byte in the body (skip the Fernet version prefix at byte 0).
    tampered = ct[:-2] + ("A" if ct[-2] != "A" else "B") + ct[-1:]
    with pytest.raises(ValueError, match="Invalid or tampered ciphertext"):
        crypto.decrypt(tampered)


def test_random_string_is_not_decryptable():
    import crypto

    with pytest.raises(ValueError):
        crypto.decrypt("not-a-real-fernet-token")


def test_encrypt_rejects_non_str():
    import crypto

    with pytest.raises(TypeError, match="encrypt expects str"):
        crypto.encrypt(b"bytes-not-str")  # type: ignore[arg-type]


def test_decrypt_rejects_non_str():
    import crypto

    with pytest.raises(TypeError, match="decrypt expects str"):
        crypto.decrypt(b"bytes-not-str")  # type: ignore[arg-type]
