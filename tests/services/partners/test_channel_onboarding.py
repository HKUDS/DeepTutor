"""Protocol and configuration tests for partner channel QR onboarding."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from deeptutor.services.partners.channel_onboarding import (
    ChannelOnboardingError,
    ChannelOnboardingManager,
)
from deeptutor.services.partners.manager import PartnerConfig


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _client_factory(handler: Any) -> Any:
    transport = httpx.MockTransport(handler)
    return lambda: httpx.AsyncClient(transport=transport)


def _manager(handler: Any, clock: FakeClock) -> ChannelOnboardingManager:
    return ChannelOnboardingManager(client_factory=_client_factory(handler), now=clock)


def _partner_manager(channels: dict[str, Any] | None = None) -> Any:
    class Manager:
        def __init__(self) -> None:
            self.saved: dict[str, Any] = {}

        def get_partner(self, partner_id: str) -> None:
            return None

        def load_config(self, partner_id: str) -> PartnerConfig:
            return PartnerConfig(name="Ada", channels=channels or {})

        def save_config(self, partner_id: str, config: PartnerConfig) -> None:
            self.saved[partner_id] = config

    return Manager()


def _ready_wecom_manager() -> tuple[ChannelOnboardingManager, Any]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ai/qc/generate":
            return httpx.Response(200, json={"data": {"scode": "s", "auth_url": "https://auth"}})
        return httpx.Response(
            200,
            json={
                "data": {
                    "status": "success",
                    "bot_info": {"botid": "bot-id", "secret": "bot-secret"},
                }
            },
        )

    class RunningPartnerManager:
        def __init__(self) -> None:
            self.config = PartnerConfig(name="Ada", channels={"wecom": {"enabled": False}})
            self.instance = SimpleNamespace(config=self.config)
            self.reload_calls = 0
            self.fail_reload = True

        def get_partner(self, partner_id: str) -> Any:
            return self.instance

        def load_config(self, partner_id: str) -> PartnerConfig:
            return self.config

        def save_config(self, partner_id: str, config: PartnerConfig) -> None:
            self.config = config
            self.instance.config = config

        async def reload_channels(self, partner_id: str) -> None:
            self.reload_calls += 1
            if self.fail_reload:
                raise RuntimeError("channel reload failed")

    manager = ChannelOnboardingManager(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        now=FakeClock(),
    )
    return manager, RunningPartnerManager()


def test_feishu_flow_switches_to_lark_and_applies_masked_config() -> None:
    requests: list[tuple[str, str, dict[str, list[str]]]] = []
    polls = [
        {"error": "authorization_pending"},
        {"user_info": {"tenant_brand": "lark"}},
        {
            "client_id": "cli_app",
            "client_secret": "app_secret",
            "user_info": {
                "open_id": "ou_scanner",
                "tenant_brand": "lark",
            },
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        requests.append((str(request.url), form["action"], form))
        if form["action"] == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        if form["action"] == "begin":
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code",
                    "verification_uri_complete": "https://accounts.feishu.cn/scan",
                    "interval": 1,
                    "expire_in": 60,
                },
            )
        return httpx.Response(400, json=polls.pop(0))

    async def run() -> None:
        clock = FakeClock()
        manager = _manager(handler, clock)
        started = await manager.start("ada", "feishu")
        assert started["status"] == "pending_scan"
        assert started["qr_payload"] == "https://accounts.feishu.cn/scan"
        assert "device-code" not in str(started)

        first = await manager.status("ada", started["session_id"])
        assert first["status"] == "pending_scan"

        switched = await manager.status("ada", started["session_id"])
        assert switched["status"] == "pending_scan"

        ready = await manager.status("ada", started["session_id"])
        assert ready["status"] == "ready"
        assert "app_secret" not in str(ready)
        assert requests[-1][0].startswith("https://accounts.larksuite.com/")

        partners = _partner_manager(
            {
                "feishu": {
                    "enabled": False,
                    "allow_from": ["ou_existing"],
                    "react_emoji": "HEART",
                },
                "wecom": {"enabled": False},
            }
        )
        applied = await manager.apply("ada", started["session_id"], partners)
        saved = partners.saved["ada"]
        assert saved.channels["feishu"] == {
            "enabled": True,
            "app_id": "cli_app",
            "app_secret": "app_secret",
            "domain": "lark",
            "allow_from": ["ou_existing", "ou_scanner"],
            "react_emoji": "HEART",
        }
        assert applied["channels"]["feishu"]["app_secret"] == "***"
        assert saved.channels["wecom"] == {"enabled": False}

        with pytest.raises(ChannelOnboardingError):
            await manager.apply("ada", started["session_id"], partners)

    import asyncio

    asyncio.run(run())


def test_feishu_denied_and_missing_identity_are_terminal() -> None:
    polls = [
        {"error": "access_denied"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        if form["action"] == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        if form["action"] == "begin":
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code",
                    "verification_uri_complete": "https://accounts.feishu.cn/scan",
                    "interval": 1,
                    "expire_in": 60,
                },
            )
        return httpx.Response(400, json=polls.pop(0))

    async def run_denied() -> None:
        manager = _manager(handler, FakeClock())
        started = await manager.start("ada", "feishu")
        denied = await manager.status("ada", started["session_id"])
        assert denied["status"] == "denied"
        assert denied["error_code"] == "access_denied"

    import asyncio

    asyncio.run(run_denied())


def test_feishu_transport_errors_retry_and_protocol_errors_fail() -> None:
    def start_and_poll(handler: Any) -> Any:
        async def run() -> Any:
            manager = _manager(handler, FakeClock())
            started = await manager.start("ada", "feishu")
            return started, await manager.status("ada", started["session_id"])

        return asyncio.run(run())

    def transport_handler(request: httpx.Request) -> httpx.Response:
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        if form["action"] == "poll":
            raise httpx.ConnectError("offline")
        if form["action"] == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        return httpx.Response(
            200,
            json={
                "device_code": "device-code",
                "verification_uri_complete": "https://accounts.feishu.cn/scan",
                "interval": 1,
                "expire_in": 60,
            },
        )

    def invalid_handler(request: httpx.Request) -> httpx.Response:
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        if form["action"] == "poll":
            return httpx.Response(200, content=b"not-json")
        if form["action"] == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        return httpx.Response(
            200,
            json={
                "device_code": "device-code",
                "verification_uri_complete": "https://accounts.feishu.cn/scan",
                "interval": 1,
                "expire_in": 60,
            },
        )

    _, pending = start_and_poll(transport_handler)
    assert pending["status"] == "pending_scan"
    _, failed = start_and_poll(invalid_handler)
    assert failed["status"] == "failed"
    assert failed["error_code"] == "invalid_response"


def test_feishu_session_expires_when_not_authorized() -> None:
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        if form["action"] == "init":
            return httpx.Response(200, json={"supported_auth_methods": ["client_secret"]})
        if form["action"] == "begin":
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code",
                    "verification_uri_complete": "https://accounts.feishu.cn/scan",
                    "interval": 1,
                    "expire_in": 60,
                },
            )
        return httpx.Response(400, json={"error": "authorization_pending"})

    async def run() -> None:
        manager = _manager(handler, clock)
        started = await manager.start("ada", "feishu")
        clock.now += 61
        expired = await manager.status("ada", started["session_id"])
        assert expired["status"] == "expired"

    asyncio.run(run())


def test_wecom_flow_preserves_existing_allowlist_and_masks_secret() -> None:
    polls = [{"data": {"status": "pending"}}, {"data": {"status": "success"}}]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != "work.weixin.qq.com":
            raise AssertionError(request.url)
        if request.url.path == "/ai/qc/generate":
            assert request.url.params["source"] == "hermes"
            return httpx.Response(
                200,
                json={"data": {"scode": " s code ", "auth_url": "https://auth"}},
            )
        assert request.url.params["scode"] == " s code "
        poll = polls.pop(0)
        if poll["data"]["status"] == "success":
            poll["data"]["bot_info"] = {"botid": "bot-id", "secret": "bot-secret"}
        return httpx.Response(200, json=poll)

    async def run() -> None:
        manager = _manager(handler, FakeClock())
        started = await manager.start("ada", "wecom")
        assert started["fallback_url"].endswith("%20s%20code%20")
        assert await manager.status("ada", started["session_id"])
        ready = await manager.status("ada", started["session_id"])
        assert ready["status"] == "ready"

        partners = _partner_manager(
            {"wecom": {"enabled": False, "allow_from": ["user-a"], "welcome_message": "hi"}}
        )
        applied = await manager.apply("ada", started["session_id"], partners)
        saved = partners.saved["ada"]
        assert saved.channels["wecom"] == {
            "enabled": True,
            "bot_id": "bot-id",
            "secret": "bot-secret",
            "allow_from": ["user-a"],
            "welcome_message": "hi",
        }
        assert applied["channels"]["wecom"]["secret"] == "***"

    import asyncio

    asyncio.run(run())


def test_wecom_success_without_credentials_fails_and_session_expires() -> None:
    polls = [
        {"data": {"status": "success", "bot_info": {}}},
    ]
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ai/qc/generate":
            return httpx.Response(200, json={"data": {"scode": "s", "auth_url": "https://auth"}})
        return httpx.Response(200, json=polls.pop(0))

    async def run() -> None:
        manager = _manager(handler, clock)
        started = await manager.start("ada", "wecom")
        failed = await manager.status("ada", started["session_id"])
        assert failed["status"] == "failed"
        assert failed["error_code"] == "missing_credentials"

        started = await manager.start("ada", "wecom")
        clock.now += 301
        expired = await manager.status("ada", started["session_id"])
        assert expired["status"] == "expired"

    import asyncio

    asyncio.run(run())


def test_wecom_protocol_and_http_poll_errors_are_terminal() -> None:
    def start_and_poll(handler: Any) -> Any:
        async def run() -> Any:
            manager = _manager(handler, FakeClock())
            started = await manager.start("ada", "wecom")
            return started, await manager.status("ada", started["session_id"])

        return asyncio.run(run())

    def generate(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"scode": "s", "auth_url": "https://auth"}})

    def invalid_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ai/qc/generate":
            return generate(request)
        return httpx.Response(200, json={"data": {}})

    def http_error_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ai/qc/generate":
            return generate(request)
        return httpx.Response(500, json={"error": "provider failed"})

    _, invalid = start_and_poll(invalid_handler)
    assert invalid["status"] == "failed"
    assert invalid["error_code"] == "invalid_response"

    _, http_error = start_and_poll(http_error_handler)
    assert http_error["status"] == "failed"
    assert http_error["error_code"] == "provider_http_error"


def test_start_reuses_active_session_and_cancel_is_terminal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ai/qc/generate":
            return httpx.Response(200, json={"data": {"scode": "s", "auth_url": "https://auth"}})
        raise AssertionError(request.url)

    async def run() -> None:
        manager = _manager(handler, FakeClock())
        first = await manager.start("ada", "wecom")
        second = await manager.start("ada", "wecom")
        assert first["session_id"] == second["session_id"]

        cancelled = await manager.cancel("ada", first["session_id"])
        assert cancelled["status"] == "cancelled"
        assert (await manager.cancel("ada", first["session_id"]))["status"] == "cancelled"

    import asyncio

    asyncio.run(run())


def test_qr_data_url_falls_back_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from deeptutor.services.partners import channel_onboarding

    monkeypatch.setitem(sys.modules, "qrcode", None)
    assert channel_onboarding._qr_data_url("https://example") is None


def test_qr_data_url_uses_png_when_dependency_is_available() -> None:
    pytest.importorskip("qrcode")
    from deeptutor.services.partners.channel_onboarding import _qr_data_url

    assert _qr_data_url("https://example").startswith("data:image/png;base64,")


def test_apply_keeps_session_ready_when_channel_reload_fails() -> None:
    async def run() -> None:
        manager, partners = _ready_wecom_manager()
        started = await manager.start("ada", "wecom")
        assert (await manager.status("ada", started["session_id"]))["status"] == "ready"

        with pytest.raises(RuntimeError, match="channel reload failed"):
            await manager.apply("ada", started["session_id"], partners)
        assert partners.reload_calls == 1
        assert manager._sessions[started["session_id"]].status == "ready"

        partners.fail_reload = False
        applied = await manager.apply("ada", started["session_id"], partners)
        assert applied["session"]["status"] == "applied"
        assert partners.reload_calls == 2
        assert partners.config.channels["wecom"]["allow_from"] == ["*"]

    asyncio.run(run())
