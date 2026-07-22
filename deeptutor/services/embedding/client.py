"""Unified embedding client backed by normalized provider runtime config."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from deeptutor.services.config.provider_runtime import (
    EMBEDDING_PROVIDERS,
    embedding_endpoint_validation_error,
)

from .adapters import ADAPTER_BACKENDS, BaseEmbeddingAdapter, EmbeddingRequest
from .config import EmbeddingConfig, get_embedding_config
from .validation import validate_embedding_batch


def _resolve_adapter_class(binding: str) -> type[BaseEmbeddingAdapter]:
    provider = (binding or "").strip().lower()
    spec = EMBEDDING_PROVIDERS.get(provider)
    if spec is None:
        supported = sorted(EMBEDDING_PROVIDERS.keys())
        raise ValueError(
            f"Unknown embedding binding: '{binding}'. Supported: {', '.join(supported)}"
        )
    cls = ADAPTER_BACKENDS.get(spec.adapter)
    if cls is None:
        raise ValueError(
            f"No adapter registered for backend '{spec.adapter}' (binding='{binding}')"
        )
    return cls


class EmbeddingClient:
    """Unified embedding client for RAG and retrieval services."""

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        self.config = config or get_embedding_config()
        self.logger = logging.getLogger(__name__)
        endpoint = self.config.effective_url or self.config.base_url
        problem = embedding_endpoint_validation_error(self.config.binding, endpoint)
        if problem:
            raise ValueError(
                f"{problem} Current Settings endpoint is {endpoint!r}. "
                "DeepTutor sends embedding requests to the Settings URL exactly; "
                "update the visible Endpoint URL instead of relying on hidden path appending."
            )
        adapter_class = _resolve_adapter_class(self.config.binding)
        self.adapter = adapter_class(
            {
                "api_key": self.config.api_key,
                "base_url": self.config.effective_url or self.config.base_url,
                "api_version": self.config.api_version,
                "model": self.config.model,
                "dimensions": self.config.dim,
                "send_dimensions": self.config.send_dimensions,
                "request_timeout": self.config.request_timeout,
                "extra_headers": self.config.extra_headers or {},
            }
        )
        self.logger.info(
            f"Initialized embedding client with {self.config.binding} adapter "
            f"(model: {self.config.model}, dimensions: {self.config.dim})"
        )

    async def embed(self, texts: List[str], progress_callback=None) -> List[List[float]]:
        if not texts:
            return []

        import asyncio

        # Clamp configured batch size against the provider's per-request item
        # cap. SiliconFlow Qwen3 family caps at 32; DashScope at 20; others
        # have generous defaults. Without this clamp, indexing a doc with many
        # chunks fails on the second batch even when "Test connection" passes.
        spec = EMBEDDING_PROVIDERS.get(self.config.binding)
        provider_max = spec.max_batch_items if spec else 256
        batch_size = max(1, min(self.config.batch_size, provider_max))
        if batch_size < self.config.batch_size:
            self.logger.info(
                f"Clamped batch_size {self.config.batch_size} -> {batch_size} "
                f"(provider '{self.config.binding}' max={provider_max})"
            )
        all_embeddings: List[List[float]] = []
        batch_delay = self.config.batch_delay
        expected_dim: int | None = None

        total_batches = (len(texts) + batch_size - 1) // batch_size
        for i, start in enumerate(range(0, len(texts), batch_size)):
            batch = texts[start : start + batch_size]
            request = EmbeddingRequest(
                texts=batch,
                model=self.config.model,
                dimensions=self.config.dim or None,
            )
            try:
                response = await self.adapter.embed(request)
            except Exception as exc:
                # Capture batch context so the task log stream / KB diagnostics
                # show actionable info instead of a bare exception string.
                import traceback

                first_chunk_chars = len(batch[0]) if batch else 0
                longest_chunk_chars = max((len(t) for t in batch), default=0)
                self.logger.error(
                    f"Embedding batch failed "
                    f"(binding={self.config.binding}, model={self.config.model}, "
                    f"batch_index={i + 1}/{total_batches}, batch_items={len(batch)}, "
                    f"first_chunk_chars={first_chunk_chars}, "
                    f"longest_chunk_chars={longest_chunk_chars}): {exc}\n"
                    f"{traceback.format_exc()}"
                )
                raise
            validated = validate_embedding_batch(
                response.embeddings,
                expected_count=len(batch),
                binding=self.config.binding,
                model=self.config.model,
                batch_index=i + 1,
                total_batches=total_batches,
                start_index=start,
            )
            batch_dim = len(validated[0]) if validated else 0
            if expected_dim is None:
                expected_dim = batch_dim
            elif batch_dim != expected_dim:
                raise ValueError(
                    "Embedding provider returned inconsistent vector dimensions "
                    f"across batches (binding={self.config.binding}, "
                    f"model={self.config.model}): expected {expected_dim}, "
                    f"got {batch_dim} in batch {i + 1}/{total_batches}. "
                    "Use a single embedding model/dimension and re-index the knowledge base."
                )

            all_embeddings.extend(validated)

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

    def supports_multimodal_contents(self) -> bool:
        """Return whether the configured adapter/model accepts multimodal contents."""
        try:
            info = self.adapter.get_model_info()
            if "multimodal" in info:
                return bool(info.get("multimodal"))
        except Exception:
            pass

        spec = EMBEDDING_PROVIDERS.get(self.config.binding)
        return bool(spec and spec.multimodal)

    async def embed_contents(
        self,
        contents: List[Dict[str, Any]],
        *,
        progress_callback=None,
    ) -> List[List[float]]:
        """Embed provider-agnostic multimodal content items.

        ``contents`` uses the same simple contract as ``EmbeddingRequest``:
        ``[{"text": "..."}, {"image": "data:...|url"}, {"video": "..."}]``.
        """
        if not contents:
            return []
        if not self.supports_multimodal_contents():
            raise ValueError(
                "Configured embedding provider/model does not support multimodal contents."
            )

        import asyncio

        spec = EMBEDDING_PROVIDERS.get(self.config.binding)
        provider_max = spec.max_batch_items if spec else 256
        batch_size = max(1, min(self.config.batch_size, provider_max))
        all_embeddings: List[List[float]] = []
        total_batches = (len(contents) + batch_size - 1) // batch_size

        for i, start in enumerate(range(0, len(contents), batch_size)):
            batch = contents[start : start + batch_size]
            request = EmbeddingRequest(
                texts=[],
                model=self.config.model,
                dimensions=self.config.dim or None,
                contents=batch,
                enable_fusion=False,
            )
            response = await self.adapter.embed(request)
            validated = validate_embedding_batch(
                response.embeddings,
                expected_count=len(batch),
                binding=self.config.binding,
                model=self.config.model,
                batch_index=i + 1,
                total_batches=total_batches,
                start_index=start,
            )
            all_embeddings.extend(validated)

            if progress_callback:
                try:
                    progress_callback(i + 1, total_batches)
                except Exception:
                    pass

            if i < total_batches - 1 and self.config.batch_delay > 0:
                await asyncio.sleep(self.config.batch_delay)

        return all_embeddings

    def embed_sync(self, texts: List[str]) -> List[List[float]]:
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.embed(texts))

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, self.embed(texts))
            return future.result()

    def get_embedding_func(self):
        async def embedding_wrapper(texts: List[str]) -> List[List[float]]:
            return await self.embed(texts)

        return embedding_wrapper


_client: Optional[EmbeddingClient] = None


def get_embedding_client(config: Optional[EmbeddingConfig] = None) -> EmbeddingClient:
    global _client
    resolved_config = config or get_embedding_config()
    if _client is None or _client.config != resolved_config:
        _client = EmbeddingClient(resolved_config)
    return _client


def reset_embedding_client() -> None:
    global _client
    _client = None
