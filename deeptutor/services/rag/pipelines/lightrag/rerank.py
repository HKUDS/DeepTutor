"""Local cross-encoder adapter for LightRAG's index-based reranking callback."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from anyio import CapacityLimiter, to_process
from anyio.lowlevel import RunVar

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

_limiter: RunVar[CapacityLimiter] = RunVar("lightrag_reranker_limiter")


@lru_cache(maxsize=1)
def _load_model(model_name: str) -> CrossEncoder:
    from sentence_transformers import CrossEncoder
    from torch import nn

    # LightRAG applies a minimum relevance score to the returned candidates.
    return CrossEncoder(model_name, default_activation_function=nn.Sigmoid())


def _rank(model_name: str, query: str, documents: list[str], top_n: int | None) -> list[dict]:
    hits = _load_model(model_name).rank(query, documents, top_k=top_n, show_progress_bar=False)
    return [
        {"index": int(hit["corpus_id"]), "relevance_score": float(hit["score"])} for hit in hits
    ]


async def rerank_documents(
    model_name: str, query: str, documents: list[str], top_n: int | None = None
) -> list[dict]:
    """Score candidates in a reusable worker so Torch stays outside the API process."""
    limiter = _limiter.get(None)
    if limiter is None:
        limiter = CapacityLimiter(1)
        _limiter.set(limiter)
    return await to_process.run_sync(
        _rank, model_name, query, documents, top_n, cancellable=True, limiter=limiter
    )
