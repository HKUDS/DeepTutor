"""Tests for the retrieval metrics."""

from __future__ import annotations

import pytest

from deeptutor.services.rag.eval import (
    aggregate_query_metrics,
    evaluate_hits,
    hit_flags,
    metric_keys,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_perfect_ranking_scores_one_across_the_board() -> None:
    hits = ({0}, {1})

    assert recall_at_k(hits, 2, 2) == 1.0
    assert precision_at_k(hits, 2) == 1.0
    assert ndcg_at_k(hits, 2, 2) == 1.0
    assert reciprocal_rank(hits, 2) == 1.0

    metrics = evaluate_hits("q1", hits, 2, 2)

    assert metrics.hit == 1.0
    assert metrics.average_precision == 1.0
    assert metrics.relevant_retrieved == 2
    assert metrics.retrieved == 2


def test_first_gold_at_rank_three_discounts_every_ranked_metric() -> None:
    hits = ({}, {}, {0})

    assert recall_at_k(hits, 1, 5) == 1.0
    assert precision_at_k(hits, 5) == pytest.approx(1 / 3)
    assert reciprocal_rank(hits, 5) == pytest.approx(1 / 3)
    assert ndcg_at_k(hits, 1, 5) == pytest.approx(0.5)
    assert evaluate_hits("q1", hits, 1, 5).average_precision == pytest.approx(1 / 3)


def test_ranking_without_any_gold_scores_zero() -> None:
    hits = ({}, {})

    assert recall_at_k(hits, 1, 5) == 0.0
    assert precision_at_k(hits, 5) == 0.0
    assert ndcg_at_k(hits, 1, 5) == 0.0
    assert reciprocal_rank(hits, 5) == 0.0
    assert evaluate_hits("q1", hits, 1, 5).hit == 0.0


def test_metrics_ignore_gold_below_the_cutoff() -> None:
    hits = ({}, {}, {}, {}, {0})
    metrics = evaluate_hits("q1", hits, 1, 3)

    assert metrics.retrieved == 5
    assert metrics.recall == 0.0
    assert metrics.ndcg == 0.0
    assert metrics.mrr == 0.0
    assert metrics.hit == 0.0


def test_repeated_coverage_of_one_gold_cannot_exceed_one() -> None:
    hits = ({0}, {0})
    metrics = evaluate_hits("q1", hits, 1, 2)

    assert metrics.recall == 1.0
    assert metrics.ndcg == 1.0
    assert metrics.average_precision == 1.0
    assert metrics.precision == 1.0


def test_partial_recall_averages_over_the_gold_pool() -> None:
    hits = ({0}, {})
    metrics = evaluate_hits("q1", hits, 2, 2)

    assert metrics.recall == 0.5
    assert metrics.precision == 0.5
    assert metrics.average_precision == 0.5
    assert metrics.ndcg == pytest.approx(0.6131, abs=1e-4)


def test_precision_uses_the_retrieved_count_not_the_cutoff() -> None:
    hits = ({0},)
    metrics = evaluate_hits("q1", hits, 1, 5)

    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.hit == 1.0


def test_hit_flags_reports_matched_ranks() -> None:
    assert hit_flags(({}, {2}, {0, 1})) == [False, True, True]


def test_metric_keys_are_cutoff_labelled() -> None:
    assert metric_keys(5) == (
        "recall@5",
        "precision@5",
        "ndcg@5",
        "mrr",
        "hit@5",
        "map@5",
    )


@pytest.mark.parametrize("k", [0, -1])
def test_a_non_positive_cutoff_is_rejected(k: int) -> None:
    hits = ({0},)

    with pytest.raises(ValueError):
        recall_at_k(hits, 1, k)
    with pytest.raises(ValueError):
        precision_at_k(hits, k)
    with pytest.raises(ValueError):
        ndcg_at_k(hits, 1, k)
    with pytest.raises(ValueError):
        evaluate_hits("q1", hits, 1, k)
    with pytest.raises(ValueError):
        metric_keys(k)


def test_query_metrics_values_and_dict_share_report_keys() -> None:
    metrics = evaluate_hits("q1", ({0}, {1}), 2, 5)

    assert set(metrics.values()) == set(metric_keys(5))
    payload = metrics.to_dict()

    assert payload["query_id"] == "q1"
    assert payload["k"] == 5
    assert payload["gold_count"] == 2
    assert payload["recall@5"] == 1.0


def test_aggregate_macro_averages_scored_cases() -> None:
    first = evaluate_hits("q1", ({0},), 1, 5)
    second = evaluate_hits("q2", (), 1, 5)

    summary = aggregate_query_metrics([first, second], 5)

    assert summary["queries"] == 2
    assert summary["recall@5"] == 0.5
    assert summary["hit@5"] == 0.5
    assert summary["mrr"] == 0.5


def test_aggregate_of_nothing_is_zeroed_not_an_error() -> None:
    summary = aggregate_query_metrics([], 5)

    assert summary["queries"] == 0
    assert summary["recall@5"] == 0.0
    assert summary["ndcg@5"] == 0.0


@pytest.mark.parametrize("count", [2, 3, 8])
def test_duplicate_gold_cannot_replace_missing_passages(count):
    duplicated = evaluate_hits("duplicate", [{0}] * count, 2, count)
    single = evaluate_hits("single", [{0}], 2, count)
    assert duplicated.recall == 0.5
    assert duplicated.ndcg == pytest.approx(single.ndcg)
    assert duplicated.ndcg == pytest.approx(0.6131, abs=1e-4)
    assert evaluate_hits("complete", [{0}, {1}], 2, count).ndcg == 1.0


def test_only_new_gold_adds_binary_gain_at_each_rank():
    import math

    assert ndcg_at_k([{0}, {0}, {0, 1}], 2, 3) == pytest.approx(
        (1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    )
    assert ndcg_at_k([{0, 1}], 2, 2) == pytest.approx(1 / (1 + 1 / math.log2(3)))
