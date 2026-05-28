"""Tests for the structured MCP error envelope (DX hygiene item #1).

Covers `_error_envelope` shape and `_classify_exception` mapping. These are the
typed errors `call_tool` returns to MCP clients in place of a bare
`{"error": str(e)}`, with a stable `code` clients can branch on.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("DEVFLEET_JWT_SECRET", "test-secret-do-not-use-in-prod-only-for-pytest")
os.environ.setdefault("DEVFLEET_ALLOWED_ORIGINS", "*")
os.environ.setdefault(
    "DEVFLEET_FERNET_KEY", "__X8JO5yCVC_-lOwTC1a9Zn2QTsraiyp0mEY9WOjxcU="
)

from mcp_external import _error_envelope, _classify_exception


def test_envelope_shape_with_retry():
    env = _error_envelope("RATE_LIMITED", "slow down", retry_after_ms=5000)
    assert env == {
        "ok": False,
        "error": {"code": "RATE_LIMITED", "message": "slow down", "retry_after_ms": 5000},
    }


def test_envelope_default_retry_is_none():
    assert _error_envelope("INTERNAL", "boom")["error"]["retry_after_ms"] is None


def test_keyerror_maps_to_invalid_params_with_field_name():
    env = _classify_exception(KeyError("project_id"))
    assert env["ok"] is False
    assert env["error"]["code"] == "INVALID_PARAMS"
    assert env["error"]["message"] == "Missing required field: project_id"


def test_valueerror_maps_to_invalid_params():
    assert _classify_exception(ValueError("bad value"))["error"]["code"] == "INVALID_PARAMS"


def test_typeerror_maps_to_invalid_params():
    assert _classify_exception(TypeError("wrong type"))["error"]["code"] == "INVALID_PARAMS"


def test_other_exceptions_map_to_internal():
    env = _classify_exception(RuntimeError("db connection lost"))
    assert env["error"]["code"] == "INTERNAL"
    assert env["error"]["message"] == "db connection lost"
