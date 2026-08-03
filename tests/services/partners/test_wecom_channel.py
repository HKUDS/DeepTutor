"""Regression coverage for the WeCom SDK integration."""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType
from typing import Any
from unittest.mock import Mock

from deeptutor.partners.channels import wecom


class CapturingWSClient:
    """Minimal wecom-aibot-sdk 1.0.8-compatible client used by the channel test."""

    connected = asyncio.Event()
    instance: CapturingWSClient | None = None

    def __init__(
        self,
        bot_id: str,
        secret: str,
        *,
        reconnect_interval: int = 1000,
        max_reconnect_attempts: int = 10,
        heartbeat_interval: int = 30000,
    ) -> None:
        self.bot_id = bot_id
        self.secret = secret
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self.heartbeat_interval = heartbeat_interval
        self.handlers: dict[str, Any] = {}
        self.did_connect = False
        self.did_disconnect = False
        type(self).instance = self

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler

    async def connect(self) -> None:
        self.did_connect = True
        type(self).connected.set()

    async def disconnect(self) -> None:
        self.did_disconnect = True


def test_wecom_channel_uses_the_pinned_sdk_startup_contract(monkeypatch: Any) -> None:
    """Use the positional constructor, connect(), and zero-argument lifecycle events."""
    # Regression for https://github.com/HKUDS/DeepTutor/issues/616
    sdk = ModuleType("wecom_aibot_sdk")
    sdk.WSClient = CapturingWSClient
    sdk.generate_req_id = lambda prefix: f"{prefix}-request"
    monkeypatch.setitem(sys.modules, "wecom_aibot_sdk", sdk)
    monkeypatch.setattr(wecom, "WECOM_AVAILABLE", True)

    async def exercise_startup() -> None:
        CapturingWSClient.connected = asyncio.Event()
        CapturingWSClient.instance = None
        channel = wecom.WecomChannel(
            {"bot_id": "bot-id", "secret": "bot-secret"},
            Mock(),
        )
        startup = asyncio.create_task(channel.start())
        await asyncio.wait_for(CapturingWSClient.connected.wait(), timeout=1)

        client = CapturingWSClient.instance
        assert client is not None
        assert (client.bot_id, client.secret) == ("bot-id", "bot-secret")
        assert client.reconnect_interval == 1000
        assert client.max_reconnect_attempts == -1
        assert client.heartbeat_interval == 30000
        assert client.did_connect

        await client.handlers["connected"]()
        await client.handlers["authenticated"]()

        startup.cancel()
        try:
            await startup
        except asyncio.CancelledError:
            pass

    asyncio.run(exercise_startup())
