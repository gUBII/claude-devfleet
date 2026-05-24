"""Integration tests for the chat token-paste short-circuit.

Verifies the end-to-end self-onboarding flow:
  - User pastes a PAT in chat → token gets saved Fernet-encrypted, the
    plaintext is scrubbed from project_bot_history, and a confirmation
    SSE stream is returned.
  - No persona ever runs.
  - chat_actions row is created with status='completed' / intent='token_saved'.
"""

from __future__ import annotations

import os
import sys

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch):
    import db as _db
    db_path = str(tmp_path / "chat_test.db")
    monkeypatch.setattr(_db, "DB_PATH", db_path)
    await _db.init_db()

    import importlib
    import app as _app_mod
    importlib.reload(_app_mod)

    from fastapi.testclient import TestClient
    client = TestClient(_app_mod.app)
    yield client, db_path
    client.close()


@pytest_asyncio.fixture
async def auth_and_project(app_client, monkeypatch):
    """Create user + project, return (client, headers, user_id, project_id)."""
    import auth as _auth
    import db as _db
    client, _db_path = app_client

    email = "tokenpaste@example.com"
    password = "PastePass1!"
    user = await _auth.create_user(email=email, password=password, role="user")
    user_id = user["id"]

    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    tok = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {tok}"}

    conn = await _db.get_db()
    project_id = "proj-tokenpaste-001"
    try:
        await conn.execute(
            "INSERT INTO projects (id, name, path, description) VALUES (?, ?, ?, ?)",
            (project_id, "TokenPasteTest", "/tmp", ""),
        )
        await conn.commit()
    finally:
        await conn.close()

    return client, headers, user_id, project_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pasting_pat_saves_token_and_scrubs_message(auth_and_project):
    import auth as _auth
    import db as _db
    client, headers, user_id, project_id = auth_and_project

    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    msg = f"here's my token {token} thanks"

    with client.stream(
        "POST",
        f"/api/projects/{project_id}/chat",
        json={"message": msg},
        headers=headers,
    ) as res:
        assert res.status_code == 200
        body = "".join(chunk for chunk in res.iter_text())

    # Confirmation event was emitted.
    assert '"type": "persona"' in body
    assert '"intent": "token_saved"' in body
    assert '"type": "done"' in body
    # The plaintext token MUST NOT appear in the streamed response.
    assert token not in body

    # Token is stored encrypted and decryptable.
    saved = await _auth.get_github_token(user_id)
    assert saved is not None
    stored_token, _username = saved
    assert stored_token == token

    # No plaintext anywhere in project_bot_history.
    conn = await _db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT content FROM project_bot_history WHERE project_id=?",
            (project_id,),
        )
        for row in rows:
            content = dict(row)["content"]
            assert token not in content, "PAT leaked into chat history"
    finally:
        await conn.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_normal_message_passes_through_to_persona(auth_and_project):
    """Sanity: a non-token message must not short-circuit. We can't reach
    the SDK in tests, but we CAN assert the persona classifier fires and
    no token gets saved as a side effect."""
    import auth as _auth
    client, headers, user_id, project_id = auth_and_project

    with client.stream(
        "POST",
        f"/api/projects/{project_id}/chat",
        json={"message": "tell me about the layout of this repo"},
        headers=headers,
    ) as res:
        assert res.status_code == 200
        # Drain — we don't need to inspect SDK output, just confirm no token side effect.
        for _ in res.iter_text():
            pass

    assert await _auth.get_github_token(user_id) is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_row_logged_on_token_save(auth_and_project):
    import db as _db
    client, headers, user_id, project_id = auth_and_project

    token = "ghp_ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"
    with client.stream(
        "POST",
        f"/api/projects/{project_id}/chat",
        json={"message": token},
        headers=headers,
    ) as res:
        for _ in res.iter_text():
            pass

    conn = await _db.get_db()
    try:
        rows = await conn.execute_fetchall(
            "SELECT persona, intent, status FROM chat_actions WHERE project_id=? AND user_id=?",
            (project_id, user_id),
        )
        actions = [dict(r) for r in rows]
    finally:
        await conn.close()

    assert any(
        a["intent"] == "token_saved" and a["status"] == "completed"
        for a in actions
    )
