"""Error normalization for LlamaIndex-backed RAG retrieval."""

from __future__ import annotations

from typing import Any, Dict


def search_error_result(query: str, exc: Exception) -> Dict[str, Any]:
    """Convert retrieval failures into actionable tool output."""
    message = str(exc)
    lower = message.lower()

    connection_failed = any(
        marker in lower
        for marker in (
            "cannot connect to",
            "connection refused",
            "all connection attempts failed",
            "cannot reach embedding api",
        )
    )
    timed_out = "timed out" in lower and any(marker in lower for marker in ("embedding", "ollama"))
    if connection_failed or timed_out:
        return {
            "query": query,
            "answer": (
                "Knowledge retrieval failed because the configured embedding "
                "service is unavailable. Check the embedding endpoint and "
                "provider, start the service if it is local, then retry. "
                f"Details: {message}"
            ),
            "content": "",
            "provider": "llamaindex",
            "error": message,
            "error_type": "embedding_connectivity",
            "log_message": "Embedding service unavailable during RAG query.",
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

    null_vector_similarity_error = (
        "unsupported operand type(s) for *" in lower and "nonetype" in lower and "float" in lower
    )
    shape_vector_error = "inhomogeneous shape" in lower or (
        "shapes" in lower and "not aligned" in lower
    )
    invalid_persisted_index = "rag index contains invalid embedding vectors" in lower
    if null_vector_similarity_error or shape_vector_error or invalid_persisted_index:
        return {
            "query": query,
            "answer": (
                "RAG search failed because this knowledge base index contains "
                "invalid embedding vectors. Re-index the knowledge base with "
                "the current embedding provider/model before querying it again."
            ),
            "content": "",
            "provider": "llamaindex",
            "error": message,
            "error_type": "invalid_embedding_index",
            "log_message": "RAG index contains invalid embedding vectors; re-index required.",
            "needs_reindex": True,
        }

    return {
        "query": query,
        "answer": f"Search failed: {message}",
        "content": "",
        "provider": "llamaindex",
        "error": message,
    }
