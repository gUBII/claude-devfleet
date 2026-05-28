# DevFleet Hardening + Rebrand — Master Plan
Generated: 2026-05-27 from 4-agent deep scan

## Branch
`feature/devfleet-hardening-rebrand` from `main`

## Commit Protocol
- Prefix: `Farhanfix(scope):` or `Farhanfeat(scope):`
- One commit per phase
- NO Co-Authored-By, NO AI attribution, zero trailer lines

---

## PHASE 1 — Security & Runtime (CRITICAL BLOCKERS)

### 1a. AuthMiddleware SSE fix (app.py)
**Problem:** Browser EventSource cannot set headers. `?token=<jwt>` query param is ignored.
Fleet events SSE and session stream always return 401 for browsers.  
**Fix:** In `AuthMiddleware.dispatch()`, after failing Bearer header check, read
`request.query_params.get("token")` and validate identically.

### 1b. Dispatch reads plaintext PAT column (app.py:1791)
**Problem:** `SELECT github_token FROM users WHERE id = ?` — empty post-migration v12.
Agents silently run without credentials.  
**Fix:** Replace with `await auth.get_github_token(user["id"])`.

### 1c. Add `require_auth` to all unprotected sensitive routes (app.py)
Routes missing auth: dispatch, MCP server CRUD, lane CRUD, session cancel,
session stream, session remote-stream, generate_next_mission, print_plan.  
**Fix:** `current_user: dict = Depends(require_auth)` on each.
Apply Phase 1a first for SSE endpoints or new gate creates 401 loop.

### 1d. HITL UUID → INTEGER column (app.py:693)
**Problem:** `mission_events.id` is INTEGER PRIMARY KEY AUTOINCREMENT.
HITL INSERT passes `str(uuid.uuid4())` → coerced to NULL → auto-int id assigned.
All downstream UUID lookups find nothing.  
**Fix:** Remove `id` from the HITL INSERT entirely.

### 1e. generate_next_mission: no auth + missing columns (app.py:1461)
**Problem:** No auth check. INSERT missing: `lane`, `model`, `mission_type`,
`created_by_email`, `created_by_name`.  
**Fix:** Add `require_auth`. Derive `lane` from mission_type, copy `model` from parent,
set `created_by_email = current_user["email"]`.

### 1f. DispatchPanel crash on stale model default (DispatchPanel.jsx:307)
**Problem:** `useState(mission.model || 'claude-opus-4-6')` — `claude-opus-4-6`
not in MODELS array → selectedModel undefined → TypeError crash.  
**Fix:** Change default to `'claude-sonnet-4-6'` (interim; Phase 3 renames to Probaho).

### 1g. Mission watcher never passes github_token (mission_watcher.py:150)
**Problem:** `asyncio.create_task(dispatch_mission(...))` omits `github_token`.
Auto-dispatched missions always commit as anonymous.  
**Fix:** Resolve via `auth.get_github_token(user_id)` before calling dispatch.
`user_id` comes from `created_by_email` lookup. Fallback to None gracefully.

### 1h. Dependency deadlock (mission_watcher.py:49)
**Problem:** Eligibility: `NOT IN (completed)` — failed/cancelled deps block children forever.  
**Fix:** Eligibility = all deps in `(completed, failed, cancelled)` AND at least one `completed`.
Or: surface children of all-terminal-failed deps as `blocked` status.

**Phase 1 verification:**
- `curl -H "Authorization: Bearer invalid" http://localhost:18801/api/dispatch` → 401
- `curl http://localhost:18801/api/dispatch` → 401
- Fleet events SSE receives events in browser (not 401)
- Dispatch a mission → agent uses correct PAT (check git commit author)

---

## PHASE 2 — Dead Code Removal

### 2a. Frontend dead components
- Delete `frontend/src/components/StatsCard.jsx` (never imported)
- Grep for `autoloop` in JSX; remove autoloop tab/button from App.jsx if present
- Grep for `plan-intelligent` in frontend; remove any UI calling `/api/plan-intelligent`

### 2b. Backend orphans
- `backend/planner_v2.py` — keep file + route, add `X-Deprecated: use /api/plan` response header
- `backend/autoloop.py` — verify imports before any removal; add deprecation comment if imported

### 2c. Legacy slash alias
- `chat_router.py` `/sonnet` alias: add comment `# TODO(2026-06-30): remove after telemetry confirms zero usage`
- Do NOT remove yet

**Phase 2 verification:**
- `grep -r "StatsCard" frontend/src` → 0 results
- `npm run build` succeeds with no import errors

---

## PHASE 3 — Rebranding (Farhan's DevFleet™ + Model Tiers)

### Identity rebrand
- App title: `"Farhan's DevFleet™"` (FastAPI title + all `<title>` tags)
- Footer/print template (~app.py:984): `"Powered by Farhan's DevFleet™ · nexis365.com.au"`
- Remove all remaining `"Claude DevFleet"` or `"Nexis365 DevFleet"` strings
- EXCEPTION: `.auth-nexis-logo` CSS class — intentional, do NOT rename

### Model tier rebrand
| Old model ID | Tier label | Character |
|---|---|---|
| claude-haiku-* | Kiran | lightweight, fast |
| claude-sonnet-* | Probaho | standard, balanced |
| claude-opus-* | Arun | deep reasoning, costlier |

### Touch points (all required)
1. `DispatchPanel.jsx` MODELS array: labels → Kiran/Probaho/Arun
   Default fallback (Phase 1f): `claude-sonnet-4-6` → label as Probaho
2. `ProjectBot.jsx` PERSONA_META: Haiku→Kiran, Sonnet→Probaho, Opus→Arun
   Cost hint line 483: `"Arun · slower · costlier"`
3. `ProjectBot.jsx` SLASH_COMMANDS: `/haiku`→`/kiran`, `/opus`→`/arun`
   Keep `/gitsheba` unchanged. Update hint text line 491.
4. `chat_router.py`: map `/kiran`→researcher, `/arun`→architect
   Add `/probaho` as explicit alias for default persona
   Keep `/sonnet` legacy alias (Phase 2c)
5. `model_router.py` + `planner.py`: update hardcoded tier labels in logs

**Phase 3 verification:**
- `grep -rn "Claude DevFleet" backend/ frontend/src` → 0 results
- `grep -rn "claude-opus-4-6" frontend/src` → 0 results
- `npm run build` succeeds
- DispatchPanel loads without crash on any mission model value
- `/kiran` and `/arun` resolve correctly in ProjectBot

---

## PHASE 4 — Schema Consistency + Quality

### 4a. SCHEMA block sync (db.py)
Add to `CREATE TABLE IF NOT EXISTS missions` block:
`lane TEXT`, `created_by_email TEXT`, `created_by_name TEXT`,
`is_chat_turn INTEGER DEFAULT 0`
Migrations remain as no-ops (ALTER TABLE has try/except for duplicate columns).

### 4b. create_lane validation (app.py:1597)
Change `body: dict` to `body: LaneCreate` (already imported).
FastAPI returns 422 instead of 500 on bad input.

### 4c. N+1 in /api/status (app.py:2877)
Single `SELECT * FROM incidents WHERE service_id IN (...)` before loop.
Build dict keyed by service_id. Replace per-row calls with dict lookups.

### 4d. Tag filter full-table scan (app.py:1289)
Apply `LIMIT`/`OFFSET` to tagged fetch path (same as untagged path).

**Phase 4 verification:**
- Fresh DB init → `PRAGMA table_info(missions)` shows all 4 new columns
- `POST /api/lanes` with `{"max_agents": "bad"}` → 422 not 500

---

## Scope Boundaries — DO NOT
- No new features beyond what's listed
- No new DB migrations for non-schema-sync changes
- No changes to Docker compose or launchd plist
- No changes to mcp_external.py (already updated)
- No changes to auth.py (already correct, just needs to be called)
- Do not rename `.auth-nexis-logo` CSS class
- Do not remove /sonnet alias
- Do not delete planner_v2.py (deprecation header only)
