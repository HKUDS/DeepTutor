"""The "thinking…" placeholder: shown while the model reasons, then retracted."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.feishu import FeishuChannel
from deeptutor.partners.channels.manager import coalesce_progress_messages


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
        create=MagicMock(return_value=_response(data=SimpleNamespace(message_id="om_notice"))),
        reply=MagicMock(return_value=_response()),
        delete=MagicMock(return_value=_response()),
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


def _notice(content: str = "🤔 正在思考…") -> OutboundMessage:
    return OutboundMessage(
        channel="feishu",
        chat_id="oc_group",
        content=content,
        metadata={"_progress": True, "_thinking_notice": True, "message_id": "om_user"},
    )


@pytest.mark.asyncio
async def test_notice_is_posted_and_retracted_once_the_card_is_live() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()

    await channel.send(_notice())

    create = channel._client.im.v1.message.create.call_args.args[0]
    assert create.request_body.msg_type == "text"
    assert json.loads(create.request_body.content)["text"] == "🤔 正在思考…"
    assert channel._thinking_notices["oc_group"] == "om_notice"

    await channel.send_delta("oc_group", "Hello", {"_stream_id": "s", "message_id": "om_user"})

    delete = channel._client.im.v1.message.delete.call_args.args[0]
    assert delete.paths["message_id"] == "om_notice"
    assert "oc_group" not in channel._thinking_notices


@pytest.mark.asyncio
async def test_final_answer_retracts_a_leftover_notice() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    await channel.send(_notice())

    await channel.send(
        OutboundMessage(channel="feishu", chat_id="oc_group", content="Answer", metadata={})
    )

    assert channel._client.im.v1.message.delete.call_args.args[0].paths == {
        "message_id": "om_notice"
    }
    assert not channel._thinking_notices


@pytest.mark.asyncio
async def test_notice_is_opt_out() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel(thinking_notice=False)

    await channel.send(_notice())

    channel._client.im.v1.message.create.assert_not_called()
    assert not channel._thinking_notices


@pytest.mark.asyncio
async def test_failed_retraction_is_tolerated() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    channel._client.im.v1.message.delete.return_value = _response(ok=False)
    await channel.send(_notice())

    await channel.send(
        OutboundMessage(channel="feishu", chat_id="oc_group", content="Answer", metadata={})
    )

    assert not channel._thinking_notices, "a failed retraction must not wedge the state"


@pytest.mark.asyncio
async def test_progress_coalescer_keeps_the_notice_on_its_own() -> None:
    """The notice has its own lifecycle, so it never merges with narration."""
    bus = MessageBus()
    await bus.publish_outbound(_notice())
    await bus.publish_outbound(
        OutboundMessage(
            channel="feishu",
            chat_id="oc_group",
            content="先看你的场景…",
            metadata={"_progress": True},
        )
    )

    first, pending = coalesce_progress_messages(bus, await bus.consume_outbound())

    assert first.content == "🤔 正在思考…"
    assert first.metadata["_thinking_notice"] is True
    assert [p.content for p in pending] == ["先看你的场景…"]


@pytest.mark.asyncio
async def test_notice_posts_do_not_block_the_loop() -> None:
    """Posting runs in a worker thread like every other SDK call."""
    pytest.importorskip("lark_oapi")
    channel = _channel()
    started = asyncio.Event()

    def slow_create(_request: object) -> SimpleNamespace:
        started.set()
        return _response(data=SimpleNamespace(message_id="om_notice"))

    channel._client.im.v1.message.create = MagicMock(side_effect=slow_create)

    await asyncio.wait_for(channel.send(_notice()), timeout=2)

    assert started.is_set()
    assert isinstance(channel._client.im.v1.message.create, MagicMock)
