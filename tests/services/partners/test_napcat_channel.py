"""Unit tests for the NapCat (OneBot v11) channel implementation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError
import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.napcat import NapcatChannel, NapcatConfig


def _make_channel(**overrides) -> NapcatChannel:
    defaults = {
        "enabled": True,
        "ws_url": "ws://127.0.0.1:3001",
        "access_token": "secret-token-123",
        "allow_from": ["*"],
        "group_policy": "mention",
    }
    defaults.update(overrides)
    config = NapcatConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return NapcatChannel(config, bus)


def _group_event(**overrides) -> dict:
    base = {
        "post_type": "message",
        "message_type": "group",
        "message_id": 1000,
        "user_id": 42,
        "group_id": 123456,
        "sender": {"nickname": "Alice", "card": ""},
        "message": [{"type": "text", "data": {"text": "hello bot"}}],
    }
    base.update(overrides)
    return base


def _private_event(**overrides) -> dict:
    base = {
        "post_type": "message",
        "message_type": "private",
        "message_id": 2000,
        "user_id": 42,
        "sender": {"nickname": "Alice"},
        "message": [{"type": "text", "data": {"text": "hi there"}}],
    }
    base.update(overrides)
    return base


class TestNapcatConfig:
    def test_default_values(self):
        cfg = NapcatConfig()
        assert cfg.enabled is False
        assert cfg.ws_url == "ws://127.0.0.1:3001"
        assert cfg.access_token == ""
        assert cfg.allow_from == []
        assert cfg.group_policy == "mention"
        assert cfg.group_policy_overrides == {}
        assert cfg.welcome_new_members is True
        assert cfg.max_image_bytes == 20 * 1024 * 1024
        # Inherited delivery overrides
        assert cfg.send_progress is True
        assert cfg.send_tool_hints is True

    def test_access_token_repr_false(self):
        cfg = NapcatConfig(access_token="super-secret")
        assert cfg.model_dump()["access_token"] == "super-secret"
        assert "super-secret" not in repr(cfg)

    def test_camel_case_alias(self):
        cfg = NapcatConfig(ws_url="ws://host:3001", access_token="t")
        d = cfg.model_dump(by_alias=True)
        assert "wsUrl" in d
        assert "accessToken" in d
        assert "groupPolicy" in d
        assert "groupPolicyOverrides" in d
        assert "maxImageBytes" in d

    def test_from_camel_case_dict(self):
        d = {
            "enabled": True,
            "wsUrl": "ws://example:3001",
            "accessToken": "secret",
            "allowFrom": ["*"],
            "groupPolicy": "open",
            "welcomeNewMembers": False,
        }
        cfg = NapcatConfig.model_validate(d)
        assert cfg.ws_url == "ws://example:3001"
        assert cfg.access_token == "secret"
        assert cfg.group_policy == "open"
        assert cfg.welcome_new_members is False

    def test_probability_policy_accepted(self):
        cfg = NapcatConfig(group_policy=0.5)
        assert cfg.group_policy == 0.5

    def test_probability_policy_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            NapcatConfig(group_policy=1.5)
        with pytest.raises(ValidationError):
            NapcatConfig(group_policy=-0.1)

    def test_group_policy_overrides_mixed_types(self):
        cfg = NapcatConfig(
            group_policy="mention",
            group_policy_overrides={"111": "open", "222": 0.3},
        )
        assert cfg.group_policy_overrides["111"] == "open"
        assert cfg.group_policy_overrides["222"] == 0.3


class TestDefaultConfig:
    def test_default_config_returns_dict(self):
        cfg = NapcatChannel.default_config()
        assert isinstance(cfg, dict)
        assert cfg["enabled"] is False
        assert "wsUrl" in cfg
        assert "accessToken" in cfg
        assert "groupPolicy" in cfg


class TestIsAllowed:
    def test_wildcard_allows_all(self):
        ch = _make_channel(allow_from=["*"])
        assert ch.is_allowed("42") is True

    def test_empty_list_denies_all(self):
        ch = _make_channel(allow_from=[])
        assert ch.is_allowed("42") is False

    def test_sender_id_match(self):
        ch = _make_channel(allow_from=["42"])
        assert ch.is_allowed("42") is True
        assert ch.is_allowed("99") is False


class TestShouldReplyInGroup:
    def test_mention_policy_requires_mention(self):
        ch = _make_channel(group_policy="mention")
        assert (
            ch._should_reply_in_group(group_id=123, mentioned_self=False, replying_to_bot=False)
            is False
        )

    def test_mention_policy_allows_mentioned(self):
        ch = _make_channel(group_policy="mention")
        assert (
            ch._should_reply_in_group(group_id=123, mentioned_self=True, replying_to_bot=False)
            is True
        )

    def test_mention_policy_allows_reply_to_bot(self):
        ch = _make_channel(group_policy="mention")
        assert (
            ch._should_reply_in_group(group_id=123, mentioned_self=False, replying_to_bot=True)
            is True
        )

    def test_open_policy_allows_all(self):
        ch = _make_channel(group_policy="open")
        assert (
            ch._should_reply_in_group(group_id=123, mentioned_self=False, replying_to_bot=False)
            is True
        )

    def test_probability_policy_below_threshold_replies(self):
        ch = _make_channel(group_policy=0.5)
        with patch("random.random", return_value=0.3):
            assert (
                ch._should_reply_in_group(group_id=123, mentioned_self=False, replying_to_bot=False)
                is True
            )

    def test_probability_policy_above_threshold_ignores(self):
        ch = _make_channel(group_policy=0.5)
        with patch("random.random", return_value=0.7):
            assert (
                ch._should_reply_in_group(group_id=123, mentioned_self=False, replying_to_bot=False)
                is False
            )

    def test_probability_zero_equals_mention(self):
        ch = _make_channel(group_policy=0.0)
        with patch("random.random", return_value=0.0):
            assert (
                ch._should_reply_in_group(group_id=123, mentioned_self=False, replying_to_bot=False)
                is False
            )

    def test_probability_one_equals_open(self):
        ch = _make_channel(group_policy=1.0)
        with patch("random.random", return_value=0.999):
            assert (
                ch._should_reply_in_group(group_id=123, mentioned_self=False, replying_to_bot=False)
                is True
            )

    def test_probability_mention_always_replies(self):
        ch = _make_channel(group_policy=0.0)
        assert (
            ch._should_reply_in_group(group_id=123, mentioned_self=True, replying_to_bot=False)
            is True
        )

    def test_override_open_beats_global_mention(self):
        ch = _make_channel(group_policy="mention", group_policy_overrides={"123": "open"})
        assert (
            ch._should_reply_in_group(group_id=123, mentioned_self=False, replying_to_bot=False)
            is True
        )

    def test_unlisted_group_falls_back_to_global(self):
        ch = _make_channel(group_policy="mention", group_policy_overrides={"123": "open"})
        assert (
            ch._should_reply_in_group(group_id=456, mentioned_self=False, replying_to_bot=False)
            is False
        )

    def test_override_probability(self):
        ch = _make_channel(group_policy="mention", group_policy_overrides={"123": 0.5})
        with patch("random.random", return_value=0.3):
            assert (
                ch._should_reply_in_group(group_id=123, mentioned_self=False, replying_to_bot=False)
                is True
            )
        with patch("random.random", return_value=0.9):
            assert (
                ch._should_reply_in_group(group_id=123, mentioned_self=False, replying_to_bot=False)
                is False
            )


class TestNormalizeSegments:
    def test_array_message_keeps_dicts_only(self):
        segs = NapcatChannel._normalize_segments(
            [{"type": "text", "data": {"text": "hi"}}, "garbage", 42]
        )
        assert segs == [{"type": "text", "data": {"text": "hi"}}]

    def test_string_message_becomes_text_segment(self):
        segs = NapcatChannel._normalize_segments("hello")
        assert segs == [{"type": "text", "data": {"text": "hello"}}]

    def test_empty_string_and_none(self):
        assert NapcatChannel._normalize_segments("") == []
        assert NapcatChannel._normalize_segments(None) == []


class TestParseSegments:
    def test_text_segments_joined(self):
        ch = _make_channel()
        text, images, mentioned, reply_to = ch._parse_segments(
            [
                {"type": "text", "data": {"text": "hello "}},
                {"type": "text", "data": {"text": " world"}},
            ]
        )
        assert text == "hello world"
        assert images == []
        assert mentioned is False
        assert reply_to is None

    def test_valid_image_collected(self):
        ch = _make_channel()
        _, images, _, _ = ch._parse_segments(
            [
                {
                    "type": "image",
                    "data": {
                        "url": "https://example.com/a.png",
                        "file": "a.png",
                        "file_size": "1024",
                    },
                }
            ]
        )
        assert images == [
            {"url": "https://example.com/a.png", "file": "a.png", "file_size": "1024"}
        ]

    def test_invalid_image_url_skipped(self):
        ch = _make_channel()
        _, images, _, _ = ch._parse_segments(
            [{"type": "image", "data": {"url": "file:///etc/passwd"}}]
        )
        assert images == []

    def test_at_self_sets_mentioned(self):
        ch = _make_channel()
        ch._self_id = 999
        text, _, mentioned, _ = ch._parse_segments(
            [
                {"type": "at", "data": {"qq": "999"}},
                {"type": "text", "data": {"text": "do something"}},
            ]
        )
        assert mentioned is True
        assert text == "do something"
        assert "@999" not in text

    def test_at_other_kept_as_text(self):
        ch = _make_channel()
        ch._self_id = 999
        text, _, mentioned, _ = ch._parse_segments(
            [
                {"type": "at", "data": {"qq": "555"}},
                {"type": "text", "data": {"text": "ping"}},
            ]
        )
        assert mentioned is False
        assert text == "@555 ping"

    def test_at_without_self_id_not_mentioned(self):
        ch = _make_channel()
        ch._self_id = None
        text, _, mentioned, _ = ch._parse_segments([{"type": "at", "data": {"qq": "999"}}])
        assert mentioned is False
        assert text == "@999"

    def test_reply_id_parsed(self):
        ch = _make_channel()
        _, _, _, reply_to = ch._parse_segments([{"type": "reply", "data": {"id": "777"}}])
        assert reply_to == 777

    def test_bad_reply_id_ignored(self):
        ch = _make_channel()
        _, _, _, reply_to = ch._parse_segments([{"type": "reply", "data": {"id": "abc"}}])
        assert reply_to is None

    def test_face_segment_rendered(self):
        ch = _make_channel()
        text, _, _, _ = ch._parse_segments([{"type": "face", "data": {"id": "14"}}])
        assert text == "[face:14]"


class TestOnMessage:
    @pytest.mark.asyncio
    async def test_private_message_dispatched(self):
        ch = _make_channel()
        await ch._on_message(_private_event())

        ch.bus.publish_inbound.assert_awaited_once()
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.channel == "napcat"
        assert msg.sender_id == "42"
        assert msg.chat_id == "private:42"
        assert msg.content == "hi there"
        assert msg.metadata["is_group"] is False
        assert msg.metadata["message_id"] == 2000

    @pytest.mark.asyncio
    async def test_duplicate_message_filtered(self):
        ch = _make_channel()
        await ch._on_message(_private_event(message_id=2000))
        ch.bus.publish_inbound.reset_mock()
        await ch._on_message(_private_event(message_id=2000))
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_group_mention_policy_rejects_unmentioned(self):
        ch = _make_channel(group_policy="mention")
        ch._self_id = 999
        await ch._on_message(_group_event())
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_group_mention_policy_allows_at_self(self):
        ch = _make_channel(group_policy="mention")
        ch._self_id = 999
        ev = _group_event(
            message=[
                {"type": "at", "data": {"qq": "999"}},
                {"type": "text", "data": {"text": "explain entropy"}},
            ]
        )
        await ch._on_message(ev)

        ch.bus.publish_inbound.assert_awaited_once()
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.chat_id == "group:123456"
        assert msg.content == "Alice: explain entropy"
        assert msg.metadata["is_group"] is True

    @pytest.mark.asyncio
    async def test_group_open_policy_allows_all(self):
        ch = _make_channel(group_policy="open")
        ch._self_id = 999
        await ch._on_message(_group_event())
        ch.bus.publish_inbound.assert_awaited_once()
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.content == "Alice: hello bot"

    @pytest.mark.asyncio
    async def test_group_card_preferred_over_nickname(self):
        ch = _make_channel(group_policy="open")
        ev = _group_event(sender={"nickname": "Alice", "card": "Prof. A"})
        await ch._on_message(ev)
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.content == "Prof. A: hello bot"

    @pytest.mark.asyncio
    async def test_group_reply_to_bot_allows(self):
        ch = _make_channel(group_policy="mention")
        ch._self_id = 999
        ch._bot_outbound_ids.append(777)
        ev = _group_event(
            message=[
                {"type": "reply", "data": {"id": "777"}},
                {"type": "text", "data": {"text": "follow-up"}},
            ]
        )
        await ch._on_message(ev)
        ch.bus.publish_inbound.assert_awaited_once()
        assert ch.bus.publish_inbound.call_args[0][0].metadata["reply_to"] == 777

    @pytest.mark.asyncio
    async def test_image_message_downloads_media(self):
        ch = _make_channel()
        with patch.object(
            ch, "_download_image", new=AsyncMock(return_value="/tmp/media/a.png")
        ) as mock_dl:
            ev = _private_event(
                message=[
                    {"type": "text", "data": {"text": "look at this"}},
                    {
                        "type": "image",
                        "data": {"url": "https://example.com/a.png", "file": "a.png"},
                    },
                ]
            )
            await ch._on_message(ev)

        mock_dl.assert_awaited_once()
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.media == ["/tmp/media/a.png"]
        assert msg.content == "look at this"

    @pytest.mark.asyncio
    async def test_empty_content_and_media_not_dispatched(self):
        ch = _make_channel()
        await ch._on_message(_private_event(message=[]))
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disallowed_sender_blocked_by_base(self):
        ch = _make_channel(allow_from=["1000"])
        await ch._on_message(_private_event(user_id=42))
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_message_type_ignored(self):
        ch = _make_channel()
        await ch._on_message(_private_event(message_type="weird"))
        ch.bus.publish_inbound.assert_not_awaited()


class TestOnNotice:
    @pytest.mark.asyncio
    async def test_group_increase_sends_welcome_event(self):
        ch = _make_channel(welcome_new_members=True)
        with patch.object(ch, "_lookup_member_name", new=AsyncMock(return_value="Bob")):
            await ch._on_notice(
                {"notice_type": "group_increase", "group_id": 123456, "user_id": 55}
            )

        ch.bus.publish_inbound.assert_awaited_once()
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.chat_id == "group:123456"
        assert "Bob" in msg.content
        assert msg.metadata["event"] == "group_increase"

    @pytest.mark.asyncio
    async def test_welcome_disabled_ignores_notice(self):
        ch = _make_channel(welcome_new_members=False)
        await ch._on_notice({"notice_type": "group_increase", "group_id": 123456, "user_id": 55})
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_other_notice_types_ignored(self):
        ch = _make_channel(welcome_new_members=True)
        await ch._on_notice({"notice_type": "group_decrease", "group_id": 1, "user_id": 2})
        ch.bus.publish_inbound.assert_not_awaited()


class TestSend:
    @pytest.mark.asyncio
    async def test_send_raises_when_not_connected(self):
        ch = _make_channel()
        ch._ws = None
        msg = OutboundMessage(channel="napcat", chat_id="private:42", content="hi")
        with pytest.raises(RuntimeError):
            await ch.send(msg)

    @pytest.mark.asyncio
    async def test_send_raises_on_invalid_chat_id(self):
        ch = _make_channel()
        ch._ws = MagicMock()
        msg = OutboundMessage(channel="napcat", chat_id="bogus", content="hi")
        with pytest.raises(ValueError):
            await ch.send(msg)

    @pytest.mark.asyncio
    async def test_send_private_text(self):
        ch = _make_channel()
        ch._ws = MagicMock()
        with patch.object(
            ch,
            "_call_action",
            new=AsyncMock(return_value={"status": "ok", "retcode": 0, "data": {"message_id": 99}}),
        ) as mock_call:
            msg = OutboundMessage(channel="napcat", chat_id="private:42", content="hello")
            await ch.send(msg)

        mock_call.assert_awaited_once()
        action, params = mock_call.call_args[0]
        assert action == "send_msg"
        assert params["message_type"] == "private"
        assert params["user_id"] == 42
        assert params["message"] == [{"type": "text", "data": {"text": "hello"}}]
        # Outbound id recorded for reply-to-bot detection
        assert 99 in ch._bot_outbound_ids

    @pytest.mark.asyncio
    async def test_send_group_text(self):
        ch = _make_channel()
        ch._ws = MagicMock()
        with patch.object(
            ch,
            "_call_action",
            new=AsyncMock(return_value={"status": "ok", "retcode": 0, "data": {}}),
        ) as mock_call:
            msg = OutboundMessage(channel="napcat", chat_id="group:123456", content="answer")
            await ch.send(msg)

        _, params = mock_call.call_args[0]
        assert params["message_type"] == "group"
        assert params["group_id"] == 123456

    @pytest.mark.asyncio
    async def test_send_empty_message_is_noop(self):
        ch = _make_channel()
        ch._ws = MagicMock()
        with patch.object(ch, "_call_action", new=AsyncMock()) as mock_call:
            msg = OutboundMessage(channel="napcat", chat_id="private:42", content="   ")
            await ch.send(msg)
        mock_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_local_image_as_base64(self, tmp_path: Path):
        img = tmp_path / "pic.png"
        img.write_bytes(b"fake-png-bytes")

        ch = _make_channel()
        ch._ws = MagicMock()
        with patch.object(
            ch,
            "_call_action",
            new=AsyncMock(return_value={"status": "ok", "retcode": 0, "data": {}}),
        ) as mock_call:
            msg = OutboundMessage(
                channel="napcat", chat_id="private:42", content="see image", media=[str(img)]
            )
            await ch.send(msg)

        _, params = mock_call.call_args[0]
        segs = params["message"]
        assert segs[0]["type"] == "image"
        assert segs[0]["data"]["file"].startswith("base64://")
        assert segs[1] == {"type": "text", "data": {"text": "see image"}}

    @pytest.mark.asyncio
    async def test_send_action_failure_propagates(self):
        ch = _make_channel()
        ch._ws = MagicMock()
        with patch.object(
            ch,
            "_call_action",
            new=AsyncMock(side_effect=RuntimeError("napcat: action send_msg failed")),
        ):
            msg = OutboundMessage(channel="napcat", chat_id="private:42", content="hello")
            with pytest.raises(RuntimeError):
                await ch.send(msg)


class TestDispatchFrame:
    @pytest.mark.asyncio
    async def test_action_response_resolves_pending_future(self):
        import asyncio

        ch = _make_channel()
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        ch._pending["echo-1"] = fut

        await ch._dispatch_frame('{"echo": "echo-1", "status": "ok", "retcode": 0}')
        assert fut.done()
        assert fut.result()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_self_id_captured_from_event(self):
        ch = _make_channel()
        with patch.object(ch, "_create_background_task") as mock_bg:
            await ch._dispatch_frame('{"post_type": "message", "self_id": 999}')
        assert ch._self_id == 999
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_json_frame_dropped(self):
        ch = _make_channel()
        await ch._dispatch_frame("not-json{")  # must not raise


class TestChannelSchema:
    def test_napcat_in_all_channel_schemas(self):
        from deeptutor.api.routers._partners_channel_schema import all_channel_schemas

        schemas = all_channel_schemas()
        assert "napcat" in schemas
        payload = schemas["napcat"]
        assert payload["display_name"] == "QQ (NapCat)"
        assert "access_token" in payload["secret_fields"]
        assert payload["default_config"]["enabled"] is False
        assert payload["default_config"]["ws_url"] == "ws://127.0.0.1:3001"

    def test_coexists_with_official_qq_channel(self):
        from deeptutor.api.routers._partners_channel_schema import all_channel_schemas

        schemas = all_channel_schemas()
        assert "qq" in schemas
        assert "napcat" in schemas
        assert schemas["qq"]["display_name"] != schemas["napcat"]["display_name"]
