"""LlamaIndex embedding adapter backed by DeepTutor's embedding service."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, List

from llama_index.core import Settings
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.bridge.pydantic import PrivateAttr

from deeptutor.services.embedding import EmbeddingConfig, get_embedding_client, get_embedding_config
from deeptutor.services.embedding.validation import validate_embedding_batch

from .config import chunk_geometry


def _config_fingerprint(config: EmbeddingConfig) -> tuple[Any, ...]:
    """Return the settings fields that affect LlamaIndex embedding behavior."""
    return (
        getattr(config, "binding", None),
        getattr(config, "model", None),
        getattr(config, "dim", None),
        getattr(config, "effective_url", None) or getattr(config, "base_url", None),
        getattr(config, "api_version", None),
        getattr(config, "send_dimensions", None),
    )


class CustomEmbedding(BaseEmbedding):
    """Custom LlamaIndex embedding adapter for DeepTutor embedding providers."""

    _client: Any = PrivateAttr()
    _logger: Any = PrivateAttr()
    _progress_callback: Any = PrivateAttr(default=None)
    _binding: Any = PrivateAttr(default=None)
    _model: Any = PrivateAttr(default=None)
    _fingerprint: Any = PrivateAttr(default=None)

    def __init__(self, **kwargs):
        progress_cb = kwargs.pop("progress_callback", None)
        embedding_config = kwargs.pop("embedding_config", None)
        super().__init__(**kwargs)
        self._logger = logging.getLogger(__name__)
        self._progress_callback = progress_cb
        client = (
            get_embedding_client(embedding_config)
            if embedding_config is not None
            else get_embedding_client()
        )
        self._bind_client(client)

    def _bind_client(self, client: Any) -> None:
        self._client = client
        client_config = getattr(self._client, "config", None)
        self._binding = getattr(client_config, "binding", None)
        self._model = getattr(client_config, "model", None)
        self._fingerprint = (
            _config_fingerprint(client_config) if client_config is not None else None
        )

    def matches_config(self, config: EmbeddingConfig) -> bool:
        """Return whether this adapter was created for the active config."""
        return self._fingerprint == _config_fingerprint(config)

    def refresh_client(self, config: EmbeddingConfig | None = None) -> Any:
        """Refresh the cached client if settings changed while the pipeline lived."""
        client = get_embedding_client(config) if config is not None else get_embedding_client()
        if client is not self._client:
            self._bind_client(client)
        return self._client

    def set_progress_callback(self, callback):
        """Set progress callback fn(batch_num, total_batches)."""
        self._progress_callback = callback

    @classmethod
    def class_name(cls) -> str:
        return "custom_embedding"

    def _run_in_new_loop(self, coro):
        """Run an async coroutine from sync context using a fresh event loop."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    async def _aget_query_embedding(self, query: str) -> List[float]:
        client = self.refresh_client()
        embeddings = await client.embed([query])
        return validate_embedding_batch(
            embeddings,
            expected_count=1,
            binding=self._binding,
            model=self._model,
        )[0]

    async def _aget_text_embedding(self, text: str) -> List[float]:
        client = self.refresh_client()
        embeddings = await client.embed([text])
        return validate_embedding_batch(
            embeddings,
            expected_count=1,
            binding=self._binding,
            model=self._model,
        )[0]

    async def _aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        client = self.refresh_client()
        embeddings = await client.embed(texts, progress_callback=self._progress_callback)
        return validate_embedding_batch(
            embeddings,
            expected_count=len(texts),
            binding=self._binding,
            model=self._model,
        )

    def _get_query_embedding(self, query: str) -> List[float]:
        return self._run_in_new_loop(self._aget_query_embedding(query))

    def _get_text_embedding(self, text: str) -> List[float]:
        return self._run_in_new_loop(self._aget_text_embedding(text))

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        self._logger.info(f"Embedding {len(texts)} text chunks...")
        result = self._run_in_new_loop(self._aget_text_embeddings(texts))
        self._logger.info(f"Embedding complete: {len(result)} vectors")
        return result


def configure_llamaindex_settings(logger=None) -> None:
    """Configure LlamaIndex globals for DeepTutor's current embedding config."""
    embedding_cfg = get_embedding_config()

    current = getattr(Settings, "_embed_model", None)
    configured = False
    if isinstance(current, CustomEmbedding) and current.matches_config(embedding_cfg):
        current.refresh_client(embedding_cfg)
    else:
        Settings.embed_model = CustomEmbedding(embedding_config=embedding_cfg)
        configured = True
    chunk_size, chunk_overlap = chunk_geometry()
    Settings.chunk_size = chunk_size
    Settings.chunk_overlap = chunk_overlap

    if logger is not None:
        message = (
            f"LlamaIndex configured: embedding={embedding_cfg.model} "
            f"({embedding_cfg.dim}D, {embedding_cfg.binding}), chunk_size={chunk_size}"
        )
        if configured:
            logger.info(message)
        else:
            logger.debug(message)


def set_progress_callback(callback) -> None:
    """Attach an indexing progress callback to the active embedding adapter."""
    embed_model = getattr(Settings, "_embed_model", None)
    if isinstance(embed_model, CustomEmbedding):
        embed_model.set_progress_callback(callback)


async def verify_embedding_connectivity(logger=None) -> None:
    """Quick smoke-test to catch embedding config/network issues before indexing."""
    if logger is not None:
        logger.info("Verifying embedding API connectivity...")
    try:
        client = get_embedding_client()
        result = await client.embed(["connectivity test"])
        validated = validate_embedding_batch(
            result,
            expected_count=1,
            binding=getattr(client.config, "binding", None),
            model=getattr(client.config, "model", None),
        )
        if logger is not None:
            logger.info(f"Embedding API OK (returned {len(validated[0])}-dim vector)")
    except Exception as exc:
        if logger is not None:
            logger.error(f"Embedding API connectivity check failed: {exc}")
        raise RuntimeError(
            f"Cannot reach embedding API. Please check your embedding configuration. Error: {exc}"
        ) from exc
