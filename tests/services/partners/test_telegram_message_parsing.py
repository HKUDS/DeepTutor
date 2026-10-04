"""Telegram channel message parsing, chunking and typing lifecycle (coverage gap #17: 418 missing / 30.2%).

Contract suite for ``deeptutor/partners/channels/telegram.py``. Most tests pin
currently-correct behavior so future changes cannot regress it; two tests
encode the desired behavior for real defects that this branch fixes in
``telegram.py`` (red-first: they failed before the fix):

1. ``test_media_group_straggler_during_flush_is_not_dropped`` —
   ``_flush_media_group`` used to pop the album buffer while removing its
   task only in ``finally``, so an album item arriving while the flush task
   was still dispatching (bus publish await) was appended to a fresh buffer
   whose flush task was never scheduled: the message was silently dropped
   and the buffer leaked. The flush now releases the task slot before
   dispatching so late items schedule their own follow-up flush.
2. ``test_denied_sender_typing_indicator_is_stopped`` — ``_on_message``
   used to start the typing indicator before ``_handle_message`` ran the
   ACL check, so a sender outside ``allowFrom`` got an endless 4-second
   ``send_chat_action`` loop that nothing ever cancelled. Typing now only
   starts for senders that pass ``is_allowed``.

Everything runs against a mocked SDK (``SimpleNamespace`` bot); no network
access and no real bot token is needed. Streaming basics are covered by
``test_channel_streaming.py``; this file does not repeat them.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("telegram")

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.telegram import (
    TELEGRAM_MAX_MESSAGE_LEN,
    TELEGRAM_REPLY_CONTEXT_MAX_LEN,
    TelegramChannel,
    _StreamBuf,
)

pytestmark = pytest.mark.usefixtures("partners_root")


# ── fixtures / builders ──────────────────────────────────────────────


def _bot() -> SimpleNamespace:
    return SimpleNamespace(
        get_me=AsyncMock(return_value=SimpleNamespace(id=555, username="tutorbot")),
        send_chat_action=AsyncMock(),
        get_file=AsyncMock(return_value=SimpleNamespace(download_to_drive=AsyncMock())),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=99)),
        send_message_draft=AsyncMock(),
        edit_message_text=AsyncMock(),
        send_photo=AsyncMock(),
        send_voice=AsyncMock(),
        send_audio=AsyncMock(),
        send_document=AsyncMock(),
    )


def _channel(
    *,
    allow=("123",),
    group_policy: str = "mention",
    reply_to_message: bool = False,
) -> TelegramChannel:
    channel = TelegramChannel(
        {
            "enabled": True,
            "token": "t",
            "allowFrom": list(allow),
            "groupPolicy": group_policy,
            "replyToMessage": reply_to_message,
        },
        MessageBus(),
    )
    channel.bus.publish_inbound = AsyncMock()
    channel._app = SimpleNamespace(bot=_bot())
    return channel


def _user(uid: int = 123, username: str | None = "alice") -> SimpleNamespace:
    return SimpleNamespace(id=uid, username=username, first_name="Alice")


def _message(
    *,
    chat_id: int = 777,
    chat_type: str = "private",
    is_forum: bool = False,
    thread_id: int | None = None,
    text: str | None = "hello",
    caption: str | None = None,
    photo: list | None = None,
    voice: object | None = None,
    document: object | None = None,
    reply_to_message: object | None = None,
    media_group_id: str | None = None,
    message_id: int = 1,
    user: SimpleNamespace | None = None,
) -> SimpleNamespace:
    user = user or _user()
    return SimpleNamespace(
        message_id=message_id,
        message_thread_id=thread_id,
        chat_id=chat_id,
        chat=SimpleNamespace(id=chat_id, type=chat_type, is_forum=is_forum),
        text=text,
        caption=caption,
        photo=photo,
        voice=voice,
        audio=None,
        document=document,
        video=None,
        video_note=None,
        animation=None,
        reply_to_message=reply_to_message,
        entities=None,
        caption_entities=None,
        media_group_id=media_group_id,
        from_user=user,
    )


def _update(message: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(message=message, effective_user=message.from_user)


def _published(channel: TelegramChannel):
    assert channel.bus.publish_inbound.await_count >= 1
    return channel.bus.publish_inbound.await_args.args[0]


async def _alive(channel: TelegramChannel, chat_id: str) -> bool:
    task = channel._typing_tasks.get(chat_id)
    return task is not None and not task.done()


# ── inbound text parsing & metadata ──────────────────────────────────


@pytest.mark.asyncio
async def test_private_text_message_forwards_content_and_metadata() -> None:
    channel = _channel()

    await channel._on_message(_update(_message()), None)

    msg = _published(channel)
    assert msg.content == "hello"
    assert msg.sender_id == "123|alice"
    assert msg.chat_id == "777"
    assert msg.media == []
    assert msg.metadata == {
        "message_id": 1,
        "user_id": 123,
        "username": "alice",
        "first_name": "Alice",
        "is_group": False,
        "message_thread_id": None,
        "is_forum": False,
        "reply_to_message_id": None,
    }


@pytest.mark.asyncio
async def test_forum_topic_message_derives_topic_session_key() -> None:
    channel = _channel()

    message = _message(
        chat_id=-100999,
        chat_type="supergroup",
        is_forum=True,
        thread_id=5,
        text="hi @tutorbot",
    )
    await channel._on_message(_update(message), None)

    msg = _published(channel)
    assert msg.metadata["is_group"] is True
    assert msg.metadata["is_forum"] is True
    assert msg.metadata["message_thread_id"] == 5
    assert msg.session_key_override == "telegram:-100999:topic:5"


@pytest.mark.asyncio
async def test_reply_context_is_truncated_at_limit() -> None:
    channel = _channel()
    long_text = "r" * (TELEGRAM_REPLY_CONTEXT_MAX_LEN + 200)
    reply = SimpleNamespace(message_id=9, text=long_text, caption=None)

    await channel._on_message(_update(_message(text="answer", reply_to_message=reply)), None)

    msg = _published(channel)
    expected_tag = f"[Reply to: {'r' * TELEGRAM_REPLY_CONTEXT_MAX_LEN}...]"
    assert msg.content.split("\n")[0] == expected_tag
    assert msg.metadata["reply_to_message_id"] == 9


@pytest.mark.asyncio
async def test_media_group_buffers_and_flushes_as_single_turn() -> None:
    channel = _channel()
    photo_a = [SimpleNamespace(file_id="pa", file_unique_id="ua")]
    photo_b = [SimpleNamespace(file_id="pb", file_unique_id="ub")]

    await channel._on_message(
        _update(
            _message(
                text=None,
                photo=photo_a,
                media_group_id="g1",
                message_id=1,
            )
        ),
        None,
    )
    await channel._on_message(
        _update(
            _message(
                text=None,
                photo=photo_b,
                media_group_id="g1",
                message_id=2,
            )
        ),
        None,
    )
    key = "777:g1"
    assert key in channel._media_group_tasks
    await channel._media_group_tasks[key]

    assert channel.bus.publish_inbound.await_count == 1
    msg = _published(channel)
    assert len(msg.media) == 2
    assert msg.content == f"[image: {msg.media[0]}]\n[image: {msg.media[1]}]"
    assert not channel._media_group_buffers
    assert key not in channel._media_group_tasks


@pytest.mark.asyncio
async def test_media_group_straggler_during_flush_is_not_dropped() -> None:
    """An album item arriving while the flush task dispatches must get its
    own follow-up flush — previously it was buffered into a fresh dict whose
    flush task was never scheduled, so the message was silently dropped and
    the buffer leaked."""
    channel = _channel()
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def slow_handle(**kwargs):
        entered.set()
        await gate.wait()

    channel._handle_message = AsyncMock(side_effect=slow_handle)

    first = _message(
        photo=[SimpleNamespace(file_id="pa", file_unique_id="ua")],
        media_group_id="g1",
        message_id=1,
    )
    await channel._on_message(_update(first), None)
    await asyncio.wait_for(entered.wait(), timeout=2)

    straggler = _message(
        photo=[SimpleNamespace(file_id="pb", file_unique_id="ub")],
        media_group_id="g1",
        message_id=2,
    )
    await channel._on_message(_update(straggler), None)
    gate.set()
    await asyncio.wait_for(asyncio.gather(*channel._media_group_tasks.values()), timeout=2)

    assert channel._handle_message.await_count == 2
    assert channel._media_group_buffers == {}


# ── media parsing ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_photo_message_downloads_largest_size_and_tags_content() -> None:
    channel = _channel()
    small = SimpleNamespace(file_id="small", file_unique_id="us")
    large = SimpleNamespace(file_id="large", file_unique_id="ul")

    await channel._on_message(
        _update(_message(text=None, caption="look", photo=[small, large])), None
    )

    channel._app.bot.get_file.assert_awaited_once_with("large")
    download_path = channel._app.bot.get_file.return_value.download_to_drive.await_args.args[0]
    assert download_path.endswith("ul.jpg")
    msg = _published(channel)
    assert msg.content == f"look\n[image: {download_path}]"
    assert msg.media == [download_path]


@pytest.mark.asyncio
async def test_voice_message_transcribes_and_tags_content() -> None:
    channel = _channel()
    channel.transcribe_audio = AsyncMock(return_value="hello transcript")
    voice = SimpleNamespace(file_id="v1", file_unique_id="uv", mime_type="audio/ogg")

    await channel._on_message(_update(_message(text=None, voice=voice)), None)

    msg = _published(channel)
    download_path = msg.media[0]
    assert download_path.endswith("uv.ogg")
    assert msg.content == "[transcription: hello transcript]"
    channel.transcribe_audio.assert_awaited_once()


@pytest.mark.asyncio
async def test_document_message_keeps_original_extension() -> None:
    channel = _channel()
    document = SimpleNamespace(
        file_id="d1",
        file_unique_id="ud",
        mime_type="application/pdf",
        file_name="notes.pdf",
    )

    await channel._on_message(_update(_message(text=None, document=document)), None)

    msg = _published(channel)
    assert msg.media[0].endswith("ud.pdf")
    assert msg.content == f"[file: {msg.media[0]}]"


@pytest.mark.asyncio
async def test_media_download_failure_degrades_to_placeholder() -> None:
    channel = _channel()
    channel._app.bot.get_file = AsyncMock(side_effect=RuntimeError("network down"))
    photo = [SimpleNamespace(file_id="p", file_unique_id="u")]

    await channel._on_message(_update(_message(text=None, photo=photo)), None)

    msg = _published(channel)
    assert msg.content == "[image: download failed]"
    assert msg.media == []


@pytest.mark.asyncio
async def test_reply_to_media_only_message_attaches_media_and_tag() -> None:
    channel = _channel()
    reply = SimpleNamespace(
        message_id=9,
        text=None,
        caption=None,
        photo=[SimpleNamespace(file_id="rp", file_unique_id="ru")],
    )

    await channel._on_message(_update(_message(text="what is this", reply_to_message=reply)), None)

    msg = _published(channel)
    assert msg.content.startswith("[Reply to: [image: ")
    assert msg.content.endswith("]\nwhat is this")
    assert len(msg.media) == 1
    assert msg.media[0].endswith("ru.jpg")


# ── group policy routing ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_group_message_without_mention_skipped_under_mention_policy() -> None:
    channel = _channel(group_policy="mention")

    await channel._on_message(_update(_message(chat_id=-100999, chat_type="supergroup")), None)

    channel.bus.publish_inbound.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_message_with_bot_mention_routes_to_group_chat() -> None:
    channel = _channel(group_policy="mention")

    await channel._on_message(
        _update(_message(chat_id=-100999, chat_type="supergroup", text="hi @tutorbot")),
        None,
    )

    msg = _published(channel)
    assert msg.chat_id == "-100999"
    assert msg.metadata["is_group"] is True


@pytest.mark.asyncio
async def test_group_open_policy_processes_media_message() -> None:
    channel = _channel(group_policy="open")

    await channel._on_message(
        _update(
            _message(
                chat_id=-100999,
                chat_type="supergroup",
                text=None,
                photo=[SimpleNamespace(file_id="p", file_unique_id="u")],
            )
        ),
        None,
    )

    msg = _published(channel)
    assert msg.chat_id == "-100999"
    assert len(msg.media) == 1


def test_has_mention_entity_matches_entity_and_text_fallback() -> None:
    channel = _channel()
    handle = "@tutorbot"

    mention_entity = SimpleNamespace(type="mention", offset=0, length=len(handle))
    text_mention = SimpleNamespace(
        type="text_mention", offset=0, length=9, user=SimpleNamespace(id=555)
    )
    text_mention_other = SimpleNamespace(
        type="text_mention", offset=0, length=5, user=SimpleNamespace(id=42)
    )

    assert channel._has_mention_entity(handle + " hi", [mention_entity], "tutorbot", 555)
    assert channel._has_mention_entity(handle + " hi", [text_mention], "tutorbot", 555)
    assert not channel._has_mention_entity("hi there", [text_mention_other], "tutorbot", 555)
    assert not channel._has_mention_entity("hi @other", [], "tutorbot", 555)
    assert channel._has_mention_entity("ping " + handle, [], "tutorbot", None)


def test_is_allowed_supports_id_username_and_star_entries() -> None:
    assert _channel(allow=["123"]).is_allowed("123|alice")
    assert _channel(allow=["alice"]).is_allowed("123|alice")
    assert _channel(allow=["*"]).is_allowed("123|alice")
    assert _channel(allow=["123"]).is_allowed("123")
    assert not _channel(allow=["123"]).is_allowed("999|mallory")
    assert not _channel(allow=["123"]).is_allowed("abc|alice")
    assert not _channel(allow=["123"]).is_allowed("123|al|ice")
    assert not _channel(allow=[]).is_allowed("123|alice")


# ── long text chunking ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_splits_long_text_into_chunks_under_limit() -> None:
    import re

    channel = _channel()
    words = " ".join(f"w{i}" for i in range(2000))
    await channel.send(OutboundMessage(channel="telegram", chat_id="777", content=words))

    bot = channel._app.bot
    texts = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert len(texts) >= 3  # 2000 words cannot fit a single 4000-char message
    assert all(len(t) <= TELEGRAM_MAX_MESSAGE_LEN for t in texts)
    # Every word survives, in order, across the chunk boundaries.
    assert re.findall(r"w\d+", "".join(texts)) == [f"w{i}" for i in range(2000)]


@pytest.mark.asyncio
async def test_stream_end_splits_oversized_html_and_sends_extras() -> None:
    channel = _channel()

    await channel.send_delta("777", "a" * 5000, {"_stream_id": "s1"})
    await channel.send_delta("777", "", {"_stream_id": "s1", "_stream_end": True})

    bot = channel._app.bot
    final_edit = bot.edit_message_text.await_args
    assert len(final_edit.kwargs["text"]) <= 4096
    extras = [c.kwargs["text"] for c in bot.send_message.await_args_list[1:]]
    assert extras
    assert all(len(t) <= 4096 for t in extras)
    assert "777" not in channel._stream_bufs


@pytest.mark.asyncio
async def test_flush_stream_overflow_reopens_stream_with_tail() -> None:
    channel = _channel()
    buf = _StreamBuf(text="x" * (TELEGRAM_MAX_MESSAGE_LEN * 2 + 1000), message_id=5)

    await channel._flush_stream_overflow(777, buf)

    bot = channel._app.bot
    edit = bot.edit_message_text.await_args
    assert edit.kwargs["message_id"] == 5
    assert len(edit.kwargs["text"]) == TELEGRAM_MAX_MESSAGE_LEN
    mids = [c.kwargs["text"] for c in bot.send_message.await_args_list]
    assert len(mids) == 2  # middle chunk + reopened tail message
    assert len(mids[-1]) == 1000
    assert buf.message_id == 99
    assert buf.text == "x" * 1000


@pytest.mark.asyncio
async def test_send_text_falls_back_to_plain_on_html_parse_error() -> None:
    from telegram.error import BadRequest

    channel = _channel()
    bot = channel._app.bot
    bot.send_message = AsyncMock(
        side_effect=[BadRequest("can't parse entities"), SimpleNamespace(message_id=1)]
    )

    await channel.send(
        OutboundMessage(channel="telegram", chat_id="777", content="plain & **bold**")
    )

    assert bot.send_message.await_count == 2
    final_call = bot.send_message.await_args_list[1]
    assert final_call.kwargs["text"] == "plain & **bold**"
    assert "parse_mode" not in final_call.kwargs


@pytest.mark.asyncio
async def test_outbound_reply_carries_reply_params_and_topic_thread() -> None:
    channel = _channel(reply_to_message=True)
    channel._message_threads[("777", 7)] = 3

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="777",
            content="reply",
            metadata={"message_id": 7},
        )
    )

    call = channel._app.bot.send_message.await_args
    assert call.kwargs["reply_parameters"].message_id == 7
    assert call.kwargs["message_thread_id"] == 3


@pytest.mark.asyncio
async def test_send_media_uses_typed_sender_per_extension(tmp_path) -> None:
    channel = _channel()
    photo = tmp_path / "pic.png"
    photo.write_bytes(b"PNG")
    document = tmp_path / "doc.pdf"
    document.write_bytes(b"PDF")

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="777",
            content="",
            media=[str(photo), str(document)],
        )
    )

    bot = channel._app.bot
    bot.send_photo.assert_awaited_once()
    bot.send_document.assert_awaited_once()
    assert bot.send_message.await_count == 0


@pytest.mark.asyncio
async def test_send_media_failure_notifies_chat_with_placeholder(tmp_path) -> None:
    channel = _channel()
    missing = tmp_path / "gone.png"

    await channel.send(
        OutboundMessage(channel="telegram", chat_id="777", content="", media=[str(missing)])
    )

    call = channel._app.bot.send_message.await_args
    assert call.kwargs["text"] == "[Failed to send: gone.png]"


@pytest.mark.asyncio
async def test_send_invalid_chat_id_is_dropped_without_crash() -> None:
    channel = _channel()

    await channel.send(OutboundMessage(channel="telegram", chat_id="not-a-number", content="hi"))

    channel._app.bot.send_message.assert_not_awaited()


# ── typing indicator & cancellation ──────────────────────────────────


@pytest.mark.asyncio
async def test_inbound_message_starts_typing_indicator() -> None:
    channel = _channel()

    await channel._on_message(_update(_message()), None)
    await asyncio.sleep(0)

    assert await _alive(channel, "777")
    channel._app.bot.send_chat_action.assert_awaited_once_with(chat_id=777, action="typing")
    channel._stop_typing("777")


@pytest.mark.asyncio
async def test_final_send_stops_typing_progress_keeps_it() -> None:
    channel = _channel()
    task = asyncio.create_task(asyncio.sleep(60))
    channel._typing_tasks["777"] = task

    await channel.send(
        OutboundMessage(
            channel="telegram", chat_id="777", content="hi", metadata={"_progress": True}
        )
    )
    assert not task.done()

    await channel.send(OutboundMessage(channel="telegram", chat_id="777", content="done"))
    await asyncio.sleep(0)
    assert task.cancelled()
    assert "777" not in channel._typing_tasks


@pytest.mark.asyncio
async def test_start_typing_replaces_existing_task() -> None:
    channel = _channel()
    first = asyncio.create_task(asyncio.sleep(60))
    channel._typing_tasks["777"] = first

    channel._start_typing("777")
    await asyncio.sleep(0)

    assert first.cancelled() or first.done()
    assert channel._typing_tasks["777"] is not first
    channel._stop_typing("777")


@pytest.mark.asyncio
async def test_typing_loop_sends_repeatedly_until_cancelled() -> None:
    channel = _channel()
    channel._start_typing("777")
    await asyncio.sleep(0.05)
    task = channel._typing_tasks["777"]
    assert channel._app.bot.send_chat_action.await_count >= 1

    channel._stop_typing("777")
    await asyncio.wait_for(task, timeout=1)
    assert task.cancelled() or task.done()
    assert "777" not in channel._typing_tasks


@pytest.mark.asyncio
async def test_typing_loop_exits_when_app_detached() -> None:
    channel = _channel()
    bot = channel._app.bot

    async def _detach(*args, **kwargs):
        channel._app = None

    bot.send_chat_action = AsyncMock(side_effect=_detach)

    channel._start_typing("777")
    await asyncio.wait_for(channel._typing_tasks["777"], timeout=1)

    bot.send_chat_action.assert_awaited_once()


@pytest.mark.asyncio
async def test_denied_sender_typing_indicator_is_stopped() -> None:
    """The typing loop for an ACL-denied sender must never start — the
    sender never gets a reply, so nothing would stop the 4-second loop."""
    channel = _channel(allow=["123"])
    mallory = _user(uid=999, username="mallory")

    await channel._on_message(_update(_message(chat_id=888, user=mallory)), None)
    await asyncio.sleep(0.05)

    assert channel.bus.publish_inbound.await_count == 0
    assert not await _alive(channel, "888")


@pytest.mark.asyncio
async def test_stop_cancels_all_typing_and_media_group_tasks() -> None:
    channel = _channel()
    channel._typing_tasks["777"] = asyncio.create_task(asyncio.sleep(60))
    channel._typing_tasks["888"] = asyncio.create_task(asyncio.sleep(60))
    channel._app.updater = SimpleNamespace(stop=AsyncMock())
    channel._app.stop = AsyncMock()
    channel._app.shutdown = AsyncMock()

    await channel.stop()

    assert all(task.done() for task in channel._typing_tasks.values())
    assert channel._typing_tasks == {}
    assert channel._app is None
