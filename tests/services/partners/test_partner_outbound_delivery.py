"""The live partner router preserves the shared streaming delivery contract."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.services.partners.manager import PartnerManager


class _FiniteBus:
    def __init__(self, messages: list[OutboundMessage]) -> None:
        self.messages = list(messages)

    async def consume_outbound(self) -> OutboundMessage:
        if self.messages:
            return self.messages.pop(0)
        raise asyncio.CancelledError


class _QueueBus:
    """A real outbound queue, drained by a finite ``consume_outbound``."""

    def __init__(self, messages: list[OutboundMessage]) -> None:
        self._bus = MessageBus()
        for message in messages:
            self._bus.outbound.put_nowait(message)

    async def consume_outbound(self) -> OutboundMessage:
        message = self.try_consume_outbound()
        if message is None:
            raise asyncio.CancelledError
        return message

    def try_consume_outbound(self) -> OutboundMessage | None:
        return self._bus.try_consume_outbound()


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


@pytest.mark.asyncio
async def test_live_router_merges_a_backlog_of_deltas_before_delivering(monkeypatch) -> None:
    """One queued burst must reach the channel as one edit, in order."""
    channel = SimpleNamespace(send=AsyncMock(), send_delta=AsyncMock())
    event_bus = SimpleNamespace(publish=AsyncMock())
    monkeypatch.setattr("deeptutor.events.event_bus.get_event_bus", lambda: event_bus)
    instance = SimpleNamespace(
        channel_manager=SimpleNamespace(get_channel=lambda _: channel),
        channel_bindings={},
        activity_feed=SimpleNamespace(publish=MagicMock()),
    )
    delivered: list[tuple[str, str]] = []
    channel.send_delta.side_effect = lambda _chat, content, _meta: delivered.append(
        ("delta", content)
    )
    channel.send.side_effect = lambda msg: delivered.append(("send", msg.content))
    bus = _QueueBus(
        [
            OutboundMessage(
                channel="feishu",
                chat_id="oc_group",
                content="Hel",
                metadata={"_stream_delta": True, "_stream_id": "turn:1"},
            ),
            OutboundMessage(
                channel="feishu",
                chat_id="oc_group",
                content="lo ",
                metadata={"_stream_delta": True, "_stream_id": "turn:1"},
            ),
            OutboundMessage(
                channel="feishu",
                chat_id="oc_group",
                content="world",
                metadata={"_stream_delta": True, "_stream_id": "turn:1"},
            ),
            OutboundMessage(
                channel="feishu",
                chat_id="oc_group",
                content="tool hint",
                metadata={"_progress": True, "_tool_hint": True},
            ),
            OutboundMessage(
                channel="feishu",
                chat_id="oc_group",
                content="",
                metadata={"_stream_end": True, "_stream_final": True, "_stream_id": "turn:1"},
            ),
        ]
    )

    await PartnerManager._outbound_router(None, "partner", bus, instance)

    # Three deltas collapsed into one stream edit; the boundary message and the
    # stream end that followed kept their order.
    assert delivered == [
        ("delta", "Hello world"),
        ("send", "tool hint"),
        ("delta", ""),
    ]
    assert channel.send_delta.await_args_list[1].args[2]["_stream_final"] is True
    # Nothing here is a final answer, so nothing fans out to the web feed.
    assert event_bus.publish.await_count == 0


@pytest.mark.asyncio
async def test_live_router_retries_finals_but_never_stream_frames(monkeypatch) -> None:
    """A failed stream frame self-heals; a final answer deserves retries."""
    channel = SimpleNamespace(send=AsyncMock(), send_delta=AsyncMock())
    monkeypatch.setattr(
        "deeptutor.events.event_bus.get_event_bus", lambda: SimpleNamespace(publish=AsyncMock())
    )
    captured: list[tuple[str, int]] = []

    async def spy(_channel, msg, *, max_attempts=3, retry_delays=None):
        captured.append((msg.content, max_attempts))

    monkeypatch.setattr("deeptutor.partners.channels.manager.send_with_retry", spy)
    instance = SimpleNamespace(
        channel_manager=SimpleNamespace(
            get_channel=lambda _: channel,
            channels_config=SimpleNamespace(send_max_retries=5),
        ),
        channel_bindings={},
        activity_feed=SimpleNamespace(publish=MagicMock()),
    )

    await PartnerManager._outbound_router(
        None,
        "partner",
        _FiniteBus(
            [
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
                    metadata={"_stream_end": True, "_stream_id": "turn:1"},
                ),
                OutboundMessage(channel="feishu", chat_id="oc_group", content="final answer"),
            ]
        ),
        instance,
    )

    assert captured == [("part", 1), ("", 1), ("final answer", 5)]


@pytest.mark.asyncio
async def test_live_router_merges_queued_progress_messages(monkeypatch) -> None:
    """Buffered mode must not post one Feishu message per narration round."""
    channel = SimpleNamespace(send=AsyncMock(), send_delta=AsyncMock())
    monkeypatch.setattr(
        "deeptutor.events.event_bus.get_event_bus", lambda: SimpleNamespace(publish=AsyncMock())
    )
    instance = SimpleNamespace(
        channel_manager=SimpleNamespace(get_channel=lambda _: channel),
        channel_bindings={},
        activity_feed=SimpleNamespace(publish=MagicMock()),
    )
    bus = _QueueBus(
        [
            OutboundMessage(
                channel="feishu",
                chat_id="oc_group",
                content="先看你的场景…",
                metadata={"_progress": True},
            ),
            OutboundMessage(
                channel="feishu",
                chat_id="oc_group",
                content="再给三句例句",
                metadata={"_progress": True},
            ),
            # Tool hints are their own kind: never folded into narration.
            OutboundMessage(
                channel="feishu",
                chat_id="oc_group",
                content="→ web_search",
                metadata={"_progress": True, "_tool_hint": True},
            ),
            OutboundMessage(channel="feishu", chat_id="oc_group", content="final answer"),
        ]
    )

    await PartnerManager._outbound_router(None, "partner", bus, instance)

    assert [call.args[0].content for call in channel.send.await_args_list] == [
        "先看你的场景…\n\n再给三句例句",
        "→ web_search",
        "final answer",
    ]


@pytest.mark.asyncio
async def test_live_router_survives_a_failing_message(monkeypatch) -> None:
    """A poison message must not kill the partner's only outbound lane."""
    channel = SimpleNamespace(send=AsyncMock(), send_delta=AsyncMock())
    channel.send.side_effect = [RuntimeError("boom"), None]
    monkeypatch.setattr(
        "deeptutor.events.event_bus.get_event_bus", lambda: SimpleNamespace(publish=AsyncMock())
    )
    instance = SimpleNamespace(
        channel_manager=SimpleNamespace(
            get_channel=lambda _: channel,
            channels_config=SimpleNamespace(send_max_retries=1),
        ),
        channel_bindings={},
        activity_feed=SimpleNamespace(publish=MagicMock()),
    )

    await PartnerManager._outbound_router(
        None,
        "partner",
        _FiniteBus(
            [
                OutboundMessage(channel="feishu", chat_id="oc_group", content="first"),
                OutboundMessage(channel="feishu", chat_id="oc_group", content="second"),
            ]
        ),
        instance,
    )

    assert channel.send.await_count == 2
    assert channel.send.await_args.args[0].content == "second"
    assert instance.channel_bindings["feishu"] == "oc_group"


@pytest.mark.asyncio
async def test_live_router_follows_a_channel_reload(monkeypatch) -> None:
    """A reloaded channel manager must take over without restarting the lane."""
    reloaded = SimpleNamespace(send=AsyncMock(), send_delta=AsyncMock())
    channel = SimpleNamespace(send=AsyncMock(), send_delta=AsyncMock())
    monkeypatch.setattr(
        "deeptutor.events.event_bus.get_event_bus", lambda: SimpleNamespace(publish=AsyncMock())
    )
    instance = SimpleNamespace(
        channel_manager=SimpleNamespace(get_channel=lambda _: channel),
        channel_bindings={},
        activity_feed=SimpleNamespace(publish=MagicMock()),
    )

    def reload(_msg) -> None:
        instance.channel_manager = SimpleNamespace(get_channel=lambda _: reloaded)

    channel.send.side_effect = reload

    await PartnerManager._outbound_router(
        None,
        "partner",
        _FiniteBus(
            [
                OutboundMessage(channel="feishu", chat_id="oc_group", content="before reload"),
                OutboundMessage(channel="feishu", chat_id="oc_group", content="after reload"),
            ]
        ),
        instance,
    )

    assert channel.send.await_count == 1
    assert reloaded.send.await_args.args[0].content == "after reload"
