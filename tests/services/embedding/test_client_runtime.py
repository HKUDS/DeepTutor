"""Tests for embedding client provider-backed execution path."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.embedding.client import EmbeddingClient, _resolve_adapter_class
from deeptutor.services.embedding.config import EmbeddingConfig


class _FakeAdapter:
    instances: list["_FakeAdapter"] = []

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.calls = []
        _FakeAdapter.instances.append(self)

    async def embed(self, request):
        self.calls.append(request)
        return type(
            "Resp",
            (),
            {
                "embeddings": [[float(i)] * (request.dimensions or 2) for i, _ in enumerate(request.texts)],
            },
        )()


def _build_config(binding: str) -> EmbeddingConfig:
    return EmbeddingConfig(
        model="text-embedding-3-small",
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        effective_url="https://api.openai.com/v1",
        binding=binding,
        provider_name=binding,
        provider_mode="standard",
        dim=8,
        batch_size=2,
        request_timeout=30,
    )


@pytest.mark.asyncio
async def test_embedding_client_batches_requests(monkeypatch) -> None:
    _FakeAdapter.instances = []
    monkeypatch.setattr("deeptutor.services.embedding.client._resolve_adapter_class", lambda _b: _FakeAdapter)
    client = EmbeddingClient(_build_config("openai"))
    vectors = await client.embed(["a", "b", "c"])
    assert len(vectors) == 3
    adapter = _FakeAdapter.instances[0]
    assert len(adapter.calls) == 2
    assert len(adapter.calls[0].texts) == 2
    assert len(adapter.calls[1].texts) == 1
    assert adapter.config["dimensions"] == 8


def test_resolve_adapter_class_supports_canonical_providers() -> None:
    assert _resolve_adapter_class("openai").__name__ == "OpenAICompatibleEmbeddingAdapter"
    assert _resolve_adapter_class("custom").__name__ == "OpenAICompatibleEmbeddingAdapter"
    assert _resolve_adapter_class("azure_openai").__name__ == "OpenAICompatibleEmbeddingAdapter"
    assert _resolve_adapter_class("cohere").__name__ == "CohereEmbeddingAdapter"
    assert _resolve_adapter_class("jina").__name__ == "JinaEmbeddingAdapter"
    assert _resolve_adapter_class("ollama").__name__ == "OllamaEmbeddingAdapter"
    assert _resolve_adapter_class("vllm").__name__ == "OpenAICompatibleEmbeddingAdapter"


def test_resolve_adapter_class_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown embedding binding"):
        _resolve_adapter_class("huggingface")


def test_every_registered_provider_has_adapter() -> None:
    """All EMBEDDING_PROVIDERS entries must resolve to a valid adapter class."""
    from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS

    for name in EMBEDDING_PROVIDERS:
        cls = _resolve_adapter_class(name)
        assert cls is not None, f"Provider '{name}' has no adapter"

