"""LlamaIndex embedding adapter backed by DeepTutor's embedding service."""

from __future__ import annotations

import asyncio
from typing import Any, List

from llama_index.core import Settings
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.bridge.pydantic import PrivateAttr

from deeptutor.logging import get_logger
from deeptutor.services.embedding import (
    get_embedding_client,
    get_embedding_config,
    reset_embedding_client,
)
from deeptutor.services.embedding.validation import validate_embedding_batch


class CustomEmbedding(BaseEmbedding):
    """Custom LlamaIndex embedding adapter for DeepTutor embedding providers."""

    _client: Any = PrivateAttr()
    _logger: Any = PrivateAttr()
    _progress_callback: Any = PrivateAttr(default=None)
    _binding: Any = PrivateAttr(default=None)
    _model: Any = PrivateAttr(default=None)

    def __init__(self, **kwargs):
        progress_cb = kwargs.pop("progress_callback", None)
        super().__init__(**kwargs)
        self._client = get_embedding_client()
        self._logger = get_logger("CustomEmbedding")
        self._progress_callback = progress_cb
        client_config = getattr(self._client, "config", None)
        self._binding = getattr(client_config, "binding", None)
        self._model = getattr(client_config, "model", None)

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
        embeddings = await self._client.embed([query])
        return validate_embedding_batch(
            embeddings,
            expected_count=1,
            binding=self._binding,
            model=self._model,
        )[0]

    async def _aget_text_embedding(self, text: str) -> List[float]:
        embeddings = await self._client.embed([text])
        return validate_embedding_batch(
            embeddings,
            expected_count=1,
            binding=self._binding,
            model=self._model,
        )[0]

    async def _aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        embeddings = await self._client.embed(
            texts, progress_callback=self._progress_callback
        )
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
    reset_embedding_client()
    embedding_cfg = get_embedding_config()

    Settings.embed_model = CustomEmbedding()
    Settings.chunk_size = 512
    Settings.chunk_overlap = 50

    if logger is not None:
        logger.info(
            f"LlamaIndex configured: embedding={embedding_cfg.model} "
            f"({embedding_cfg.dim}D, {embedding_cfg.binding}), chunk_size=512"
        )


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
        if not result or not result[0]:
            raise RuntimeError("Embedding API returned empty result")
        if logger is not None:
            logger.info(f"Embedding API OK (returned {len(result[0])}-dim vector)")
    except Exception as exc:
        if logger is not None:
            logger.error(f"Embedding API connectivity check failed: {exc}")
        raise RuntimeError(
            "Cannot reach embedding API. Please check your embedding configuration. "
            f"Error: {exc}"
        ) from exc
