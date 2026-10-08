"""Tests for the retrieval-evaluation report."""

from __future__ import annotations

import json

from deeptutor.services.rag.eval import (
    EvalReport,
    MatchPolicy,
    QueryEvaluation,
    evaluate_hits,
    format_metric,
)

K = 5


def _scored(case_id: str = "q1", query: str = "what is alpha", hits=({0},), gold_count: int = 1):
    return QueryEvaluation(
        case_id=case_id,
        query=query,
        k=K,
        gold_count=gold_count,
        hits=hits,
        metrics=evaluate_hits(case_id, hits, gold_count, K),
        provider="llamaindex",
    )


def _failed(case_id: str = "q2", error: str = "RuntimeError: connection reset"):
    return QueryEvaluation(
        case_id=case_id,
        query="what is beta",
        k=K,
        gold_count=1,
        hits=(),
        metrics=evaluate_hits(case_id, (), 1, K),
        error=error,
    )


def _report(*evaluations: QueryEvaluation) -> EvalReport:
    return EvalReport(
        dataset_name="physics-ch1",
        kb_name="textbook",
        provider="llamaindex",
        k=K,
        mode="hybrid",
        policy=MatchPolicy(),
        evaluations=evaluations,
        duration_seconds=1.234,
    )


def test_aggregate_means_the_scored_cases_only() -> None:
    summary = _report(_scored(), _failed()).aggregate()

    assert summary["queries"] == 1
    assert summary["queries_scored"] == 1
    assert summary["queries_failed"] == 1
    assert summary["recall@5"] == 1.0
    assert summary["mrr"] == 1.0


def test_a_report_of_only_failures_still_aggregates() -> None:
    summary = _report(_failed()).aggregate()

    assert summary["queries_scored"] == 0
    assert summary["queries_failed"] == 1
    assert summary["recall@5"] == 0.0


def test_to_dict_carries_the_run_context_and_per_case_detail() -> None:
    payload = _report(_scored(query="什么是注意力"), _failed()).to_dict()

    assert payload["dataset"] == "physics-ch1"
    assert payload["kb"] == "textbook"
    assert payload["provider"] == "llamaindex"
    assert payload["k"] == K
    assert payload["mode"] == "hybrid"
    assert payload["duration_seconds"] == 1.23
    assert payload["match_policy"] == {"min_ratio": 0.5, "min_tokens": 4}

    scored, failed = payload["queries"]
    assert scored["matched_gold"] == [[0]]
    assert scored["context_only"] is False
    assert scored["query"] == "什么是注意力"
    assert failed["error"] == "RuntimeError: connection reset"
    assert failed["matched_gold"] == []


def test_to_json_round_trips_and_keeps_unicode_readable() -> None:
    report = _report(_scored(query="什么是注意力"))

    text = report.to_json()

    assert "什么是注意力" in text
    assert json.loads(text) == report.to_dict()


def test_metric_columns_and_cells_match_the_cutoff() -> None:
    report = _report(_scored(hits=({}, {0}), gold_count=2))

    assert report.metric_columns() == ("recall@5", "precision@5", "ndcg@5", "mrr", "hit@5", "map@5")
    cells = report.format_metrics(report.evaluations[0])

    assert cells["recall@5"] == "0.500"
    assert cells["mrr"] == "0.500"
    assert cells["hit@5"] == "1.000"


def test_summary_lines_describe_the_run_and_the_metrics() -> None:
    lines = _report(_scored(), _failed()).summary_lines()

    joined = "\n".join(lines)
    assert "kb: textbook" in joined
    assert "provider: llamaindex" in joined
    assert "k: 5  mode: hybrid" in joined
    assert "cases: 2  scored: 1  failed: 1" in joined
    assert "recall@5=1.000" in joined
    assert "excluded from the means" in joined


def test_summary_lines_omit_the_failure_note_when_every_case_scored() -> None:
    joined = "\n".join(_report(_scored()).summary_lines())

    assert "excluded from the means" not in joined
    assert "failed: 0" in joined


def test_mode_falls_back_to_the_engine_default_in_the_summary() -> None:
    report = EvalReport(
        dataset_name="set",
        kb_name="kb",
        provider="",
        k=K,
        mode=None,
        policy=MatchPolicy(),
        evaluations=(),
    )

    joined = "\n".join(report.summary_lines())

    assert "mode: engine default" in joined
    assert "provider: unknown" in joined


def test_format_metric_uses_three_decimals() -> None:
    assert format_metric(1) == "1.000"
    assert format_metric(0.5) == "0.500"
    assert format_metric(0.12345) == "0.123"
