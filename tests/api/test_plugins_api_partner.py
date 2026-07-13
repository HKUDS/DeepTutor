"""Regression tests for partner-compatible plugin capability streaming."""

from __future__ import annotations

import importlib
import json
import re
from typing import Any

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)


def _events(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.strip().split("\n\n"):
        event = ""
        data = "{}"
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        if event:
            events.append((event, json.loads(data)))
    return events


def _client_with_fake_partner(monkeypatch):
    from deeptutor.core.stream import StreamEvent, StreamEventType
    from deeptutor.services.partners.manager import PartnerConfig

    class FakeInstance:
        running = True

    class FakeMgr:
        def __init__(self):
            self.calls: list[dict[str, Any]] = []

        def get_partner(self, partner_id: str):
            return FakeInstance()

        def load_config(self, partner_id: str):
            return PartnerConfig(name=partner_id)

        async def start_partner(self, partner_id: str, config: PartnerConfig):
            return FakeInstance()

        async def send_message(self, partner_id: str, content: str, **kwargs):
            self.calls.append({"partner_id": partner_id, "content": content, **kwargs})
            on_event = kwargs.get("on_event")
            if on_event:
                await on_event(StreamEvent(type=StreamEventType.THINKING, content="thinking"))
            return "streamed answer"

    mgr = FakeMgr()
    partners_router_mod = importlib.import_module("deeptutor.api.routers.partners")
    plugins_router_mod = importlib.import_module("deeptutor.api.routers.plugins_api")
    monkeypatch.setattr(partners_router_mod, "get_partner_manager", lambda: mgr)
    partners_router_mod._start_locks.clear()

    app = FastAPI()
    app.include_router(plugins_router_mod.router, prefix="/api/v1/plugins")
    return TestClient(app), mgr


def test_plugin_chat_stream_routes_to_specified_partner_session(monkeypatch):
    client, mgr = _client_with_fake_partner(monkeypatch)

    response = client.post(
        "/api/v1/plugins/capabilities/chat/execute-stream",
        json={
            "content": "hi",
            # Legacy TutorBot HTTP API field name still addresses a partner.
            "bot_id": "math-bot",
            "session_id": "lesson-1",
            "enabledTools": [],
            "knowledgeBases": [],
            "language": "zh",
            "llmSelection": {"profile_id": "p-alt", "model_id": "m-alt"},
        },
    )

    assert response.status_code == 200
    events = _events(response.text)
    assert ("session", {"partner_id": "math-bot", "session_id": "lesson-1"}) in events
    assert ("thinking", {"content": "thinking"}) in events
    assert ("content", {"content": "streamed answer"}) in events
    assert ("done", {"partner_id": "math-bot", "session_id": "lesson-1"}) in events
    assert len(mgr.calls) == 1
    call = mgr.calls[0]
    assert call["partner_id"] == "math-bot"
    assert call["content"] == "hi"
    assert call["chat_id"] == "lesson-1"
    assert call["session_id"] == "lesson-1"
    assert callable(call["on_event"])


def test_plugin_chat_stream_creates_session_when_missing(monkeypatch):
    client, mgr = _client_with_fake_partner(monkeypatch)

    response = client.post(
        "/api/v1/plugins/capabilities/chat/execute-stream",
        json={"content": "first message", "bot_id": "math-bot"},
    )

    assert response.status_code == 200
    assert "event: done" in response.text
    match = re.search(r'"session_id": "([^"]+)"', response.text)
    assert match is not None
    session_id = match.group(1)
    assert session_id != "web"
    assert mgr.calls[0]["session_id"] == session_id
    assert mgr.calls[0]["chat_id"] == session_id
