"""DISABLE_SSL_VERIFY coverage for the OpenAI Codex Responses provider.

The flag controls the initial request. A certificate verification failure must
never trigger an automatic retry with verification disabled.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from deeptutor.services.llm import openai_http_client
from deeptutor.services.llm.exceptions import LLMProviderTransportError
from deeptutor.services.llm.provider_core import openai_codex_provider


@pytest.fixture(autouse=True)
def _clean_ssl_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISABLE_SSL_VERIFY", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setattr(openai_http_client, "_warning_logged", False)


def _stub_token_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Token:
        access_token = "test-token"
        account_id = "test-account"
        generation = 1

    async def _fake_load_token(self: Any) -> _Token:
        return _Token()

    class _Service:
        @asynccontextmanager
        async def inference_guard(self):
            yield

        async def recover_after_unauthorized(self, generation: int) -> None:
            del generation

        def validate_runtime_profile(
            self,
            token: _Token,
            model_slug: str,
            reasoning_effort: str | None,
        ) -> None:
            del token, model_slug, reasoning_effort

    monkeypatch.setattr(
        openai_codex_provider,
        "get_codex_oauth_service",
        lambda: _Service(),
        raising=False,
    )
    monkeypatch.setattr(openai_codex_provider.OpenAICodexProvider, "_load_token", _fake_load_token)


@pytest.mark.asyncio
async def test_codex_first_attempt_verify_true_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_token_loader(monkeypatch)
    captured: list[dict[str, Any]] = []

    async def fake_request(*args: Any, **kwargs: Any) -> tuple[str, list[Any], str]:
        captured.append(kwargs)
        return ("ok", [], "stop")

    monkeypatch.setattr(openai_codex_provider, "_request_codex", fake_request)

    provider = openai_codex_provider.OpenAICodexProvider()
    result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert result.content == "ok"
    assert captured[0]["verify"] is True


@pytest.mark.asyncio
async def test_codex_first_attempt_verify_false_when_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISABLE_SSL_VERIFY", "1")
    _stub_token_loader(monkeypatch)
    captured: list[dict[str, Any]] = []

    async def fake_request(*args: Any, **kwargs: Any) -> tuple[str, list[Any], str]:
        captured.append(kwargs)
        return ("ok", [], "stop")

    monkeypatch.setattr(openai_codex_provider, "_request_codex", fake_request)

    provider = openai_codex_provider.OpenAICodexProvider()
    result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert result.content == "ok"
    assert captured[0]["verify"] is False


@pytest.mark.asyncio
async def test_codex_certificate_failure_never_retries_without_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_token_loader(monkeypatch)
    captured: list[dict[str, Any]] = []

    async def fake_request(*args: Any, **kwargs: Any) -> tuple[str, list[Any], str]:
        captured.append(kwargs)
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] cert chain")

    monkeypatch.setattr(openai_codex_provider, "_request_codex", fake_request)

    provider = openai_codex_provider.OpenAICodexProvider()
    with pytest.raises(LLMProviderTransportError):
        await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert len(captured) == 1
    assert captured[0]["verify"] is True
