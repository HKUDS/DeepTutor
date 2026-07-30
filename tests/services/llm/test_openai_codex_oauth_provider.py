from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import pytest

from deeptutor.services.codex_auth.constants import CODEX_RESPONSES_URL
from deeptutor.services.codex_auth.contracts import CodexAuthError, CodexToken
from deeptutor.services.llm.provider_core import openai_codex_provider as module
from deeptutor.services.llm.provider_core.openai_codex_provider import (
    CodexHTTPError,
    OpenAICodexProvider,
)


class FakeCodexService:
    def __init__(self) -> None:
        self.token = CodexToken(
            access_token="test-access-token",
            account_id="account-123",
            expires_at=2_000_000_000,
            generation=7,
        )
        self.token_calls = 0
        self.guard_entries = 0
        self.recovered_generation: int | None = None

    async def get_token(self) -> CodexToken:
        self.token_calls += 1
        return self.token

    async def recover_after_unauthorized(self, generation: int) -> None:
        self.recovered_generation = generation

    @asynccontextmanager
    async def inference_guard(self) -> AsyncIterator[None]:
        self.guard_entries += 1
        yield


@pytest.mark.asyncio
async def test_provider_uses_deeptutor_token_service_and_raw_sol_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeCodexService()
    requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    async def request(
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        **_kwargs: Any,
    ) -> tuple[str, list[Any], str]:
        requests.append((url, headers, body))
        return "ok", [], "stop"

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", request)

    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
        model="openai-codex/gpt-5.6-sol",
        reasoning_effort="medium",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Look something up",
                    "parameters": {"type": "object"},
                },
            }
        ],
    )

    url, headers, body = requests[0]
    assert result.finish_reason == "stop"
    assert service.token_calls == 1
    assert service.guard_entries == 1
    assert url == CODEX_RESPONSES_URL
    assert headers["Authorization"] == "Bearer test-access-token"
    assert headers["chatgpt-account-id"] == "account-123"
    assert body["model"] == "gpt-5.6-sol"
    assert body["reasoning"] == {"effort": "medium"}
    assert body["tools"][0]["name"] == "lookup"


@pytest.mark.asyncio
async def test_401_refreshes_for_next_request_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeCodexService()
    request_count = 0

    async def rejected_request(*_args: Any, **_kwargs: Any) -> tuple[str, list[Any], str]:
        nonlocal request_count
        request_count += 1
        raise CodexHTTPError(401, module._friendly_error(401))

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", rejected_request)

    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
        model="gpt-5.6-sol",
    )

    assert request_count == 1
    assert service.recovered_generation == service.token.generation
    assert result.finish_reason == "error"
    assert "retry" in result.content.lower()


@pytest.mark.asyncio
async def test_401_with_dead_refresh_token_does_not_promise_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telling the user "already refreshed, retry" would loop them forever."""
    service = FakeCodexService()

    async def failed_recovery(generation: int) -> None:
        raise CodexAuthError(
            "authentication_required",
            "Sign in to Codex before using this model.",
            401,
        )

    async def rejected_request(*_args: Any, **_kwargs: Any) -> tuple[str, list[Any], str]:
        raise CodexHTTPError(401, module._friendly_error(401))

    service.recover_after_unauthorized = failed_recovery  # type: ignore[method-assign]
    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", rejected_request)

    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
        model="gpt-5.6-sol",
    )

    assert result.finish_reason == "error"
    assert "retry" not in result.content.lower()
    assert "sign in again" in result.content.lower()


@pytest.mark.asyncio
async def test_429_never_reads_openai_api_key_or_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeCodexService()
    destinations: list[str] = []
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")

    async def rate_limited(
        url: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> tuple[str, list[Any], str]:
        destinations.append(url)
        raise CodexHTTPError(429, "Codex usage quota exceeded.")

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", rate_limited)

    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
        model="gpt-5.6-sol",
    )

    assert "Codex usage quota" in result.content
    assert destinations == [CODEX_RESPONSES_URL]
    assert service.token_calls == 1


@pytest.mark.asyncio
async def test_provider_does_not_expose_network_error_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeCodexService()

    async def network_failure(
        *_args: Any,
        **_kwargs: Any,
    ) -> tuple[str, list[Any], str]:
        raise RuntimeError("private proxy host and token")

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(module, "_request_codex", network_failure)

    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
    )

    assert result.finish_reason == "error"
    assert "private proxy" not in result.content
    assert "token" not in result.content.lower()


def test_provider_source_no_longer_imports_oauth_cli_kit() -> None:
    source = module.__loader__.get_source(module.__name__)  # type: ignore[union-attr]

    assert source is not None
    assert "oauth_cli_kit" not in source
    assert "get_codex_oauth_service" in source
    assert OpenAICodexProvider().get_default_model() == "openai-codex/gpt-5.6-sol"
