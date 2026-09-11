"""Optional cross-encoder reranking for the LlamaIndex pipeline."""

from __future__ import annotations

from collections import OrderedDict
import logging
import math
from threading import Lock
from typing import Any, Callable

from llama_index.core.schema import MetadataMode, NodeWithScore

logger = logging.getLogger(__name__)

_RERANKER_CACHE: "OrderedDict[str, Any]" = OrderedDict()
_RERANKER_CACHE_LOCK = Lock()
_RERANKER_CACHE_MAXSIZE = 2


def clear_reranker_cache() -> None:
    """Drop cached reranker models (used by tests and settings changes)."""
    with _RERANKER_CACHE_LOCK:
        _RERANKER_CACHE.clear()


def _load_cross_encoder(model_name: str) -> Any:
    """Load a SentenceTransformers cross-encoder lazily."""
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name)


def _cross_encoder(
    model_name: str,
    loader: Callable[[str], Any] | None = None,
) -> Any | None:
    with _RERANKER_CACHE_LOCK:
        cached = _RERANKER_CACHE.get(model_name)
        if cached is not None:
            _RERANKER_CACHE.move_to_end(model_name)
            return cached

    try:
        model = (loader or _load_cross_encoder)(model_name)
    except ImportError:
        logger.warning(
            "Reranker model %r is configured, but sentence-transformers is not installed; "
            "using embedding retrieval unchanged.",
            model_name,
        )
        return None
    except Exception as exc:
        logger.warning(
            "Failed to load reranker model %r; using embedding retrieval unchanged: %s",
            model_name,
            exc,
        )
        return None

    with _RERANKER_CACHE_LOCK:
        _RERANKER_CACHE[model_name] = model
        _RERANKER_CACHE.move_to_end(model_name)
        while len(_RERANKER_CACHE) > _RERANKER_CACHE_MAXSIZE:
            _RERANKER_CACHE.popitem(last=False)
    return model


def _sigmoid(value: float) -> float:
    """Convert cross-encoder logits to a stable 0..1 source score."""
    try:
        if value >= 0:
            return 1.0 / (1.0 + math.exp(-value))
        exp_value = math.exp(value)
        return exp_value / (1.0 + exp_value)
    except (OverflowError, ValueError):
        return 1.0 if value > 0 else 0.0


def _identity_logits(scores: Any) -> Any:
    """Request raw cross-encoder logits from SentenceTransformers."""
    return scores


def rerank_nodes(
    query: str,
    nodes: list[Any],
    *,
    top_k: int,
    model_name: str,
    loader: Callable[[str], Any] | None = None,
) -> list[Any]:
    """Rerank LlamaIndex results and return at most ``top_k`` nodes.

    Missing optional dependencies and model-load failures are non-fatal: the
    first-stage ordering is returned so saved knowledge remains searchable.
    """
    requested = max(1, int(top_k))
    if not query or not nodes or not model_name:
        return nodes[:requested]

    model = _cross_encoder(model_name, loader)
    if model is None:
        return nodes[:requested]

    pairs = [(query, result.node.get_content(metadata_mode=MetadataMode.LLM)) for result in nodes]
    try:
        raw_scores = model.predict(pairs, activation_fct=_identity_logits)
        ranked = sorted(
            (
                (index, float(score))
                for index, score in enumerate(raw_scores)
                if math.isfinite(float(score))
            ),
            key=lambda item: item[1],
            reverse=True,
        )[:requested]
    except Exception as exc:
        logger.warning(
            "Reranker model %r failed while scoring %d candidates; "
            "using embedding retrieval unchanged: %s",
            model_name,
            len(nodes),
            exc,
        )
        return nodes[:requested]

    return [NodeWithScore(node=nodes[index].node, score=_sigmoid(score)) for index, score in ranked]


__all__ = ["clear_reranker_cache", "rerank_nodes"]
