"""Run an evaluation set against a knowledge base and score its retrieval.

The runner drives the same search path a chat turn uses (``rag_search`` →
:class:`~deeptutor.services.rag.service.RAGService` → the KB's bound pipeline),
so a score reflects production retrieval rather than a re-implementation of it.
One case is one search; the ranked citations it returns are matched against the
case's gold passages and scored at the configured cutoff.

A case that cannot be scored — the engine raised, or it answered with an error
envelope (a missing index, a credentials failure) — is recorded as failed with
its message. Failed cases are excluded from the aggregate so an unreachable
engine reports "0 of 8 scored" instead of a misleadingly low quality score.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import logging
import time
from typing import TYPE_CHECKING, Any

from .dataset import EvalCase, EvalDataset
from .matching import MatchPolicy, RelevanceMatcher, source_text
from .metrics import QueryMetrics, evaluate_hits

if TYPE_CHECKING:  # ``report`` imports this module's result type.
    from .report import EvalReport

logger = logging.getLogger(__name__)

#: Search callable shaped like :func:`deeptutor.tools.rag_tool.rag_search`.
SearchFn = Callable[..., Awaitable[dict[str, Any]]]
#: Progress hook: ``(index, total, evaluation)`` after each case.
ProgressFn = Callable[[int, int, "QueryEvaluation"], None]

#: The engine returned ranked citations.
SOURCE_MODE_CITATIONS = "sources"
#: The engine returned context but no citations; the context is scored as one span.
SOURCE_MODE_CONTEXT = "content"


@dataclass(frozen=True)
class QueryEvaluation:
    """One case's retrieval result, its ranked hits, and its metrics."""

    case_id: str
    query: str
    k: int
    gold_count: int
    hits: tuple[frozenset[int], ...]
    metrics: QueryMetrics
    source_mode: str = SOURCE_MODE_CITATIONS
    provider: str = ""
    error: str = ""
    sources: tuple[dict[str, Any], ...] = ()

    @property
    def failed(self) -> bool:
        """True when the case could not be scored (error or failed engine)."""
        return bool(self.error)

    def to_dict(self) -> dict[str, Any]:
        """Serializable form, including which gold passages were covered."""
        return {
            "case_id": self.case_id,
            "query": self.query,
            "error": self.error,
            "provider": self.provider,
            "source_mode": self.source_mode,
            "matched_gold": [sorted(indices) for indices in self.hits],
            **self.metrics.to_dict(),
        }


def _extract_sources(result: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Pull the ranked citations out of a search result.

    Engines that offload retrieval (LightRAG server, WeKnora, IMA) and the local
    ones all normalize to ``sources``. An engine that answers with context but no
    citations is scored on that context as a single span, so the case still says
    whether the material came back at all.
    """
    raw = result.get("sources")
    if isinstance(raw, list):
        records = [item for item in raw if isinstance(item, Mapping)]
        if records:
            return [dict(record) for record in records], SOURCE_MODE_CITATIONS

    content = result.get("content") or result.get("answer") or ""
    if isinstance(content, str) and content.strip():
        return [{"content": content}], SOURCE_MODE_CONTEXT
    return [], SOURCE_MODE_CITATIONS


def _error_message(result: Mapping[str, Any]) -> str:
    """The engine's own failure text, or an empty string when the search worked."""
    if result.get("needs_reindex"):
        message = (
            result.get("answer") or result.get("content") or "Knowledge base needs re-indexing."
        )
        return str(message)
    if result.get("error_type"):
        message = result.get("answer") or result.get("content") or result["error_type"]
        return str(message)
    return ""


async def _default_search(
    query: str,
    *,
    kb_name: str,
    kb_base_dir: str | None,
    mode: str | None,
    top_k: int,
) -> dict[str, Any]:
    """Retrieve through the production path (``rag_search`` → the bound pipeline)."""
    from deeptutor.tools.rag_tool import rag_search

    kwargs: dict[str, Any] = {"top_k": top_k}
    if mode:
        kwargs["mode"] = mode
    return await rag_search(query=query, kb_name=kb_name, kb_base_dir=kb_base_dir, **kwargs)


class RetrievalEvaluator:
    """Score a knowledge base against an evaluation set.

    Args:
        kb_name: The knowledge base to search.
        kb_base_dir: KB root to search; ``None`` resolves the caller's workspace.
        k: Rank cutoff for every metric.
        mode: Search mode for engines that support one (e.g. ``hybrid``);
            ``None`` leaves each engine on its own default.
        query_limit: Evaluate only the first N cases.
        policy: Gold-matching thresholds; defaults to :class:`MatchPolicy`.
        search_fn: Search callable override, for tests and embedders.
        provider: Provider label for the report; a search result's own
            ``provider`` still wins per case.

    Raises:
        ValueError: ``kb_name`` is empty or ``k`` is below 1.
    """

    def __init__(
        self,
        *,
        kb_name: str,
        kb_base_dir: str | None = None,
        k: int = 5,
        mode: str | None = None,
        query_limit: int | None = None,
        policy: MatchPolicy | None = None,
        search_fn: SearchFn | None = None,
        provider: str = "",
    ) -> None:
        self.kb_name = (kb_name or "").strip()
        if not self.kb_name:
            raise ValueError("kb_name must be a non-empty string")
        self.k = int(k)
        if self.k < 1:
            raise ValueError("k must be >= 1")
        self.kb_base_dir = kb_base_dir
        self.mode = mode or None
        self.query_limit = query_limit if query_limit and query_limit > 0 else None
        self.policy = policy or MatchPolicy()
        self.search_fn: SearchFn = search_fn or _default_search
        self.provider = provider

    async def evaluate(
        self,
        dataset: EvalDataset,
        *,
        progress: ProgressFn | None = None,
    ) -> EvalReport:
        """Score every case and return the report defined in ``...eval.report``."""
        from .report import EvalReport

        cases = dataset.limited(self.query_limit).cases
        started = time.monotonic()
        evaluations: list[QueryEvaluation] = []
        for index, case in enumerate(cases, start=1):
            evaluation = await self.evaluate_case(case)
            evaluations.append(evaluation)
            if evaluation.failed:
                logger.warning(
                    "Evaluation case %s could not be scored: %s", case.id, evaluation.error
                )
            if progress is not None:
                progress(index, len(cases), evaluation)

        return EvalReport(
            dataset_name=dataset.name,
            kb_name=self.kb_name,
            provider=self.provider,
            k=self.k,
            mode=self.mode,
            policy=self.policy,
            evaluations=tuple(evaluations),
            duration_seconds=time.monotonic() - started,
        )

    async def evaluate_case(self, case: EvalCase) -> QueryEvaluation:
        """Search one case and score the citations it came back with."""
        matcher = RelevanceMatcher(case.gold, self.policy)
        try:
            result = await self.search_fn(
                query=case.query,
                kb_name=self.kb_name,
                kb_base_dir=self.kb_base_dir,
                mode=self.mode,
                top_k=self.k,
            )
        except Exception as exc:
            return self._failure(case, matcher, f"{type(exc).__name__}: {exc}")

        if not isinstance(result, Mapping):
            kind = type(result).__name__
            return self._failure(case, matcher, f"unexpected search result {kind}")

        error = _error_message(result)
        if error:
            return self._failure(case, matcher, error)

        sources, source_mode = _extract_sources(result)
        hits = tuple(
            frozenset(matcher.match(source_text(source)).indices) for source in sources[: self.k]
        )
        return QueryEvaluation(
            case_id=case.id,
            query=case.query,
            k=self.k,
            gold_count=matcher.gold_count,
            hits=hits,
            metrics=evaluate_hits(case.id, hits, matcher.gold_count, self.k),
            source_mode=source_mode,
            provider=str(result.get("provider") or self.provider),
            sources=tuple(sources),
        )

    def _failure(self, case: EvalCase, matcher: RelevanceMatcher, message: str) -> QueryEvaluation:
        """Record a case that could not be scored, with zeroed metrics."""
        return QueryEvaluation(
            case_id=case.id,
            query=case.query,
            k=self.k,
            gold_count=matcher.gold_count,
            hits=(),
            metrics=evaluate_hits(case.id, (), matcher.gold_count, self.k),
            provider=self.provider,
            error=message,
        )


async def evaluate_dataset(
    dataset: EvalDataset,
    *,
    kb_name: str,
    kb_base_dir: str | None = None,
    k: int = 5,
    mode: str | None = None,
    query_limit: int | None = None,
    policy: MatchPolicy | None = None,
    search_fn: SearchFn | None = None,
    provider: str = "",
    progress: ProgressFn | None = None,
) -> EvalReport:
    """Score one dataset against one knowledge base (see :class:`RetrievalEvaluator`)."""
    evaluator = RetrievalEvaluator(
        kb_name=kb_name,
        kb_base_dir=kb_base_dir,
        k=k,
        mode=mode,
        query_limit=query_limit,
        policy=policy,
        search_fn=search_fn,
        provider=provider,
    )
    return await evaluator.evaluate(dataset, progress=progress)


__all__ = [
    "ProgressFn",
    "QueryEvaluation",
    "RetrievalEvaluator",
    "SearchFn",
    "SOURCE_MODE_CITATIONS",
    "SOURCE_MODE_CONTEXT",
    "evaluate_dataset",
]
