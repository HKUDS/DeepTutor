"""A streamed Feishu answer must have one confirmed delivery path."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.base import deliver_outbound
from deeptutor.partners.channels.feishu import FeishuChannel


def _channel() -> FeishuChannel:
    channel = FeishuChannel({"enabled": True, "appId": "app", "appSecret": "secret"}, MessageBus())
    channel._client = SimpleNamespace()
    channel._create_streaming_card_sync = MagicMock(return_value="card-1")
    channel._stream_update_text_sync = MagicMock(return_value=True)
    channel._close_streaming_mode_sync = MagicMock(return_value=True)
    channel._send_message_sync = MagicMock(return_value=True)
    return channel


def _message(content: str, **metadata: object) -> OutboundMessage:
    return OutboundMessage(
        channel="feishu",
        chat_id="oc_group",
        content=content,
        metadata={"message_id": "om_user", "_stream_id": "turn:finish", **metadata},
    )


@pytest.mark.asyncio
async def test_successful_stream_end_suppresses_plain_final() -> None:
    channel = _channel()
    await deliver_outbound(channel, _message("Answer", _stream_delta=True))
    await deliver_outbound(channel, _message("", _stream_end=True, _stream_final=True))
    await deliver_outbound(channel, _message("Answer", _streamed=True))

    channel._send_message_sync.assert_not_called()


@pytest.mark.asyncio
async def test_failed_stream_card_falls_back_to_plain_final() -> None:
    channel = _channel()
    channel._create_streaming_card_sync.return_value = None
    channel._send_message_sync.side_effect = [False, True]

    await deliver_outbound(channel, _message("Answer", _stream_delta=True))
    await deliver_outbound(channel, _message("", _stream_end=True, _stream_final=True))
    await deliver_outbound(channel, _message("Answer", _streamed=True))

    assert channel._send_message_sync.call_count == 2
    assert channel._send_message_sync.call_args_list[-1].args[2] == "text"


@pytest.mark.asyncio
async def test_failed_stream_close_does_not_duplicate_visible_answer() -> None:
    channel = _channel()
    channel._close_streaming_mode_sync.return_value = False

    await deliver_outbound(channel, _message("Answer", _stream_delta=True))
    await deliver_outbound(channel, _message("", _stream_end=True, _stream_final=True))
    await deliver_outbound(channel, _message("Answer", _streamed=True))

    channel._stream_update_text_sync.assert_called_with("card-1", "Answer", 2)
    channel._send_message_sync.assert_not_called()


@pytest.mark.asyncio
async def test_transient_reaction_delete_failure_is_retried() -> None:
    channel = _channel()
    channel._working_reactions["om_user"] = ("reaction-1", time.monotonic())
    channel._remove_reaction_sync = MagicMock(side_effect=[False, True])
    channel._REACTION_DELETE_RETRY_DELAYS = (0,)

    await channel._finish_reaction("om_user")

    assert channel._remove_reaction_sync.call_count == 2
    assert "om_user" not in channel._working_reactions


@pytest.mark.asyncio
async def test_long_turn_still_removes_its_working_reaction() -> None:
    channel = _channel()
    channel._working_reactions["om_user"] = (
        "reaction-1",
        time.monotonic() - channel._WORKING_REACTION_TTL - 1,
    )
    channel._remove_reaction_sync = MagicMock(return_value=True)

    await channel._finish_reaction("om_user")

    channel._remove_reaction_sync.assert_called_once_with("om_user", "reaction-1")
    assert "om_user" not in channel._working_reactions


@pytest.mark.asyncio
async def test_abandoned_turn_reaction_expires_without_another_message() -> None:
    channel = _channel()
    channel._WORKING_REACTION_TTL = 0.01
    channel._add_reaction_sync = MagicMock(return_value="reaction-1")
    channel._remove_reaction_sync = MagicMock(return_value=True)

    await channel._add_reaction("om_user")
    expiry = channel._reaction_expiry_tasks["om_user"]
    await asyncio.wait_for(expiry, timeout=1)

    channel._remove_reaction_sync.assert_called_once_with("om_user", "reaction-1")
    assert "om_user" not in channel._working_reactions
