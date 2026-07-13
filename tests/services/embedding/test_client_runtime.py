"""Tests for embedding client provider-backed execution path."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.embedding.client import (
    EmbeddingClient,
    _resolve_adapter_class,
    get_embedding_client,
    reset_embedding_client,
)
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
                "embeddings": [
                    [float(i)] * (request.dimensions or 2) for i, _ in enumerate(request.texts)
                ],
            },
        )()


def _build_config(
    binding: str,
    *,
    model: str = "text-embedding-3-small",
    base_url: str = "https://api.openai.com/v1/embeddings",
    send_dimensions: bool | None = None,
) -> EmbeddingConfig:
    return EmbeddingConfig(
        model=model,
        api_key="sk-test",
        base_url=base_url,
        effective_url=base_url,
        binding=binding,
        provider_name=binding,
        provider_mode="standard",
        dim=8,
        send_dimensions=send_dimensions,
        batch_size=2,
        request_timeout=30,
    )


@pytest.mark.asyncio
async def test_embedding_client_batches_requests(monkeypatch) -> None:
    _FakeAdapter.instances = []
    monkeypatch.setattr(
        "deeptutor.services.embedding.client._resolve_adapter_class", lambda _b: _FakeAdapter
    )
    client = EmbeddingClient(_build_config("openai"))
    vectors = await client.embed(["a", "b", "c"])
    assert len(vectors) == 3
    adapter = _FakeAdapter.instances[0]
    assert len(adapter.calls) == 2
    assert len(adapter.calls[0].texts) == 2
    assert len(adapter.calls[1].texts) == 1
    assert adapter.config["dimensions"] == 8


@pytest.mark.asyncio
async def test_embedding_client_rejects_null_vector_values(monkeypatch) -> None:
    class _NullValueAdapter(_FakeAdapter):
        async def embed(self, request):
            self.calls.append(request)
            return type("Resp", (), {"embeddings": [[0.1, None, 0.3]]})()

    monkeypatch.setattr(
        "deeptutor.services.embedding.client._resolve_adapter_class",
        lambda _b: _NullValueAdapter,
    )
    client = EmbeddingClient(_build_config("openai"))

    with pytest.raises(ValueError, match="dimension 1 is null"):
        await client.embed(["bad"])


@pytest.mark.asyncio
async def test_embedding_client_rejects_dropped_vectors(monkeypatch) -> None:
    class _DroppedVectorAdapter(_FakeAdapter):
        async def embed(self, request):
            self.calls.append(request)
            return type("Resp", (), {"embeddings": [[0.1, 0.2]]})()

    monkeypatch.setattr(
        "deeptutor.services.embedding.client._resolve_adapter_class",
        lambda _b: _DroppedVectorAdapter,
    )
    client = EmbeddingClient(_build_config("openai"))

    with pytest.raises(ValueError, match="expected 2, got 1"):
        await client.embed(["a", "b"])


@pytest.mark.asyncio
async def test_embedding_client_rejects_inconsistent_batch_dimensions(monkeypatch) -> None:
    class _InconsistentAdapter(_FakeAdapter):
        async def embed(self, request):
            self.calls.append(request)
            return type("Resp", (), {"embeddings": [[0.1, 0.2], [0.3]]})()

    monkeypatch.setattr(
        "deeptutor.services.embedding.client._resolve_adapter_class",
        lambda _b: _InconsistentAdapter,
    )
    client = EmbeddingClient(_build_config("openai"))

    with pytest.raises(ValueError, match="inconsistent vector dimensions"):
        await client.embed(["a", "b"])


def test_resolve_adapter_class_supports_canonical_providers() -> None:
    assert _resolve_adapter_class("openai").__name__ == "OpenAICompatibleEmbeddingAdapter"
    assert _resolve_adapter_class("custom").__name__ == "OpenAICompatibleEmbeddingAdapter"
    assert _resolve_adapter_class("azure_openai").__name__ == "OpenAICompatibleEmbeddingAdapter"
    assert _resolve_adapter_class("cohere").__name__ == "CohereEmbeddingAdapter"
    assert _resolve_adapter_class("jina").__name__ == "JinaEmbeddingAdapter"
    assert _resolve_adapter_class("ollama").__name__ == "OllamaEmbeddingAdapter"
    assert _resolve_adapter_class("vllm").__name__ == "OpenAICompatibleEmbeddingAdapter"
    assert _resolve_adapter_class("openrouter").__name__ == "OpenAICompatibleEmbeddingAdapter"


def test_resolve_adapter_class_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown embedding binding"):
        _resolve_adapter_class("huggingface")


def test_embedding_client_rejects_ollama_root_endpoint() -> None:
    cfg = EmbeddingConfig(
        model="nomic-embed-text",
        api_key="sk-no-key-required",
        base_url="http://localhost:11434",
        effective_url="http://localhost:11434",
        binding="ollama",
        provider_name="ollama",
        provider_mode="local",
    )

    with pytest.raises(ValueError, match="/api/embed"):
        EmbeddingClient(cfg)


def test_embedding_client_rejects_openrouter_base_endpoint() -> None:
    cfg = EmbeddingConfig(
        model="qwen/qwen3-embedding-8b",
        api_key="sk-or-test",
        base_url="https://openrouter.ai/api/v1",
        effective_url="https://openrouter.ai/api/v1",
        binding="openrouter",
        provider_name="openrouter",
        provider_mode="standard",
    )

    with pytest.raises(ValueError, match="/embeddings"):
        EmbeddingClient(cfg)


def test_get_embedding_client_refreshes_when_config_changes(monkeypatch) -> None:
    from deeptutor.services.embedding import client as client_module

    _FakeAdapter.instances = []
    first_config = _build_config("openai")
    second_config = _build_config("openai")
    second_config.model = "text-embedding-new"

    active_config = {"value": first_config}
    monkeypatch.setattr(
        client_module,
        "_resolve_adapter_class",
        lambda _b: _FakeAdapter,
    )
    monkeypatch.setattr(
        client_module,
        "get_embedding_config",
        lambda: active_config["value"],
    )

    reset_embedding_client()
    first_client = get_embedding_client()
    active_config["value"] = second_config
    second_client = get_embedding_client()
    same_second_client = get_embedding_client()

    assert first_client is not second_client
    assert second_client is same_second_client
    assert second_client.config.model == "text-embedding-new"
    reset_embedding_client()


@pytest.mark.parametrize("flag", [True, False, None])
def test_embedding_client_propagates_send_dimensions_to_adapter(
    monkeypatch, flag: bool | None
) -> None:
    """``EmbeddingConfig.send_dimensions`` must reach the adapter's config dict."""
    _FakeAdapter.instances = []
    monkeypatch.setattr(
        "deeptutor.services.embedding.client._resolve_adapter_class", lambda _b: _FakeAdapter
    )
    EmbeddingClient(_build_config("openai", send_dimensions=flag))
    assert _FakeAdapter.instances[-1].config["send_dimensions"] is flag


def test_every_registered_provider_has_adapter() -> None:
    """All EMBEDDING_PROVIDERS entries must resolve to a valid adapter class."""
    from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS

    for name in EMBEDDING_PROVIDERS:
        cls = _resolve_adapter_class(name)
        assert cls is not None, f"Provider '{name}' has no adapter"


def test_embedding_client_multimodal_detection_uses_model_level_metadata() -> None:
    text_model = EmbeddingClient(
        _build_config(
            "siliconflow",
            model="Qwen/Qwen3-Embedding-8B",
            base_url="https://api.siliconflow.cn/v1/embeddings",
        )
    )
    vision_model = EmbeddingClient(
        _build_config(
            "siliconflow",
            model="Qwen/Qwen3-VL-Embedding-8B",
            base_url="https://api.siliconflow.cn/v1/embeddings",
        )
    )
    cohere_v3 = EmbeddingClient(
        _build_config(
            "cohere",
            model="embed-multilingual-v3.0",
            base_url="https://api.cohere.com/v2/embed",
        )
    )

    assert text_model.supports_multimodal_contents() is False
    assert vision_model.supports_multimodal_contents() is True
    assert cohere_v3.supports_multimodal_contents() is False
