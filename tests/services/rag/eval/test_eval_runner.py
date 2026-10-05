"""Tests for the retrieval-evaluation runner."""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

from deeptutor.services.rag.eval import (
    EvalDataset,
    MatchPolicy,
    RetrievalEvaluator,
    evaluate_dataset,
)
from deeptutor.services.rag.eval import runner as runner_module

GOLD = "alpha beta gamma delta epsilon zeta"
UNRELATED = "boiling pasta needs salted water"


def _dataset(*queries: str, gold: str = GOLD, **kwargs: Any) -> EvalDataset:
    return EvalDataset.from_cases(
        [{"query": query, "gold": [gold]} for query in queries],
        **kwargs,
    )


def _sources(*texts: str) -> dict[str, Any]:
    return {"sources": [{"content": text} for text in texts], "provider": "fake"}


class _Recorder:
    """Async search stand-in that records its calls and replays canned results."""

    def __init__(self, *results: Any) -> None:
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        result = self.results[min(len(self.calls) - 1, len(self.results) - 1)]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.asyncio
async def test_matching_citations_score_a_full_recall() -> None:
    search = _Recorder(_sources(f"{GOLD} and more text", UNRELATED))

    report = await evaluate_dataset(_dataset("what is alpha"), kb_name="kb", k=5, search_fn=search)

    evaluation = report.evaluations[0]
    assert evaluation.hits[0] == frozenset({0})
    assert evaluation.metrics.recall == 1.0
    assert evaluation.metrics.mrr == 1.0
    assert evaluation.provider == "fake"
    assert evaluation.source_mode == "sources"
    assert not evaluation.failed


@pytest.mark.asyncio
async def test_search_receives_the_kb_mode_and_cutoff() -> None:
    search = _Recorder(_sources(GOLD))

    await evaluate_dataset(
        _dataset("q"),
        kb_name="physics",
        kb_base_dir="/tmp/kbs",
        k=3,
        mode="hybrid",
        search_fn=search,
    )

    assert search.calls == [
        {
            "query": "q",
            "kb_name": "physics",
            "kb_base_dir": "/tmp/kbs",
            "mode": "hybrid",
            "top_k": 3,
        }
    ]


def test_default_search_only_forwards_a_mode_when_one_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    captured: list[dict[str, Any]] = []

    async def fake_search(**kwargs: Any) -> dict[str, Any]:
        captured.append(kwargs)
        return {}

    module = types.ModuleType("deeptutor.tools.rag_tool")
    module.rag_search = fake_search  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deeptutor.tools.rag_tool", module)

    asyncio.run(
        runner_module._default_search("q", kb_name="kb", kb_base_dir=None, mode=None, top_k=2)
    )
    asyncio.run(
        runner_module._default_search("q", kb_name="kb", kb_base_dir=None, mode="hybrid", top_k=2)
    )

    assert captured[0] == {"query": "q", "kb_name": "kb", "kb_base_dir": None, "top_k": 2}
    assert captured[1]["mode"] == "hybrid"


@pytest.mark.asyncio
async def test_missing_citations_score_zero_but_stay_scored() -> None:
    search = _Recorder(_sources(UNRELATED))

    report = await evaluate_dataset(_dataset("q"), kb_name="kb", k=5, search_fn=search)

    evaluation = report.evaluations[0]
    assert not evaluation.failed
    assert evaluation.metrics.recall == 0.0
    assert report.aggregate()["queries_scored"] == 1


@pytest.mark.asyncio
async def test_an_engine_error_envelope_is_recorded_and_excluded_from_the_means() -> None:
    search = _Recorder(
        {"error_type": "embedding_error", "answer": "Embedding API key not set"},
        _sources(GOLD),
    )

    report = await evaluate_dataset(_dataset("q1", "q2"), kb_name="kb", k=5, search_fn=search)

    failed = report.evaluations[0]
    assert failed.failed
    assert "Embedding API key not set" in failed.error
    assert failed.metrics.recall == 0.0

    summary = report.aggregate()
    assert summary["queries_scored"] == 1
    assert summary["queries_failed"] == 1
    assert summary["recall@5"] == 1.0


@pytest.mark.asyncio
async def test_a_missing_index_is_reported_as_a_failed_case() -> None:
    search = _Recorder({"needs_reindex": True, "answer": "This knowledge base has no index."})

    report = await evaluate_dataset(_dataset("q"), kb_name="kb", k=5, search_fn=search)

    evaluation = report.evaluations[0]
    assert evaluation.failed
    assert "no index" in evaluation.error


@pytest.mark.asyncio
async def test_a_raised_search_error_is_captured_with_its_type() -> None:
    search = _Recorder(RuntimeError("connection reset"))

    report = await evaluate_dataset(_dataset("q"), kb_name="kb", k=5, search_fn=search)

    evaluation = report.evaluations[0]
    assert evaluation.failed
    assert evaluation.error == "RuntimeError: connection reset"


@pytest.mark.asyncio
async def test_a_non_mapping_result_is_reported_rather_than_crashing() -> None:
    search = _Recorder("not a result")

    report = await evaluate_dataset(_dataset("q"), kb_name="kb", k=5, search_fn=search)

    assert report.evaluations[0].failed
    assert "unexpected search result str" in report.evaluations[0].error


@pytest.mark.asyncio
async def test_context_without_citations_is_scored_as_one_span() -> None:
    search = _Recorder({"content": f"prefix {GOLD} suffix", "provider": "graphrag"})

    report = await evaluate_dataset(_dataset("q"), kb_name="kb", k=5, search_fn=search)

    evaluation = report.evaluations[0]
    assert evaluation.source_mode == "content"
    assert evaluation.hits[0] == frozenset({0})
    assert evaluation.metrics.recall == 1.0


@pytest.mark.asyncio
async def test_hits_are_capped_at_the_cutoff() -> None:
    search = _Recorder(_sources(UNRELATED, GOLD))

    report = await evaluate_dataset(_dataset("q"), kb_name="kb", k=1, search_fn=search)

    evaluation = report.evaluations[0]
    assert len(evaluation.hits) == 1
    assert evaluation.metrics.recall == 0.0
    assert evaluation.metrics.hit == 0.0


@pytest.mark.asyncio
async def test_query_limit_shortens_the_run_and_drives_progress() -> None:
    search = _Recorder(_sources(GOLD))
    seen: list[tuple[int, int, str]] = []

    def progress(index: int, total: int, evaluation: Any) -> None:
        seen.append((index, total, evaluation.case_id))

    report = await evaluate_dataset(
        _dataset("q1", "q2", "q3"),
        kb_name="kb",
        k=5,
        query_limit=2,
        search_fn=search,
        progress=progress,
    )

    assert len(report.evaluations) == 2
    assert len(search.calls) == 2
    assert seen == [(1, 2, "q1"), (2, 2, "q2")]


@pytest.mark.asyncio
async def test_case_ids_and_queries_are_carried_into_the_report() -> None:
    search = _Recorder(_sources(GOLD))

    report = await evaluate_dataset(
        _dataset("first question", "second question"), kb_name="kb", k=5, search_fn=search
    )

    assert [item.case_id for item in report.evaluations] == ["q1", "q2"]
    assert [item.query for item in report.evaluations] == ["first question", "second question"]


def test_evaluator_rejects_an_unusable_cutoff_or_kb_name() -> None:
    with pytest.raises(ValueError):
        RetrievalEvaluator(kb_name="kb", k=0)
    with pytest.raises(ValueError):
        RetrievalEvaluator(kb_name="   ")


@pytest.mark.asyncio
async def test_a_custom_match_policy_flows_through_the_run() -> None:
    search = _Recorder(_sources("alpha beta gamma iota"))

    report = await evaluate_dataset(
        _dataset("q", gold="alpha beta gamma delta"),
        kb_name="kb",
        k=5,
        policy=MatchPolicy(min_ratio=0.5, min_tokens=3),
        search_fn=search,
    )

    assert report.policy.min_tokens == 3
    assert report.evaluations[0].metrics.recall == 1.0
