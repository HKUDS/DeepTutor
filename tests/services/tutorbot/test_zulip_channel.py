"""Unit tests for the Zulip channel implementation."""

from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deeptutor.tutorbot.bus.queue import MessageBus
from deeptutor.tutorbot.channels.zulip import ZulipChannel, ZulipConfig


def _make_channel(**overrides) -> ZulipChannel:
    defaults = {
        "enabled": True,
        "site": "https://example.zulipchat.com",
        "email": "bot@example.com",
        "api_key": "secret-key-123",
        "allow_from": ["*"],
        "group_policy": "mention",
        "timeout": 60.0,
    }
    defaults.update(overrides)
    config = ZulipConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return ZulipChannel(config, bus)


class TestZulipConfig:
    def test_default_values(self):
        cfg = ZulipConfig()
        assert cfg.enabled is False
        assert cfg.site == ""
        assert cfg.email == ""
        assert cfg.api_key == ""
        assert cfg.allow_from == []
        assert cfg.group_policy == "mention"
        assert cfg.timeout == 60.0

    def test_api_key_repr_false(self):
        cfg = ZulipConfig(api_key="super-secret")
        dumped = cfg.model_dump()
        assert dumped["api_key"] == "super-secret"
        r = repr(cfg)
        assert "super-secret" not in r

    def test_camel_case_alias(self):
        cfg = ZulipConfig(site="https://example.zulipchat.com", api_key="k")
        d = cfg.model_dump(by_alias=True)
        assert "apiKey" in d
        assert "groupPolicy" in d

    def test_from_camel_case_dict(self):
        d = {
            "enabled": True,
            "site": "https://example.zulipchat.com",
            "email": "bot@example.com",
            "apiKey": "secret",
            "allowFrom": ["*"],
            "groupPolicy": "open",
        }
        cfg = ZulipConfig.model_validate(d)
        assert cfg.api_key == "secret"
        assert cfg.group_policy == "open"
        assert cfg.allow_from == ["*"]


class TestDefaultConfig:
    def test_default_config_returns_dict(self):
        cfg = ZulipChannel.default_config()
        assert isinstance(cfg, dict)
        assert cfg["enabled"] is False
        assert "site" in cfg
        assert "apiKey" in cfg


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

    def test_composite_sender_id_email_match(self):
        ch = _make_channel(allow_from=["user@example.com"])
        assert ch.is_allowed("42|user@example.com") is True
        assert ch.is_allowed("42|other@example.com") is False

    def test_composite_sender_id_numeric_match(self):
        ch = _make_channel(allow_from=["42"])
        assert ch.is_allowed("42|user@example.com") is True

    def test_composite_sender_id_no_pipe(self):
        ch = _make_channel(allow_from=["42"])
        assert ch.is_allowed("42") is True


class TestIsOwnMessage:
    def test_matches_by_email(self):
        ch = _make_channel()
        ch._bot_email = "bot@example.com"
        ch._bot_user_id = 100
        assert ch._is_own_message({"sender_email": "bot@example.com", "sender_id": 200}) is True

    def test_matches_by_user_id(self):
        ch = _make_channel()
        ch._bot_email = "bot@example.com"
        ch._bot_user_id = 100
        assert ch._is_own_message({"sender_email": "other@example.com", "sender_id": 100}) is True

    def test_not_own_message(self):
        ch = _make_channel()
        ch._bot_email = "bot@example.com"
        ch._bot_user_id = 100
        assert ch._is_own_message({"sender_email": "user@example.com", "sender_id": 200}) is False


class TestIsDuplicate:
    def test_skips_messages_below_max_message_id(self):
        ch = _make_channel()
        ch._max_message_id = 100
        assert ch._is_duplicate({"id": 50}) is True

    def test_allows_new_messages(self):
        ch = _make_channel()
        ch._max_message_id = 100
        assert ch._is_duplicate({"id": 101}) is False

    def test_detects_duplicate_in_seen_ids(self):
        ch = _make_channel()
        ch._max_message_id = 0
        ch._seen_ids = deque([101, 102, 103], maxlen=5000)
        assert ch._is_duplicate({"id": 102}) is True

    def test_adds_new_id_to_seen(self):
        ch = _make_channel()
        ch._max_message_id = 0
        ch._is_duplicate({"id": 200})
        assert 200 in ch._seen_ids

    def test_none_id_not_duplicate(self):
        ch = _make_channel()
        assert ch._is_duplicate({}) is False


class TestIsMentioned:
    def test_mentioned_flag(self):
        ch = _make_channel()
        ch._bot_user_id = 100
        assert ch._is_mentioned({"flags": ["mentioned"]}) is True

    def test_no_flags(self):
        ch = _make_channel()
        ch._bot_user_id = 100
        assert ch._is_mentioned({"flags": []}) is False

    def test_other_flags(self):
        ch = _make_channel()
        ch._bot_user_id = 100
        assert ch._is_mentioned({"flags": ["has_alert_word"]}) is False

    def test_no_bot_user_id(self):
        ch = _make_channel()
        ch._bot_user_id = None
        assert ch._is_mentioned({"flags": ["mentioned"]}) is False


class TestExtractUploadLinks:
    def test_markdown_image(self):
        content = "Check this: ![photo.png](/user_uploads/2/ce/abc123/photo.png)"
        links = ZulipChannel._extract_upload_links(content)
        assert len(links) == 1
        assert links[0][0] == "photo.png"
        assert links[0][1] == "/user_uploads/2/ce/abc123/photo.png"

    def test_markdown_file_link(self):
        content = "Here is [report.pdf](/user_uploads/2/ce/def456/report.pdf)"
        links = ZulipChannel._extract_upload_links(content)
        assert len(links) == 1
        assert links[0][0] == "report.pdf"
        assert links[0][1] == "/user_uploads/2/ce/def456/report.pdf"

    def test_html_img_src(self):
        content = '<p><img src="/user_uploads/2/ce/abc123/photo.png"></p>'
        links = ZulipChannel._extract_upload_links(content, content_type="text/html")
        assert len(links) == 1
        assert links[0][1] == "/user_uploads/2/ce/abc123/photo.png"

    def test_html_a_href(self):
        content = '<a href="/user_uploads/2/ce/def456/report.pdf">report.pdf</a>'
        links = ZulipChannel._extract_upload_links(content, content_type="text/html")
        assert len(links) == 1
        assert links[0][1] == "/user_uploads/2/ce/def456/report.pdf"

    def test_multiple_links(self):
        content = (
            "See ![img.png](/user_uploads/2/ce/aaa/img.png) "
            "and [doc.pdf](/user_uploads/2/ce/bbb/doc.pdf)"
        )
        links = ZulipChannel._extract_upload_links(content)
        assert len(links) == 2

    def test_dedup_same_path(self):
        content = (
            "![img.png](/user_uploads/2/ce/aaa/img.png) "
            "again [img.png](/user_uploads/2/ce/aaa/img.png)"
        )
        links = ZulipChannel._extract_upload_links(content)
        assert len(links) == 1

    def test_no_uploads(self):
        content = "Just a plain message with no attachments"
        links = ZulipChannel._extract_upload_links(content)
        assert links == []

    def test_non_upload_link_ignored(self):
        content = "[Zulip](https://zulip.com) and [docs](/help/)"
        links = ZulipChannel._extract_upload_links(content)
        assert links == []

    def test_empty_name_uses_path(self):
        content = "![](/user_uploads/2/ce/abc123/photo.png)"
        links = ZulipChannel._extract_upload_links(content)
        assert len(links) == 1
        assert links[0][0] == "photo.png"


class TestDownloadAttachments:
    def test_extracts_from_markdown_content(self):
        ch = _make_channel()
        message = {
            "content": "Check ![img.png](/user_uploads/2/ce/abc/img.png)",
            "content_type": "text/x-markdown",
        }
        with patch.object(
            ch,
            "_extract_upload_links",
            return_value=[("img.png", "/user_uploads/2/ce/abc/img.png")],
        ):
            with patch("deeptutor.tutorbot.channels.zulip.requests.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.raise_for_status = MagicMock()
                mock_resp.content = b"fake-image-data"
                mock_get.return_value = mock_resp
                with patch.object(Path, "exists", return_value=False):
                    with patch.object(Path, "write_bytes"):
                        paths = ch._download_attachments(message)
                        assert len(paths) == 1
                        mock_get.assert_called_once()
                        call_url = mock_get.call_args[0][0]
                        assert (
                            call_url
                            == "https://example.zulipchat.com/user_uploads/2/ce/abc/img.png"
                        )

    def test_no_uploads_returns_empty(self):
        ch = _make_channel()
        message = {"content": "No attachments here", "content_type": "text/x-markdown"}
        with patch.object(ch, "_extract_upload_links", return_value=[]):
            paths = ch._download_attachments(message)
            assert paths == []

    def test_caches_existing_file(self):
        ch = _make_channel()
        message = {
            "content": "![img.png](/user_uploads/2/ce/abc/img.png)",
            "content_type": "text/x-markdown",
        }
        with patch.object(
            ch,
            "_extract_upload_links",
            return_value=[("img.png", "/user_uploads/2/ce/abc/img.png")],
        ):
            from pathlib import Path as RealPath
            from unittest.mock import mock_open

            with patch.object(RealPath, "exists", return_value=True):
                paths = ch._download_attachments(message)
                assert len(paths) == 1

    def test_attachment_destination_uses_upload_path_digest(self, tmp_path: Path):
        first = ZulipChannel._attachment_destination(
            tmp_path,
            "image.png",
            "/user_uploads/2/aa/first/image.png",
            0,
        )
        second = ZulipChannel._attachment_destination(
            tmp_path,
            "image.png",
            "/user_uploads/2/bb/second/image.png",
            0,
        )

        assert first != second
        assert first.name.endswith("_image.png")
        assert second.name.endswith("_image.png")


class TestConvertLatexToZulip:
    def test_inline_math(self):
        result = ZulipChannel._convert_latex_to_zulip("The value $x^2$ is positive")
        assert result == "The value $$x^2$$ is positive"

    def test_display_math(self):
        result = ZulipChannel._convert_latex_to_zulip("$$\n\\int_a^b f(x) dx\n$$")
        assert "```math" in result
        assert "\\int_a^b f(x) dx" in result
        assert "$$" not in result

    def test_display_math_single_line(self):
        result = ZulipChannel._convert_latex_to_zulip("$$E = mc^2$$")
        assert "```math" in result
        assert "E = mc^2" in result

    def test_mixed_inline_and_display(self):
        result = ZulipChannel._convert_latex_to_zulip("Inline $a+b$ and display:\n$$c+d$$")
        assert "$$a+b$$" in result
        assert "```math" in result
        assert "c+d" in result

    def test_code_block_preserved(self):
        result = ZulipChannel._convert_latex_to_zulip("```python\nx = $1 + $2\n```")
        assert "```python" in result
        assert "$1 + $2" in result

    def test_inline_code_preserved(self):
        result = ZulipChannel._convert_latex_to_zulip("Use `$x$` variable")
        assert "`$x$`" in result

    def test_no_math_unchanged(self):
        text = "Just plain text without any math"
        assert ZulipChannel._convert_latex_to_zulip(text) == text

    def test_already_double_dollar_preserved_as_display(self):
        result = ZulipChannel._convert_latex_to_zulip("$$x^2$$")
        assert "```math" in result

    def test_multiple_inline(self):
        result = ZulipChannel._convert_latex_to_zulip("$a$ and $b$ and $c$")
        assert result == "$$a$$ and $$b$$ and $$c$$"


class TestConvertZulipLatexToStandard:
    def test_inline_math(self):
        result = ZulipChannel._convert_zulip_latex_to_standard("The value $$x^2$$ is positive")
        assert result == "The value $x^2$ is positive"

    def test_display_math(self):
        result = ZulipChannel._convert_zulip_latex_to_standard("```math\n\\int_a^b f(x) dx\n```")
        assert "$$" in result
        assert "\\int_a^b f(x) dx" in result
        assert "```math" not in result

    def test_mixed(self):
        result = ZulipChannel._convert_zulip_latex_to_standard(
            "Inline $$a+b$$ and display:\n```math\nc+d\n```"
        )
        assert "$a+b$" in result
        assert "$$" in result
        assert "c+d" in result

    def test_code_block_preserved(self):
        result = ZulipChannel._convert_zulip_latex_to_standard("```python\nx = $$1 + $$2\n```")
        assert "```python" in result
        assert "$$1 + $$2" in result

    def test_no_math_unchanged(self):
        text = "Just plain text"
        assert ZulipChannel._convert_zulip_latex_to_standard(text) == text

    def test_roundtrip_inline(self):
        original = "The value $x^2$ is positive"
        zulip_fmt = ZulipChannel._convert_latex_to_zulip(original)
        restored = ZulipChannel._convert_zulip_latex_to_standard(zulip_fmt)
        assert restored == original

    def test_roundtrip_display(self):
        original = "$$\n\\int_a^b f(x) dx\n$$"
        zulip_fmt = ZulipChannel._convert_latex_to_zulip(original)
        restored = ZulipChannel._convert_zulip_latex_to_standard(zulip_fmt)
        assert "\\int_a^b f(x) dx" in restored


class TestBuildSendRequest:
    def test_stream_message(self):
        ch = _make_channel()
        metadata = {
            "msg_type": "stream",
            "stream": "general",
            "topic": "hello",
        }
        req = ch._build_send_request("stream:general:hello", "Hello world", metadata)
        assert req["type"] == "stream"
        assert req["to"] == "general"
        assert req["subject"] == "hello"
        assert req["content"] == "Hello world"

    def test_stream_message_no_topic(self):
        ch = _make_channel()
        metadata = {"msg_type": "stream", "stream": "general", "topic": ""}
        req = ch._build_send_request("stream:general", "Hi", metadata)
        assert req["subject"] == "(no topic)"

    def test_private_message(self):
        ch = _make_channel()
        metadata = {
            "msg_type": "private",
            "recipient_user_id": "42",
        }
        req = ch._build_send_request("pm:42", "Hello", metadata)
        assert req["type"] == "private"
        assert req["to"] == ["42"]

    def test_private_message_fallback_to_email(self):
        ch = _make_channel()
        metadata = {
            "msg_type": "private",
            "sender_email": "user@example.com",
        }
        req = ch._build_send_request("pm:42", "Hello", metadata)
        assert req["to"] == ["user@example.com"]


class TestOnMessage:
    def _make_msg(self, **overrides) -> dict:
        base = {
            "id": 200,
            "type": "private",
            "content": "Hello bot",
            "sender_id": 42,
            "sender_email": "user@example.com",
            "sender_full_name": "Test User",
            "display_recipient": [
                {"id": 42, "email": "user@example.com"},
                {"id": 100, "email": "bot@example.com"},
            ],
            "subject": "",
            "flags": [],
            "attachments": [],
        }
        base.update(overrides)
        return base

    @pytest.mark.asyncio
    async def test_private_message_dispatched(self):
        ch = _make_channel()
        ch._bot_email = "bot@example.com"
        ch._bot_user_id = 100
        ch._max_message_id = 0
        ch._loop = asyncio.get_running_loop()

        msg = self._make_msg()
        ch._on_message(msg)

        await asyncio.sleep(0.1)
        ch.bus.publish_inbound.assert_awaited_once()
        call_args = ch.bus.publish_inbound.call_args[0][0]
        assert call_args.channel == "zulip"
        assert call_args.sender_id == "42|user@example.com"
        assert call_args.chat_id == "pm:42"
        assert call_args.content == "Hello bot"

    @pytest.mark.asyncio
    async def test_own_message_filtered(self):
        ch = _make_channel()
        ch._bot_email = "bot@example.com"
        ch._bot_user_id = 100
        ch._max_message_id = 0
        ch._loop = asyncio.get_running_loop()

        msg = self._make_msg(sender_email="bot@example.com", sender_id=100)
        ch._on_message(msg)

        await asyncio.sleep(0.1)
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_duplicate_message_filtered(self):
        ch = _make_channel()
        ch._bot_email = "bot@example.com"
        ch._bot_user_id = 100
        ch._max_message_id = 0
        ch._loop = asyncio.get_running_loop()

        msg = self._make_msg(id=200)
        ch._on_message(msg)
        await asyncio.sleep(0.1)

        ch.bus.publish_inbound.reset_mock()
        ch._on_message(msg)
        await asyncio.sleep(0.1)
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stream_mention_policy_rejects_unmentioned(self):
        ch = _make_channel(group_policy="mention")
        ch._bot_email = "bot@example.com"
        ch._bot_user_id = 100
        ch._max_message_id = 0
        ch._loop = asyncio.get_running_loop()

        msg = self._make_msg(
            type="stream",
            display_recipient="general",
            subject="test",
            flags=[],
        )
        ch._on_message(msg)

        await asyncio.sleep(0.1)
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stream_mention_policy_allows_mentioned(self):
        ch = _make_channel(group_policy="mention")
        ch._bot_email = "bot@example.com"
        ch._bot_user_id = 100
        ch._max_message_id = 0
        ch._loop = asyncio.get_running_loop()

        msg = self._make_msg(
            type="stream",
            display_recipient="general",
            subject="test",
            flags=["mentioned"],
        )
        ch._on_message(msg)

        await asyncio.sleep(0.1)
        ch.bus.publish_inbound.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stream_open_policy_allows_all(self):
        ch = _make_channel(group_policy="open")
        ch._bot_email = "bot@example.com"
        ch._bot_user_id = 100
        ch._max_message_id = 0
        ch._loop = asyncio.get_running_loop()

        msg = self._make_msg(
            type="stream",
            display_recipient="general",
            subject="test",
            flags=[],
        )
        ch._on_message(msg)

        await asyncio.sleep(0.1)
        ch.bus.publish_inbound.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stream_message_includes_prefix(self):
        ch = _make_channel(group_policy="open")
        ch._bot_email = "bot@example.com"
        ch._bot_user_id = 100
        ch._max_message_id = 0
        ch._loop = asyncio.get_running_loop()

        msg = self._make_msg(
            type="stream",
            display_recipient="general",
            subject="test topic",
            content="Hello",
            flags=[],
        )
        ch._on_message(msg)

        await asyncio.sleep(0.1)
        call_args = ch.bus.publish_inbound.call_args[0][0]
        assert call_args.chat_id == "stream:general:test topic"
        assert call_args.session_key_override == "zulip:stream:general:test topic"
        assert "**[general > test topic]**" in call_args.content

    @pytest.mark.asyncio
    async def test_empty_stream_topic_gets_stable_no_topic_scope(self):
        ch = _make_channel(group_policy="open")
        ch._bot_email = "bot@example.com"
        ch._bot_user_id = 100
        ch._max_message_id = 0
        ch._loop = asyncio.get_running_loop()

        msg = self._make_msg(
            type="stream",
            display_recipient="general",
            subject="",
            content="Hello",
            flags=[],
        )
        ch._on_message(msg)

        await asyncio.sleep(0.1)
        call_args = ch.bus.publish_inbound.call_args[0][0]
        assert call_args.chat_id == "stream:general:(no topic)"
        assert call_args.session_key_override == "zulip:stream:general:(no topic)"


class TestSend:
    @pytest.mark.asyncio
    async def test_send_text_uses_call_endpoint(self):
        ch = _make_channel()
        mock_client = MagicMock()
        mock_client.call_endpoint.return_value = {"result": "success"}
        ch._client = mock_client

        from deeptutor.tutorbot.bus.events import OutboundMessage

        msg = OutboundMessage(
            channel="zulip",
            chat_id="pm:42",
            content="Hello",
            metadata={"msg_type": "private", "recipient_user_id": "42"},
        )
        await ch.send(msg)

        mock_client.call_endpoint.assert_called_once()
        call_kwargs = mock_client.call_endpoint.call_args
        assert call_kwargs.kwargs["url"] == "messages"
        assert call_kwargs.kwargs["timeout"] == 60.0

    @pytest.mark.asyncio
    async def test_send_stops_typing_on_final_response(self):
        ch = _make_channel()
        mock_client = MagicMock()
        mock_client.call_endpoint.return_value = {"result": "success"}
        ch._client = mock_client

        typing_task = asyncio.create_task(asyncio.sleep(100))
        ch._typing_tasks["pm:42"] = typing_task

        from deeptutor.tutorbot.bus.events import OutboundMessage

        msg = OutboundMessage(
            channel="zulip",
            chat_id="pm:42",
            content="Hello",
            metadata={},
        )
        await ch.send(msg)
        assert "pm:42" not in ch._typing_tasks

    @pytest.mark.asyncio
    async def test_send_keeps_typing_on_progress(self):
        ch = _make_channel()
        mock_client = MagicMock()
        mock_client.call_endpoint.return_value = {"result": "success"}
        ch._client = mock_client

        typing_task = asyncio.create_task(asyncio.sleep(100))
        ch._typing_tasks["pm:42"] = typing_task

        from deeptutor.tutorbot.bus.events import OutboundMessage

        msg = OutboundMessage(
            channel="zulip",
            chat_id="pm:42",
            content="Thinking...",
            metadata={"_progress": True},
        )
        await ch.send(msg)
        assert "pm:42" in ch._typing_tasks

    @pytest.mark.asyncio
    async def test_send_no_client_returns_early(self):
        ch = _make_channel()
        ch._client = None

        from deeptutor.tutorbot.bus.events import OutboundMessage

        msg = OutboundMessage(
            channel="zulip",
            chat_id="pm:42",
            content="Hello",
            metadata={},
        )
        await ch.send(msg)


class TestUploadAndSend:
    @pytest.mark.asyncio
    async def test_upload_uses_call_endpoint(self):
        ch = _make_channel()
        mock_client = MagicMock()

        def fake_call_endpoint(**kwargs):
            if kwargs.get("url") == "user_uploads":
                return {"result": "success", "uri": "/user_uploads/img.png"}
            return {"result": "success"}

        mock_client.call_endpoint.side_effect = fake_call_endpoint
        ch._client = mock_client

        from deeptutor.tutorbot.bus.events import OutboundMessage

        msg = OutboundMessage(
            channel="zulip",
            chat_id="pm:42",
            content="",
            media=["/tmp/test.png"],
            metadata={"msg_type": "private", "recipient_user_id": "42"},
        )
        await ch.send(msg)

        upload_calls = [
            c
            for c in mock_client.call_endpoint.call_args_list
            if c.kwargs.get("url") == "user_uploads"
        ]
        assert len(upload_calls) == 1
        assert upload_calls[0].kwargs["timeout"] == 60.0


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_deregisters_queue(self):
        ch = _make_channel()
        mock_client = MagicMock()
        ch._client = mock_client
        ch._queue_id = "test-queue-123"
        ch._running = True

        saved_client = ch._client
        await ch.stop()

        saved_client.deregister.assert_called_once_with("test-queue-123")
        assert ch._queue_id is None
        assert ch._client is None
        assert ch._running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_typing_tasks(self):
        ch = _make_channel()
        mock_client = MagicMock()
        ch._client = mock_client
        ch._running = True

        task = asyncio.create_task(asyncio.sleep(100))
        ch._typing_tasks["pm:42"] = task

        await ch.stop()
        await asyncio.sleep(0)
        assert task.cancelled() or task.done()
        assert len(ch._typing_tasks) == 0


class TestRegisterQueue:
    def test_register_success(self):
        ch = _make_channel()
        mock_client = MagicMock()
        mock_client.register.return_value = {
            "result": "success",
            "queue_id": "q-123",
            "last_event_id": 10,
            "max_message_id": 500,
        }
        ch._client = mock_client

        ch._register_queue()
        assert ch._queue_id == "q-123"
        assert ch._last_event_id == 10
        assert ch._max_message_id == 500

    def test_register_failure(self):
        ch = _make_channel()
        mock_client = MagicMock()
        mock_client.register.return_value = {
            "result": "error",
            "msg": "bad request",
        }
        ch._client = mock_client

        ch._register_queue()
        assert ch._queue_id is None


class TestCallWithRetry:
    def test_succeeds_on_first_attempt(self):
        ch = _make_channel()
        fn = MagicMock(return_value={"result": "success"})
        result = ch._call_with_retry(fn)
        assert result == {"result": "success"}
        assert fn.call_count == 1

    def test_retries_on_failure(self):
        ch = _make_channel()
        fn = MagicMock(
            side_effect=[Exception("fail"), Exception("fail again"), {"result": "success"}]
        )
        with patch("time.sleep"):
            result = ch._call_with_retry(fn)
        assert result == {"result": "success"}
        assert fn.call_count == 3

    def test_raises_after_max_retries(self):
        ch = _make_channel()
        fn = MagicMock(side_effect=Exception("persistent failure"))
        with patch("time.sleep"):
            with pytest.raises(Exception, match="persistent failure"):
                ch._call_with_retry(fn)
        assert fn.call_count == 3


class TestStart:
    @pytest.mark.asyncio
    async def test_start_without_config_returns_early(self):
        ch = _make_channel(site="", email="", api_key="")
        await ch.start()
        assert ch._running is False

    @pytest.mark.asyncio
    async def test_start_profile_failure(self, monkeypatch):
        ch = _make_channel()
        fake_zulip = SimpleNamespace(Client=MagicMock())
        monkeypatch.setitem(sys.modules, "zulip", fake_zulip)
        with patch("deeptutor.tutorbot.channels.zulip.ZulipChannel._call_with_retry") as mock_retry:
            mock_retry.return_value = {"result": "error"}
            await ch.start()

        assert ch._running is False
