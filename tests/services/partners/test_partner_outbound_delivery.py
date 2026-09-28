"""The live partner router preserves the shared streaming delivery contract."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.services.partners.manager import PartnerManager


class _FiniteBus:
    def __init__(self, messages: list[OutboundMessage]) -> None:
        self.messages = list(messages)

    async def consume_outbound(self) -> OutboundMessage:
        if self.messages:
            return self.messages.pop(0)
        raise asyncio.CancelledError


@pytest.mark.asyncio
async def test_live_router_dispatches_delta_end_and_final_once(monkeypatch) -> None:
    channel = SimpleNamespace(send=AsyncMock(), send_delta=AsyncMock())
    event_bus = SimpleNamespace(publish=AsyncMock())
    monkeypatch.setattr("deeptutor.events.event_bus.get_event_bus", lambda: event_bus)
    instance = SimpleNamespace(
        channel_manager=SimpleNamespace(get_channel=lambda _: channel),
        channel_bindings={},
        activity_feed=SimpleNamespace(publish=MagicMock()),
    )
    messages = [
        OutboundMessage(
            channel="feishu",
            chat_id="oc_group",
            content="part",
            metadata={"_stream_delta": True, "_stream_id": "turn:1"},
        ),
        OutboundMessage(
            channel="feishu",
            chat_id="oc_group",
            content="",
            metadata={"_stream_end": True, "_stream_final": True, "_stream_id": "turn:1"},
        ),
        OutboundMessage(
            channel="feishu",
            chat_id="oc_group",
            content="part",
            metadata={"_streamed": True},
        ),
        OutboundMessage(channel="telegram", chat_id="42", content="ordinary reply"),
    ]
    instance.channel_manager.get_channel = lambda _: channel

    await PartnerManager._outbound_router(None, "partner", _FiniteBus(messages), instance)

    assert channel.send_delta.await_count == 2
    assert channel.send_delta.await_args_list[1].args[2]["_stream_final"] is True
    assert channel.send.await_count == 1
    assert channel.send.await_args.args[0].content == "ordinary reply"
    assert event_bus.publish.await_count == 2  # streamed final and ordinary final
    assert instance.activity_feed.publish.call_count == 2
