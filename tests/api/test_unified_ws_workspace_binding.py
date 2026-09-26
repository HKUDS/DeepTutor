"""The WebSocket boundary must preserve omission separately from explicit null."""

import json
from types import SimpleNamespace

from fastapi import WebSocketDisconnect
import pytest

from deeptutor.api.routers.unified_ws import unified_websocket


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", [{}, {"workspace_id": None}, {"workspace_id": "ws_test"}])
async def test_start_turn_preserves_workspace_and_parent_field_presence(monkeypatch, binding):
    captured = []

    async def authenticate(_ws):
        return None

    class Turns:
        async def start_turn(self, payload):
            captured.append(payload)
            return {"id": "chat"}, {"id": "turn"}

        async def subscribe_turn(self, *_args, **_kwargs):
            if False:
                yield None

    class Socket:
        app = SimpleNamespace(
            state=SimpleNamespace(application_container=SimpleNamespace(turns=Turns()))
        )

        def __init__(self):
            self.incoming = iter(
                [
                    {
                        "protocol_version": "2.0",
                        "type": "start_turn",
                        "content": "continue",
                        "session_id": "chat",
                        **binding,
                    },
                    {
                        "protocol_version": "2.0",
                        "type": "start_turn",
                        "content": "edit root",
                        "session_id": "chat",
                        "parent_message_id": None,
                        **binding,
                    },
                ]
            )

        async def accept(self):
            pass

        async def receive_text(self):
            try:
                return json.dumps(next(self.incoming))
            except StopIteration:
                raise WebSocketDisconnect()

        async def send_text(self, _text):
            pass

    monkeypatch.setattr("deeptutor.api.routers.auth.ws_require_auth", authenticate)
    await unified_websocket(Socket())
    assert len(captured) == 2
    for payload in captured:
        assert ("workspace_id" in payload) == ("workspace_id" in binding)
        if binding:
            assert payload["workspace_id"] == binding["workspace_id"]
    assert "parent_message_id" not in captured[0]
    assert captured[1]["parent_message_id"] is None
