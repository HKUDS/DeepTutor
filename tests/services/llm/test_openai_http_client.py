"""Tests for OpenAI SDK HTTP client options shared across providers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.services.llm import openai_http_client
from deeptutor.services.llm.exceptions import LLMConfigError


@pytest.fixture(autouse=True)
def _clean_ssl_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISABLE_SSL_VERIFY", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setattr(openai_http_client, "_warning_logged", False)


def _enable_ssl_override(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    clients: list[Any] = []

    class HTTPClientStub:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            clients.append(self)

    monkeypatch.setenv("DISABLE_SSL_VERIFY", "1")
    monkeypatch.setattr(openai_http_client.httpx, "AsyncClient", HTTPClientStub)
    return clients


def _capture_async_openai(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    class AsyncOpenAIStub:
        def __init__(self, **kwargs: Any) -> None:
            captured.append(kwargs)

    monkeypatch.setattr(module, "AsyncOpenAI", AsyncOpenAIStub)
    return captured


def test_openai_client_kwargs_disable_ssl_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    clients = _enable_ssl_override(monkeypatch)

    kwargs = openai_http_client.openai_client_kwargs(timeout=60)

    assert kwargs["http_client"] is clients[0]
    assert clients[0].kwargs == {"verify": False, "timeout": 60}


def test_openai_client_kwargs_rejects_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISABLE_SSL_VERIFY", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(LLMConfigError, match="not allowed in production"):
        openai_http_client.openai_client_kwargs()


def test_provider_core_passes_disable_ssl_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.llm.provider_core import openai_compat_provider as provider_mod

    clients = _enable_ssl_override(monkeypatch)
    captured = _capture_async_openai(monkeypatch, provider_mod)

    provider_mod.OpenAICompatProvider(api_key="sk-test", api_base="https://example.com/v1")

    assert captured[0]["http_client"] is clients[0]
    assert clients[0].kwargs["verify"] is False


def test_azure_provider_passes_disable_ssl_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.services.llm.provider_core import azure_openai_provider as azure_mod

    clients = _enable_ssl_override(monkeypatch)
    captured = _capture_async_openai(monkeypatch, azure_mod)

    azure_mod.AzureOpenAIProvider(
        api_key="sk-test",
        api_base="https://example.openai.azure.com",
        default_model="gpt-test",
    )

    assert captured[0]["http_client"] is clients[0]
    assert clients[0].kwargs["verify"] is False


def test_tutorbot_provider_passes_disable_ssl_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.tutorbot.providers import openai_compat_provider as tutorbot_mod

    clients = _enable_ssl_override(monkeypatch)
    captured = _capture_async_openai(monkeypatch, tutorbot_mod)

    tutorbot_mod.OpenAICompatProvider(api_key="sk-test", api_base="https://example.com/v1")

    assert captured[0]["http_client"] is clients[0]
    assert clients[0].kwargs["verify"] is False


@pytest.mark.asyncio
async def test_sdk_complete_passes_disable_ssl_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.llm import executors

    clients = _enable_ssl_override(monkeypatch)
    captured = _capture_async_openai(monkeypatch, executors)

    async def fake_create_with_format_fallback(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        )

    monkeypatch.setattr(executors, "_create_with_format_fallback", fake_create_with_format_fallback)

    result = await executors.sdk_complete(
        prompt="hi",
        system_prompt="system",
        provider_name="openai",
        model="gpt-test",
        api_key="sk-test",
        base_url="https://example.com/v1",
    )

    assert result == "ok"
    assert captured[0]["http_client"] is clients[0]
    assert clients[0].kwargs["verify"] is False


@pytest.mark.asyncio
async def test_sdk_stream_passes_disable_ssl_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.llm import executors

    clients = _enable_ssl_override(monkeypatch)
    captured = _capture_async_openai(monkeypatch, executors)

    class StreamStub:
        def __init__(self) -> None:
            self._chunks = [
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="hi"))],
                )
            ]

        def __aiter__(self) -> "StreamStub":
            return self

        async def __anext__(self) -> Any:
            if not self._chunks:
                raise StopAsyncIteration
            return self._chunks.pop(0)

    async def fake_create_with_format_fallback(*_args: Any, **_kwargs: Any) -> StreamStub:
        return StreamStub()

    monkeypatch.setattr(executors, "_create_with_format_fallback", fake_create_with_format_fallback)

    chunks = [
        chunk
        async for chunk in executors.sdk_stream(
            prompt="hi",
            system_prompt="system",
            provider_name="openai",
            model="gpt-test",
            api_key="sk-test",
            base_url="https://example.com/v1",
        )
    ]

    assert chunks == ["hi"]
    assert captured[0]["http_client"] is clients[0]
    assert clients[0].kwargs["verify"] is False


def test_embedding_sdk_passes_disable_ssl_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.embedding.adapters import openai_sdk as embedding_mod

    clients = _enable_ssl_override(monkeypatch)
    captured = _capture_async_openai(monkeypatch, embedding_mod)

    adapter = embedding_mod.OpenAISDKEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://example.com/v1",
            "model": "text-embedding-3-large",
            "request_timeout": 30,
        }
    )
    adapter._build_client()

    assert captured[0]["http_client"] is clients[0]
    assert clients[0].kwargs == {"verify": False, "timeout": 60}
