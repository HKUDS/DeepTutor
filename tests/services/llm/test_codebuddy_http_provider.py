"""Tests for the SDK-free CodeBuddy HTTP provider."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

import pytest

from deeptutor.services.codebuddy_credentials import (
    INTERNAL_ENDPOINT,
    CodeBuddyAuthUnavailable,
)
from deeptutor.services.llm.provider_core import codebuddy_http_provider as http_module
from deeptutor.services.llm.provider_core.base import LLMResponse
from deeptutor.services.llm.provider_core.codebuddy_http_provider import (
    CodeBuddyHTTPProvider,
    build_codebuddy_provider,
    codebuddy_http_available,
)


def _sign_in(tmp_path: Path, monkeypatch, *, expires_in: float = 86400.0) -> Path:
    path = tmp_path / "Tencent-Cloud.coding-copilot.info"
    path.write_text(
        json.dumps(
            {
                "account": {"uid": "uid-1", "nickname": "tester"},
                "auth": {
                    "accessToken": "access-token",
                    "refreshToken": "refresh-token",
                    "expiresAt": int((time.time() + expires_in) * 1000),
                    "refreshExpiresAt": int((time.time() + 7776000) * 1000),
                    "domain": "www.codebuddy.cn",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPTUTOR_CODEBUDDY_AUTH_FILE", str(path))
    return path


def _capture_stream(monkeypatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def fake_chat_stream(self, **kwargs):
        captured.update(kwargs)
        captured["api_key"] = self._client.api_key
        captured["base_url"] = str(self._client.base_url).rstrip("/")
        return LLMResponse(content="OK")

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.openai_compat_provider."
        "OpenAICompatProvider.chat_stream",
        fake_chat_stream,
    )
    return captured


@pytest.mark.asyncio
async def test_provider_uses_local_session_and_regional_endpoint(tmp_path, monkeypatch) -> None:
    _sign_in(tmp_path, monkeypatch)
    captured = _capture_stream(monkeypatch)

    provider = CodeBuddyHTTPProvider()
    response = await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "OK"
    assert captured["api_key"] == "access-token"
    assert captured["base_url"] == INTERNAL_ENDPOINT + "/v2"
    assert provider.extra_headers["X-User-Id"] == "uid-1"


@pytest.mark.asyncio
async def test_blocking_chat_streams_because_cloud_rejects_non_stream(
    tmp_path, monkeypatch
) -> None:
    _sign_in(tmp_path, monkeypatch)
    captured = _capture_stream(monkeypatch)

    async def fail_chat(self, **kwargs):
        raise AssertionError("CodeBuddy rejects stream: false")

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.openai_compat_provider.OpenAICompatProvider.chat",
        fail_chat,
    )

    response = await CodeBuddyHTTPProvider().chat(messages=[{"role": "user", "content": "hi"}])

    assert response.content == "OK"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_expired_session_is_refreshed_before_the_request(tmp_path, monkeypatch) -> None:
    _sign_in(tmp_path, monkeypatch, expires_in=-60.0)
    captured = _capture_stream(monkeypatch)

    async def fake_refresh(credentials):
        from dataclasses import replace

        return replace(credentials, access_token="fresh-token", expires_at=time.time() + 3600)

    monkeypatch.setattr(http_module, "refresh_credentials", fake_refresh)

    await CodeBuddyHTTPProvider().chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert captured["api_key"] == "fresh-token"


@pytest.mark.asyncio
async def test_signed_out_provider_reports_how_to_sign_in() -> None:
    provider = CodeBuddyHTTPProvider()

    with pytest.raises(CodeBuddyAuthUnavailable, match="not signed in"):
        await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_api_key_mode_sends_the_key_header(monkeypatch) -> None:
    captured = _capture_stream(monkeypatch)

    provider = CodeBuddyHTTPProvider(api_key="cb-key")
    await provider.chat_stream(messages=[{"role": "user", "content": "hi"}])

    assert provider.extra_headers["X-API-Key"] == "cb-key"
    assert captured["api_key"] == "cb-key"


@pytest.mark.asyncio
async def test_provider_strips_deeptutor_session_id(tmp_path, monkeypatch) -> None:
    _sign_in(tmp_path, monkeypatch)
    captured = _capture_stream(monkeypatch)

    await CodeBuddyHTTPProvider().chat_stream(
        messages=[{"role": "user", "content": "hi"}],
        deeptutor_session_id="session-1",
    )

    assert "deeptutor_session_id" not in captured


def test_placeholder_api_key_is_not_treated_as_auth() -> None:
    assert codebuddy_http_available("sk-no-key-required") is False


def test_dispatch_prefers_http_when_signed_in(tmp_path, monkeypatch) -> None:
    _sign_in(tmp_path, monkeypatch)
    monkeypatch.setattr(http_module, "sdk_installed", lambda: True)

    assert isinstance(build_codebuddy_provider(), CodeBuddyHTTPProvider)


def test_dispatch_falls_back_to_http_when_sdk_is_absent(monkeypatch) -> None:
    monkeypatch.setattr(http_module, "sdk_installed", lambda: False)

    assert isinstance(build_codebuddy_provider(), CodeBuddyHTTPProvider)
