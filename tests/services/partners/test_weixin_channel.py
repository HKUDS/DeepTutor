"""Unit tests for the Weixin / personal WeChat partner channel."""

from __future__ import annotations

import base64
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.api.routers._partners_channel_schema import all_channel_schemas
from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels import weixin as weixin_mod
from deeptutor.partners.channels.registry import discover_all, discover_channel_names
from deeptutor.partners.channels.weixin import (
    CONTEXT_TOKEN_MAX_AGE_S,
    ITEM_IMAGE,
    ITEM_TEXT,
    MESSAGE_TYPE_BOT,
    WeixinChannel,
    WeixinConfig,
    _parse_aes_key,
    _pkcs7_unpad_safe,
)
from deeptutor.partners.config import paths as partner_paths
from deeptutor.partners.helpers import ensure_dir


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Redirect default Weixin runtime state to a temp directory."""

    monkeypatch.setattr(
        partner_paths, "get_runtime_subdir", lambda name: ensure_dir(tmp_path / name)
    )
    return tmp_path / "weixin"


def _make_channel(**overrides) -> WeixinChannel:
    defaults = {
        "enabled": True,
        "allow_from": ["*"],
        "token": "token-123",
    }
    defaults.update(overrides)
    config = WeixinConfig.model_validate(defaults)
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return WeixinChannel(config, bus)


def _text_msg(**overrides) -> dict:
    base = {
        "message_id": "m-1",
        "from_user_id": "wx-user-1",
        "context_token": "ctx-1",
        "item_list": [
            {"type": ITEM_TEXT, "text_item": {"text": "hello from wechat"}},
        ],
    }
    base.update(overrides)
    return base


class TestWeixinConfig:
    def test_default_values(self):
        cfg = WeixinConfig()
        assert cfg.enabled is False
        assert cfg.allow_from == []
        assert cfg.base_url == "https://ilinkai.weixin.qq.com"
        assert cfg.cdn_base_url == "https://novac2c.cdn.weixin.qq.com/c2c"
        assert cfg.route_tag is None
        assert cfg.token == ""
        assert cfg.state_dir == ""
        assert cfg.poll_timeout == weixin_mod.DEFAULT_LONG_POLL_TIMEOUT_S
        assert cfg.send_progress is True
        assert cfg.send_tool_hints is True

    def test_camel_case_alias(self):
        cfg = WeixinConfig(
            base_url="https://base.example",
            cdn_base_url="https://cdn.example",
            route_tag="r1",
        )
        dumped = cfg.model_dump(by_alias=True)
        assert dumped["baseUrl"] == "https://base.example"
        assert dumped["cdnBaseUrl"] == "https://cdn.example"
        assert dumped["routeTag"] == "r1"
        assert "sendProgress" in dumped
        assert "sendToolHints" in dumped

    def test_from_camel_case_dict(self):
        cfg = WeixinConfig.model_validate(
            {
                "enabled": True,
                "allowFrom": ["wx-user-1"],
                "baseUrl": "https://base.example",
                "cdnBaseUrl": "https://cdn.example",
                "routeTag": 7,
                "pollTimeout": 10,
                "sendProgress": False,
            }
        )
        assert cfg.allow_from == ["wx-user-1"]
        assert cfg.base_url == "https://base.example"
        assert cfg.cdn_base_url == "https://cdn.example"
        assert cfg.route_tag == 7
        assert cfg.poll_timeout == 10
        assert cfg.send_progress is False


class TestDefaultAndDiscovery:
    def test_default_config_returns_alias_dict(self):
        cfg = WeixinChannel.default_config()
        assert cfg["enabled"] is False
        assert "baseUrl" in cfg
        assert "cdnBaseUrl" in cfg
        assert "pollTimeout" in cfg
        assert "sendProgress" in cfg

    def test_registry_discovers_weixin(self, state_dir):
        assert "weixin" in discover_channel_names()
        assert discover_all()["weixin"] is WeixinChannel

    def test_qr_helper_module_is_not_offered_as_a_channel(self, state_dir):
        """``weixin_qr`` holds the login protocol, not a channel."""
        assert "weixin_qr" in discover_channel_names()
        assert "weixin_qr" not in discover_all()
        assert "weixin_qr" not in all_channel_schemas()

    def test_schema_exposes_weixin_and_delivery_fields(self, state_dir):
        payload = all_channel_schemas()["weixin"]
        assert payload["display_name"] == "WeChat"
        props = payload["json_schema"]["properties"]
        assert "send_progress" in props
        assert "send_tool_hints" in props
        assert "base_url" in props


class TestStateAndHeaders:
    def test_save_and_load_state(self, state_dir):
        ch = _make_channel(token="", state_dir=str(state_dir))
        ch._token = "saved-token"
        ch._get_updates_buf = "cursor"
        ch._context_tokens = {"wx-user-1": "ctx"}
        ch._typing_tickets = {"wx-user-1": {"ticket": "typing"}}
        ch._save_state()

        loaded = _make_channel(token="", state_dir=str(state_dir))
        assert loaded._load_state() is True
        assert loaded._token == "saved-token"
        assert loaded._get_updates_buf == "cursor"
        assert loaded._context_tokens == {"wx-user-1": "ctx"}
        assert loaded._typing_tickets["wx-user-1"]["ticket"] == "typing"

    def test_state_is_isolated_per_partner(self, tmp_path, monkeypatch):
        """Two Partners on WeChat must not share one bot identity."""
        monkeypatch.setattr(partner_paths, "_base_dir", lambda: ensure_dir(tmp_path / "partners"))

        alice = _make_channel(token="")
        alice.partner_id = "alice-tutor"
        bob = _make_channel(token="")
        bob.partner_id = "bob-tutor"

        assert alice._get_state_dir() != bob._get_state_dir()

        alice._token = "token-alice"
        alice._get_updates_buf = "cursor-alice"
        alice._save_state()

        # Bob has no identity of his own: he must NOT inherit Alice's.
        assert bob._load_state() is False
        assert bob._token == ""

        # And Bob logging in must not overwrite Alice's stored identity.
        bob._token = "token-bob"
        bob._get_updates_buf = "cursor-bob"
        bob._save_state()

        reloaded = _make_channel(token="")
        reloaded.partner_id = "alice-tutor"
        assert reloaded._load_state() is True
        assert reloaded._token == "token-alice"
        assert reloaded._get_updates_buf == "cursor-alice"

    def test_configured_token_wins_but_session_still_loads(self, state_dir):
        """Config owns identity; the file owns cursor and context tokens."""
        seeded = _make_channel(token="", state_dir=str(state_dir))
        seeded._token = "token-from-file"
        seeded._get_updates_buf = "cursor"
        seeded._context_tokens = {"wx-user-1": "ctx"}
        seeded._save_state()

        ch = _make_channel(token="token-from-config", state_dir=str(state_dir))
        ch._token = ch.config.token
        ch._load_state()

        assert ch._token == "token-from-config"
        assert ch._get_updates_buf == "cursor"
        assert ch._context_tokens == {"wx-user-1": "ctx"}

    def test_headers_include_auth_and_route_tag(self):
        ch = _make_channel(route_tag="r1")
        ch._token = "secret-token"
        headers = ch._make_headers()
        assert headers["Authorization"] == "Bearer secret-token"
        assert headers["AuthorizationType"] == "ilink_bot_token"
        assert headers["iLink-App-Id"] == "bot"
        assert headers["SKRouteTag"] == "r1"
        assert base64.b64decode(headers["X-WECHAT-UIN"]).decode().isdigit()


class TestInboundProcessing:
    @pytest.mark.asyncio
    async def test_text_message_published_to_bus(self, state_dir):
        ch = _make_channel(state_dir=str(state_dir))
        ch._start_typing = AsyncMock()

        await ch._process_message(_text_msg())

        ch.bus.publish_inbound.assert_awaited_once()
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.channel == "weixin"
        assert msg.sender_id == "wx-user-1"
        assert msg.chat_id == "wx-user-1"
        assert msg.content == "hello from wechat"
        assert msg.media == []
        assert msg.metadata["message_id"] == "m-1"
        assert ch._context_tokens["wx-user-1"] == "ctx-1"

    @pytest.mark.asyncio
    async def test_duplicate_message_is_ignored(self, state_dir):
        ch = _make_channel(state_dir=str(state_dir))
        ch._start_typing = AsyncMock()

        await ch._process_message(_text_msg())
        await ch._process_message(_text_msg())

        ch.bus.publish_inbound.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bot_message_is_ignored(self, state_dir):
        ch = _make_channel(state_dir=str(state_dir))
        await ch._process_message(_text_msg(message_type=MESSAGE_TYPE_BOT))
        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_allowlist_blocks_sender(self, state_dir):
        ch = _make_channel(state_dir=str(state_dir), allow_from=["someone-else"])
        ch._start_typing = AsyncMock()

        await ch._process_message(_text_msg())

        ch.bus.publish_inbound.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_image_download_path_is_attached(self, state_dir):
        ch = _make_channel(state_dir=str(state_dir))
        ch._start_typing = AsyncMock()
        ch._download_media_item = AsyncMock(return_value="/tmp/weixin-image.jpg")
        msg = _text_msg(
            item_list=[
                {
                    "type": ITEM_IMAGE,
                    "image_item": {
                        "media": {"full_url": "https://cdn.example/image.jpg"},
                    },
                }
            ]
        )

        await ch._process_message(msg)

        published = ch.bus.publish_inbound.call_args[0][0]
        assert "[Image: source: /tmp/weixin-image.jpg]" in published.content
        assert published.media == ["/tmp/weixin-image.jpg"]


class TestOutbound:
    @pytest.mark.asyncio
    async def test_send_requires_authenticated_client(self, state_dir):
        ch = _make_channel(state_dir=str(state_dir))
        with pytest.raises(RuntimeError, match="not initialized or not authenticated"):
            await ch.send(OutboundMessage(channel="weixin", chat_id="wx-user-1", content="hi"))

    @pytest.mark.asyncio
    async def test_send_text_posts_weixin_message(self, state_dir):
        ch = _make_channel(state_dir=str(state_dir))
        ch._client = object()  # only used for the non-None assertion
        ch._api_post = AsyncMock(return_value={"ret": 0, "errcode": 0})

        await ch._send_text("wx-user-1", "hello", "ctx-1")

        endpoint, body = ch._api_post.await_args.args
        assert endpoint == "ilink/bot/sendmessage"
        assert body["msg"]["to_user_id"] == "wx-user-1"
        assert body["msg"]["context_token"] == "ctx-1"
        assert body["msg"]["item_list"][0]["text_item"]["text"] == "hello"
        assert body["msg"]["client_id"].startswith("deeptutor-")

    @pytest.mark.asyncio
    async def test_send_text_raises_api_error(self, state_dir):
        ch = _make_channel(state_dir=str(state_dir))
        ch._client = object()
        ch._api_post = AsyncMock(return_value={"ret": 1, "errcode": 2, "errmsg": "boom"})

        with pytest.raises(RuntimeError, match="WeChat send text error"):
            await ch._send_text("wx-user-1", "hello", "ctx-1")

    @pytest.mark.asyncio
    async def test_tool_hints_are_buffered(self, state_dir):
        ch = _make_channel(state_dir=str(state_dir))
        ch._client = object()
        ch._token = "token"

        await ch.send(
            OutboundMessage(
                channel="weixin",
                chat_id="wx-user-1",
                content="rag(query)",
                metadata={"_progress": True, "_tool_hint": True},
            )
        )

        assert ch._pending_tool_hints == {"wx-user-1": ["rag(query)"]}

    @pytest.mark.asyncio
    async def test_tool_hints_respect_effective_flag(self, state_dir):
        ch = _make_channel(state_dir=str(state_dir))
        ch._client = object()
        ch._token = "token"
        ch.send_tool_hints = False

        await ch.send(
            OutboundMessage(
                channel="weixin",
                chat_id="wx-user-1",
                content="rag(query)",
                metadata={"_progress": True, "_tool_hint": True},
            )
        )

        assert ch._pending_tool_hints == {}

    @pytest.mark.asyncio
    async def test_final_message_flushes_buffered_hints_first(self, state_dir):
        ch = _make_channel(state_dir=str(state_dir))
        ch._client = object()
        ch._token = "token"
        ch._context_tokens["wx-user-1"] = "ctx-1"
        ch._context_token_at["wx-user-1"] = time.time()
        ch._pending_tool_hints["wx-user-1"] = ["hint-1", "hint-2"]
        ch._send_text = AsyncMock()
        ch._get_typing_ticket = AsyncMock(return_value="")
        ch._stop_typing = AsyncMock()

        await ch.send(OutboundMessage(channel="weixin", chat_id="wx-user-1", content="final"))

        assert [call.args[1] for call in ch._send_text.await_args_list] == [
            "hint-1\n\nhint-2",
            "final",
        ]
        assert ch._pending_tool_hints == {}

    @pytest.mark.asyncio
    async def test_stream_end_flushes_hints(self, state_dir):
        ch = _make_channel(state_dir=str(state_dir))
        ch._flush_tool_hints = AsyncMock()

        await ch.send_delta("wx-user-1", "", {"_stream_end": True})

        ch._flush_tool_hints.assert_awaited_once_with("wx-user-1")

    @pytest.mark.asyncio
    async def test_refresh_context_token_when_stale(self, state_dir):
        ch = _make_channel(state_dir=str(state_dir))
        ch._context_token_at["wx-user-1"] = time.time() - CONTEXT_TOKEN_MAX_AGE_S - 1
        ch._api_post = AsyncMock(return_value={"ret": 0, "context_token": "ctx-new"})

        out = await ch._refresh_context_token_if_stale("wx-user-1", "ctx-old")

        assert out == "ctx-new"
        assert ch._context_tokens["wx-user-1"] == "ctx-new"


class TestCryptoHelpers:
    def test_parse_raw_aes_key(self):
        raw = b"1234567890abcdef"
        assert _parse_aes_key(base64.b64encode(raw).decode()) == raw

    def test_parse_hex_encoded_aes_key(self):
        raw = b"1234567890abcdef"
        hex_b64 = base64.b64encode(raw.hex().encode()).decode()
        assert _parse_aes_key(hex_b64) == raw

    def test_pkcs7_unpad_safe(self):
        assert _pkcs7_unpad_safe(b"abc" + b"\x0d" * 13) == b"abc"
        assert _pkcs7_unpad_safe(b"abc") == b"abc"
