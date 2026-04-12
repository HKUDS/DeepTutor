"""Unified embedding client backed by normalized provider runtime config."""

from __future__ import annotations

from typing import List, Optional

from deeptutor.logging import get_logger

from .adapters.base import BaseEmbeddingAdapter, EmbeddingRequest
from .adapters.cohere import CohereEmbeddingAdapter
from .adapters.jina import JinaEmbeddingAdapter
from .adapters.ollama import OllamaEmbeddingAdapter
from .adapters.openai_compatible import OpenAICompatibleEmbeddingAdapter
from .config import EmbeddingConfig, get_embedding_config

_OPENAI_COMPAT_PROVIDERS = {"custom", "openai", "azure_openai", "vllm"}
_COHERE_PROVIDERS = {"cohere"}
_JINA_PROVIDERS = {"jina"}
_OLLAMA_PROVIDERS = {"ollama"}


def _resolve_adapter_class(binding: str) -> type[BaseEmbeddingAdapter]:
    provider = (binding or "").strip().lower()
    if provider in _OPENAI_COMPAT_PROVIDERS:
        return OpenAICompatibleEmbeddingAdapter
    if provider in _COHERE_PROVIDERS:
        return CohereEmbeddingAdapter
    if provider in _JINA_PROVIDERS:
        return JinaEmbeddingAdapter
    if provider in _OLLAMA_PROVIDERS:
        return OllamaEmbeddingAdapter
    supported = sorted(
        _OPENAI_COMPAT_PROVIDERS | _COHERE_PROVIDERS | _JINA_PROVIDERS | _OLLAMA_PROVIDERS
    )
    raise ValueError(
        f"Unknown embedding binding: '{binding}'. Supported providers: {', '.join(supported)}"
    )


class EmbeddingClient:
    """Unified embedding client for RAG and retrieval services."""

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        self.config = config or get_embedding_config()
        self.logger = get_logger("EmbeddingClient")
        adapter_class = _resolve_adapter_class(self.config.binding)
        self.adapter = adapter_class(
            {
                "api_key": self.config.api_key,
                "base_url": self.config.effective_url or self.config.base_url,
                "api_version": self.config.api_version,
                "model": self.config.model,
                "dimensions": self.config.dim,
                "request_timeout": self.config.request_timeout,
                "extra_headers": self.config.extra_headers or {},
            }
        )
        self.logger.info(
            f"Initialized embedding client with {self.config.binding} adapter "
            f"(model: {self.config.model}, dimensions: {self.config.dim})"
        )

    async def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        batch_size = max(1, self.config.batch_size)
        all_embeddings: List[List[float]] = []

        try:
            for start in range(0, len(texts), batch_size):
                batch = texts[start : start + batch_size]
                request = EmbeddingRequest(
                    texts=batch,
                    model=self.config.model,
                    dimensions=self.config.dim,
                )
                response = await self.adapter.embed(request)
                all_embeddings.extend(response.embeddings)
            self.logger.debug(
                f"Generated {len(all_embeddings)} embeddings using "
                f"{self.config.binding} (batch_size={batch_size})"
            )
            return all_embeddings
        except Exception as exc:
            self.logger.error(f"Embedding request failed: {exc}")
            raise

    def embed_sync(self, texts: List[str]) -> List[List[float]]:
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self.embed(texts))
                    return future.result()
            return loop.run_until_complete(self.embed(texts))
        except RuntimeError:
            return asyncio.run(self.embed(texts))

    def get_embedding_func(self):
        async def embedding_wrapper(texts: List[str]) -> List[List[float]]:
            return await self.embed(texts)

        return embedding_wrapper


_client: Optional[EmbeddingClient] = None


def get_embedding_client(config: Optional[EmbeddingConfig] = None) -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient(config)
    return _client


def reset_embedding_client() -> None:
    global _client
    _client = None

