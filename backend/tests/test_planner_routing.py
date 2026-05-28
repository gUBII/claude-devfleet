"""Tests for planner.py model-routing integration.

Mocks the LLM call (_call_planner) so the test runs offline and deterministically.
Verifies:
  - missions inserted with per-phase model assignments matching the router
  - result dict contains model_routing summary
  - routing disabled → all missions get default sonnet (regression guard)
  - savings are credited to authenticated devs via /api/plan
"""

from __future__ import annotations

import json
from unittest.mock import patch

import aiosqlite
import pytest


_FAKE_PLAN = json.dumps({
    "project_name": "TestProject",
    "project_description": "Generated test fixture",
    "missions": [
        {
            "title": "Rename module foo to bar",
            "detailed_prompt": "Mechanical rename across the codebase.",
            "acceptance_criteria": "All references updated",
            "mission_type": "fix",
            "tags": [],
            "depends_on_index": None,
            "priority": 1,
        },
        {
            "title": "Implement REST endpoint",
            "detailed_prompt": "Add POST /users returning 201",
            "acceptance_criteria": "Endpoint returns 201",
            "mission_type": "implement",
            "tags": [],
            "depends_on_index": 0,
            "priority": 1,
        },
        {
            "title": "Architect data model",
            "detailed_prompt": "Design system for multi-tenant isolation",
            "acceptance_criteria": "ADR written",
            "mission_type": "review",
            "tags": [],
            "depends_on_index": 1,
            "priority": 1,
        },
    ],
})

# Haiku-heavy plan — used for tests that assert savings credit. The
# 3-phase fixture above includes an Opus phase that eats the savings
# (and gets clamped to 0), which is correct behaviour but doesn't
# exercise the "credit the dev" code path.
_FAKE_PLAN_CHEAP = json.dumps({
    "project_name": "CheapProject",
    "project_description": "All-mechanical fixture",
    "missions": [
        {
            "title": "Rename module foo to bar",
            "detailed_prompt": "Mechanical rename across the codebase.",
            "acceptance_criteria": "All references updated",
            "mission_type": "fix",
            "tags": [],
            "depends_on_index": None,
            "priority": 1,
        },
        {
            "title": "Fix typos in README",
            "detailed_prompt": "Spelling cleanup only.",
            "acceptance_criteria": "No typos",
            "mission_type": "fix",
            "tags": [],
            "depends_on_index": 0,
            "priority": 1,
        },
    ],
})


@pytest.mark.asyncio
async def test_plan_project_assigns_per_phase_models(tmp_db, tmp_path):
    import planner

    with patch.object(planner, "_call_planner", return_value=_FAKE_PLAN):
        result = await planner.plan_project("any prompt", str(tmp_path / "proj"))

    assert result["model_routing"] is not None
    routing = result["model_routing"]
    assert routing["enabled"] is True
    assert len(routing["phases"]) == 3

    tiers = [p["tier"] for p in routing["phases"]]
    assert tiers == ["haiku", "sonnet", "opus"]
    # Opus eats the haiku savings here — clamp keeps the field non-negative.
    # A separate haiku-only test exercises the credit path.
    assert routing["dollars_saved_vs_sonnet"] >= 0

    # Verify the missions' model column matches the router decision
    async with aiosqlite.connect(tmp_db) as db:
        async with db.execute(
            "SELECT title, model FROM missions ORDER BY mission_number"
        ) as cur:
            rows = await cur.fetchall()
    by_title = {r[0]: r[1] for r in rows}
    assert by_title["Rename module foo to bar"] == "claude-haiku-4-5-20251001"
    assert by_title["Implement REST endpoint"] == "claude-sonnet-4-6"
    assert by_title["Architect data model"] == "claude-opus-4-7"


@pytest.mark.asyncio
async def test_plan_project_routing_disabled_keeps_all_sonnet(tmp_db, tmp_path):
    """Regression guard: passing enable_model_routing=False matches pre-Feature-1 behaviour."""
    import planner

    with patch.object(planner, "_call_planner", return_value=_FAKE_PLAN):
        result = await planner.plan_project(
            "any prompt", str(tmp_path / "proj"),
            enable_model_routing=False,
        )

    assert result["model_routing"] is None

    async with aiosqlite.connect(tmp_db) as db:
        async with db.execute("SELECT DISTINCT model FROM missions") as cur:
            rows = await cur.fetchall()
    assert [r[0] for r in rows] == ["claude-sonnet-4-6"]


@pytest.mark.asyncio
async def test_plan_endpoint_credits_authenticated_dev_with_savings(
    tmp_path, monkeypatch
):
    """When a logged-in dev plans with routing, savings flow into dev_metrics."""
    monkeypatch.setenv("DEVFLEET_FERNET_KEY", "LB3EdGLPlPohv-pv9m1f-BYRve1oS7_36Db1xaRs7N0=")
    monkeypatch.setenv("DEVFLEET_JWT_SECRET", "test-secret-for-pytest-only")

    import db as _db
    p = str(tmp_path / "plan_credit.db")
    monkeypatch.setattr(_db, "DB_PATH", p)
    await _db.init_db()

    import importlib
    import app as _app_mod
    importlib.reload(_app_mod)

    import auth as _auth
    await _auth.create_user(email="dev@x.local", password="Test1234!", role="user")

    from fastapi.testclient import TestClient
    client = TestClient(_app_mod.app)

    # Log in to get a token
    res = client.post("/api/auth/login", json={"email": "dev@x.local", "password": "Test1234!"})
    token = res.json()["access_token"]

    # Mock the planner LLM call so the test is offline + deterministic.
    # Use the cheap (haiku-heavy) fixture so savings > 0 and the credit fires.
    import planner
    with patch.object(planner, "_call_planner", return_value=_FAKE_PLAN_CHEAP):
        res = client.post(
            "/api/plan",
            json={"prompt": "demo", "project_path": str(tmp_path / "proj")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert res.status_code == 201, res.text

    # Look up the user's metrics — should have non-zero savings
    import dev_metrics
    user = await _auth.get_user_by_email("dev@x.local")
    m = await dev_metrics.get_metrics(user["id"])
    assert m is not None
    assert m["dollars_saved_routing"] > 0
    assert m["likeness_points"] > 0
    client.close()


@pytest.mark.asyncio
async def test_plan_endpoint_does_not_credit_unauthenticated(tmp_path, monkeypatch):
    """No JWT → no dev_metrics write. Backwards compat for legacy callers."""
    monkeypatch.setenv("DEVFLEET_FERNET_KEY", "LB3EdGLPlPohv-pv9m1f-BYRve1oS7_36Db1xaRs7N0=")
    monkeypatch.setenv("DEVFLEET_JWT_SECRET", "test-secret-for-pytest-only")

    import db as _db
    p = str(tmp_path / "plan_anon.db")
    monkeypatch.setattr(_db, "DB_PATH", p)
    await _db.init_db()

    import importlib
    import app as _app_mod
    importlib.reload(_app_mod)

    from fastapi.testclient import TestClient
    client = TestClient(_app_mod.app)

    import planner
    with patch.object(planner, "_call_planner", return_value=_FAKE_PLAN):
        res = client.post(
            "/api/plan",
            json={"prompt": "demo", "project_path": str(tmp_path / "proj")},
        )
    assert res.status_code == 201, res.text

    # No dev_metrics row should exist
    async with aiosqlite.connect(p) as db:
        async with db.execute("SELECT COUNT(*) FROM dev_metrics") as cur:
            count = (await cur.fetchone())[0]
    assert count == 0
    client.close()
