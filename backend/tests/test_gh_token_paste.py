"""Tests for gh_token_paste — PAT detection + scrubbing.

Why these patterns and not others: only classic (ghp_…) and fine-grained
(github_pat_…) PATs are issued from Settings → Developer settings for a
human operator. OAuth/server tokens are not in scope and must NOT match —
otherwise we risk eating an unrelated string that happens to share the
prefix.
"""

from __future__ import annotations

import pytest


def test_detects_classic_pat():
    import gh_token_paste

    msg = "here you go ghp_abcdefghijklmnopqrstuvwxyz0123456789 thanks"
    token = gh_token_paste.find_token(msg)
    assert token == "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


def test_detects_fine_grained_pat():
    import gh_token_paste

    # 82+ chars after the github_pat_ prefix — built deterministically.
    body = ("a" * 41) + "_" + ("B" * 41)  # 83 chars, contains _ which is in the alphabet
    msg = f"my token: github_pat_{body}"
    token = gh_token_paste.find_token(msg)
    assert token == f"github_pat_{body}"


def test_no_token_returns_none():
    import gh_token_paste

    assert gh_token_paste.find_token("just a normal message about ghp_short") is None
    assert gh_token_paste.find_token("") is None
    assert gh_token_paste.find_token("plain text") is None


def test_does_not_match_other_prefixes():
    """OAuth (gho_), user-to-server (ghu_), server-to-server (ghs_) are
    out of scope and must not be eaten by the detector."""
    import gh_token_paste

    for prefix in ("gho_", "ghu_", "ghs_"):
        msg = f"unrelated {prefix}" + "x" * 36
        assert gh_token_paste.find_token(msg) is None, prefix


def test_redact_replaces_token_with_marker():
    import gh_token_paste

    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    msg = f"please save {token} for me"
    out = gh_token_paste.redact(msg)
    assert token not in out
    assert gh_token_paste.REDACTED in out
    assert "please save" in out


def test_redact_handles_multiple_tokens():
    import gh_token_paste

    t1 = "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    t2 = "ghp_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    out = gh_token_paste.redact(f"{t1} and also {t2}")
    assert t1 not in out
    assert t2 not in out
    assert out.count(gh_token_paste.REDACTED) == 2


def test_redact_is_idempotent():
    import gh_token_paste

    msg = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    once = gh_token_paste.redact(msg)
    twice = gh_token_paste.redact(once)
    assert once == twice


def test_redact_empty_message():
    import gh_token_paste

    assert gh_token_paste.redact("") == ""
    assert gh_token_paste.redact(None) is None
