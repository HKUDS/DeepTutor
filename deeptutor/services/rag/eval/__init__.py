"""Retrieval-quality evaluation for knowledge bases.

``deeptutor kb eval`` scores a knowledge base against a QA set: each case pairs a
query with the gold passages an ideal retrieval should return, and the run reports
Recall@k, Precision@k, nDCG@k, MRR, MAP and Hit@k. The metrics are pure functions
over the ranking — no model judges the output — so a score is reproducible, cheap
to recompute, and comparable across engines, embedding models and retrieval
settings. That is what makes the set usable as a regression gate: record a
baseline with ``--save``, change a setting, and diff the metrics.

Nothing here writes to a knowledge base or mutates its index; evaluation only
reads through the same search path a chat turn uses.

Example:
    >>> from deeptutor.services.rag.eval import EvalDataset, evaluate_dataset
    >>> dataset = EvalDataset.from_cases(
    ...     [{"query": "What is attention?", "gold": ["Attention weighs each token."]}]
    ... )
    >>> report = await evaluate_dataset(dataset, kb_name="ml-notes", k=5)
    >>> report.aggregate()["recall@5"]
"""

from .dataset import EvalCase, EvalDataset, EvalDatasetError, load_dataset
from .matching import (
    DEFAULT_MIN_RATIO,
    DEFAULT_MIN_TOKENS,
    MatchPolicy,
    MatchResult,
    RelevanceMatcher,
    normalize_text,
    source_text,
)
from .metrics import (
    QueryMetrics,
    aggregate_query_metrics,
    average_precision,
    evaluate_hits,
    hit_at_k,
    hit_flags,
    metric_keys,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from .report import EvalReport, format_metric
from .runner import (
    SOURCE_MODE_CITATIONS,
    SOURCE_MODE_CONTEXT,
    ProgressFn,
    QueryEvaluation,
    RetrievalEvaluator,
    evaluate_dataset,
)

__all__ = [
    "DEFAULT_MIN_RATIO",
    "DEFAULT_MIN_TOKENS",
    "EvalCase",
    "EvalDataset",
    "EvalDatasetError",
    "EvalReport",
    "MatchPolicy",
    "MatchResult",
    "ProgressFn",
    "QueryEvaluation",
    "QueryMetrics",
    "RelevanceMatcher",
    "RetrievalEvaluator",
    "SOURCE_MODE_CITATIONS",
    "SOURCE_MODE_CONTEXT",
    "aggregate_query_metrics",
    "average_precision",
    "evaluate_dataset",
    "evaluate_hits",
    "format_metric",
    "hit_at_k",
    "hit_flags",
    "load_dataset",
    "metric_keys",
    "ndcg_at_k",
    "normalize_text",
    "precision_at_k",
    "recall_at_k",
    "reciprocal_rank",
    "source_text",
]
