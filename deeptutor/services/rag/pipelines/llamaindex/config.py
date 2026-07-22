"""Configuration helpers for DeepTutor's LlamaIndex RAG pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import os

VECTOR_PROFILE = "vector"
HYBRID_PROFILE = "hybrid"
SUPPORTED_RETRIEVAL_PROFILES = {VECTOR_PROFILE, HYBRID_PROFILE}


@dataclass(frozen=True)
class RetrievalConfig:
    """Runtime retrieval knobs for the LlamaIndex pipeline."""

    profile: str = HYBRID_PROFILE
    vector_top_k_multiplier: int = 2
    bm25_top_k_multiplier: int = 2
    fusion_num_queries: int = 1

    def candidate_top_k(self, top_k: int, multiplier: int) -> int:
        """Return the number of candidates to ask a child retriever for."""
        requested = max(1, int(top_k))
        return max(requested, requested * max(1, int(multiplier)))


def normalize_retrieval_profile(value: str | None) -> str:
    """Return a supported retrieval profile, defaulting to hybrid."""
    profile = (value or "").strip().lower()
    if profile in SUPPORTED_RETRIEVAL_PROFILES:
        return profile
    return HYBRID_PROFILE


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


__all__ = [
    "HYBRID_PROFILE",
    "RetrievalConfig",
    "SUPPORTED_RETRIEVAL_PROFILES",
    "VECTOR_PROFILE",
    "chunk_geometry",
    "default_top_k",
    "normalize_retrieval_profile",
    "retrieval_config_from_env",
    "retrieval_config_from_settings",
]
