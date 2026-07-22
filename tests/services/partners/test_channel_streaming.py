"""send_delta streaming contract for telegram / discord / feishu.

Covers the shared protocol: first delta creates a message, later deltas edit
in place (throttled), ``_stream_end`` renders the final text, and a new
``_stream_id`` opens a new message.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.discord import DiscordChannel
from deeptutor.partners.channels.feishu import FeishuChannel
from deeptutor.partners.channels.telegram import TelegramChannel


def _meta(stream_id: str, end: bool = False) -> dict[str, Any]:
    meta: dict[str, Any] = {"_stream_id": stream_id}
    if end:
        meta["_stream_end"] = True
    else:
        meta["_stream_delta"] = True
    return meta


# ── Telegram ─────────────────────────────────────────────────────────


def _telegram_channel() -> TelegramChannel:
    ch = TelegramChannel({"enabled": True, "token": "t", "allowFrom": ["*"]}, MessageBus())
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=99)),
        edit_message_text=AsyncMock(),
    )
    ch._app = SimpleNamespace(bot=bot)
    return ch


class TestTelegramStreaming:
    @pytest.mark.asyncio
    async def test_first_delta_sends_then_end_edits_final(self):
        ch = _telegram_channel()
        bot = ch._app.bot

        await ch.send_delta("1", "Hello ", _meta("s1"))
        bot.send_message.assert_awaited_once()
        assert ch._stream_bufs["1"].message_id == 99

        await ch.send_delta("1", "**world**", _meta("s1"))
        await ch.send_delta("1", "", _meta("s1", end=True))
        # Final edit renders markdown → HTML.
        final_call = bot.edit_message_text.await_args_list[-1]
        assert final_call.kwargs["message_id"] == 99
        assert "<b>world</b>" in final_call.kwargs["text"]
        assert "1" not in ch._stream_bufs

    @pytest.mark.asyncio
    async def test_edits_throttled_within_interval(self):
        ch = _telegram_channel()
        bot = ch._app.bot

        await ch.send_delta("1", "a", _meta("s1"))
        # Immediately after the initial send, the next delta only buffers.
        await ch.send_delta("1", "b", _meta("s1"))
        bot.edit_message_text.assert_not_awaited()
        assert ch._stream_bufs["1"].text == "ab"

    @pytest.mark.asyncio
    async def test_new_stream_id_opens_new_message(self):
        ch = _telegram_channel()
        bot = ch._app.bot

        await ch.send_delta("1", "first", _meta("s1"))
        await ch.send_delta("1", "second", _meta("s2"))
        assert bot.send_message.await_count == 2
        assert ch._stream_bufs["1"].text == "second"

    @pytest.mark.asyncio
    async def test_end_without_buffer_is_noop(self):
        ch = _telegram_channel()
        await ch.send_delta("1", "", _meta("s1", end=True))
        ch._app.bot.edit_message_text.assert_not_awaited()


# ── Discord ──────────────────────────────────────────────────────────


def _discord_response(payload: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _discord_channel() -> DiscordChannel:
    ch = DiscordChannel({"enabled": True, "token": "t", "allowFrom": ["*"]}, MessageBus())
    ch._http = MagicMock()
    ch._http.request = AsyncMock(return_value=_discord_response({"id": "555"}))
    return ch


class TestDiscordStreaming:
    @pytest.mark.asyncio
    async def test_first_delta_posts_then_end_patches(self):
        ch = _discord_channel()

        await ch.send_delta("42", "Hello", _meta("s1"))
        method, url = ch._http.request.await_args_list[0].args[:2]
        assert method == "POST" and url.endswith("/channels/42/messages")
        assert ch._stream_bufs["42"].message_id == "555"

        await ch.send_delta("42", "", _meta("s1", end=True))
        method, url = ch._http.request.await_args_list[-1].args[:2]
        assert method == "PATCH" and url.endswith("/messages/555")
        assert "42" not in ch._stream_bufs

    @pytest.mark.asyncio
    async def test_new_stream_id_opens_new_message(self):
        ch = _discord_channel()
        await ch.send_delta("42", "first", _meta("s1"))
        await ch.send_delta("42", "second", _meta("s2"))
        posts = [c for c in ch._http.request.await_args_list if c.args[0] == "POST"]
        assert len(posts) == 2
        assert ch._stream_bufs["42"].text == "second"

    @pytest.mark.asyncio
    async def test_api_error_raises_for_manager_retry(self):
        ch = _discord_channel()
        bad = _discord_response({})
        bad.raise_for_status.side_effect = RuntimeError("500")
        ch._http.request = AsyncMock(return_value=bad)

        with pytest.raises(RuntimeError):
            await ch.send_delta("42", "x", _meta("s1"))


# ── Feishu ───────────────────────────────────────────────────────────


def _feishu_channel(monkeypatch) -> FeishuChannel:
    ch = FeishuChannel({"enabled": True, "appId": "a", "appSecret": "s"}, MessageBus())
    ch._client = MagicMock()  # only truthiness is used once helpers are stubbed
    monkeypatch.setattr(ch, "_create_streaming_card_sync", MagicMock(return_value="card-1"))
    monkeypatch.setattr(ch, "_stream_update_text_sync", MagicMock(return_value=True))
    monkeypatch.setattr(ch, "_close_streaming_mode_sync", MagicMock(return_value=True))
    monkeypatch.setattr(ch, "_send_message_sync", MagicMock(return_value=True))
    return ch


class TestFeishuStreaming:
    @pytest.mark.asyncio
    async def test_card_created_streamed_and_closed(self, monkeypatch):
        ch = _feishu_channel(monkeypatch)

        await ch.send_delta("oc_1", "Hello", _meta("s1"))
        ch._create_streaming_card_sync.assert_called_once()
        ch._stream_update_text_sync.assert_called_with("card-1", "Hello", 1)

        await ch.send_delta("oc_1", "", _meta("s1", end=True))
        # Final text update then streaming_mode close, with growing sequence.
        assert ch._stream_update_text_sync.call_args_list[-1].args == ("card-1", "Hello", 2)
        ch._close_streaming_mode_sync.assert_called_once_with("card-1", 3)
        assert not ch._stream_bufs

    @pytest.mark.asyncio
    async def test_failed_final_update_falls_back_to_card(self, monkeypatch):
        ch = _feishu_channel(monkeypatch)

        await ch.send_delta("oc_1", "Hello", _meta("s1"))
        ch._stream_update_text_sync.return_value = False
        await ch.send_delta("oc_1", "", _meta("s1", end=True))

        ch._close_streaming_mode_sync.assert_not_called()
        ch._send_message_sync.assert_called()  # regular interactive card fallback

    @pytest.mark.asyncio
    async def test_segments_get_separate_cards(self, monkeypatch):
        ch = _feishu_channel(monkeypatch)
        ch._create_streaming_card_sync.side_effect = ["card-1", "card-2"]

        await ch.send_delta("oc_1", "narration", _meta("s1"))
        await ch.send_delta("oc_1", "", _meta("s1", end=True))
        await ch.send_delta("oc_1", "answer", _meta("s2"))

        assert ch._create_streaming_card_sync.call_count == 2
