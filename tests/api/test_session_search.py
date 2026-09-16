from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import sessions as sessions_router
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def test_session_search_route_precedes_dynamic_session_route(tmp_path, monkeypatch) -> None:
    store = SQLiteSessionStore(tmp_path / "history.db")
    session = asyncio.run(store.create_session(title="Older chat", session_id="native"))
    message_id = asyncio.run(
        store.add_message(session["id"], "user", "The remembered equation is x + y")
    )
    monkeypatch.setattr(sessions_router, "get_session_store", lambda: store)
    app = FastAPI()
    app.include_router(sessions_router.router, prefix="/api/sessions")

    with TestClient(app) as client:
        response = client.get("/api/sessions/search", params={"q": "equation", "limit": 5})
        blank = client.get("/api/sessions/search", params={"q": "   "})
        too_long = client.get("/api/sessions/search", params={"q": "x" * 201})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 5
    assert body["offset"] == 0
    assert body["sessions"][0]["match_message_id"] == message_id
    assert blank.status_code == 400
    assert too_long.status_code == 422
