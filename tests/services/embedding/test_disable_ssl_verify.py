"""DISABLE_SSL_VERIFY coverage for embedding adapters that use raw httpx.

Companion to ``tests/services/llm/test_openai_http_client.py`` (SDK clients) and
``tests/services/llm/test_codex_disable_ssl_verify.py`` (codex retry path).
Each adapter constructs ``httpx.AsyncClient`` directly; this asserts the
``verify`` kwarg flips to ``False`` when ``DISABLE_SSL_VERIFY`` is set, and
defaults to ``True`` otherwise.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.cohere import CohereEmbeddingAdapter
from deeptutor.services.embedding.adapters.jina import JinaEmbeddingAdapter
from deeptutor.services.embedding.adapters.ollama import OllamaEmbeddingAdapter
from deeptutor.services.embedding.adapters.openai_compatible import (
    OpenAICompatibleEmbeddingAdapter,
)
from deeptutor.services.llm import openai_http_client


@pytest.fixture(autouse=True)
def _clean_ssl_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISABLE_SSL_VERIFY", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setattr(openai_http_client, "_warning_logged", False)


def _capture_verify(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch ``httpx.AsyncClient`` to record the ``verify`` kwarg."""
    captured: dict[str, Any] = {}
    real_init = httpx.AsyncClient.__init__

    def fake_init(self: httpx.AsyncClient, **kwargs: Any) -> None:  # noqa: ANN001
        captured["verify"] = kwargs.get("verify", "<unset>")
        real_init(self, **kwargs)

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        request = httpx.Request("POST", url)
        return httpx.Response(
            status_code=200,
            json={
                "data": [{"embedding": [0.1, 0.2, 0.3]}],
                "embeddings": [[0.1, 0.2, 0.3]],
                "model": "test-model",
            },
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "__init__", fake_init)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return captured


@pytest.mark.asyncio
async def test_openai_compatible_honors_disable_ssl_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISABLE_SSL_VERIFY", "true")
    captured = _capture_verify(monkeypatch)
    adapter = OpenAICompatibleEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://example.test/v1/embeddings",
            "model": "test-model",
            "dimensions": 0,
            "send_dimensions": False,
            "request_timeout": 5,
        }
    )
    await adapter.embed(EmbeddingRequest(texts=["hello"], model="test-model"))
    assert captured["verify"] is False


@pytest.mark.asyncio
async def test_openai_compatible_defaults_to_verify_true(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_verify(monkeypatch)
    adapter = OpenAICompatibleEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://example.test/v1/embeddings",
            "model": "test-model",
            "dimensions": 0,
            "send_dimensions": False,
            "request_timeout": 5,
        }
    )
    await adapter.embed(EmbeddingRequest(texts=["hello"], model="test-model"))
    assert captured["verify"] is True


@pytest.mark.asyncio
async def test_jina_honors_disable_ssl_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISABLE_SSL_VERIFY", "yes")
    captured = _capture_verify(monkeypatch)
    adapter = JinaEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://api.jina.test/v1/embeddings",
            "model": "jina-embeddings-v3",
            "dimensions": 0,
            "send_dimensions": False,
            "request_timeout": 5,
        }
    )
    await adapter.embed(EmbeddingRequest(texts=["hello"], model="jina-embeddings-v3"))
    assert captured["verify"] is False


@pytest.mark.asyncio
async def test_ollama_honors_disable_ssl_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISABLE_SSL_VERIFY", "on")
    captured = _capture_verify(monkeypatch)
    adapter = OllamaEmbeddingAdapter(
        {
            "api_key": "",
            "base_url": "https://ollama.test/api/embeddings",
            "model": "nomic-embed-text",
            "dimensions": 0,
            "request_timeout": 5,
        }
    )
    await adapter.embed(EmbeddingRequest(texts=["hello"], model="nomic-embed-text"))
    assert captured["verify"] is False


@pytest.mark.asyncio
async def test_cohere_honors_disable_ssl_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISABLE_SSL_VERIFY", "1")
    captured = _capture_verify(monkeypatch)
    adapter = CohereEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://api.cohere.test/v1/embed",
            "model": "embed-v3",
            "dimensions": 0,
            "request_timeout": 5,
            "api_version": "v1",
        }
    )
    await adapter.embed(EmbeddingRequest(texts=["hello"], model="embed-v3"))
    assert captured["verify"] is False


@pytest.mark.asyncio
async def test_disable_ssl_verify_blocked_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISABLE_SSL_VERIFY", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")
    _capture_verify(monkeypatch)
    adapter = JinaEmbeddingAdapter(
        {
            "api_key": "sk-test",
            "base_url": "https://api.jina.test/v1/embeddings",
            "model": "jina-embeddings-v3",
            "dimensions": 0,
            "send_dimensions": False,
            "request_timeout": 5,
        }
    )
    with pytest.raises(Exception, match="not allowed in production"):
        await adapter.embed(EmbeddingRequest(texts=["hello"], model="jina-embeddings-v3"))
