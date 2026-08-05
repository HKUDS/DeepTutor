"""Azure OpenAI provider explicit-``api_protocol`` contract (MOD-02).

The Azure provider is a Responses-only backend.  ``auto`` and
``openai_responses`` are allowed; any other explicit protocol must raise the
stable :class:`UnifiedProtocolError` before an SDK request is issued.  All
tests are offline: the SDK client is replaced by a recording stub.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.llm.provider_core.azure_openai_provider import (
    AzureOpenAIProvider,
)
from deeptutor.services.llm.provider_core.base import LLMResponse
from deeptutor.services.llm.provider_core.unified.types import UnifiedProtocolError

MESSAGES = [{"role": "user", "content": "Hi"}]

_OK_RESPONSE: dict[str, Any] = {
    "output": [
        {
            "type": "message",
            "content": [{"type": "output_text", "text": "Hello there!"}],
        }
    ]
}


class _ResponsesStub:
    """Recording stand-in for ``client.responses``."""

    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []
        self.result: Any = _OK_RESPONSE
        self.error: Exception | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.create_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class _ClientStub:
    """Recording stand-in for ``AsyncOpenAI``."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.responses = _ResponsesStub()


def _make_azure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_protocol: str = "auto",
    strict_protocol: bool = False,
    api_base: str = "https://example.openai.azure.com",
) -> tuple[AzureOpenAIProvider, _ClientStub]:
    from deeptutor.services.llm.provider_core import azure_openai_provider as azure_mod

    clients: list[_ClientStub] = []

    def _factory(**kwargs: Any) -> _ClientStub:
        client = _ClientStub(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(azure_mod, "AsyncOpenAI", _factory)
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base=api_base,
        default_model="gpt-5.2-chat",
        api_protocol=api_protocol,
        strict_protocol=strict_protocol,
    )
    return provider, clients[0]


class TestEndpointNormalization:
    def test_appends_openai_v1_to_plain_azure_host(self, monkeypatch) -> None:
        provider, client = _make_azure(monkeypatch, api_base="https://example.openai.azure.com")
        assert str(client.kwargs["base_url"]) == "https://example.openai.azure.com/openai/v1/"

    def test_preserves_existing_openai_v1_suffix(self, monkeypatch) -> None:
        provider, client = _make_azure(
            monkeypatch, api_base="https://example.openai.azure.com/openai/v1"
        )
        assert str(client.kwargs["base_url"]) == "https://example.openai.azure.com/openai/v1/"

    def test_strips_trailing_slash_before_appending(self, monkeypatch) -> None:
        provider, client = _make_azure(
            monkeypatch, api_base="https://example.openai.azure.com/openai/v1/"
        )
        assert str(client.kwargs["base_url"]) == "https://example.openai.azure.com/openai/v1/"


class TestExplicitProtocolContract:
    def test_openai_responses_is_allowed_and_reaches_sdk(self, monkeypatch) -> None:
        import asyncio

        provider, client = _make_azure(
            monkeypatch,
            api_protocol="openai_responses",
            strict_protocol=True,
        )
        response = asyncio.run(provider.chat(MESSAGES))
        assert isinstance(response, LLMResponse)
        assert response.content == "Hello there!"
        assert response.finish_reason == "stop"
        assert len(client.responses.create_calls) == 1
        assert client.responses.create_calls[0]["stream"] is False

    def test_unsupported_explicit_protocol_makes_zero_sdk_calls(self, monkeypatch) -> None:
        import asyncio

        provider, client = _make_azure(
            monkeypatch,
            api_protocol="openai_chat_completions",
            strict_protocol=True,
        )
        with pytest.raises(UnifiedProtocolError) as excinfo:
            asyncio.run(provider.chat(MESSAGES))
        assert excinfo.value.code == "protocol_unsupported"
        assert excinfo.value.protocol == "openai_chat_completions"
        assert client.responses.create_calls == []

    def test_unsupported_explicit_protocol_stream_makes_zero_sdk_calls(self, monkeypatch) -> None:
        import asyncio

        provider, client = _make_azure(
            monkeypatch,
            api_protocol="anthropic_messages",
            strict_protocol=True,
        )
        with pytest.raises(UnifiedProtocolError) as excinfo:
            asyncio.run(provider.chat_stream(MESSAGES))
        assert excinfo.value.code == "protocol_unsupported"
        assert client.responses.create_calls == []


class TestStrictCallFailure:
    def test_strict_explicit_responses_surfaces_stable_protocol_error(self, monkeypatch) -> None:
        import asyncio

        provider, client = _make_azure(
            monkeypatch,
            api_protocol="openai_responses",
            strict_protocol=True,
        )
        client.responses.error = RuntimeError("provider boom")
        with pytest.raises(UnifiedProtocolError) as excinfo:
            asyncio.run(provider.chat(MESSAGES))
        assert excinfo.value.code == "protocol_call_failed"
        assert excinfo.value.protocol == "openai_responses"
        assert excinfo.value.provider == "azure_openai"
        assert len(client.responses.create_calls) == 1

    def test_auto_call_failure_returns_legacy_error_response(self, monkeypatch) -> None:
        import asyncio

        provider, client = _make_azure(
            monkeypatch,
            api_protocol="auto",
            strict_protocol=False,
        )
        client.responses.error = RuntimeError("provider boom")
        response = asyncio.run(provider.chat(MESSAGES))
        assert isinstance(response, LLMResponse)
        assert response.finish_reason == "error"
        assert "Error" in (response.content or "")
        assert len(client.responses.create_calls) == 1

    def test_non_strict_explicit_responses_failure_keeps_legacy_error(self, monkeypatch) -> None:
        import asyncio

        provider, client = _make_azure(
            monkeypatch,
            api_protocol="openai_responses",
            strict_protocol=False,
        )
        client.responses.error = RuntimeError("provider boom")
        response = asyncio.run(provider.chat(MESSAGES))
        assert isinstance(response, LLMResponse)
        assert response.finish_reason == "error"
        assert len(client.responses.create_calls) == 1
