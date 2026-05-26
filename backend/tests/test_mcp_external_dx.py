"""Tests for new MCP DX fixes (#1, #5, #7 from MCP DX audit).

Coverage:
- Lane routing through create_mission (#1)
- update_mission and delete_mission tools (#5)
- State taxonomy for get_report (#7)
"""

import json
import os
import sys
import uuid

import pytest
import pytest_asyncio
import aiosqlite

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set required env vars BEFORE importing app/db modules
os.environ.setdefault("DEVFLEET_JWT_SECRET", "test-secret-do-not-use-in-prod-only-for-pytest")
os.environ.setdefault("DEVFLEET_ALLOWED_ORIGINS", "*")
os.environ.setdefault(
    "DEVFLEET_FERNET_KEY", "__X8JO5yCVC_-lOwTC1a9Zn2QTsraiyp0mEY9WOjxcU="
)


@pytest_asyncio.fixture
async def in_memory_db():
    """Create an in-memory SQLite DB with the full schema."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row

    # Import and run the schema from db.py
    import db as _db

    await conn.executescript(_db.SCHEMA)

    # Run migrations
    migrations = [
        "ALTER TABLE agent_sessions ADD COLUMN claude_session_id TEXT DEFAULT ''",
        "ALTER TABLE reports ADD COLUMN preview_url TEXT DEFAULT ''",
        "ALTER TABLE missions ADD COLUMN model TEXT DEFAULT 'claude-sonnet-4-6'",
        "ALTER TABLE missions ADD COLUMN max_turns INTEGER",
        "ALTER TABLE missions ADD COLUMN max_budget_usd REAL",
        "ALTER TABLE missions ADD COLUMN allowed_tools TEXT DEFAULT ''",
        "ALTER TABLE missions ADD COLUMN mission_type TEXT DEFAULT 'implement'",
        "ALTER TABLE agent_sessions ADD COLUMN remote_url TEXT DEFAULT ''",
        "ALTER TABLE agent_sessions ADD COLUMN total_cost_usd REAL DEFAULT 0",
        "ALTER TABLE agent_sessions ADD COLUMN total_tokens INTEGER DEFAULT 0",
        "ALTER TABLE missions ADD COLUMN parent_mission_id TEXT",
        "ALTER TABLE missions ADD COLUMN depends_on TEXT DEFAULT '[]'",
        "ALTER TABLE missions ADD COLUMN auto_dispatch INTEGER DEFAULT 0",
        "ALTER TABLE missions ADD COLUMN schedule_cron TEXT",
        "ALTER TABLE missions ADD COLUMN schedule_enabled INTEGER DEFAULT 0",
        "ALTER TABLE missions ADD COLUMN last_scheduled_at TEXT",
        "ALTER TABLE missions ADD COLUMN mission_number INTEGER",
        "ALTER TABLE missions ADD COLUMN lane TEXT DEFAULT 'coder'",
        "ALTER TABLE agent_sessions ADD COLUMN last_activity_at TEXT",
        "ALTER TABLE agent_sessions ADD COLUMN cache_read_tokens INTEGER DEFAULT 0",
        "ALTER TABLE agent_sessions ADD COLUMN cache_creation_tokens INTEGER DEFAULT 0",
        "ALTER TABLE agent_sessions ADD COLUMN branch_name TEXT DEFAULT ''",
        "ALTER TABLE missions ADD COLUMN created_by_email TEXT DEFAULT ''",
        "ALTER TABLE missions ADD COLUMN created_by_name TEXT DEFAULT ''",
    ]

    for migration in migrations:
        try:
            await conn.execute(migration)
        except Exception:
            pass

    # Create a test project
    await conn.execute(
        "INSERT INTO projects (id, name, path, description) VALUES (?, ?, ?, ?)",
        ("p1", "test-project", "/tmp/test-project", "Test project for MCP DX tests"),
    )
    await conn.commit()

    yield conn
    await conn.close()


class TestCreateMissionLaneRouting:
    """Test #1: Lane routing through create_mission."""

    async def test_create_mission_persists_explicit_lane(self, in_memory_db):
        """Passing lane='reviewer' should persist that lane in DB."""
        from mcp_external import _create_mission

        result = await _create_mission(
            {
                "project_id": "p1",
                "title": "Test Review",
                "prompt": "Review the code",
                "lane": "reviewer",
            },
            in_memory_db,
        )

        assert result["id"]
        assert result["lane"] == "reviewer"

        # Verify in DB
        cur = await in_memory_db.execute(
            "SELECT lane FROM missions WHERE id = ?", (result["id"],)
        )
        row = await cur.fetchone()
        assert row["lane"] == "reviewer"

    async def test_create_mission_derives_lane_from_mission_type(self, in_memory_db):
        """Without lane, derive from mission_type."""
        from mcp_external import _create_mission

        result = await _create_mission(
            {
                "project_id": "p1",
                "title": "Test Security",
                "prompt": "Check for vulns",
                "mission_type": "security",
            },
            in_memory_db,
        )

        assert result["mission_type"] == "security"
        assert result["lane"] == "security"

        cur = await in_memory_db.execute(
            "SELECT lane FROM missions WHERE id = ?", (result["id"],)
        )
        row = await cur.fetchone()
        assert row["lane"] == "security"

    async def test_create_mission_defaults_to_coder(self, in_memory_db):
        """No lane, no mission_type → default lane='coder'."""
        from mcp_external import _create_mission

        result = await _create_mission(
            {
                "project_id": "p1",
                "title": "Test Default",
                "prompt": "Do some coding",
            },
            in_memory_db,
        )

        assert result["lane"] == "coder"
        assert result["mission_type"] == "implement"

    async def test_create_mission_explicit_lane_overrides_mission_type(
        self, in_memory_db
    ):
        """Explicit lane should override mission_type default."""
        from mcp_external import _create_mission

        result = await _create_mission(
            {
                "project_id": "p1",
                "title": "Test Override",
                "prompt": "Testing mission",
                "mission_type": "implement",
                "lane": "e2e",
            },
            in_memory_db,
        )

        assert result["mission_type"] == "implement"
        assert result["lane"] == "e2e"

    async def test_create_mission_all_mission_types(self, in_memory_db):
        """Test lane derivation for all mission_type values."""
        from mcp_external import _create_mission

        mission_types = [
            ("implement", "coder"),
            ("fix", "coder"),
            ("full", "coder"),
            ("review", "reviewer"),
            ("security", "security"),
            ("test", "tester"),
            ("e2e", "e2e"),
            ("qa", "qa"),
            ("dynamic_test", "dynamic_tester"),
            ("explore", "explorer"),
            ("planner", "orchestrator"),
            ("orchestrator", "orchestrator"),
            ("research", "researcher"),
        ]

        for mission_type, expected_lane in mission_types:
            result = await _create_mission(
                {
                    "project_id": "p1",
                    "title": f"Test {mission_type}",
                    "prompt": "Test",
                    "mission_type": mission_type,
                },
                in_memory_db,
            )
            assert result["lane"] == expected_lane, f"Failed for {mission_type}"


class TestUpdateMission:
    """Test #5: update_mission tool."""

    async def test_update_mission_changes_fields(self, in_memory_db):
        """Update title, prompt, priority → confirm new values."""
        from mcp_external import _create_mission, _update_mission

        # Create a mission first
        created = await _create_mission(
            {
                "project_id": "p1",
                "title": "Original Title",
                "prompt": "Original prompt",
                "priority": 0,
            },
            in_memory_db,
        )
        mid = created["id"]

        # Update it
        result = await _update_mission(
            {
                "mission_id": mid,
                "title": "Updated Title",
                "prompt": "Updated prompt",
                "priority": 2,
            },
            in_memory_db,
        )

        assert result["id"] == mid
        assert result["updated"]["title"] == "Updated Title"
        assert result["updated"]["prompt"] == "Updated prompt"
        assert result["updated"]["priority"] == 2

        # Verify in DB
        cur = await in_memory_db.execute(
            "SELECT title, detailed_prompt, priority FROM missions WHERE id = ?",
            (mid,),
        )
        row = await cur.fetchone()
        assert row["title"] == "Updated Title"
        assert row["detailed_prompt"] == "Updated prompt"
        assert row["priority"] == 2

    async def test_update_mission_refuses_running(self, in_memory_db):
        """Cannot update a running mission."""
        from mcp_external import _create_mission, _update_mission

        created = await _create_mission(
            {
                "project_id": "p1",
                "title": "Running Mission",
                "prompt": "Test",
            },
            in_memory_db,
        )
        mid = created["id"]

        # Set status to running
        await in_memory_db.execute(
            "UPDATE missions SET status = ? WHERE id = ?", ("running", mid)
        )
        await in_memory_db.commit()

        # Try to update
        result = await _update_mission(
            {
                "mission_id": mid,
                "title": "New Title",
            },
            in_memory_db,
        )

        assert "error" in result

    async def test_update_mission_replaces_depends_on(self, in_memory_db):
        """Update depends_on → confirm list is replaced, not appended."""
        from mcp_external import _create_mission, _update_mission

        created = await _create_mission(
            {
                "project_id": "p1",
                "title": "Test",
                "prompt": "Test",
                "depends_on": ["old-id"],
            },
            in_memory_db,
        )
        mid = created["id"]

        # Update depends_on
        result = await _update_mission(
            {
                "mission_id": mid,
                "depends_on": ["new-id-1", "new-id-2"],
            },
            in_memory_db,
        )

        assert result["updated"]["depends_on"] == ["new-id-1", "new-id-2"]

        # Verify in DB (JSON list)
        cur = await in_memory_db.execute(
            "SELECT depends_on FROM missions WHERE id = ?", (mid,)
        )
        row = await cur.fetchone()
        deps = json.loads(row["depends_on"])
        assert deps == ["new-id-1", "new-id-2"]

    async def test_update_mission_returns_error_for_unknown(self, in_memory_db):
        """Bogus mission_id → error."""
        from mcp_external import _update_mission

        result = await _update_mission(
            {
                "mission_id": "unknown-id",
                "title": "New Title",
            },
            in_memory_db,
        )

        assert "error" in result

    async def test_update_mission_changes_auto_dispatch(self, in_memory_db):
        """Update auto_dispatch field."""
        from mcp_external import _create_mission, _update_mission

        created = await _create_mission(
            {
                "project_id": "p1",
                "title": "Test",
                "prompt": "Test",
                "auto_dispatch": False,
            },
            in_memory_db,
        )
        mid = created["id"]

        result = await _update_mission(
            {
                "mission_id": mid,
                "auto_dispatch": True,
            },
            in_memory_db,
        )

        assert result["updated"]["auto_dispatch"] is True

    async def test_update_mission_changes_lane(self, in_memory_db):
        """Update lane directly."""
        from mcp_external import _create_mission, _update_mission

        created = await _create_mission(
            {
                "project_id": "p1",
                "title": "Test",
                "prompt": "Test",
                "lane": "coder",
            },
            in_memory_db,
        )
        mid = created["id"]

        result = await _update_mission(
            {
                "mission_id": mid,
                "lane": "security",
            },
            in_memory_db,
        )

        assert result["updated"]["lane"] == "security"


class TestDeleteMission:
    """Test #5: delete_mission tool."""

    async def test_delete_removes_mission_and_reports(self, in_memory_db):
        """Delete cascades to reports and agent_sessions."""
        from mcp_external import _create_mission, _delete_mission

        created = await _create_mission(
            {
                "project_id": "p1",
                "title": "To Delete",
                "prompt": "Test",
            },
            in_memory_db,
        )
        mid = created["id"]

        # Create a session and report
        sid = str(uuid.uuid4())
        await in_memory_db.execute(
            "INSERT INTO agent_sessions (id, mission_id, model) VALUES (?, ?, ?)",
            (sid, mid, "claude-sonnet-4-6"),
        )
        rid = str(uuid.uuid4())
        await in_memory_db.execute(
            "INSERT INTO reports (id, session_id, mission_id, what_done) VALUES (?, ?, ?, ?)",
            (rid, sid, mid, "Finished"),
        )
        await in_memory_db.commit()

        # Delete
        result = await _delete_mission({"mission_id": mid}, in_memory_db)

        assert result["deleted"] is True

        # Verify cascade delete
        cur = await in_memory_db.execute(
            "SELECT COUNT(*) FROM missions WHERE id = ?", (mid,)
        )
        count = (await cur.fetchone())[0]
        assert count == 0

        cur = await in_memory_db.execute(
            "SELECT COUNT(*) FROM reports WHERE id = ?", (rid,)
        )
        count = (await cur.fetchone())[0]
        assert count == 0

    async def test_delete_refuses_running(self, in_memory_db):
        """Cannot delete a running mission."""
        from mcp_external import _create_mission, _delete_mission

        created = await _create_mission(
            {
                "project_id": "p1",
                "title": "Running",
                "prompt": "Test",
            },
            in_memory_db,
        )
        mid = created["id"]

        await in_memory_db.execute(
            "UPDATE missions SET status = ? WHERE id = ?", ("running", mid)
        )
        await in_memory_db.commit()

        result = await _delete_mission({"mission_id": mid}, in_memory_db)

        assert "error" in result

    async def test_delete_refuses_when_dependents_exist(self, in_memory_db):
        """Cannot delete if other missions depend on it."""
        from mcp_external import _create_mission, _delete_mission

        # Create mission A
        a = await _create_mission(
            {
                "project_id": "p1",
                "title": "Mission A",
                "prompt": "Test",
            },
            in_memory_db,
        )
        aid = a["id"]

        # Create mission B that depends on A
        b = await _create_mission(
            {
                "project_id": "p1",
                "title": "Mission B",
                "prompt": "Test",
                "depends_on": [aid],
            },
            in_memory_db,
        )

        # Try to delete A
        result = await _delete_mission({"mission_id": aid}, in_memory_db)

        assert "error" in result
        assert "blocked_by" in result
        assert len(result["blocked_by"]) > 0

    async def test_delete_mission_not_found(self, in_memory_db):
        """Delete bogus mission → error."""
        from mcp_external import _delete_mission

        result = await _delete_mission({"mission_id": "unknown"}, in_memory_db)

        assert "error" in result


class TestGetReportStateTaxonomy:
    """Test #7: get_report state taxonomy."""

    async def test_get_report_not_found(self, in_memory_db):
        """Bogus mission_id → state='not_found'."""
        from mcp_external import _get_report

        result = await _get_report({"mission_id": "unknown"}, in_memory_db)

        assert result["state"] == "not_found"
        assert "error" in result

    async def test_get_report_pending(self, in_memory_db):
        """Mission in draft → state='pending'."""
        from mcp_external import _create_mission, _get_report

        created = await _create_mission(
            {
                "project_id": "p1",
                "title": "Pending",
                "prompt": "Test",
            },
            in_memory_db,
        )
        mid = created["id"]

        result = await _get_report({"mission_id": mid}, in_memory_db)

        assert result["state"] == "pending"
        assert result["mission_status"] == "draft"

    async def test_get_report_running(self, in_memory_db):
        """Mission running, no report → state='running'."""
        from mcp_external import _create_mission, _get_report

        created = await _create_mission(
            {
                "project_id": "p1",
                "title": "Running",
                "prompt": "Test",
            },
            in_memory_db,
        )
        mid = created["id"]

        # Create session
        sid = str(uuid.uuid4())
        await in_memory_db.execute(
            "INSERT INTO agent_sessions (id, mission_id, status, model) VALUES (?, ?, ?, ?)",
            (sid, mid, "running", "claude-sonnet-4-6"),
        )

        # Set mission to running
        await in_memory_db.execute(
            "UPDATE missions SET status = ? WHERE id = ?", ("running", mid)
        )
        await in_memory_db.commit()

        result = await _get_report({"mission_id": mid}, in_memory_db)

        assert result["state"] == "running"
        assert result["session_id"] == sid

    async def test_get_report_no_report_submitted(self, in_memory_db):
        """Completed mission, no report row → state='no_report_submitted'."""
        from mcp_external import _create_mission, _get_report

        created = await _create_mission(
            {
                "project_id": "p1",
                "title": "Completed",
                "prompt": "Test",
            },
            in_memory_db,
        )
        mid = created["id"]

        # Create session
        sid = str(uuid.uuid4())
        await in_memory_db.execute(
            "INSERT INTO agent_sessions (id, mission_id, status, model) VALUES (?, ?, ?, ?)",
            (sid, mid, "completed", "claude-sonnet-4-6"),
        )

        # Set mission to completed
        await in_memory_db.execute(
            "UPDATE missions SET status = ? WHERE id = ?", ("completed", mid)
        )
        await in_memory_db.commit()

        result = await _get_report({"mission_id": mid}, in_memory_db)

        assert result["state"] == "no_report_submitted"
        assert result["session_id"] == sid

    async def test_get_report_found(self, in_memory_db):
        """Report exists → state='found' with all fields."""
        from mcp_external import _create_mission, _get_report

        created = await _create_mission(
            {
                "project_id": "p1",
                "title": "With Report",
                "prompt": "Test",
            },
            in_memory_db,
        )
        mid = created["id"]

        # Create session
        sid = str(uuid.uuid4())
        await in_memory_db.execute(
            "INSERT INTO agent_sessions (id, mission_id, status, model) VALUES (?, ?, ?, ?)",
            (sid, mid, "completed", "claude-sonnet-4-6"),
        )

        # Create report
        rid = str(uuid.uuid4())
        await in_memory_db.execute(
            """INSERT INTO reports
               (id, session_id, mission_id, files_changed, what_done, what_open,
                what_tested, what_untested, next_steps, errors_encountered)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rid,
                sid,
                mid,
                "file1.py",
                "Added feature",
                "None",
                "Tests pass",
                "Error handling",
                "Add docs",
                "None",
            ),
        )

        # Set mission to completed
        await in_memory_db.execute(
            "UPDATE missions SET status = ? WHERE id = ?", ("completed", mid)
        )
        await in_memory_db.commit()

        result = await _get_report({"mission_id": mid}, in_memory_db)

        assert result["state"] == "found"
        assert result["mission_status"] == "completed"
        assert result["files_changed"] == "file1.py"
        assert result["what_done"] == "Added feature"
        assert result["what_tested"] == "Tests pass"
        assert "created_at" in result

    async def test_get_report_completed_no_session(self, in_memory_db):
        """Completed but no session → unknown state."""
        from mcp_external import _create_mission, _get_report

        created = await _create_mission(
            {
                "project_id": "p1",
                "title": "No Session",
                "prompt": "Test",
            },
            in_memory_db,
        )
        mid = created["id"]

        # Set mission to completed without creating session
        await in_memory_db.execute(
            "UPDATE missions SET status = ? WHERE id = ?", ("completed", mid)
        )
        await in_memory_db.commit()

        result = await _get_report({"mission_id": mid}, in_memory_db)

        # Should be "unknown" since mission is completed but has no session
        assert result["state"] == "unknown"
