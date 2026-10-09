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
    normalize_retrieval_profile,
    retrieval_config_from_settings,
)
from .rerank import rerank_nodes

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


def bm25_available() -> bool:
    """Whether LlamaIndex's BM25 retriever package is importable.

    Exposed so status surfaces can distinguish the *configured* retrieval
    profile from the *effective* one: on Python 3.14 the BM25 dependency is
    marker-excluded, and a deployment configured for hybrid then runs
    vector-only without any signal otherwise (#1792).
    """
    return _import_bm25_retriever() is not None


def effective_retrieval_profile(profile: str | None) -> str:
    """The retrieval profile that would actually run, given BM25 availability.

    A hybrid configuration degrades to vector-only when the BM25 package is
    missing; vector-only configurations are unaffected.
    """
    normalized = normalize_retrieval_profile(profile)
    if normalized == HYBRID_PROFILE and not bm25_available():
        return VECTOR_PROFILE
    return normalized


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
        # #1792: an INFO line was invisible in normal runs, so deployments on
        # Python 3.14 (where the BM25 dependency is marker-excluded) ran
        # vector-only without ever knowing. The configured profile is not the
        # effective one — say so at warning level.
        logger.warning(
            "LlamaIndex BM25 retriever package is not installed; configured "
            "retrieval profile will run vector-only. Install "
            "'llama-index-retrievers-bm25' to restore hybrid retrieval."
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
        # Only reachable for non-vector profiles: the configured stack
        # degrades to vector-only here, and the operator must know (#1792).
        logger.warning(
            "Retrieval profile %r requires BM25 but it is unavailable; "
            "running vector-only. Install 'llama-index-retrievers-bm25' "
            "or switch the profile to 'vector'.",
            retrieval_config.profile,
        )
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


def retrieve_nodes(
    index: Any,
    storage_dir: Path,
    query: str,
    *,
    top_k: int = 5,
) -> list[Any]:
    """Run first-stage retrieval and the optional cross-encoder reranker."""
    config = retrieval_config_from_settings()
    candidate_top_k = config.rerank_candidate_top_k(top_k)
    retriever = build_retriever(
        index,
        storage_dir,
        top_k=candidate_top_k,
        config=config,
    )
    candidates = retriever.retrieve(query)
    if not config.reranker_model:
        return candidates[: max(1, int(top_k))]

    return rerank_nodes(
        query,
        candidates,
        top_k=top_k,
        model_name=config.reranker_model,
    )


__all__ = [
    "BM25_PERSIST_DIRNAME",
    "bm25_available",
    "build_bm25_retriever",
    "build_retriever",
    "effective_retrieval_profile",
    "persist_bm25_retriever",
    "retrieve_nodes",
]
