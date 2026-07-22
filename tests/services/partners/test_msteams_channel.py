"""Unit tests for the Microsoft Teams channel implementation."""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import msteams as msteams_mod
from deeptutor.partners.channels.msteams import (
    MSTEAMS_REF_FILENAME,
    MSTEAMS_REF_META_FILENAME,
    ConversationRef,
    MSTeamsChannel,
    MSTeamsConfig,
)


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Redirect the channel's runtime state dir to a temp directory."""
    monkeypatch.setattr(msteams_mod, "get_runtime_subdir", lambda name: tmp_path)
    return tmp_path


def _make_channel(**overrides) -> MSTeamsChannel:
    defaults = {
        "enabled": True,
        "app_id": "app-123",
        "app_password": "secret-pass",
        "allow_from": ["*"],
    }
    defaults.update(overrides)
    config = MSTeamsConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return MSTeamsChannel(config, bus)


def _activity(**overrides) -> dict:
    base = {
        "type": "message",
        "id": "act-1",
        "text": "Hello bot",
        "serviceUrl": "https://smba.trafficmanager.net/amer/",
        "from": {"id": "29:user", "aadObjectId": "aad-user-1", "name": "Test User"},
        "recipient": {"id": "28:bot"},
        "conversation": {"id": "a:conv-1", "conversationType": "personal"},
        "channelData": {"tenant": {"id": "tenant-1"}},
    }
    base.update(overrides)
    return base


class TestMSTeamsConfig:
    def test_default_values(self):
        cfg = MSTeamsConfig()
        assert cfg.enabled is False
        assert cfg.app_id == ""
        assert cfg.app_password == ""
        assert cfg.tenant_id == ""
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 3978
        assert cfg.path == "/api/messages"
        assert cfg.allow_from == []
        assert cfg.reply_in_thread is True
        assert cfg.validate_inbound_auth is True
        assert cfg.ref_ttl_days == 30
        assert cfg.prune_web_chat_refs is True
        assert cfg.prune_non_personal_refs is True
        assert "smba.trafficmanager.net" in cfg.trusted_service_url_hosts
        # Inherited DeliveryOverrides flags
        assert cfg.send_progress is True
        assert cfg.send_tool_hints is True

    def test_camel_case_alias(self):
        cfg = MSTeamsConfig(app_id="a", app_password="p")
        d = cfg.model_dump(by_alias=True)
        assert "appId" in d
        assert "appPassword" in d
        assert "allowFrom" in d
        assert "validateInboundAuth" in d
        assert "trustedServiceUrlHosts" in d

    def test_from_camel_case_dict(self):
        d = {
            "enabled": True,
            "appId": "app-1",
            "appPassword": "pw",
            "allowFrom": ["*"],
            "refTtlDays": 7,
            "validateInboundAuth": False,
        }
        cfg = MSTeamsConfig.model_validate(d)
        assert cfg.app_id == "app-1"
        assert cfg.app_password == "pw"
        assert cfg.allow_from == ["*"]
        assert cfg.ref_ttl_days == 7
        assert cfg.validate_inbound_auth is False


class TestDefaultConfig:
    def test_default_config_returns_dict(self):
        cfg = MSTeamsChannel.default_config()
        assert isinstance(cfg, dict)
        assert cfg["enabled"] is False
        assert "appId" in cfg
        assert "appPassword" in cfg
        assert "trustedServiceUrlHosts" in cfg


class TestIsAllowed:
    def test_wildcard_allows_all(self, state_dir):
        ch = _make_channel(allow_from=["*"])
        assert ch.is_allowed("aad-user-1") is True

    def test_empty_list_denies_all(self, state_dir):
        ch = _make_channel(allow_from=[])
        assert ch.is_allowed("aad-user-1") is False

    def test_sender_id_match(self, state_dir):
        ch = _make_channel(allow_from=["aad-user-1"])
        assert ch.is_allowed("aad-user-1") is True
        assert ch.is_allowed("aad-user-2") is False


class TestTrustedServiceUrl:
    def test_default_teams_host_trusted(self, state_dir):
        ch = _make_channel()
        assert ch._is_trusted_service_url("https://smba.trafficmanager.net/amer/") is True

    def test_wildcard_subdomain_trusted(self, state_dir):
        ch = _make_channel()
        assert ch._is_trusted_service_url("https://smba.botframework.com/") is True

    def test_wildcard_does_not_match_bare_domain(self, state_dir):
        ch = _make_channel()
        assert ch._is_trusted_service_url("https://botframework.com/") is False

    def test_http_rejected(self, state_dir):
        ch = _make_channel()
        assert ch._is_trusted_service_url("http://smba.trafficmanager.net/amer/") is False

    def test_unknown_host_rejected(self, state_dir):
        ch = _make_channel()
        assert ch._is_trusted_service_url("https://evil.example.com/") is False

    def test_empty_rejected(self, state_dir):
        ch = _make_channel()
        assert ch._is_trusted_service_url("") is False


class TestSanitizeInboundText:
    def test_plain_text_passthrough(self, state_dir):
        ch = _make_channel()
        assert ch._sanitize_inbound_text(_activity(text="Hello there")) == "Hello there"

    def test_strips_bot_mention_markup(self, state_dir):
        ch = _make_channel()
        out = ch._sanitize_inbound_text(_activity(text="<at>DeepTutor</at> explain entropy"))
        assert out == "explain entropy"

    def test_normalizes_html_entities(self, state_dir):
        ch = _make_channel()
        out = ch._sanitize_inbound_text(_activity(text="a&nbsp;&amp;&nbsp;b"))
        assert out == "a & b"

    def test_reply_wrapper_normalized(self, state_dir):
        ch = _make_channel()
        out = ch._sanitize_inbound_text(
            _activity(text="Replying to Bob Smith\nwhat about question 2?")
        )
        assert out == "User is replying to: Bob Smith\nUser reply: what about question 2?"

    def test_reply_to_id_triggers_quote_normalization(self, state_dir):
        ch = _make_channel()
        out = ch._sanitize_inbound_text(
            _activity(text="Replying to Alice:\nfollow-up", replyToId="act-0")
        )
        assert out.startswith("User is replying to: Alice")
        assert "User reply: follow-up" in out

    def test_empty_text_returns_empty(self, state_dir):
        ch = _make_channel()
        assert ch._sanitize_inbound_text(_activity(text="")) == ""


class TestHandleActivity:
    @pytest.mark.asyncio
    async def test_personal_message_dispatched(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity())

        ch.bus.publish_inbound.assert_awaited_once()
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.channel == "msteams"
        assert msg.sender_id == "aad-user-1"
        assert msg.chat_id == "a:conv-1"
        assert msg.content == "Hello bot"
        assert msg.metadata["msteams"]["conversation_type"] == "personal"
        assert msg.metadata["msteams"]["activity_id"] == "act-1"
        assert msg.metadata["msteams"]["from_name"] == "Test User"

    @pytest.mark.asyncio
    async def test_sender_id_falls_back_to_from_id(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity(**{"from": {"id": "29:user"}}))
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.sender_id == "29:user"

    @pytest.mark.asyncio
    async def test_non_message_type_ignored(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity(type="conversationUpdate"))
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_untrusted_service_url_ignored(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity(serviceUrl="https://evil.example.com/"))
        ch.bus.publish_inbound.assert_not_awaited()
        assert ch._conversation_refs == {}

    @pytest.mark.asyncio
    async def test_own_echo_ignored(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(
            _activity(**{"from": {"id": "28:bot"}, "recipient": {"id": "28:bot"}})
        )
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_personal_conversation_ignored(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(
            _activity(conversation={"id": "19:thread", "conversationType": "groupChat"})
        )
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_sender_ignored(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity(**{"from": {}}))
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_denied_sender_not_dispatched_and_no_ref_stored(self, state_dir):
        ch = _make_channel(allow_from=[])
        await ch._handle_activity(_activity())
        ch.bus.publish_inbound.assert_not_awaited()
        assert ch._conversation_refs == {}
        assert not (state_dir / MSTEAMS_REF_FILENAME).exists()

    @pytest.mark.asyncio
    async def test_mention_only_text_uses_fallback_response(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity(text="<at>DeepTutor</at>"))
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.content == ch.config.mention_only_response


class TestConversationRefs:
    @pytest.mark.asyncio
    async def test_ref_stored_and_persisted(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity())

        ref = ch._conversation_refs["a:conv-1"]
        assert ref.service_url == "https://smba.trafficmanager.net/amer/"
        assert ref.activity_id == "act-1"
        assert ref.bot_id == "28:bot"
        assert ref.tenant_id == "tenant-1"
        assert ref.conversation_type == "personal"

        refs_on_disk = json.loads((state_dir / MSTEAMS_REF_FILENAME).read_text())
        assert "a:conv-1" in refs_on_disk
        assert refs_on_disk["a:conv-1"]["conversation_id"] == "a:conv-1"

        meta_on_disk = json.loads((state_dir / MSTEAMS_REF_META_FILENAME).read_text())
        assert meta_on_disk["a:conv-1"]["updated_at"] is not None

    @pytest.mark.asyncio
    async def test_refs_reload_on_new_instance(self, state_dir):
        ch1 = _make_channel()
        await ch1._handle_activity(_activity())

        ch2 = _make_channel()
        assert "a:conv-1" in ch2._conversation_refs
        assert ch2._conversation_refs["a:conv-1"].service_url == (
            "https://smba.trafficmanager.net/amer/"
        )

    @pytest.mark.asyncio
    async def test_stale_ref_pruned_by_ttl_on_load(self, state_dir):
        ch1 = _make_channel()
        await ch1._handle_activity(_activity())

        stale_ts = time.time() - 31 * 24 * 60 * 60
        (state_dir / MSTEAMS_REF_META_FILENAME).write_text(
            json.dumps({"a:conv-1": {"updated_at": stale_ts}})
        )

        ch2 = _make_channel(ref_ttl_days=30)
        assert "a:conv-1" not in ch2._conversation_refs
        refs_on_disk = json.loads((state_dir / MSTEAMS_REF_FILENAME).read_text())
        assert refs_on_disk == {}

    @pytest.mark.asyncio
    async def test_fresh_ref_survives_ttl_on_load(self, state_dir):
        ch1 = _make_channel()
        await ch1._handle_activity(_activity())

        ch2 = _make_channel(ref_ttl_days=30)
        assert "a:conv-1" in ch2._conversation_refs

    def test_prune_drops_webchat_refs(self, state_dir):
        ch = _make_channel()
        ch._conversation_refs["wc"] = ConversationRef(
            service_url="https://webchat.botframework.com/",
            conversation_id="wc",
            conversation_type="personal",
            updated_at=time.time(),
        )
        assert ch._prune_conversation_refs() is True
        assert "wc" not in ch._conversation_refs

    def test_prune_drops_non_personal_refs(self, state_dir):
        ch = _make_channel()
        ch._conversation_refs["grp"] = ConversationRef(
            service_url="https://smba.trafficmanager.net/amer/",
            conversation_id="grp",
            conversation_type="groupChat",
            updated_at=time.time(),
        )
        assert ch._prune_conversation_refs() is True
        assert "grp" not in ch._conversation_refs

    def test_prune_drops_untrusted_refs(self, state_dir):
        ch = _make_channel()
        ch._conversation_refs["bad"] = ConversationRef(
            service_url="https://evil.example.com/",
            conversation_id="bad",
            conversation_type="personal",
            updated_at=time.time(),
        )
        assert ch._prune_conversation_refs() is True
        assert "bad" not in ch._conversation_refs

    def test_prune_keeps_valid_refs(self, state_dir):
        ch = _make_channel()
        ch._conversation_refs["ok"] = ConversationRef(
            service_url="https://smba.trafficmanager.net/amer/",
            conversation_id="ok",
            conversation_type="personal",
            updated_at=time.time(),
        )
        assert ch._prune_conversation_refs() is False
        assert "ok" in ch._conversation_refs

    def test_touch_updates_recent_timestamp_only_after_interval(self, state_dir):
        ch = _make_channel(ref_touch_interval_s=300)
        old_ts = time.time() - 10  # within the 300s interval
        ch._conversation_refs["c"] = ConversationRef(
            service_url="https://smba.trafficmanager.net/amer/",
            conversation_id="c",
            conversation_type="personal",
            updated_at=old_ts,
        )
        ch._touch_conversation_ref("c")
        assert ch._conversation_refs["c"].updated_at == old_ts

        ch._conversation_refs["c"].updated_at = time.time() - 600  # past interval
        ch._touch_conversation_ref("c")
        assert ch._conversation_refs["c"].updated_at > time.time() - 5


class TestSend:
    @pytest.mark.asyncio
    async def test_send_without_http_client_raises(self, state_dir):
        ch = _make_channel()
        msg = OutboundMessage(channel="msteams", chat_id="a:conv-1", content="hi")
        with pytest.raises(RuntimeError, match="not initialized"):
            await ch.send(msg)

    @pytest.mark.asyncio
    async def test_send_without_ref_raises(self, state_dir):
        ch = _make_channel()
        ch._http = AsyncMock()
        msg = OutboundMessage(channel="msteams", chat_id="a:unknown", content="hi")
        with pytest.raises(RuntimeError, match="ref not found"):
            await ch.send(msg)

    @pytest.mark.asyncio
    async def test_send_untrusted_ref_raises(self, state_dir):
        ch = _make_channel()
        ch._http = AsyncMock()
        ch._conversation_refs["a:conv-1"] = ConversationRef(
            service_url="https://evil.example.com/",
            conversation_id="a:conv-1",
        )
        msg = OutboundMessage(channel="msteams", chat_id="a:conv-1", content="hi")
        with pytest.raises(RuntimeError, match="untrusted service_url"):
            await ch.send(msg)

    @pytest.mark.asyncio
    async def test_send_posts_to_activities_endpoint(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity())

        ch._http = AsyncMock()
        ch._token = "cached-token"
        ch._token_expires_at = time.time() + 3600
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        ch._http.post.return_value = resp

        msg = OutboundMessage(channel="msteams", chat_id="a:conv-1", content="Answer")
        await ch.send(msg)

        ch._http.post.assert_awaited_once()
        call = ch._http.post.call_args
        assert call.args[0] == (
            "https://smba.trafficmanager.net/amer/v3/conversations/a:conv-1/activities"
        )
        assert call.kwargs["headers"]["Authorization"] == "Bearer cached-token"
        assert call.kwargs["json"]["text"] == "Answer"
        assert call.kwargs["json"]["replyToId"] == "act-1"  # reply_in_thread default

    @pytest.mark.asyncio
    async def test_send_failure_raises_for_manager_retry(self, state_dir):
        ch = _make_channel()
        await ch._handle_activity(_activity())

        ch._http = AsyncMock()
        ch._token = "cached-token"
        ch._token_expires_at = time.time() + 3600
        ch._http.post.side_effect = RuntimeError("boom")

        msg = OutboundMessage(channel="msteams", chat_id="a:conv-1", content="Answer")
        with pytest.raises(RuntimeError, match="boom"):
            await ch.send(msg)


class TestSupportsStreaming:
    def test_streaming_not_supported(self, state_dir):
        # msteams does not implement send_delta; supports_streaming must be False.
        ch = _make_channel()
        assert ch.supports_streaming is False
        assert type(ch).send_delta is msteams_mod.BaseChannel.send_delta


class TestValidateInboundAuth:
    @pytest.mark.asyncio
    async def test_missing_deps_raises_clear_error(self, state_dir, monkeypatch):
        ch = _make_channel()
        monkeypatch.setattr(msteams_mod, "MSTEAMS_AVAILABLE", False)
        with pytest.raises(RuntimeError, match=r"PyJWT\[crypto\]"):
            await ch._validate_inbound_auth("Bearer abc", _activity())

    @pytest.mark.asyncio
    async def test_missing_bearer_rejected(self, state_dir):
        ch = _make_channel()
        with pytest.raises(ValueError, match="missing bearer token"):
            await ch._validate_inbound_auth("", _activity())

    @pytest.mark.asyncio
    async def test_empty_bearer_rejected(self, state_dir):
        ch = _make_channel()
        with pytest.raises(ValueError, match="empty bearer token"):
            await ch._validate_inbound_auth("Bearer   ", _activity())


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self, state_dir):
        ch = _make_channel()
        ch._running = True
        await ch.stop()
        assert ch._running is False
        assert ch._server is None
        assert ch._http is None
