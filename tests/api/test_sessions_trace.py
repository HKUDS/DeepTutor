from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import sessions as sessions_router
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def test_message_trace_is_paginated_and_session_scoped(tmp_path, monkeypatch) -> None:
    store = SQLiteSessionStore(tmp_path / "chat.db")
    session = asyncio.run(store.ensure_session(None))
    other = asyncio.run(store.ensure_session(None))
    turn = asyncio.run(store.begin_turn(session["id"], capability="chat"))
    message_id = asyncio.run(store.add_message(session["id"], "assistant", "answer"))
    asyncio.run(
        store.append_turn_events(
            turn["id"],
            [
                {"type": "tool_call", "content": "lookup", "metadata": {}},
                {"type": "done", "metadata": {"assistant_message_id": message_id}},
            ],
        )
    )
    assert asyncio.run(store.link_turn_message(turn["id"], message_id)) is True

    monkeypatch.setattr(sessions_router, "get_session_store", lambda: store)
    app = FastAPI()
    app.include_router(sessions_router.router, prefix="/api/sessions")

    with TestClient(app) as client:
        page = client.get(f"/api/sessions/{session['id']}/messages/{message_id}/events?limit=1")
        assert page.status_code == 200
        body = page.json()
        assert body["turn_id"] == turn["id"]
        assert body["total"] == 2
        assert body["events"][0]["seq"] == 1
        assert body["next_seq"] == 1
        assert body["complete"] is False

        denied = client.get(f"/api/sessions/{other['id']}/messages/{message_id}/events")
        assert denied.status_code == 404

        malformed = client.get(f"/api/sessions/{session['id']}/messages/not-a-sqlite-id/events")
        assert malformed.status_code == 404

    detail = asyncio.run(store.get_session_with_messages(session["id"]))
    assert detail is not None
    message = detail["messages"][0]
    assert message["events"][0]["type"] == "tool_call"
    assert message["events"][-1]["type"] == "done"
    trace = message["trace"]
    assert {
        "turn_id": trace["turn_id"],
        "total": trace["total"],
        "last_seq": trace["last_seq"],
        "truncated": trace["truncated"],
    } == {
        "turn_id": turn["id"],
        "total": 2,
        "last_seq": 2,
        "truncated": False,
    }
    # The turn's real span travels with the preview, because the preview keeps
    # only tool and terminal events and so cannot say when the turn began.
    first, last = message["events"][0], message["events"][-1]
    assert trace["started_at"] <= first["timestamp"]
    assert trace["ended_at"] >= last["timestamp"]
