"""Unified embedding client backed by normalized provider runtime config."""

from __future__ import annotations

from typing import List, Optional

from deeptutor.logging import get_logger
from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS

from .adapters.base import BaseEmbeddingAdapter, EmbeddingRequest
from .adapters.cohere import CohereEmbeddingAdapter
from .adapters.jina import JinaEmbeddingAdapter
from .adapters.ollama import OllamaEmbeddingAdapter
from .adapters.openai_compatible import OpenAICompatibleEmbeddingAdapter
from .config import EmbeddingConfig, get_embedding_config

_ADAPTER_MAP: dict[str, type[BaseEmbeddingAdapter]] = {
    "openai_compat": OpenAICompatibleEmbeddingAdapter,
    "cohere": CohereEmbeddingAdapter,
    "jina": JinaEmbeddingAdapter,
    "ollama": OllamaEmbeddingAdapter,
}


def _resolve_adapter_class(binding: str) -> type[BaseEmbeddingAdapter]:
    provider = (binding or "").strip().lower()
    spec = EMBEDDING_PROVIDERS.get(provider)
    if spec is None:
        supported = sorted(EMBEDDING_PROVIDERS.keys())
        raise ValueError(
            f"Unknown embedding binding: '{binding}'. Supported: {', '.join(supported)}"
        )
    cls = _ADAPTER_MAP.get(spec.adapter)
    if cls is None:
        raise ValueError(f"No adapter registered for backend '{spec.adapter}' (binding='{binding}')")
    return cls


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

    async def embed(
        self, texts: List[str], progress_callback=None
    ) -> List[List[float]]:
        if not texts:
            return []

        import asyncio

        batch_size = max(1, self.config.batch_size)
        all_embeddings: List[List[float]] = []
        batch_delay = self.config.batch_delay

        try:
            total_batches = (len(texts) + batch_size - 1) // batch_size
            for i, start in enumerate(range(0, len(texts), batch_size)):
                batch = texts[start : start + batch_size]
                request = EmbeddingRequest(
                    texts=batch,
                    model=self.config.model,
                    dimensions=self.config.dim,
                )
                response = await self.adapter.embed(request)
                all_embeddings.extend(response.embeddings)

                # Report progress after each batch
                if progress_callback:
                    try:
                        progress_callback(i + 1, total_batches)
                    except Exception:
                        pass

                # Delay between batches to avoid rate limiting
                if i < total_batches - 1 and batch_delay > 0:
                    await asyncio.sleep(batch_delay)

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

