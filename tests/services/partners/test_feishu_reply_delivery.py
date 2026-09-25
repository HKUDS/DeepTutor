"""Feishu replies and working badges follow confirmed final delivery (#1517)."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.feishu import FeishuChannel


def _response(*, ok: bool = True, data: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        success=lambda: ok,
        data=data,
        code=0 if ok else 500,
        msg="ok" if ok else "unavailable",
        get_log_id=lambda: "log-1",
    )


def _channel() -> FeishuChannel:
    channel = FeishuChannel({"enabled": True, "appId": "app", "appSecret": "secret"}, MessageBus())
    message = SimpleNamespace(create=MagicMock(return_value=_response()))
    message.reply = MagicMock(return_value=_response())
    reaction = SimpleNamespace(
        create=MagicMock(return_value=_response(data=SimpleNamespace(reaction_id="reaction-1"))),
        delete=MagicMock(return_value=_response()),
    )
    card = SimpleNamespace(
        create=MagicMock(return_value=_response(data=SimpleNamespace(card_id="card-1")))
    )
    channel._client = SimpleNamespace(
        im=SimpleNamespace(v1=SimpleNamespace(message=message, message_reaction=reaction)),
        cardkit=SimpleNamespace(v1=SimpleNamespace(card=card)),
    )
    return channel


def test_reply_endpoint_uses_inbound_message_id_and_thread_flag() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()

    assert channel._send_message_sync("chat_id", "oc_group", "text", '{"text":"hi"}', "om_user")
    request = channel._client.im.v1.message.reply.call_args.args[0]
    assert request.paths["message_id"] == "om_user"
    assert request.request_body.reply_in_thread is True
    assert request.request_body.msg_type == "text"
    channel._client.im.v1.message.create.assert_not_called()

    assert channel._send_message_sync("chat_id", "oc_group", "text", '{"text":"notice"}')
    channel._client.im.v1.message.create.assert_called_once()


def test_explicit_reply_rejection_falls_back_to_standalone_delivery() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    channel._client.im.v1.message.reply.return_value = _response(ok=False)

    assert channel._send_message_sync("chat_id", "oc_group", "text", '{"text":"hi"}', "om_old")
    channel._client.im.v1.message.reply.assert_called_once()
    channel._client.im.v1.message.create.assert_called_once()


def test_uncertain_reply_transport_error_does_not_send_duplicate() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()
    channel._client.im.v1.message.reply.side_effect = TimeoutError("response lost")

    assert not channel._send_message_sync("chat_id", "oc_group", "text", '{"text":"hi"}', "om_user")
    channel._client.im.v1.message.create.assert_not_called()


def test_reaction_receipt_is_deleted_by_its_own_id() -> None:
    pytest.importorskip("lark_oapi")
    channel = _channel()

    assert channel._add_reaction_sync("om_user", "THUMBSUP") == "reaction-1"
    assert channel._remove_reaction_sync("om_user", "reaction-1") is True
    delete_request = channel._client.im.v1.message_reaction.delete.call_args.args[0]
    assert delete_request.paths == {
        "message_id": "om_user",
        "reaction_id": "reaction-1",
    }


@pytest.mark.asyncio
async def test_only_successful_final_send_clears_working_reaction() -> None:
    channel = _channel()
    channel._working_reactions["om_user"] = ("reaction-1", time.monotonic())
    channel._send_message_sync = MagicMock(return_value=True)
    channel._remove_reaction_sync = MagicMock(return_value=True)

    progress = OutboundMessage(
        channel="feishu",
        chat_id="oc_group",
        content="Thinking",
        metadata={"message_id": "om_user", "_progress": True},
    )
    await channel.send(progress)
    assert "om_user" in channel._working_reactions
    channel._remove_reaction_sync.assert_not_called()

    channel._send_message_sync.return_value = False
    final = OutboundMessage(
        channel="feishu",
        chat_id="oc_group",
        content="Answer",
        metadata={"message_id": "om_user"},
    )
    await channel.send(final)
    assert "om_user" in channel._working_reactions

    channel._send_message_sync.return_value = True
    await channel.send(final)
    assert "om_user" not in channel._working_reactions
    channel._remove_reaction_sync.assert_called_once_with("om_user", "reaction-1")
    assert channel._send_message_sync.call_args.args[-1] == "om_user"


@pytest.mark.asyncio
async def test_failed_reaction_delete_retains_receipt_for_retry() -> None:
    channel = _channel()
    channel._working_reactions["om_user"] = ("reaction-1", time.monotonic())
    channel._REACTION_DELETE_RETRY_DELAYS = (0,)
    channel._REACTION_LATE_RETRY_DELAYS = (0,)
    channel._remove_reaction_sync = MagicMock(side_effect=[False, False, True])

    await channel._finish_reaction("om_user")
    assert "om_user" in channel._working_reactions
    await channel._reaction_cleanup_tasks[("om_user", "reaction-1")]
    assert "om_user" not in channel._working_reactions


@pytest.mark.asyncio
async def test_streaming_card_replies_and_cleans_only_finalized_answer() -> None:
    channel = _channel()
    channel._working_reactions["om_user"] = ("reaction-1", time.monotonic())
    channel._stream_update_text_sync = MagicMock(return_value=True)
    channel._close_streaming_mode_sync = MagicMock(return_value=True)
    channel._remove_reaction_sync = MagicMock(return_value=True)

    await channel.send_delta("oc_group", "Narration", {"_stream_id": "n", "message_id": "om_user"})
    card_reply = channel._client.im.v1.message.reply.call_args.args[0]
    assert card_reply.paths["message_id"] == "om_user"
    assert card_reply.request_body.msg_type == "interactive"
    await channel.send_delta(
        "oc_group", "", {"_stream_id": "n", "_stream_end": True, "message_id": "om_user"}
    )
    assert "om_user" in channel._working_reactions

    await channel.send_delta("oc_group", "Answer", {"_stream_id": "f", "message_id": "om_user"})
    await channel.send_delta(
        "oc_group",
        "",
        {
            "_stream_id": "f",
            "_stream_end": True,
            "_stream_final": True,
            "message_id": "om_user",
        },
    )
    assert "om_user" not in channel._working_reactions
    channel._remove_reaction_sync.assert_called_once_with("om_user", "reaction-1")


@pytest.mark.asyncio
async def test_failed_stream_fallback_keeps_badge_until_reply_delivered() -> None:
    channel = _channel()
    channel._working_reactions["om_user"] = ("reaction-1", time.monotonic())
    channel._create_streaming_card_sync = MagicMock(return_value=None)
    channel._send_message_sync = MagicMock(return_value=False)
    channel._remove_reaction_sync = MagicMock(return_value=True)

    await channel.send_delta("ou_user", "Answer", {"_stream_id": "f", "message_id": "om_user"})
    await channel.send_delta(
        "ou_user",
        "",
        {"_stream_id": "f", "_stream_end": True, "_stream_final": True},
    )
    assert channel._send_message_sync.call_args.args[-1] == "om_user"
    assert "om_user" in channel._working_reactions
    channel._remove_reaction_sync.assert_not_called()


def test_reaction_receipts_expire_and_remain_bounded() -> None:
    channel = _channel()
    channel._MAX_WORKING_REACTIONS = 2
    now = time.monotonic()
    channel._working_reactions.update(
        {
            "expired": ("r0", now - channel._WORKING_REACTION_TTL - 1),
            "first": ("r1", now - 2),
            "second": ("r2", now - 1),
            "third": ("r3", now),
        }
    )

    channel._prune_working_reactions()
    assert list(channel._working_reactions) == ["second", "third"]


@pytest.mark.asyncio
async def test_disallowed_inbound_message_does_not_get_stuck_working_badge() -> None:
    channel = _channel()  # empty allowFrom denies this sender
    channel._add_reaction = AsyncMock()
    event = SimpleNamespace(
        message=SimpleNamespace(
            message_id="om_user",
            chat_id="oc_group",
            chat_type="p2p",
            message_type="text",
            content='{"text":"hello"}',
        ),
        sender=SimpleNamespace(sender_type="user", sender_id=SimpleNamespace(open_id="ou_user")),
    )

    await channel._on_message(SimpleNamespace(event=event))
    channel._add_reaction.assert_not_awaited()
