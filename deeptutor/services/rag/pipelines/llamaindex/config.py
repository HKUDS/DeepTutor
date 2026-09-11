"""Configuration helpers for DeepTutor's LlamaIndex RAG pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import os
import sys

VECTOR_PROFILE = "vector"
HYBRID_PROFILE = "hybrid"
SUPPORTED_RETRIEVAL_PROFILES = {VECTOR_PROFILE, HYBRID_PROFILE}
FLAT_VECTOR_INDEX = "flat"
HNSW_VECTOR_INDEX = "hnsw"
SUPPORTED_VECTOR_INDEX_TYPES = {FLAT_VECTOR_INDEX, HNSW_VECTOR_INDEX}


def should_show_progress() -> bool:
    """Whether to emit LlamaIndex ``tqdm`` progress bars.

    tqdm writes carriage-return progress lines to ``sys.stdout``. When
    DeepTutor runs as a server that stream is a pipe whose read end (the
    launcher's relay thread) can close mid-indexing, and the next tqdm write
    then raises :class:`BrokenPipeError`, killing document indexing. DeepTutor
    reports indexing progress through its own ``ProgressTracker``, so the tqdm
    output is only wanted in an interactive CLI/REPL session.
    """
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


@dataclass(frozen=True)
class RetrievalConfig:
    """Runtime retrieval knobs for the LlamaIndex pipeline."""

    profile: str = HYBRID_PROFILE
    vector_top_k_multiplier: int = 2
    bm25_top_k_multiplier: int = 2
    fusion_num_queries: int = 1
    reranker_model: str = ""
    rerank_top_k: int = 50

    def candidate_top_k(self, top_k: int, multiplier: int) -> int:
        """Return the number of candidates to ask a child retriever for."""
        requested = max(1, int(top_k))
        return max(requested, requested * max(1, int(multiplier)))

    def rerank_candidate_top_k(self, top_k: int) -> int:
        """Return the first-stage candidate count before optional reranking."""
        requested = max(1, int(top_k))
        if not self.reranker_model:
            return requested
        return max(requested, min(100, max(1, int(self.rerank_top_k))))


@dataclass(frozen=True)
class VectorIndexConfig:
    """FAISS construction knobs for the next full index build."""

    type: str = FLAT_VECTOR_INDEX
    hnsw_m: int = 32
    hnsw_ef_construction: int = 200
    hnsw_ef_search: int = 64


def normalize_retrieval_profile(value: str | None) -> str:
    """Return a supported retrieval profile, defaulting to hybrid."""
    profile = (value or "").strip().lower()
    if profile in SUPPORTED_RETRIEVAL_PROFILES:
        return profile
    return HYBRID_PROFILE


def normalize_reranker_model(value: str | None) -> str:
    """Return a bounded Hugging Face model identifier (empty disables rerank)."""
    return (value or "").strip()[:200]


def normalize_vector_index_type(value: str | None) -> str:
    """Return a supported vector index type, defaulting to exact flat search."""
    index_type = (value or "").strip().lower()
    if index_type in SUPPORTED_VECTOR_INDEX_TYPES:
        return index_type
    return FLAT_VECTOR_INDEX


def retrieval_config_from_env() -> RetrievalConfig:
    """Build retrieval config from environment variables.

    The default is intentionally ``hybrid``. If the optional LlamaIndex BM25
    integration is not installed, the retriever builder transparently falls
    back to plain vector retrieval.
    """

    return RetrievalConfig(
        profile=normalize_retrieval_profile(
            os.getenv("DEEPTUTOR_RAG_RETRIEVAL_PROFILE") or os.getenv("RAG_RETRIEVAL_PROFILE")
        )
    )


def _load_runtime_settings() -> dict:
    """Load the persisted LlamaIndex engine settings (env overrides applied)."""
    from deeptutor.services.config import load_llamaindex_settings

    return load_llamaindex_settings()


def retrieval_config_from_settings() -> RetrievalConfig:
    """Build retrieval config from persisted engine settings.

    Falls back to defaults on any read error so retrieval never breaks because
    of a malformed settings file. ``fusion_num_queries`` stays at the dataclass
    default — query generation needs a real LLM, but the fusion retriever runs
    on a MockLLM, so it is not user-tunable.
    """
    try:
        settings = _load_runtime_settings()
    except Exception:
        return RetrievalConfig()
    return RetrievalConfig(
        profile=normalize_retrieval_profile(settings.get("retrieval_profile")),
        vector_top_k_multiplier=int(settings.get("vector_top_k_multiplier", 2) or 2),
        bm25_top_k_multiplier=int(settings.get("bm25_top_k_multiplier", 2) or 2),
        reranker_model=normalize_reranker_model(settings.get("reranker_model")),
        rerank_top_k=int(settings.get("rerank_top_k", 50) or 50),
    )


def vector_index_config_from_settings() -> VectorIndexConfig:
    """Build FAISS construction settings, retaining the exact flat default."""
    try:
        settings = _load_runtime_settings()
    except Exception:
        return VectorIndexConfig()
    return VectorIndexConfig(
        type=normalize_vector_index_type(settings.get("vector_index_type")),
        hnsw_m=int(settings.get("hnsw_m", 32) or 32),
        hnsw_ef_construction=int(settings.get("hnsw_ef_construction", 200) or 200),
        hnsw_ef_search=int(settings.get("hnsw_ef_search", 64) or 64),
    )


def default_top_k() -> int:
    """The configured default number of chunks a retrieval returns."""
    try:
        return int(_load_runtime_settings().get("top_k", 5) or 5)
    except Exception:
        return 5


def chunk_geometry() -> tuple[int, int]:
    """The configured ``(chunk_size, chunk_overlap)`` for indexing."""
    try:
        settings = _load_runtime_settings()
        chunk_size = settings.get("chunk_size", 512)
        chunk_overlap = settings.get("chunk_overlap", 50)
        return int(chunk_size if chunk_size is not None else 512), int(
            chunk_overlap if chunk_overlap is not None else 50
        )
    except Exception:
        return 512, 50


def image_description_limits() -> tuple[int, float]:
    """Return the configured vision-call concurrency and per-image timeout."""
    try:
        settings = _load_runtime_settings()
        concurrency = int(settings.get("image_description_concurrency", 4) or 4)
        timeout_seconds = float(settings.get("image_description_timeout_seconds", 60) or 60)
        return min(16, max(1, concurrency)), min(600.0, max(5.0, timeout_seconds))
    except Exception:
        return 4, 60.0


__all__ = [
    "HYBRID_PROFILE",
    "RetrievalConfig",
    "SUPPORTED_RETRIEVAL_PROFILES",
    "SUPPORTED_VECTOR_INDEX_TYPES",
    "VECTOR_PROFILE",
    "FLAT_VECTOR_INDEX",
    "HNSW_VECTOR_INDEX",
    "chunk_geometry",
    "default_top_k",
    "image_description_limits",
    "normalize_retrieval_profile",
    "normalize_reranker_model",
    "retrieval_config_from_env",
    "retrieval_config_from_settings",
    "vector_index_config_from_settings",
]
