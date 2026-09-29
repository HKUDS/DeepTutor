"""Rank-aware retrieval metrics for knowledge-base evaluation.

Every metric is computed at a rank cutoff ``k`` from the *hits* a case produced:
``hits[i]`` is the set of gold-passage indices the chunk at rank ``i + 1`` covers
(see :mod:`deeptutor.services.rag.eval.matching`). Working from a set per rank —
rather than a single relevant/irrelevant flag — is what lets Recall count each
gold passage once even when two chunks quote it, and lets MAP credit the rank at
which each *new* passage first appears.

No metric here calls a model: they are pure functions over rankings, so a score
is reproducible from a stored report and cannot drift with a judge's sampling.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
import math

#: A per-rank record of which gold passages that rank covered.
Hits = Sequence[Collection[int]]

#: QueryMetrics attributes in the order of :func:`metric_keys`.
_METRIC_ATTRS = ("recall", "precision", "ndcg", "mrr", "hit", "average_precision")


def metric_keys(k: int) -> tuple[str, ...]:
    """Report keys for a cutoff ``k``, in display order."""
    _require_k(k)
    return (f"recall@{k}", f"precision@{k}", f"ndcg@{k}", "mrr", f"hit@{k}", f"map@{k}")


def _require_k(k: int) -> int:
    """Validate a rank cutoff, returning it as an int."""
    value = int(k)
    if value < 1:
        raise ValueError("k must be >= 1")
    return value


def _window(hits: Hits, k: int | None) -> Sequence[Collection[int]]:
    """Truncate a ranking to the cutoff (``None`` keeps every retrieved rank)."""
    if k is None:
        return hits
    return hits[: _require_k(k)]


def hit_flags(hits: Hits, k: int | None = None) -> list[bool]:
    """Whether each rank (up to ``k``) covered at least one gold passage."""
    return [bool(matched) for matched in _window(hits, k)]


def recall_at_k(hits: Hits, gold_count: int, k: int) -> float:
    """Share of the case's gold passages retrieved within the top ``k``."""
    cutoff = _require_k(k)
    if gold_count <= 0:
        return 0.0
    found: set[int] = set()
    for matched in hits[:cutoff]:
        found.update(matched)
    return min(1.0, len(found) / gold_count)


def precision_at_k(hits: Hits, k: int) -> float:
    """Share of the retrieved chunks within ``k`` that covered a gold passage.

    The denominator is the number of chunks actually retrieved, so a short
    knowledge base is not punished for returning fewer than ``k`` chunks.
    """
    cutoff = _require_k(k)
    window = hits[:cutoff]
    if not window:
        return 0.0
    return sum(1 for matched in window if matched) / len(window)


def hit_at_k(hits: Hits, k: int) -> float:
    """``1.0`` when any gold passage reached the top ``k`` — the citation hit rate."""
    return 1.0 if any(_window(hits, k)) else 0.0


def reciprocal_rank(hits: Hits, k: int | None = None) -> float:
    """Reciprocal rank of the first chunk that covered a gold passage (MRR@k)."""
    for rank, matched in enumerate(_window(hits, k), start=1):
        if matched:
            return 1.0 / rank
    return 0.0


def average_precision(hits: Hits, gold_count: int, k: int | None = None) -> float:
    """Mean of the precision measured each time a *new* gold passage appears."""
    if gold_count <= 0:
        return 0.0
    seen: set[int] = set()
    total = 0.0
    for rank, matched in enumerate(_window(hits, k), start=1):
        fresh = {index for index in matched if index not in seen}
        if not fresh:
            continue
        seen.update(fresh)
        total += len(seen) / rank
    return min(1.0, total / gold_count)


def _dcg(gains: Sequence[float]) -> float:
    """Discounted cumulative gain with the standard ``log2(rank + 1)`` discount."""
    return sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))


def ndcg_at_k(hits: Hits, gold_count: int, k: int) -> float:
    """Binary nDCG@k — whether the gold passages are ranked near the top.

    The ideal ranking holds the case's gold passages (capped at ``k``) ahead of
    everything else, so a case whose gold is all retrieved but buried below
    irrelevant chunks scores below 1.
    """
    cutoff = _require_k(k)
    if gold_count <= 0:
        return 0.0
    gains = [1.0 if matched else 0.0 for matched in hits[:cutoff]]
    ideal_dcg = _dcg([1.0] * min(gold_count, cutoff))
    if ideal_dcg == 0:
        return 0.0
    return min(1.0, _dcg(gains) / ideal_dcg)


@dataclass(frozen=True)
class QueryMetrics:
    """One case's retrieval scores, plus the counts a report should show."""

    query_id: str
    k: int
    retrieved: int
    relevant_retrieved: int
    gold_count: int
    recall: float
    precision: float
    ndcg: float
    mrr: float
    hit: float
    average_precision: float

    def values(self) -> dict[str, float]:
        """Metric values keyed the way reports display them."""
        keys = metric_keys(self.k)
        return dict(zip(keys, (getattr(self, name) for name in _METRIC_ATTRS)))

    def to_dict(self) -> dict[str, float | int | str]:
        """Counts plus rounded metrics, ready for JSON output."""
        return {
            "query_id": self.query_id,
            "k": self.k,
            "retrieved": self.retrieved,
            "relevant_retrieved": self.relevant_retrieved,
            "gold_count": self.gold_count,
            **{key: round(value, 4) for key, value in self.values().items()},
        }


def evaluate_hits(query_id: str, hits: Hits, gold_count: int, k: int) -> QueryMetrics:
    """Score one case's ranking at cutoff ``k``."""
    cutoff = _require_k(k)
    window = hits[:cutoff]
    return QueryMetrics(
        query_id=query_id,
        k=cutoff,
        retrieved=len(hits),
        relevant_retrieved=sum(1 for matched in window if matched),
        gold_count=max(0, int(gold_count)),
        recall=recall_at_k(hits, gold_count, cutoff),
        precision=precision_at_k(hits, cutoff),
        ndcg=ndcg_at_k(hits, gold_count, cutoff),
        mrr=reciprocal_rank(hits, cutoff),
        hit=hit_at_k(hits, cutoff),
        average_precision=average_precision(hits, gold_count, cutoff),
    )


def aggregate_query_metrics(items: Sequence[QueryMetrics], k: int) -> dict[str, float | int]:
    """Macro-average the metrics of ``items`` at cutoff ``k``.

    An empty list yields zeros rather than an error, so a report always has a
    metrics block to print.
    """
    keys = metric_keys(k)
    averages = {key: 0.0 for key in keys}
    if items:
        for key, name in zip(keys, _METRIC_ATTRS):
            total = sum(getattr(item, name) for item in items)
            averages[key] = round(total / len(items), 4)
    return {**averages, "queries": len(items)}


__all__ = [
    "Hits",
    "QueryMetrics",
    "aggregate_query_metrics",
    "average_precision",
    "evaluate_hits",
    "hit_at_k",
    "hit_flags",
    "metric_keys",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
]
