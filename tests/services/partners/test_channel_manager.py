"""Unit tests for TutorBot channel dispatch behavior."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.channels.manager import ChannelManager
from deeptutor.partners.config.schema import ChannelsConfig


class _OneShotBus:
    def __init__(self, msg: OutboundMessage):
        self._msg = msg
        self._calls = 0

    async def consume_outbound(self) -> OutboundMessage:
        self._calls += 1
        if self._calls == 1:
            return self._msg
        raise asyncio.CancelledError


class _DummyChannel:
    def __init__(self):
        self.send = AsyncMock()
        self.send_delta = AsyncMock()
        # Effective flags normally set by ChannelManager._init_channels
        # from the per-channel config.
        self.send_progress = True
        self.send_tool_hints = True


async def _dispatch_one(
    msg: OutboundMessage,
    *,
    send_progress: bool = True,
    send_tool_hints: bool = True,
    config: ChannelsConfig | None = None,
) -> _DummyChannel:
    channel = _DummyChannel()
    channel.send_progress = send_progress
    channel.send_tool_hints = send_tool_hints
    manager = ChannelManager(config or ChannelsConfig(), _OneShotBus(msg))  # type: ignore[arg-type]
    manager.channels = {msg.channel: channel}  # type: ignore[dict-item]

    await manager._dispatch_outbound()
    return channel


class TestChannelManagerToolHints:
    @pytest.mark.asyncio
    async def test_tool_hint_progress_skipped_by_default(self):
        msg = OutboundMessage(
            channel="zulip",
            chat_id="pm:42",
            content='message("Hello")',
            metadata={"_progress": True, "_tool_hint": True},
        )

        channel = await _dispatch_one(msg, send_tool_hints=False)

        channel.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tool_hint_progress_dispatched_when_enabled(self):
        msg = OutboundMessage(
            channel="zulip",
            chat_id="pm:42",
            content='message("Hello")',
            metadata={"_progress": True, "_tool_hint": True},
        )

        channel = await _dispatch_one(msg, send_tool_hints=True)

        channel.send.assert_awaited_once_with(msg)


class _MultiShotBus:
    """Bus stub that yields queued messages then cancels the dispatcher.

    Messages live in ``outbound`` (a real queue) so the manager's delta
    coalescing — which drains ``bus.outbound`` directly — sees them too.
    """

    def __init__(self, msgs: list[OutboundMessage]):
        self.outbound = asyncio.Queue()
        for m in msgs:
            self.outbound.put_nowait(m)

    async def consume_outbound(self) -> OutboundMessage:
        try:
            return self.outbound.get_nowait()
        except asyncio.QueueEmpty:
            raise asyncio.CancelledError from None


async def _dispatch_many(
    msgs: list[OutboundMessage], config: ChannelsConfig | None = None
) -> _DummyChannel:
    channel = _DummyChannel()
    manager = ChannelManager(config or ChannelsConfig(), _MultiShotBus(msgs))  # type: ignore[arg-type]
    manager.channels = {msgs[0].channel: channel}  # type: ignore[dict-item]
    await manager._dispatch_outbound()
    return channel


class TestSendRetry:
    @pytest.mark.asyncio
    async def test_send_retries_on_failure_then_succeeds(self, monkeypatch):
        monkeypatch.setattr("deeptutor.partners.channels.manager._SEND_RETRY_DELAYS", (0, 0, 0))
        msg = OutboundMessage(channel="zulip", chat_id="1", content="hi")
        channel = _DummyChannel()
        channel.send.side_effect = [RuntimeError("boom"), None]
        manager = ChannelManager(ChannelsConfig(), _MultiShotBus([]))  # type: ignore[arg-type]

        await manager._send_with_retry(channel, msg)  # type: ignore[arg-type]

        assert channel.send.await_count == 2

    @pytest.mark.asyncio
    async def test_send_gives_up_after_max_retries(self, monkeypatch):
        monkeypatch.setattr("deeptutor.partners.channels.manager._SEND_RETRY_DELAYS", (0, 0, 0))
        msg = OutboundMessage(channel="zulip", chat_id="1", content="hi")
        channel = _DummyChannel()
        channel.send.side_effect = RuntimeError("boom")
        manager = ChannelManager(
            ChannelsConfig(send_max_retries=2),
            _MultiShotBus([]),  # type: ignore[arg-type]
        )

        await manager._send_with_retry(channel, msg)  # type: ignore[arg-type]

        assert channel.send.await_count == 2


class TestDuplicateSuppression:
    @pytest.mark.asyncio
    async def test_same_reply_to_same_origin_suppressed(self):
        meta = {"origin_message_id": "m1"}
        msgs = [
            OutboundMessage(channel="zulip", chat_id="1", content="same", metadata=dict(meta)),
            OutboundMessage(channel="zulip", chat_id="1", content="same", metadata=dict(meta)),
        ]
        channel = await _dispatch_many(msgs)
        assert channel.send.await_count == 1

    @pytest.mark.asyncio
    async def test_same_reply_to_different_origin_delivered(self):
        msgs = [
            OutboundMessage(
                channel="zulip",
                chat_id="1",
                content="same",
                metadata={"origin_message_id": "m1"},
            ),
            OutboundMessage(
                channel="zulip",
                chat_id="1",
                content="same",
                metadata={"origin_message_id": "m2"},
            ),
        ]
        channel = await _dispatch_many(msgs)
        assert channel.send.await_count == 2


class TestStreamDispatch:
    @pytest.mark.asyncio
    async def test_consecutive_deltas_coalesce(self):
        sid = {"_stream_delta": True, "_stream_id": "t:1"}
        msgs = [
            OutboundMessage(channel="zulip", chat_id="1", content="a", metadata=dict(sid)),
            OutboundMessage(channel="zulip", chat_id="1", content="b", metadata=dict(sid)),
            OutboundMessage(channel="zulip", chat_id="1", content="c", metadata=dict(sid)),
        ]
        channel = await _dispatch_many(msgs)
        # First delta waits on the queue; the rest coalesce into one edit.
        assert channel.send_delta.await_count <= 2
        total = "".join(c.args[1] for c in channel.send_delta.await_args_list)
        assert total == "abc"
        channel.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stream_end_routed_to_send_delta(self):
        msgs = [
            OutboundMessage(
                channel="zulip",
                chat_id="1",
                content="",
                metadata={"_stream_end": True, "_stream_id": "t:1"},
            ),
        ]
        channel = await _dispatch_many(msgs)
        channel.send_delta.assert_awaited_once()
        channel.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_streamed_final_skips_plain_send(self):
        msgs = [
            OutboundMessage(
                channel="zulip",
                chat_id="1",
                content="final",
                metadata={"_streamed": True},
            ),
        ]
        channel = await _dispatch_many(msgs)
        channel.send.assert_not_awaited()
        channel.send_delta.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deltas_of_different_streams_not_merged(self):
        msgs = [
            OutboundMessage(
                channel="zulip",
                chat_id="1",
                content="a",
                metadata={"_stream_delta": True, "_stream_id": "t:1"},
            ),
            OutboundMessage(
                channel="zulip",
                chat_id="1",
                content="b",
                metadata={"_stream_delta": True, "_stream_id": "t:2"},
            ),
        ]
        channel = await _dispatch_many(msgs)
        assert channel.send_delta.await_count == 2
        chunks = [c.args[1] for c in channel.send_delta.await_args_list]
        assert chunks == ["a", "b"]


def test_channel_registry_discovers_builtin_channels() -> None:
    from deeptutor.partners.channels.base import BaseChannel
    from deeptutor.partners.channels.registry import discover_all, discover_channel_names

    names = set(discover_channel_names())
    assert {"telegram", "slack", "discord", "zulip"} <= names

    channels = discover_all()
    assert {"telegram", "slack", "discord", "zulip"} <= set(channels)
    assert all(issubclass(cls, BaseChannel) for cls in channels.values())
