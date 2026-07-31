"""Unified embedding client backed by normalized provider runtime config."""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
import logging
import math
from typing import Any, Dict, List, Optional

from deeptutor.services.config.provider_runtime import (
    EMBEDDING_PROVIDERS,
    embedding_endpoint_validation_error,
)

from .adapters import ADAPTER_BACKENDS, BaseEmbeddingAdapter, EmbeddingRequest
from .config import EmbeddingConfig, get_embedding_config
from .validation import validate_embedding_batch


def _estimate_text_tokens(texts: List[str]) -> int:
    """Estimate provider input tokens before an embedding request.

    Embedding providers do not share a response usage schema, so the hard
    preflight reservation uses a conservative character-based estimate and
    reconciles with provider usage when available.
    """
    chars = sum(len(text or "") for text in texts)
    return max(1, math.ceil(chars / 3.5))


def _estimate_content_tokens(contents: List[Dict[str, Any]]) -> int:
    text_items = [str(item.get("text") or "") for item in contents]
    estimated = _estimate_text_tokens(text_items)
    # Image/video-only embedding requests still consume provider work but may
    # expose no token count. Count each such item minimally for quota purposes.
    return max(estimated, sum(1 for item in contents if not item.get("text")))


def _usage_tokens(usage: Any) -> int:
    if isinstance(usage, Mapping):
        for key in ("total_tokens", "prompt_tokens", "input_tokens", "tokens"):
            value = usage.get(key)
            try:
                if value is not None and int(value) > 0:
                    return int(value)
            except (TypeError, ValueError):
                continue
    for key in ("total_tokens", "prompt_tokens", "input_tokens", "tokens"):
        value = getattr(usage, key, None)
        try:
            if value is not None and int(value) > 0:
                return int(value)
        except (TypeError, ValueError):
            continue
    return 0


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

    def _reserve_quota(self, estimated_tokens: int):
        if self.config.source == "byok":
            from deeptutor.multi_user.byok_usage import start_byok_usage
            from deeptutor.multi_user.execution_source import get_execution_source
            from deeptutor.multi_user.context import get_current_user

            source = get_execution_source()
            source_for_service = source if source and source.service == "embedding" else None
            return start_byok_usage(
                service="embedding",
                user_id=source_for_service.user_id if source_for_service else get_current_user().id,
                profile_id=(
                    source_for_service.profile_id
                    if source_for_service and source_for_service.profile_id
                    else self.config.profile_id or "unknown"
                ),
                provider=self.config.provider_name or self.config.binding,
                model=self.config.model,
                estimated_units=estimated_tokens,
            )
        from deeptutor.multi_user.token_quota import reserve_current_user_units

        return reserve_current_user_units(
            resource="embedding",
            requested_units=estimated_tokens,
        )

    @staticmethod
    def _finalize_quota(lease: Any, usage: Any, estimated_tokens: int) -> None:
        if lease is not None:
            lease.finalize(_usage_tokens(usage) or estimated_tokens)

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
            estimated_tokens = _estimate_text_tokens(batch)
            lease = self._reserve_quota(estimated_tokens)
            try:
                response = await self.adapter.embed(request)
            except Exception as exc:
                if lease is not None:
                    lease.release()
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
            try:
                validated = validate_embedding_batch(
                    response.embeddings,
                    expected_count=len(batch),
                    binding=self.config.binding,
                    model=self.config.model,
                    batch_index=i + 1,
                    total_batches=total_batches,
                    start_index=start,
                )
            except Exception:
                if lease is not None:
                    lease.release()
                raise
            self._finalize_quota(lease, getattr(response, "usage", None), estimated_tokens)
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
            estimated_tokens = _estimate_content_tokens(batch)
            lease = self._reserve_quota(estimated_tokens)
            try:
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
            except Exception:
                if lease is not None:
                    lease.release()
                raise
            self._finalize_quota(lease, getattr(response, "usage", None), estimated_tokens)
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


_SCOPED_CLIENT: ContextVar[EmbeddingClient | None] = ContextVar(
    "deeptutor_scoped_embedding_client", default=None
)


def get_embedding_client(config: Optional[EmbeddingConfig] = None) -> EmbeddingClient:
    resolved_config = config or get_embedding_config()
    client = _SCOPED_CLIENT.get()
    if client is None or client.config != resolved_config:
        client = EmbeddingClient(resolved_config)
        _SCOPED_CLIENT.set(client)
    return client


def reset_embedding_client() -> None:
    _SCOPED_CLIENT.set(None)
