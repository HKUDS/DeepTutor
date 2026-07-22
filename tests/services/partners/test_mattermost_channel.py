"""Unit tests for the Mattermost channel implementation."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import mattermost as mm_module
from deeptutor.partners.channels.mattermost import MattermostChannel, MattermostConfig


def _make_channel(**overrides) -> MattermostChannel:
    defaults = {
        "enabled": True,
        "server_url": "https://mm.example.com",
        "bot_token": "tok-123",
        "allow_from": ["*"],
        "group_policy": "mention",
        "reply_in_thread": True,
    }
    defaults.update(overrides)
    config = MattermostConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    ch = MattermostChannel(config, bus)
    ch._bot_user_id = "bot-id"
    ch._bot_username = "tutor"
    return ch


def _event(post: dict, *, channel_type: str = "O", mentions: list[str] | None = None) -> dict:
    data: dict = {"post": json.dumps(post), "channel_type": channel_type}
    if mentions is not None:
        data["mentions"] = json.dumps(mentions)
    return data


def _post(**overrides) -> dict:
    base = {
        "id": "post-1",
        "channel_id": "chan-1",
        "user_id": "user-9",
        "message": "hello",
        "root_id": "",
        "type": "",
    }
    base.update(overrides)
    return base


def _ok_http() -> AsyncMock:
    """An AsyncMock httpx client whose responses pass ``raise_for_status``."""
    http = AsyncMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"file_infos": [{"id": "file-xyz"}]})
    http.post = AsyncMock(return_value=resp)
    return http


class TestMattermostConfig:
    def test_default_values(self):
        cfg = MattermostConfig()
        assert cfg.enabled is False
        assert cfg.server_url == ""
        assert cfg.bot_token == ""
        assert cfg.allow_from == []
        assert cfg.group_policy == "mention"
        assert cfg.reply_in_thread is True
        assert cfg.verify_ssl is True

    def test_bot_token_repr_hidden(self):
        cfg = MattermostConfig(bot_token="super-secret")
        assert cfg.bot_token == "super-secret"
        assert "super-secret" not in repr(cfg)

    def test_camel_case_alias_roundtrip(self):
        cfg = MattermostConfig(server_url="https://x", bot_token="t")
        dumped = cfg.model_dump(by_alias=True)
        assert "serverUrl" in dumped
        assert "botToken" in dumped
        assert "groupPolicy" in dumped

    def test_from_camel_case_dict(self):
        cfg = MattermostConfig.model_validate(
            {
                "enabled": True,
                "serverUrl": "https://mm.example.com",
                "botToken": "t",
                "allowFrom": ["*"],
                "groupPolicy": "open",
                "replyInThread": False,
            }
        )
        assert cfg.server_url == "https://mm.example.com"
        assert cfg.bot_token == "t"
        assert cfg.group_policy == "open"
        assert cfg.reply_in_thread is False


class TestDefaultConfig:
    def test_returns_dict(self):
        cfg = MattermostChannel.default_config()
        assert isinstance(cfg, dict)
        assert cfg["enabled"] is False
        assert "serverUrl" in cfg
        assert "botToken" in cfg


class TestUrlHelpers:
    def test_api_base_https(self):
        assert MattermostChannel._api_base_url("https://mm.example.com") == (
            "https://mm.example.com/api/v4"
        )

    def test_api_base_strips_trailing_slash(self):
        assert MattermostChannel._api_base_url("https://mm.example.com/") == (
            "https://mm.example.com/api/v4"
        )

    def test_ws_url_https_to_wss(self):
        assert MattermostChannel._websocket_url("https://mm.example.com") == (
            "wss://mm.example.com/api/v4/websocket"
        )

    def test_ws_url_http_to_ws(self):
        assert MattermostChannel._websocket_url("http://localhost:8065") == (
            "ws://localhost:8065/api/v4/websocket"
        )

    def test_no_scheme_defaults_https(self):
        assert MattermostChannel._websocket_url("mm.example.com") == (
            "wss://mm.example.com/api/v4/websocket"
        )

    def test_empty_url(self):
        assert MattermostChannel._api_base_url("") == ""
        assert MattermostChannel._websocket_url("") == ""


class TestIsAllowed:
    def test_wildcard_allows_all(self):
        assert _make_channel(allow_from=["*"]).is_allowed("anyone") is True

    def test_empty_denies_all(self):
        assert _make_channel(allow_from=[]).is_allowed("anyone") is False

    def test_specific_match(self):
        ch = _make_channel(allow_from=["user-9"])
        assert ch.is_allowed("user-9") is True
        assert ch.is_allowed("user-x") is False


class TestStripBotMention:
    def test_removes_leading_mention(self):
        ch = _make_channel()
        assert ch._strip_bot_mention("@tutor what is 2+2?") == "what is 2+2?"

    def test_no_username_noop(self):
        ch = _make_channel()
        ch._bot_username = ""
        assert ch._strip_bot_mention("@tutor hi") == "@tutor hi"


class TestShouldRespondInChannel:
    def test_open_policy_always_true(self):
        ch = _make_channel(group_policy="open")
        assert ch._should_respond_in_channel("no mention here", {}) is True

    def test_mention_via_mentions_list(self):
        ch = _make_channel(group_policy="mention")
        data = {"mentions": json.dumps(["bot-id"])}
        assert ch._should_respond_in_channel("hey", data) is True

    def test_mention_via_text(self):
        ch = _make_channel(group_policy="mention")
        assert ch._should_respond_in_channel("hi @tutor", {}) is True

    def test_no_mention_false(self):
        ch = _make_channel(group_policy="mention")
        assert ch._should_respond_in_channel("just chatting", {}) is False


@pytest.mark.asyncio
class TestHandlePosted:
    async def test_channel_mention_forwarded(self):
        ch = _make_channel(group_policy="mention")
        await ch._handle_posted(_event(_post(message="@tutor explain"), mentions=["bot-id"]))
        ch.bus.publish_inbound.assert_awaited_once()
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.channel == "mattermost"
        assert msg.sender_id == "user-9"
        assert msg.chat_id == "chan-1"
        assert msg.content == "explain"
        # Root post → thread root is its own id; channel msgs get a thread key.
        assert msg.metadata["mattermost"]["root_id"] == "post-1"
        assert msg.session_key == "mattermost:chan-1:post-1"

    async def test_dm_bypasses_group_policy(self):
        ch = _make_channel(group_policy="mention")
        await ch._handle_posted(_event(_post(message="no mention"), channel_type="D"))
        ch.bus.publish_inbound.assert_awaited_once()
        msg = ch.bus.publish_inbound.call_args[0][0]
        # DMs use the default channel-scoped session key (no thread suffix).
        assert msg.session_key == "mattermost:chan-1"

    async def test_own_message_skipped(self):
        ch = _make_channel()
        await ch._handle_posted(_event(_post(user_id="bot-id"), channel_type="D"))
        ch.bus.publish_inbound.assert_not_awaited()

    async def test_system_message_skipped(self):
        ch = _make_channel()
        await ch._handle_posted(_event(_post(type="system_join_channel"), channel_type="D"))
        ch.bus.publish_inbound.assert_not_awaited()

    async def test_disallowed_sender_skipped(self):
        ch = _make_channel(allow_from=["someone-else"])
        await ch._handle_posted(_event(_post(), channel_type="D"))
        ch.bus.publish_inbound.assert_not_awaited()

    async def test_unmentioned_channel_message_skipped(self):
        ch = _make_channel(group_policy="mention")
        await ch._handle_posted(_event(_post(message="just chatting"), channel_type="O"))
        ch.bus.publish_inbound.assert_not_awaited()

    async def test_reply_keeps_existing_thread_root(self):
        ch = _make_channel(group_policy="open")
        await ch._handle_posted(_event(_post(root_id="root-7"), channel_type="O"))
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.metadata["mattermost"]["root_id"] == "root-7"
        assert msg.session_key == "mattermost:chan-1:root-7"

    async def test_no_thread_when_reply_in_thread_disabled(self):
        ch = _make_channel(group_policy="open", reply_in_thread=False)
        await ch._handle_posted(_event(_post(), channel_type="O"))
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.metadata["mattermost"]["root_id"] == ""
        # No thread root → default channel-scoped session key.
        assert msg.session_key == "mattermost:chan-1"

    async def test_malformed_post_ignored(self):
        ch = _make_channel()
        await ch._handle_posted({"post": "not-json"})
        await ch._handle_posted({})  # no post key
        ch.bus.publish_inbound.assert_not_awaited()


@pytest.mark.asyncio
class TestSend:
    async def test_text_post_with_thread(self):
        ch = _make_channel()
        ch._http = _ok_http()
        msg = OutboundMessage(
            channel="mattermost",
            chat_id="chan-1",
            content="answer",
            metadata={"mattermost": {"root_id": "root-7"}},
        )
        await ch.send(msg)
        ch._http.post.assert_awaited_once()
        url = ch._http.post.call_args[0][0]
        body = ch._http.post.call_args.kwargs["json"]
        assert url.endswith("/api/v4/posts")
        assert body == {"channel_id": "chan-1", "message": "answer", "root_id": "root-7"}

    async def test_long_message_split(self, monkeypatch):
        monkeypatch.setattr(mm_module, "MAX_MESSAGE_LEN", 10)
        ch = _make_channel()
        ch._http = _ok_http()
        await ch.send(OutboundMessage(channel="mattermost", chat_id="c", content="x" * 25))
        assert ch._http.post.await_count == 3

    async def test_media_only_sends_empty_post_with_files(self):
        ch = _make_channel()
        ch._http = _ok_http()
        ch._upload_file = AsyncMock(return_value="file-1")
        await ch.send(
            OutboundMessage(channel="mattermost", chat_id="c", content="", media=["/tmp/a.png"])
        )
        body = ch._http.post.call_args.kwargs["json"]
        assert body["message"] == ""
        assert body["file_ids"] == ["file-1"]

    async def test_files_only_on_first_chunk(self, monkeypatch):
        monkeypatch.setattr(mm_module, "MAX_MESSAGE_LEN", 10)
        ch = _make_channel()
        ch._http = _ok_http()
        ch._upload_file = AsyncMock(return_value="file-1")
        await ch.send(
            OutboundMessage(
                channel="mattermost", chat_id="c", content="x" * 25, media=["/tmp/a.png"]
            )
        )
        first_body = ch._http.post.await_args_list[0].kwargs["json"]
        second_body = ch._http.post.await_args_list[1].kwargs["json"]
        assert first_body["file_ids"] == ["file-1"]
        assert "file_ids" not in second_body

    async def test_empty_message_no_media_is_noop(self):
        ch = _make_channel()
        ch._http = _ok_http()
        await ch.send(OutboundMessage(channel="mattermost", chat_id="c", content=""))
        ch._http.post.assert_not_awaited()

    async def test_post_failure_propagates_for_retry(self):
        ch = _make_channel()
        http = _ok_http()
        http.post.return_value.raise_for_status.side_effect = RuntimeError("500")
        ch._http = http
        with pytest.raises(RuntimeError):
            await ch.send(OutboundMessage(channel="mattermost", chat_id="c", content="hi"))

    async def test_no_client_is_noop(self):
        ch = _make_channel()
        ch._http = None
        # Should not raise even though the client isn't running.
        await ch.send(OutboundMessage(channel="mattermost", chat_id="c", content="hi"))


@pytest.mark.asyncio
class TestUploadFile:
    async def test_uploads_existing_file(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("data")
        ch = _make_channel()
        ch._http = _ok_http()
        file_id = await ch._upload_file("chan-1", str(f))
        assert file_id == "file-xyz"
        assert ch._http.post.call_args[0][0].endswith("/api/v4/files")
        assert ch._http.post.call_args.kwargs["params"] == {"channel_id": "chan-1"}

    async def test_missing_file_returns_none(self):
        ch = _make_channel()
        ch._http = _ok_http()
        assert await ch._upload_file("chan-1", "/nope/missing.txt") is None
        ch._http.post.assert_not_awaited()

    async def test_oversize_file_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mm_module, "MAX_ATTACHMENT_BYTES", 1)
        f = tmp_path / "big.bin"
        f.write_bytes(b"xx")
        ch = _make_channel()
        ch._http = _ok_http()
        assert await ch._upload_file("chan-1", str(f)) is None
        ch._http.post.assert_not_awaited()


@pytest.mark.asyncio
class TestDownloadFiles:
    async def test_no_file_ids_returns_empty(self):
        ch = _make_channel()
        ch._http = _ok_http()
        assert await ch._download_files(_post()) == []
