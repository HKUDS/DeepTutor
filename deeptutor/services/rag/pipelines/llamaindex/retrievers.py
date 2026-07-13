"""Retriever composition for the LlamaIndex RAG pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
from typing import Any

from llama_index.core.llms.mock import MockLLM
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES

from .config import (
    HYBRID_PROFILE,
    VECTOR_PROFILE,
    RetrievalConfig,
    retrieval_config_from_settings,
)

logger = logging.getLogger(__name__)

BM25_PERSIST_DIRNAME = "bm25_retriever"


def _import_bm25_retriever():
    try:
        from llama_index.retrievers.bm25 import BM25Retriever

        return BM25Retriever
    except ImportError:
        return None


def _bm25_persist_dir(storage_dir: Path) -> Path:
    return storage_dir / BM25_PERSIST_DIRNAME


def _set_similarity_top_k(retriever: Any, top_k: int) -> Any:
    if hasattr(retriever, "similarity_top_k"):
        retriever.similarity_top_k = top_k
    return retriever


def _corpus_size(index: Any) -> int | None:
    """Best-effort count of indexed nodes (the BM25 corpus size)."""
    docstore = getattr(index, "docstore", None)
    docs = getattr(docstore, "docs", None)
    if isinstance(docs, dict):
        return len(docs)
    return None


def build_bm25_retriever(index: Any, storage_dir: Path, *, top_k: int) -> Any | None:
    """Build or load LlamaIndex's official BM25 retriever if available."""
    top_k = max(1, int(top_k))
    # BM25 raises ("k of N is larger than the number of available scores") when
    # similarity_top_k exceeds the corpus size — so a small knowledge base (e.g. a
    # single short document) would crash hybrid retrieval at query time. Clamp to
    # the node count so it returns what it has instead of erroring.
    corpus_size = _corpus_size(index)
    if corpus_size:
        top_k = min(top_k, corpus_size)
    bm25_cls = _import_bm25_retriever()
    if bm25_cls is None:
        logger.info(
            "LlamaIndex BM25 retriever package is not installed; falling back to vector retrieval."
        )
        return None

    persist_dir = _bm25_persist_dir(storage_dir)
    if persist_dir.exists():
        try:
            retriever = bm25_cls.from_persist_dir(str(persist_dir))
            return _set_similarity_top_k(retriever, top_k)
        except Exception as exc:
            logger.warning("Failed to load persisted BM25 retriever from %s: %s", persist_dir, exc)

    try:
        return bm25_cls.from_defaults(index=index, similarity_top_k=top_k)
    except Exception as exc:
        logger.warning("Failed to build BM25 retriever; falling back to vector retrieval: %s", exc)
        return None


def persist_bm25_retriever(index: Any, storage_dir: Path, *, top_k: int) -> bool:
    """Persist BM25 sidecar index for faster hybrid retrieval.

    Missing optional dependencies are non-fatal because hybrid retrieval can
    still be enabled in deployments that install ``llama-index-retrievers-bm25``.
    """
    top_k = max(1, int(top_k))
    bm25_cls = _import_bm25_retriever()
    if bm25_cls is None:
        return False

    persist_dir = _bm25_persist_dir(storage_dir)
    if persist_dir.exists():
        shutil.rmtree(persist_dir, ignore_errors=True)

    try:
        retriever = bm25_cls.from_defaults(index=index, similarity_top_k=top_k)
    except Exception as exc:
        logger.warning("Failed to build BM25 retriever for persistence: %s", exc)
        return False

    if not hasattr(retriever, "persist"):
        return False

    persist_dir.mkdir(parents=True, exist_ok=True)
    try:
        retriever.persist(str(persist_dir))
        return True
    except Exception as exc:
        logger.warning("Failed to persist BM25 retriever to %s: %s", persist_dir, exc)
        return False


def build_retriever(
    index: Any,
    storage_dir: Path,
    *,
    top_k: int = 5,
    config: RetrievalConfig | None = None,
) -> Any:
    """Compose the retrieval stack from official LlamaIndex retrievers."""
    top_k = max(1, int(top_k))
    retrieval_config = config or retrieval_config_from_settings()
    if retrieval_config.profile == VECTOR_PROFILE:
        return index.as_retriever(similarity_top_k=top_k)

    bm25_top_k = retrieval_config.candidate_top_k(top_k, retrieval_config.bm25_top_k_multiplier)
    bm25_retriever = build_bm25_retriever(index, storage_dir, top_k=bm25_top_k)
    if bm25_retriever is None:
        return index.as_retriever(similarity_top_k=top_k)

    if retrieval_config.profile == HYBRID_PROFILE:
        vector_top_k = retrieval_config.candidate_top_k(
            top_k, retrieval_config.vector_top_k_multiplier
        )
        vector_retriever = index.as_retriever(similarity_top_k=vector_top_k)
        return QueryFusionRetriever(
            [vector_retriever, bm25_retriever],
            llm=MockLLM(),
            mode=FUSION_MODES.RECIPROCAL_RANK,
            similarity_top_k=top_k,
            num_queries=retrieval_config.fusion_num_queries,
            use_async=False,
        )

    return index.as_retriever(similarity_top_k=top_k)


__all__ = [
    "BM25_PERSIST_DIRNAME",
    "build_bm25_retriever",
    "build_retriever",
    "persist_bm25_retriever",
]
