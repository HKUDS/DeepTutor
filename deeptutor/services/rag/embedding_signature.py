"""Embedding-signature helpers for RAG index version selection."""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.services.rag.index_versioning import EmbeddingSignature

logger = logging.getLogger(__name__)

LLAMAINDEX_INGESTION_SCHEMA_VERSION = "2"
LLAMAINDEX_VISUAL_MAPPING_VERSION = "1"
LLAMAINDEX_DESCRIPTION_PROMPT_VERSION = "2"


def signature_from_config(config: Any) -> EmbeddingSignature:
    """Build a stable RAG index signature from an embedding config object."""
    return EmbeddingSignature(
        binding=(getattr(config, "binding", "") or "").strip().lower(),
        model=(getattr(config, "model", "") or "").strip(),
        dimension=int(getattr(config, "dim", 0) or 0),
        base_url=(
            getattr(config, "effective_url", None) or getattr(config, "base_url", None) or ""
        ).strip(),
        api_version=(getattr(config, "api_version", "") or "").strip(),
    )


def signature_from_embedding_config() -> EmbeddingSignature | None:
    """Compute the signature for the currently-active embedding config."""
    try:
        from deeptutor.services.embedding import get_embedding_config
    except Exception:  # pragma: no cover - import error
        return None

    try:
        return signature_from_config(get_embedding_config())
    except Exception as exc:
        logger.debug(f"Cannot resolve embedding signature: {exc}")
        return None


def with_llamaindex_schema(signature: EmbeddingSignature | None) -> EmbeddingSignature | None:
    """Attach the LlamaIndex node-contract versions to an embedding signature."""
    if signature is None:
        return None
    fields = ("binding", "model", "dimension", "base_url", "api_version")
    if not all(hasattr(signature, field) for field in fields):
        # Some callers/tests provide a hash-only signature object. Preserve that
        # backward-compatible protocol; real embedding signatures carry fields.
        return signature
    return EmbeddingSignature(
        binding=signature.binding,
        model=signature.model,
        dimension=signature.dimension,
        base_url=signature.base_url,
        api_version=signature.api_version,
        ingestion_schema_version=LLAMAINDEX_INGESTION_SCHEMA_VERSION,
        visual_mapping_version=LLAMAINDEX_VISUAL_MAPPING_VERSION,
        description_prompt_version=LLAMAINDEX_DESCRIPTION_PROMPT_VERSION,
    )


def llamaindex_signature_from_embedding_config() -> EmbeddingSignature | None:
    """Compute the active embedding signature plus LlamaIndex ingestion schema."""
    return with_llamaindex_schema(signature_from_embedding_config())


def embedding_meta_fields() -> dict[str, Any]:
    """Embedding identity fields to stamp into a version's ``meta.json``.

    LlamaIndex versions already record the full signature; the graph engines
    (GraphRAG/LightRAG) use a synthetic provider signature, so they stamp these
    extra fields at build time. The probe used when *linking* an external index
    reads them to verify the index was built with a compatible embedding model
    — without which graph engines fail retrieval silently on a mismatch.
    """
    signature = signature_from_embedding_config()
    if signature is None:
        return {}
    return {
        "embedding_signature": signature.hash(),
        "embedding_model": signature.model,
        "embedding_dim": signature.dimension,
    }
