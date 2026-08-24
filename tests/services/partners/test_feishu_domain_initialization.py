"""Feishu/Lark SDK initialization contract tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.partners.channels import feishu as feishu_mod
from deeptutor.partners.channels.feishu import FeishuChannel


class _Chain:
    def __init__(self, calls: list[tuple[str, Any]], result: Any) -> None:
        self.calls = calls
        self.result = result

    def __getattr__(self, name: str) -> Any:
        def method(value: Any = None) -> "_Chain":
            self.calls.append((name, value))
            return self

        return method

    def build(self) -> Any:
        self.calls.append(("build", None))
        return self.result


@pytest.mark.asyncio
async def test_feishu_channel_selects_domain_for_rest_and_websocket_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rest_calls: list[tuple[str, Any]] = []
    event_calls: list[tuple[str, Any]] = []
    ws_clients: list[dict[str, Any]] = []

    class Client:
        @staticmethod
        def builder() -> _Chain:
            return _Chain(rest_calls, object())

    class EventDispatcherHandler:
        @staticmethod
        def builder(*args: Any) -> _Chain:
            return _Chain(event_calls, object())

    class WSClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            ws_clients.append({"args": args, "kwargs": kwargs})

    lark = SimpleNamespace(
        Client=Client,
        EventDispatcherHandler=EventDispatcherHandler,
        LogLevel=SimpleNamespace(INFO="INFO"),
        ws=SimpleNamespace(Client=WSClient),
    )
    const = SimpleNamespace(FEISHU_DOMAIN="FEISHU_DOMAIN", LARK_DOMAIN="LARK_DOMAIN")

    monkeypatch.setitem(__import__("sys").modules, "lark_oapi", lark)
    monkeypatch.setitem(__import__("sys").modules, "lark_oapi.ws", lark.ws)
    monkeypatch.setitem(__import__("sys").modules, "lark_oapi.core", SimpleNamespace())
    monkeypatch.setitem(__import__("sys").modules, "lark_oapi.core.const", const)
    monkeypatch.setattr(feishu_mod, "FEISHU_AVAILABLE", True)
    monkeypatch.setattr(
        feishu_mod,
        "threading",
        SimpleNamespace(Thread=lambda *args, **kwargs: SimpleNamespace(start=lambda: None)),
    )

    async def exercise(domain: str) -> None:
        rest_calls.clear()
        ws_clients.clear()
        channel = FeishuChannel(
            {
                "enabled": True,
                "app_id": "app-id",
                "app_secret": "app-secret",
                "domain": domain,
            },
            object(),
        )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(channel.start(), timeout=0.05)

    await exercise("lark")
    assert ("domain", "LARK_DOMAIN") in rest_calls
    assert ws_clients[0]["kwargs"]["domain"] == "LARK_DOMAIN"
    assert ws_clients[0]["kwargs"]["extra_ua_tags"] == ["channel"]

    await exercise("feishu")
    assert ("domain", "FEISHU_DOMAIN") in rest_calls
    assert ws_clients[0]["kwargs"]["domain"] == "FEISHU_DOMAIN"
    assert ws_clients[0]["kwargs"]["extra_ua_tags"] == ["channel"]
