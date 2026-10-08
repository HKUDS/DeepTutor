"""Feishu live streaming: tuned typewriter pace, bounded retries, released WS.

The card path used to (a) run at Feishu's default 1 character / 70 ms typewriter
pace, so a finished answer kept typing for a long time, and (b) retry card
creation on *every* delta when the API rejected it, turning the reply into a
slow dribble. Both are bounded here.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.base import deliver_outbound
from deeptutor.partners.channels.feishu import FeishuChannel, _shutdown_ws_client


def _response(*, ok: bool = True, data: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        success=lambda: ok,
        data=data,
        code=0 if ok else 500,
        msg="ok" if ok else "unavailable",
        get_log_id=lambda: "log-1",
    )


def _channel(**config: object) -> FeishuChannel:
    channel = FeishuChannel(
        {"enabled": True, "appId": "app", "appSecret": "secret", **config}, MessageBus()
    )
    message = SimpleNamespace(
        create=MagicMock(return_value=_response()),
        reply=MagicMock(return_value=_response()),
    )
    card = SimpleNamespace(
        create=MagicMock(return_value=_response(data=SimpleNamespace(card_id="card-1")))
    )
    card_element = SimpleNamespace(content=MagicMock(return_value=_response()))
    channel._client = SimpleNamespace(
        im=SimpleNamespace(v1=SimpleNamespace(message=message)),
        cardkit=SimpleNamespace(v1=SimpleNamespace(card=card, card_element=card_element)),
    )
    return channel


def _message(content: str, **metadata: object) -> OutboundMessage:
    return OutboundMessage(
        channel="feishu",
        chat_id="oc_group",
        content=content,
        metadata={"message_id": "om_user", "_stream_id": "turn:1", **metadata},
    )


def _created_card_config(channel: FeishuChannel) -> dict:
    request = channel._client.cardkit.v1.card.create.call_args.args[0]
    return json.loads(request.request_body.data)["config"]


def test_streaming_card_tunes_the_client_typewriter_pace() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()

    assert channel._create_streaming_card_sync("chat_id", "oc_group") == "card-1"

    config = _created_card_config(channel)
    assert config["streaming_mode"] is True
    # Feishu's defaults are 70 ms per character; keep the card ahead of the model.
    assert config["streaming_config"] == {
        "print_frequency_ms": {"default": 30},
        "print_step": {"default": 6},
        "print_strategy": "fast",
    }


def test_zero_print_tuning_falls_back_to_platform_defaults() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel(stream_print_step=0)

    channel._create_streaming_card_sync("chat_id", "oc_group")

    assert "streaming_config" not in _created_card_config(channel)


@pytest.mark.asyncio
async def test_repeated_card_creation_failures_stop_hammering_the_api() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    channel._STREAM_CREATE_RETRY_INTERVAL = 0
    channel._client.cardkit.v1.card.create.return_value = _response(ok=False)

    for _ in range(10):
        await deliver_outbound(channel, _message("x", _stream_delta=True))

    assert channel._client.cardkit.v1.card.create.call_count == channel._MAX_STREAM_CREATE_FAILURES


@pytest.mark.asyncio
async def test_degraded_stream_still_delivers_the_full_answer() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    channel._STREAM_CREATE_RETRY_INTERVAL = 0
    channel._client.cardkit.v1.card.create.return_value = _response(ok=False)

    await deliver_outbound(channel, _message("Hello ", _stream_delta=True))
    await deliver_outbound(channel, _message("world", _stream_delta=True))
    await deliver_outbound(channel, _message("", _stream_end=True, _stream_final=True))

    assert channel._client.im.v1.message.reply.call_count == 1
    body = channel._client.im.v1.message.reply.call_args.args[0].request_body.content
    assert "Hello world" in body


@pytest.mark.asyncio
async def test_ws_shutdown_cancels_sdk_tasks_and_closes_the_connection() -> None:
    loop = asyncio.get_running_loop()
    connection = SimpleNamespace(close=AsyncMock())
    client = SimpleNamespace(_conn=connection)
    parked = asyncio.create_task(asyncio.sleep(3600))

    await _shutdown_ws_client(client, loop)

    with pytest.raises(asyncio.CancelledError):
        await parked
    connection.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_releases_the_websocket_listener(monkeypatch) -> None:
    channel = _channel()
    requested = MagicMock()
    monkeypatch.setattr(channel, "_request_ws_shutdown", requested)
    channel._ws_client = SimpleNamespace()
    channel._ws_thread = SimpleNamespace(is_alive=lambda: False)

    await channel.stop()

    requested.assert_called_once()
    assert channel._ws_client is None
    assert channel._ws_thread is None
