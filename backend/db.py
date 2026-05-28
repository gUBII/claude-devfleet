import aiosqlite
import os

DB_PATH = os.environ.get("DEVFLEET_DB", os.path.join(os.path.dirname(__file__), "..", "data", "devfleet.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS missions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    detailed_prompt TEXT NOT NULL,
    acceptance_criteria TEXT DEFAULT '',
    status TEXT DEFAULT 'draft',
    priority INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    tags TEXT DEFAULT '[]',
    model TEXT DEFAULT 'claude-sonnet-4-6',
    max_turns INTEGER,
    max_budget_usd REAL,
    allowed_tools TEXT DEFAULT '',
    mission_type TEXT DEFAULT 'implement',
    parent_mission_id TEXT,
    depends_on TEXT DEFAULT '[]',
    auto_dispatch INTEGER DEFAULT 0,
    schedule_cron TEXT,
    schedule_enabled INTEGER DEFAULT 0,
    last_scheduled_at TEXT,
    mission_number INTEGER,
    lane TEXT DEFAULT '',
    created_by_email TEXT DEFAULT '',
    created_by_name TEXT DEFAULT '',
    is_chat_turn INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'running',
    started_at TEXT DEFAULT (datetime('now')),
    ended_at TEXT,
    exit_code INTEGER,
    output_log TEXT DEFAULT '',
    error_log TEXT DEFAULT '',
    model TEXT DEFAULT 'claude-sonnet-4-6',
    token_usage TEXT DEFAULT '{}',
    claude_session_id TEXT DEFAULT '',
    remote_url TEXT DEFAULT '',
    total_cost_usd REAL DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    last_activity_at TEXT,
    branch_name TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    files_changed TEXT DEFAULT '',
    what_done TEXT DEFAULT '',
    what_open TEXT DEFAULT '',
    what_tested TEXT DEFAULT '',
    what_untested TEXT DEFAULT '',
    next_steps TEXT DEFAULT '',
    errors_encountered TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS monitored_services (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    group_name TEXT DEFAULT 'Default',
    description TEXT DEFAULT '',
    check_interval INTEGER DEFAULT 30,
    timeout_ms INTEGER DEFAULT 5000,
    expected_status INTEGER DEFAULT 200,
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT NOT NULL REFERENCES monitored_services(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    response_time_ms INTEGER,
    status_code INTEGER,
    error_message TEXT DEFAULT '',
    checked_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_health_checks_service_time
    ON health_checks(service_id, checked_at DESC);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    service_id TEXT REFERENCES monitored_services(id) ON DELETE SET NULL,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'investigating',
    severity TEXT DEFAULT 'minor',
    started_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    session_id TEXT PRIMARY KEY REFERENCES agent_sessions(id) ON DELETE CASCADE,
    messages_json TEXT DEFAULT '[]',
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mission_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id TEXT NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    source_mission_id TEXT,
    data TEXT DEFAULT '{}',
    failure_layer TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_mission_events_mission
    ON mission_events(mission_id, created_at DESC);

CREATE TABLE IF NOT EXISTS mcp_configs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    server_name TEXT NOT NULL,
    server_type TEXT DEFAULT 'stdio',
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_mcp_configs_project
    ON mcp_configs(project_id);

CREATE TABLE IF NOT EXISTS lanes (
    name TEXT PRIMARY KEY,
    max_agents INTEGER NOT NULL DEFAULT 1,
    default_model TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
    tool_preset TEXT NOT NULL DEFAULT 'implement',
    append_prompt TEXT DEFAULT '',
    color TEXT DEFAULT '#888888',
    icon TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lane_mcp_tools (
    id TEXT PRIMARY KEY,
    lane_name TEXT NOT NULL REFERENCES lanes(name) ON DELETE CASCADE,
    server_name TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    trigger_hint TEXT DEFAULT 'always',
    UNIQUE(lane_name, server_name, tool_name)
);

CREATE TABLE IF NOT EXISTS lane_prompt_critiques (
    lane_name TEXT PRIMARY KEY REFERENCES lanes(name) ON DELETE CASCADE,
    critique_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prompt_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    content_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'user',
    created_at TEXT DEFAULT (datetime('now')),
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS invite_tokens (
    token TEXT PRIMARY KEY,
    created_by TEXT NOT NULL REFERENCES users(id),
    used_by TEXT REFERENCES users(id),
    used_at TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS hitl_questions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    options TEXT DEFAULT '[]',
    reply TEXT,
    asked_at TEXT DEFAULT (datetime('now')),
    answered_at TEXT
);

CREATE TABLE IF NOT EXISTS project_bot_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bot_history_project
    ON project_bot_history(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS dev_metrics (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    likeness_points INTEGER DEFAULT 0,
    pr_merges_clean INTEGER DEFAULT 0,
    pr_merges_total INTEGER DEFAULT 0,
    dollars_saved_routing REAL DEFAULT 0,
    current_clean_streak INTEGER DEFAULT 0,
    longest_clean_streak INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA cache_size=-64000")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.executescript(SCHEMA)
        # Migrations for existing DBs
        migrations = [
            "ALTER TABLE agent_sessions ADD COLUMN claude_session_id TEXT DEFAULT ''",
            "ALTER TABLE reports ADD COLUMN preview_url TEXT DEFAULT ''",
            # v2: Claude Code power features
            "ALTER TABLE missions ADD COLUMN model TEXT DEFAULT 'claude-sonnet-4-6'",
            "ALTER TABLE missions ADD COLUMN max_turns INTEGER",
            "ALTER TABLE missions ADD COLUMN max_budget_usd REAL",
            "ALTER TABLE missions ADD COLUMN allowed_tools TEXT DEFAULT ''",
            "ALTER TABLE missions ADD COLUMN mission_type TEXT DEFAULT 'implement'",
            "ALTER TABLE agent_sessions ADD COLUMN remote_url TEXT DEFAULT ''",
            "ALTER TABLE agent_sessions ADD COLUMN total_cost_usd REAL DEFAULT 0",
            "ALTER TABLE agent_sessions ADD COLUMN total_tokens INTEGER DEFAULT 0",
            # v3: Phase 3 — multi-agent, dependencies, scheduling
            "ALTER TABLE missions ADD COLUMN parent_mission_id TEXT",
            "ALTER TABLE missions ADD COLUMN depends_on TEXT DEFAULT '[]'",
            "ALTER TABLE missions ADD COLUMN auto_dispatch INTEGER DEFAULT 0",
            "ALTER TABLE missions ADD COLUMN schedule_cron TEXT",
            "ALTER TABLE missions ADD COLUMN schedule_enabled INTEGER DEFAULT 0",
            "ALTER TABLE missions ADD COLUMN last_scheduled_at TEXT",
            "ALTER TABLE missions ADD COLUMN mission_number INTEGER",
            # v4: agentic lanes
            "ALTER TABLE missions ADD COLUMN lane TEXT DEFAULT 'coder'",
            # v5: failure layer classification (dispatch vs agent)
            "ALTER TABLE mission_events ADD COLUMN failure_layer TEXT",
            # v6: activity heartbeat + accurate cost tracking
            "ALTER TABLE agent_sessions ADD COLUMN last_activity_at TEXT",
            "ALTER TABLE agent_sessions ADD COLUMN cache_read_tokens INTEGER DEFAULT 0",
            "ALTER TABLE agent_sessions ADD COLUMN cache_creation_tokens INTEGER DEFAULT 0",
            # v7: lane-aware branch naming
            "ALTER TABLE agent_sessions ADD COLUMN branch_name TEXT DEFAULT ''",
            # v8: online auth
            "ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'",
            # v9: per-user mission attribution
            "ALTER TABLE missions ADD COLUMN created_by_email TEXT DEFAULT ''",
            "ALTER TABLE missions ADD COLUMN created_by_name TEXT DEFAULT ''",
            # v10: HITL + project bot
            "CREATE TABLE IF NOT EXISTS hitl_questions (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, question TEXT NOT NULL, options TEXT DEFAULT '[]', reply TEXT, asked_at TEXT DEFAULT (datetime('now')), answered_at TEXT)",
            "CREATE TABLE IF NOT EXISTS project_bot_history (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))",
            "CREATE INDEX IF NOT EXISTS idx_bot_history_project ON project_bot_history(project_id, created_at DESC)",
            # v11: Moofasa planner mode — mark which assistant rows are plans for context compaction
            "ALTER TABLE project_bot_history ADD COLUMN is_plan INTEGER DEFAULT 0",
            "ALTER TABLE project_bot_history ADD COLUMN plan_title TEXT DEFAULT ''",
            # v12: persona chat + RBAC + encrypted GH tokens.
            # github_token already exists in some prod DBs as an out-of-band addition;
            # ensure it's tracked here, then add the encrypted twin we read from going forward.
            "ALTER TABLE users ADD COLUMN github_token TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN github_token_encrypted TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN github_username TEXT DEFAULT ''",
            "ALTER TABLE project_bot_history ADD COLUMN user_id TEXT DEFAULT ''",
            "ALTER TABLE project_bot_history ADD COLUMN persona TEXT DEFAULT ''",
            # Persisted handoff target so the "Open Live Agent →" CTA survives
            # page reload. Backend sets this when the assistant turn is a
            # git_operator handoff; empty for inline researcher/architect rows.
            "ALTER TABLE project_bot_history ADD COLUMN handoff_session_id TEXT DEFAULT ''",
            # is_chat_turn lets the mission watcher / board hide synthetic git_operator
            # chat turns from operator-facing mission lists.
            "ALTER TABLE missions ADD COLUMN is_chat_turn INTEGER DEFAULT 0",
            "CREATE TABLE IF NOT EXISTS chat_actions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "project_id TEXT NOT NULL, "
            "user_id TEXT NOT NULL, "
            "persona TEXT NOT NULL, "
            "intent TEXT NOT NULL, "
            "command TEXT DEFAULT '', "
            "status TEXT NOT NULL, "
            "data TEXT DEFAULT '{}', "
            "session_id TEXT, "
            "created_at TEXT DEFAULT (datetime('now')))",
            "CREATE INDEX IF NOT EXISTS idx_chat_actions_project ON chat_actions(project_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_chat_actions_user ON chat_actions(user_id, created_at DESC)",
            "CREATE TABLE IF NOT EXISTS chat_summaries ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "project_id TEXT NOT NULL, "
            "summary_date TEXT NOT NULL, "
            "summary TEXT NOT NULL, "
            "message_count INTEGER DEFAULT 0, "
            "action_count INTEGER DEFAULT 0, "
            "created_at TEXT DEFAULT (datetime('now')), "
            "UNIQUE(project_id, summary_date))",
            "CREATE TABLE IF NOT EXISTS user_permissions ("
            "user_id TEXT NOT NULL, "
            "permission TEXT NOT NULL, "
            "granted_by TEXT, "
            "granted_at TEXT DEFAULT (datetime('now')), "
            "PRIMARY KEY (user_id, permission))",
            # v13: GitHub identity bundle — populated from GET /user after PAT save.
            # Used to set git config user.name/user.email per-user inside the
            # worktree, so commits are attributed to the actual operator and
            # pushes go out under their credential. noreply_email avoids
            # leaking private primary emails.
            "ALTER TABLE users ADD COLUMN github_login TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN github_name TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN github_noreply_email TEXT DEFAULT ''",
            # v14: user-created lanes (Fleet Config "New Lane" button). Built-in
            # lanes from LANE_DEFAULTS stay user_created=0 so the disable-on-
            # startup guard never touches them; user lanes survive restarts.
            "ALTER TABLE lanes ADD COLUMN user_created INTEGER DEFAULT 0",
            # v15: dev_metrics — Likeness points + behaviour tracking.
            # Populated lazily on first increment; admin users get no row
            # (excluded by helpers in dev_metrics.py). Reads by DevProfiles
            # dashboard.
            "CREATE TABLE IF NOT EXISTS dev_metrics ("
            "user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, "
            "likeness_points INTEGER DEFAULT 0, "
            "pr_merges_clean INTEGER DEFAULT 0, "
            "pr_merges_total INTEGER DEFAULT 0, "
            "dollars_saved_routing REAL DEFAULT 0, "
            "current_clean_streak INTEGER DEFAULT 0, "
            "longest_clean_streak INTEGER DEFAULT 0, "
            "updated_at TEXT DEFAULT (datetime('now')))",
            # v16: skip_quality_gates opt-out flag — lets operators mark a mission
            # so the coder lane skips the REV-/TEST- sub-mission spawn step
            # and proceeds directly to submit_report.
            "ALTER TABLE missions ADD COLUMN skip_quality_gates INTEGER DEFAULT 0",
            # v17: per-user project-scope bindings. Non-admin users only see and
            # dispatch into projects bound here; admins are implicitly bound to
            # all (enforced in auth.user_has_project_access). Grandfather seed
            # below grants every existing non-admin access to every existing
            # project so the rollout doesn't strip current users; new projects
            # default-deny until an admin grants.
            "CREATE TABLE IF NOT EXISTS user_project_access ("
            "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE, "
            "granted_by TEXT, "
            "granted_at TEXT DEFAULT (datetime('now')), "
            "PRIMARY KEY (user_id, project_id))",
            "CREATE INDEX IF NOT EXISTS idx_upa_user ON user_project_access(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_upa_project ON user_project_access(project_id)",
            # Grandfather seed — idempotent via PRIMARY KEY conflict on re-run.
            "INSERT OR IGNORE INTO user_project_access (user_id, project_id, granted_by) "
            "SELECT u.id, p.id, 'system-seed-v17' FROM users u CROSS JOIN projects p "
            "WHERE u.role != 'admin'",
            # v18: idempotency keys for the create_mission / dispatch_mission MCP
            # tools. Lets a client safely retry after a network blip without
            # creating a duplicate mission or spawning a second agent. NULL = no
            # key supplied; the partial unique index only constrains non-NULL keys
            # (SQLite treats multiple NULLs as distinct, but the WHERE clause keeps
            # the index small and the intent explicit).
            "ALTER TABLE missions ADD COLUMN idempotency_key TEXT",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_missions_idempotency_key "
            "ON missions(idempotency_key) WHERE idempotency_key IS NOT NULL",
            "ALTER TABLE agent_sessions ADD COLUMN idempotency_key TEXT",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_idempotency_key "
            "ON agent_sessions(idempotency_key) WHERE idempotency_key IS NOT NULL",
        ]
        for migration in migrations:
            try:
                await db.execute(migration)
            except Exception:
                pass  # Column / table already exists

        # v12 data migration: encrypt any plaintext github_token values that
        # haven't been ported yet. Idempotent — the WHERE clause skips rows
        # already migrated. Crypto import is deferred so failures here don't
        # block schema setup in environments that haven't set the Fernet key
        # yet (the encrypted column still exists, just stays empty).
        try:
            async with db.execute(
                "SELECT id, github_token FROM users "
                "WHERE github_token IS NOT NULL AND github_token != '' "
                "AND (github_token_encrypted IS NULL OR github_token_encrypted = '')"
            ) as cur:
                _rows = await cur.fetchall()
            if _rows:
                import crypto as _crypto
                for _row in _rows:
                    _uid, _plain = _row[0], _row[1]
                    try:
                        _enc = _crypto.encrypt(_plain)
                        await db.execute(
                            "UPDATE users SET github_token_encrypted=? WHERE id=?",
                            (_enc, _uid),
                        )
                    except Exception as _exc:
                        import logging as _logging
                        _logging.getLogger("devfleet").warning(
                            "Failed to encrypt github_token for user %s: %s", _uid, _exc
                        )
        except Exception as _exc:
            import logging as _logging
            _logging.getLogger("devfleet").warning(
                "Skipped github_token encryption migration: %s", _exc
            )

        # v13 data migration: backfill identity columns for users who already
        # have an encrypted token but pre-date the github_login column.
        # Idempotent via the WHERE clause. Each GitHub /user call is a few
        # hundred ms; capped at a handful of users in practice (≤ team size).
        # Network/auth failure on any single user is logged and skipped — the
        # row's identity stays empty and the persona prompt will nudge a
        # re-paste.
        try:
            async with db.execute(
                "SELECT id, github_token_encrypted FROM users "
                "WHERE github_token_encrypted IS NOT NULL "
                "AND github_token_encrypted != '' "
                "AND (github_login IS NULL OR github_login = '')"
            ) as cur:
                _id_rows = await cur.fetchall()
            if _id_rows:
                import crypto as _crypto
                from gh_identity import fetch_github_identity as _fetch_id
                for _row in _id_rows:
                    _uid, _enc = _row[0], _row[1]
                    try:
                        _plain = _crypto.decrypt(_enc)
                    except Exception as _exc:
                        import logging as _logging
                        _logging.getLogger("devfleet").warning(
                            "Identity backfill: decrypt failed for %s: %s",
                            _uid, _exc,
                        )
                        continue
                    _ident = await _fetch_id(_plain)
                    if _ident is None:
                        import logging as _logging
                        _logging.getLogger("devfleet").warning(
                            "Identity backfill: GitHub /user failed for %s "
                            "(token may be revoked) — leaving empty",
                            _uid,
                        )
                        continue
                    await db.execute(
                        "UPDATE users SET github_login=?, github_name=?, "
                        "github_noreply_email=? WHERE id=?",
                        (_ident.login, _ident.name, _ident.noreply_email, _uid),
                    )
                await db.commit()
        except Exception as _exc:
            import logging as _logging
            _logging.getLogger("devfleet").warning(
                "Skipped github identity backfill: %s", _exc
            )

        # Full re-sync of all lane fields from LANE_DEFAULTS
        # INSERT OR IGNORE seeds new lanes; UPDATE syncs capacity/model/preset/style — but NOT
        # append_prompt, which the user can customise via Prompt Studio and must survive restarts.
        # Also disables lanes no longer in LANE_DEFAULTS (deprecated/renamed lanes)
        from models import LANE_DEFAULTS as _LD
        # Disable lanes that were once in LANE_DEFAULTS but no longer are
        # (deprecated/renamed built-ins). Excludes user-created lanes — those
        # live independent of LANE_DEFAULTS and must survive restarts.
        await db.execute(
            f"UPDATE lanes SET enabled=0 "
            f"WHERE name NOT IN ({','.join('?' for _ in _LD)}) "
            f"AND COALESCE(user_created, 0) = 0",
            list(_LD.keys()),
        )
        for _lane_name, _policy in _LD.items():
            await db.execute(
                """INSERT INTO lanes (name, max_agents, default_model, tool_preset, append_prompt, color, icon)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     max_agents    = excluded.max_agents,
                     default_model = excluded.default_model,
                     tool_preset   = excluded.tool_preset,
                     color         = excluded.color,
                     icon          = excluded.icon""",
                (
                    _lane_name,
                    _policy["max_agents"],
                    _policy["default_model"],
                    _policy["tool_preset"],
                    _policy["append_prompt"],
                    _policy.get("color", "#888888"),
                    _policy.get("icon", ""),
                ),
            )

        # Backfill mission_number for existing missions that don't have one
        # Use a CTE with ROW_NUMBER to assign sequential numbers per project
        await db.execute("""
            UPDATE missions SET mission_number = (
                SELECT rn FROM (
                    SELECT id, ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY created_at, id) AS rn
                    FROM missions
                ) numbered WHERE numbered.id = missions.id
            ) WHERE mission_number IS NULL
        """)

        # Seed default lanes (imported here to avoid top-level circular import)
        from models import LANE_DEFAULTS
        for name, policy in LANE_DEFAULTS.items():
            await db.execute(
                """INSERT OR IGNORE INTO lanes
                   (name, max_agents, default_model, tool_preset, append_prompt, color, icon)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    name,
                    policy["max_agents"],
                    policy["default_model"],
                    policy["tool_preset"],
                    policy["append_prompt"],
                    policy["color"],
                    policy["icon"],
                ),
            )

        # Seed default MCP tools per lane (INSERT OR IGNORE — preserves user toggles)
        _DEVFLEET_TOOLS = [
            ("devfleet-context", "get_mission_context", "always"),
            ("devfleet-context", "get_project_context", "always"),
            ("devfleet-context", "get_session_history", "always"),
            ("devfleet-context", "get_team_context", "always"),
            ("devfleet-context", "read_past_reports", "always"),
            ("devfleet-tools", "submit_report", "always"),
            ("devfleet-tools", "create_sub_mission", "only when spawning parallel sub-tasks"),
            ("devfleet-tools", "request_review", "after completing implementation"),
            ("devfleet-tools", "get_sub_mission_status", "when waiting on sub-missions"),
            ("devfleet-tools", "list_project_missions", "when checking project context"),
            ("devfleet-tools", "ask_human", "only when genuinely blocked and need a human decision"),
        ]
        for _lane_name in _LD:
            for _server, _tool, _hint in _DEVFLEET_TOOLS:
                _tool_id = f"{_lane_name}__{_server}__{_tool}"
                await db.execute(
                    """INSERT OR IGNORE INTO lane_mcp_tools (id, lane_name, server_name, tool_name, trigger_hint)
                       VALUES (?, ?, ?, ?, ?)""",
                    (_tool_id, _lane_name, _server, _tool, _hint),
                )

        # Backfill missions.lane from mission_type for existing rows
        await db.execute("""
            UPDATE missions SET lane = CASE mission_type
                WHEN 'implement' THEN 'coder'
                WHEN 'fix'       THEN 'coder'
                WHEN 'full'      THEN 'coder'
                WHEN 'review'    THEN 'reviewer'
                WHEN 'test'      THEN 'tester'
                WHEN 'explore'   THEN 'explorer'
                WHEN 'planner'   THEN 'planner'
                ELSE 'coder'
            END
            WHERE lane IS NULL OR lane = ''
        """)

        # Seed first admin from env if no users exist
        _admin_email = os.environ.get("DEVFLEET_ADMIN_EMAIL")
        _admin_pw = os.environ.get("DEVFLEET_ADMIN_PASSWORD")
        if _admin_email and _admin_pw:
            _existing = await db.execute_fetchall(
                "SELECT id FROM users WHERE email=?", (_admin_email,)
            )
            if not _existing:
                from auth import hash_password as _hp
                import uuid as _uuid
                _aid = str(_uuid.uuid4())
                await db.execute(
                    "INSERT INTO users (id, email, password_hash, role) VALUES (?,?,?,'admin')",
                    (_aid, _admin_email, _hp(_admin_pw))
                )
                import logging as _logging
                _logging.getLogger("devfleet").info("Seeded initial admin: %s", _admin_email)

        await db.commit()


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA cache_size=-64000")
    return db
