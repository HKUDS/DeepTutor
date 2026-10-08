"""Error normalization for LlamaIndex-backed RAG retrieval."""

from __future__ import annotations

from typing import Any, Dict


def _invalid_index_reason(message: str) -> str:
    """Extract the persisted-store failure reason recorded by the loader."""
    _, _, detail = message.partition("Details: ")
    if not detail:
        return ""
    return detail.split(". ", 1)[0].rstrip(".")


def search_error_result(query: str, exc: Exception) -> Dict[str, Any]:
    """Convert retrieval failures into actionable tool output."""
    message = str(exc)
    lower = message.lower()

    null_vector_similarity_error = (
        "unsupported operand type(s) for *" in lower and "nonetype" in lower and "float" in lower
    )
    shape_vector_error = "inhomogeneous shape" in lower or (
        "shapes" in lower and "not aligned" in lower
    )
    invalid_persisted_index = "rag index contains invalid embedding vectors" in lower
    if invalid_persisted_index or null_vector_similarity_error or shape_vector_error:
        # Classify the persisted-index diagnosis before the provider-response
        # branch so its "Details:" tail about stored vectors is never treated
        # as a live provider failure (issue #440).
        reason = _invalid_index_reason(message)
        reason_clause = f" ({reason})" if reason else ""
        return {
            "query": query,
            "answer": (
                "RAG search failed because this knowledge base index contains "
                f"invalid embedding vectors{reason_clause}. Re-index the "
                "knowledge base with the current embedding provider/model "
                "before querying it again: open the knowledge base page and "
                "run its 'Re-index' action (Index versions → Re-index). "
                "Re-uploading documents reuses the damaged index and cannot "
                "repair it."
            ),
            "content": "",
            "provider": "llamaindex",
            "error": message,
            "error_type": "invalid_embedding_index",
            "log_message": "RAG index contains invalid embedding vectors; re-index required.",
            "needs_reindex": True,
        }

    if "embedding provider returned invalid" in lower:
        return {
            "query": query,
            "answer": (
                "RAG search failed because the embedding provider returned an "
                f"invalid query vector: {message}"
            ),
            "content": "",
            "provider": "llamaindex",
            "error": message,
            "error_type": "invalid_embedding_provider_response",
            "log_message": (
                "Embedding provider returned an invalid query vector; check "
                "the embedding provider/model configuration."
            ),
        }

    return {
        "query": query,
        "answer": f"Search failed: {message}",
        "content": "",
        "provider": "llamaindex",
        "error": message,
    }
