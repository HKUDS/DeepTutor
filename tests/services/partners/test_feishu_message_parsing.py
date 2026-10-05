"""Feishu channel message parsing and reply routing (coverage gap #9: 495 missing / 55.5%).

Red-first contract suite for ``deeptutor/partners/channels/feishu.py``. Most
tests pin currently-correct behavior so a fix card cannot regress it; the
marked FAILING tests encode the desired behavior for three real defects on
origin/main (``ef2d9e5c3``):

1. ``test_interactive_card_extracts_header_title_and_element_bodies`` /
   ``test_interactive_json_string_content_is_parsed`` — card ``elements`` is a
   flat list, but ``_extract_interactive_content`` iterates it as a list of
   lists, so every card body is silently dropped (only titles survive).
2. ``test_video_media_download_uses_file_resource_type`` — ``media`` (video)
   downloads request ``type="media"``, which the Feishu resource API rejects
   (it only accepts ``image``/``file`` — see ``_download_file_sync``'s own
   comment; only ``audio`` is converted today).
3. ``test_group_text_replaces_mention_placeholders_with_display_names`` —
   group text keeps raw ``@_user_1`` placeholders instead of the mention
   display names, so the partner LLM receives internal tokens.

Everything runs against a mocked SDK; no real credentials are needed.
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("lark_oapi")

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.feishu import (
    FeishuChannel,
    _extract_post_content,
    _extract_share_card_content,
)

pytestmark = pytest.mark.usefixtures("partners_root")


def _sdk_response(*, ok: bool = True, file_name: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        success=lambda: ok,
        data=None,
        code=0 if ok else 500,
        msg="ok" if ok else "unavailable",
        get_log_id=lambda: "log-1",
        file=io.BytesIO(b"BINARY"),
        file_name=file_name,
    )


def _channel(
    *,
    allow=("ou_user", "ou_alice"),
    group_policy: str = "mention",
) -> FeishuChannel:
    channel = FeishuChannel(
        {
            "enabled": True,
            "appId": "app",
            "appSecret": "secret",
            "allowFrom": list(allow),
            "groupPolicy": group_policy,
        },
        MessageBus(),
    )
    channel._client = SimpleNamespace(
        im=SimpleNamespace(
            v1=SimpleNamespace(message_resource=SimpleNamespace(get=MagicMock())),
        ),
    )
    channel.bus.publish_inbound = AsyncMock()
    channel._add_reaction = AsyncMock()
    return channel


def _mention(*, key: str, name: str, open_id: str, user_id: str | None) -> SimpleNamespace:
    return SimpleNamespace(key=key, name=name, id=SimpleNamespace(open_id=open_id, user_id=user_id))


def _event(
    msg_type: str,
    content: object,
    *,
    chat_type: str = "p2p",
    chat_id: str | None = None,
    sender_id: str = "ou_user",
    sender_type: str = "user",
    message_id: str = "om_1",
    mentions: list | None = None,
    raw_content: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_id=message_id,
                chat_id=chat_id or ("oc_group" if chat_type == "group" else "oc_p2p"),
                chat_type=chat_type,
                message_type=msg_type,
                content=raw_content if raw_content is not None else json.dumps(content),
                mentions=mentions or [],
            ),
            sender=SimpleNamespace(
                sender_type=sender_type, sender_id=SimpleNamespace(open_id=sender_id)
            ),
        )
    )


def _published(channel: FeishuChannel):
    assert channel.bus.publish_inbound.await_count == 1
    return channel.bus.publish_inbound.await_args.args[0]


# ── text parsing ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_p2p_text_message_forwarded_to_sender_chat() -> None:
    channel = _channel()

    await channel._on_message(_event("text", {"text": "hello"}))

    msg = _published(channel)
    assert msg.content == "hello"
    assert msg.sender_id == "ou_user"
    assert msg.chat_id == "ou_user"
    assert msg.media == []
    assert msg.metadata == {
        "message_id": "om_1",
        "chat_type": "p2p",
        "msg_type": "text",
    }
    channel._add_reaction.assert_awaited_once_with("om_1", "THUMBSUP")


@pytest.mark.asyncio
async def test_group_text_replaces_mention_placeholders_with_display_names() -> None:
    """FAILING: raw @_user_N placeholders reach the partner LLM verbatim."""
    channel = _channel()
    event = _event(
        "text",
        {"text": "@_user_1 @_user_2 please summarize"},
        chat_type="group",
        mentions=[
            _mention(key="@_user_1", name="DeepTutor", open_id="ou_bot", user_id=None),
            _mention(key="@_user_2", name="Alice", open_id="ou_alice", user_id="u_alice"),
        ],
    )

    await channel._on_message(event)

    msg = _published(channel)
    assert msg.content == "@DeepTutor @Alice please summarize"
    assert "@_user_" not in msg.content


# ── rich text (post) parsing ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_message_parses_text_at_and_downloads_images() -> None:
    channel = _channel()
    channel._client.im.v1.message_resource.get.return_value = _sdk_response(file_name="pic.png")

    post = {
        "title": "Report",
        "content": [
            [
                {"tag": "text", "text": "intro"},
                {"tag": "at", "user_name": "alice"},
                {"tag": "img", "image_key": "img_key_1"},
            ]
        ],
    }
    await channel._on_message(_event("post", post))

    msg = _published(channel)
    assert msg.content == "Report intro @alice\n[image: pic.png]"
    assert len(msg.media) == 1
    assert msg.media[0].endswith("pic.png")
    request = channel._client.im.v1.message_resource.get.call_args.args[0]
    assert request.paths == {"message_id": "om_1", "file_key": "img_key_1"}
    assert request.type == "image"


def test_extract_post_content_supports_localized_wrapped_and_fallback() -> None:
    block = {
        "title": "Report",
        "content": [[{"tag": "text", "text": "intro"}]],
    }

    assert _extract_post_content(block) == ("Report intro", [])
    assert _extract_post_content({"zh_cn": block}) == ("Report intro", [])
    assert _extract_post_content({"post": {"zh_cn": block}}) == ("Report intro", [])
    assert _extract_post_content(
        {"fr_fr": {"content": [[{"tag": "text", "text": "bonjour"}]]}}
    ) == (
        "bonjour",
        [],
    )
    assert _extract_post_content("not-a-dict") == ("", [])
    assert _extract_post_content({"title": "", "content": [[]]}) == ("", [])


# ── media parsing ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_video_media_download_uses_file_resource_type() -> None:
    """FAILING: the resource request carries type="media", which the API rejects."""
    channel = _channel()
    channel._client.im.v1.message_resource.get.return_value = _sdk_response(file_name="clip.mp4")

    await channel._on_message(_event("media", {"file_key": "vk_video"}))

    request = channel._client.im.v1.message_resource.get.call_args.args[0]
    assert request.type == "file"
    msg = _published(channel)
    assert msg.content == "[media: clip.mp4]"
    assert len(msg.media) == 1


@pytest.mark.asyncio
async def test_audio_download_uses_file_resource_type_and_opus_suffix() -> None:
    channel = _channel()
    channel._client.im.v1.message_resource.get.return_value = _sdk_response(file_name="voice-note")

    await channel._on_message(_event("audio", {"file_key": "ak_voice"}))

    request = channel._client.im.v1.message_resource.get.call_args.args[0]
    assert request.type == "file"
    msg = _published(channel)
    assert msg.content == "[audio: voice-note.opus]"
    assert msg.media[0].endswith("voice-note.opus")


@pytest.mark.asyncio
async def test_file_message_saved_and_forwarded() -> None:
    channel = _channel()
    channel._client.im.v1.message_resource.get.return_value = _sdk_response(file_name="notes.pdf")

    await channel._on_message(_event("file", {"file_key": "fk_doc"}))

    msg = _published(channel)
    assert msg.content == "[file: notes.pdf]"
    assert len(msg.media) == 1
    assert msg.media[0].endswith("notes.pdf")
    assert msg.metadata["msg_type"] == "file"


@pytest.mark.asyncio
async def test_image_download_failure_degrades_to_placeholder() -> None:
    channel = _channel()
    channel._client.im.v1.message_resource.get.return_value = _sdk_response(ok=False)

    await channel._on_message(_event("image", {"image_key": "ik_broken"}))

    msg = _published(channel)
    assert msg.content == "[image: download failed]"
    assert msg.media == []


# ── share cards / interactive parsing ────────────────────────────────


@pytest.mark.asyncio
async def test_interactive_card_extracts_header_title_and_element_bodies() -> None:
    """FAILING: flat card elements are iterated as a list of lists, dropping bodies."""
    channel = _channel()
    card = {
        "header": {"title": {"content": "Card Header"}},
        "elements": [
            {"tag": "markdown", "content": "md body"},
            {"tag": "div", "text": {"content": "div text"}},
            {"tag": "div", "fields": [{"text": {"content": "field A"}}]},
            {"tag": "a", "href": "https://x.co", "text": "go"},
            {"tag": "button", "text": {"content": "Click"}, "multi_url": {"url": "https://b.co"}},
            {"tag": "img", "alt": {"content": "chart alt"}},
            {"tag": "img"},
            {"tag": "note", "elements": [{"tag": "plain_text", "content": "note txt"}]},
            {
                "tag": "column_set",
                "columns": [{"elements": [{"tag": "plain_text", "content": "col cell"}]}],
            },
            {"tag": "mystery", "elements": [{"tag": "plain_text", "content": "nested unk"}]},
        ],
    }

    await channel._on_message(_event("interactive", card))

    expected = "\n".join(
        [
            "title: Card Header",
            "md body",
            "div text",
            "field A",
            "link: https://x.co",
            "go",
            "Click",
            "link: https://b.co",
            "chart alt",
            "[image]",
            "note txt",
            "col cell",
            "nested unk",
        ]
    )
    assert _published(channel).content == expected


def test_interactive_json_string_content_is_parsed() -> None:
    """FAILING: serialized card bodies are dropped the same way as dict ones."""
    from deeptutor.partners.channels.feishu import _extract_interactive_content

    assert _extract_interactive_content(
        '{"elements":[{"tag":"plain_text","content":"str body"}]}'
    ) == ["str body"]
    assert _extract_interactive_content("plain words") == ["plain words"]
    assert _extract_interactive_content([1, 2]) == []


def test_share_card_types_render_descriptive_placeholders() -> None:
    assert _extract_share_card_content({"chat_id": "oc_x"}, "share_chat") == "[shared chat: oc_x]"
    assert _extract_share_card_content({"user_id": "ou_x"}, "share_user") == "[shared user: ou_x]"
    assert (
        _extract_share_card_content({"event_key": "cal_1"}, "share_calendar_event")
        == "[shared calendar event: cal_1]"
    )
    assert _extract_share_card_content({}, "system") == "[system message]"
    assert _extract_share_card_content({}, "merge_forward") == "[merged forward messages]"
    assert _extract_share_card_content({}, "wizard") == "[wizard]"


# ── routing: private chat vs group ───────────────────────────────────


@pytest.mark.asyncio
async def test_group_message_without_mention_skipped_under_mention_policy() -> None:
    channel = _channel(group_policy="mention")

    await channel._on_message(_event("text", {"text": "no mention"}, chat_type="group"))

    channel.bus.publish_inbound.assert_not_awaited()
    channel._add_reaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_group_message_with_bot_mention_routes_to_group_chat() -> None:
    channel = _channel(group_policy="mention")

    await channel._on_message(
        _event(
            "text",
            {"text": "@_user_1 hi"},
            chat_type="group",
            mentions=[_mention(key="@_user_1", name="DeepTutor", open_id="ou_bot", user_id=None)],
        )
    )

    msg = _published(channel)
    assert msg.chat_id == "oc_group"
    assert msg.metadata["chat_type"] == "group"
    channel._add_reaction.assert_awaited_once()


@pytest.mark.asyncio
async def test_group_media_message_routes_to_group_with_media_path() -> None:
    channel = _channel(group_policy="open")
    channel._client.im.v1.message_resource.get.return_value = _sdk_response(file_name="clip.mp4")

    await channel._on_message(_event("media", {"file_key": "vk_group"}, chat_type="group"))

    msg = _published(channel)
    assert msg.chat_id == "oc_group"
    assert len(msg.media) == 1
    assert msg.media[0].endswith("clip.mp4")
    assert msg.metadata["chat_type"] == "group"


def test_is_bot_mentioned_detects_bot_and_all_but_not_user_mentions() -> None:
    channel = _channel()

    bot_mention = _mention(key="@_user_1", name="DeepTutor", open_id="ou_bot", user_id=None)
    user_mention = _mention(key="@_user_2", name="Alice", open_id="ou_alice", user_id="u_alice")

    def _message(content: str, mentions: list) -> SimpleNamespace:
        return SimpleNamespace(content=content, mentions=mentions)

    assert channel._is_bot_mentioned(_message("x", [bot_mention])) is True
    assert channel._is_bot_mentioned(_message("x", [user_mention])) is False
    assert channel._is_bot_mentioned(_message("@_all team", [])) is True
    assert channel._is_bot_mentioned(_message("plain", [])) is False


@pytest.mark.asyncio
async def test_duplicate_message_id_is_processed_once() -> None:
    channel = _channel()

    await channel._on_message(_event("text", {"text": "hello"}))
    await channel._on_message(_event("text", {"text": "hello"}))

    assert channel.bus.publish_inbound.await_count == 1


@pytest.mark.asyncio
async def test_bot_sender_messages_are_ignored() -> None:
    channel = _channel()

    await channel._on_message(
        _event("text", {"text": "echo"}, sender_id="ou_bot", sender_type="bot")
    )

    channel.bus.publish_inbound.assert_not_awaited()
    channel._add_reaction.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_content_json_is_dropped_without_crash() -> None:
    channel = _channel()

    await channel._on_message(_event("text", None, raw_content="not-json{{"))

    channel.bus.publish_inbound.assert_not_awaited()
    channel._add_reaction.assert_not_awaited()


# ── outbound reply routing ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_outbound_p2p_reply_uses_open_id_and_targets_inbound_source() -> None:
    from deeptutor.partners.bus.events import OutboundMessage

    channel = _channel()
    channel._send_message_sync = MagicMock(return_value=True)

    await channel.send(
        OutboundMessage(
            channel="feishu",
            chat_id="ou_user",
            content="hi",
            metadata={"message_id": "om_in"},
        )
    )

    assert channel._send_message_sync.call_args.args == (
        "open_id",
        "ou_user",
        "text",
        json.dumps({"text": "hi"}, ensure_ascii=False),
        "om_in",
    )


@pytest.mark.asyncio
async def test_outbound_group_reply_uses_chat_id_receive_type() -> None:
    from deeptutor.partners.bus.events import OutboundMessage

    channel = _channel()
    channel._send_message_sync = MagicMock(return_value=True)

    await channel.send(OutboundMessage(channel="feishu", chat_id="oc_group", content="hi"))

    args = channel._send_message_sync.call_args.args
    assert args[0] == "chat_id"
    assert args[1] == "oc_group"
    assert args[2] == "text"
