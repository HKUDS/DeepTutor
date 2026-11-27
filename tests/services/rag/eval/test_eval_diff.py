"""Tests for diffing two retrieval-evaluation reports (the ``kb eval-diff`` core)."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.rag.eval import EvalReport, MatchPolicy, QueryEvaluation, evaluate_hits
from deeptutor.services.rag.eval.diff import diff_reports

K = 5
KEYS = (f"recall@{K}", f"precision@{K}", f"ndcg@{K}", "mrr", f"hit@{K}", f"map@{K}")


def _metrics(**overrides: float) -> dict[str, float]:
    """A complete metric block for the cutoff, zero-filled unless overridden."""
    return {key: 0.0 for key in KEYS} | overrides


def _case(case_id: str, *, error: str = "", **overrides: float) -> dict[str, Any]:
    """A serialized per-case row in the shape ``kb eval --save`` writes."""
    return {
        "case_id": case_id,
        "query": f"query {case_id}",
        "error": error,
        **_metrics(**overrides),
    }


def _report(
    *,
    k: int = K,
    metrics: dict[str, float] | None = None,
    queries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A serialized report mapping in the shape ``kb eval --save`` writes."""
    return {
        "dataset": "set",
        "kb": "kb1",
        "provider": "llamaindex",
        "k": k,
        "mode": "",
        "duration_seconds": 0.1,
        "match_policy": {"min_ratio": 0.5, "min_tokens": 3},
        "metrics": _metrics() if metrics is None else metrics,
        "queries": queries or [],
    }


def _report_object(*rankings: tuple[frozenset[int], ...]) -> EvalReport:
    """A live report object; each ranking is one case's per-rank matched-gold sets."""
    evaluations = tuple(
        QueryEvaluation(
            case_id=f"q{index}",
            query=f"query q{index}",
            k=K,
            gold_count=1,
            hits=ranking,
            metrics=evaluate_hits(f"q{index}", ranking, 1, K),
            provider="fake",
        )
        for index, ranking in enumerate(rankings)
    )
    return EvalReport(
        dataset_name="set",
        kb_name="kb1",
        provider="fake",
        k=K,
        mode=None,
        policy=MatchPolicy(),
        evaluations=evaluations,
        duration_seconds=0.1,
    )


def test_metric_deltas_are_signed_and_directioned() -> None:
    baseline = _report(metrics=_metrics(**{"recall@5": 0.5, "mrr": 1.0, "hit@5": 1.0}))
    candidate = _report(metrics=_metrics(**{"recall@5": 1.0, "mrr": 1.0, "hit@5": 0.5}))

    diff = diff_reports(baseline, candidate)

    assert diff.k == K
    assert diff.metrics["recall@5"].delta == pytest.approx(0.5)
    assert diff.metrics["recall@5"].improved
    assert diff.metrics["hit@5"].delta == pytest.approx(-0.5)
    assert diff.metrics["hit@5"].regressed
    flat = diff.metrics["mrr"].to_dict()
    assert flat["direction"] == "flat"
    assert flat["delta"] == 0.0
    assert diff.has_regression


def test_a_delta_below_the_epsilon_is_not_a_direction() -> None:
    baseline = _report(metrics=_metrics(mrr=0.3))
    candidate = _report(metrics=_metrics(mrr=0.3 + 1e-12))

    delta = diff_reports(baseline, candidate).metrics["mrr"]

    assert not delta.improved
    assert not delta.regressed
    assert delta.to_dict()["direction"] == "flat"


def test_object_and_serialized_forms_diff_the_same() -> None:
    late_hit = (frozenset(), frozenset({0}))
    early_hit = (frozenset({0}), frozenset())
    baseline = _report_object(late_hit)
    candidate = _report_object(early_hit)

    as_objects = diff_reports(baseline, candidate)
    as_dicts = diff_reports(baseline.to_dict(), candidate.to_dict())

    # ``QueryMetrics.to_dict`` rounds to 4 decimals, so the serialized form is
    # compared with a tolerance; in practice both sides of a diff are saved reports.
    payload = as_dicts.to_dict()
    assert as_objects.to_dict()["metrics"].keys() == payload["metrics"].keys()
    assert as_objects.metrics["mrr"].delta == pytest.approx(0.5)
    for key, delta in as_objects.metrics.items():
        assert delta.delta == pytest.approx(payload["metrics"][key]["delta"], abs=1e-3)
    assert set(as_objects.cases) == set(payload["cases"]) == {"q0"}
    assert as_objects.cases["q0"].comparable
    for key, delta in as_objects.cases["q0"].metrics.items():
        assert delta.delta == pytest.approx(
            payload["cases"]["q0"]["metrics"][key]["delta"], abs=1e-3
        )


def test_reports_at_different_k_are_rejected() -> None:
    with pytest.raises(ValueError, match="different k"):
        diff_reports(_report(k=5), _report(k=3))


def test_cases_unique_to_one_run_are_added_and_removed() -> None:
    baseline = _report(queries=[_case("q1", **{"recall@5": 1.0}), _case("q2", **{"recall@5": 1.0})])
    candidate = _report(
        queries=[_case("q2", **{"recall@5": 1.0}), _case("q3", **{"recall@5": 1.0})]
    )

    diff = diff_reports(baseline, candidate)

    assert diff.added_cases == ("q3",)
    assert diff.removed_cases == ("q1",)
    assert set(diff.cases) == {"q2"}
    assert diff.cases["q2"].comparable


def test_a_case_failed_by_either_run_is_not_comparable() -> None:
    baseline = _report(queries=[_case("q1", **{"recall@5": 1.0})])
    candidate = _report(queries=[_case("q1", error="index missing", **{"recall@5": 0.0})])

    case = diff_reports(baseline, candidate).cases["q1"]

    assert case.baseline_failed is False
    assert case.candidate_failed is True
    assert not case.comparable
    assert case.metrics == {}
    assert case.worst_key is None


def test_case_movement_classifies_improvements_and_regressions() -> None:
    baseline = _report(
        queries=[_case("up", **{"recall@5": 0.5}), _case("down", **{"recall@5": 1.0})]
    )
    candidate = _report(
        queries=[_case("up", **{"recall@5": 1.0}), _case("down", **{"recall@5": 0.0})]
    )

    diff = diff_reports(baseline, candidate)

    assert diff.cases["up"] in diff.improved_cases
    assert diff.cases["down"] in diff.regressed_cases
    assert diff.cases["down"].worst_key == "recall@5"
    assert diff.has_regression

    flat_candidate = _report(
        queries=[_case("up", **{"recall@5": 1.0}), _case("down", **{"recall@5": 1.0})]
    )
    assert not diff_reports(baseline, flat_candidate).has_regression


def test_to_dict_and_summary_lines_render_for_the_cli() -> None:
    baseline = _report(
        metrics=_metrics(**{"recall@5": 0.4}), queries=[_case("q1", **{"recall@5": 0.4})]
    )
    candidate = _report(
        metrics=_metrics(**{"recall@5": 0.8}),
        queries=[_case("q1", **{"recall@5": 0.8}), _case("q2", **{"recall@5": 1.0})],
    )

    diff = diff_reports(baseline, candidate, baseline_label="before", candidate_label="after")
    payload = diff.to_dict()

    assert payload["baseline"] == "before"
    assert payload["candidate"] == "after"
    assert payload["k"] == K
    assert payload["metrics"]["recall@5"]["direction"] == "improved"
    assert payload["metrics"]["recall@5"]["delta"] == pytest.approx(0.4)
    assert payload["added_cases"] == ["q2"]
    assert set(payload["cases"]) == {"q1"}

    joined = "\n".join(diff.summary_lines())
    assert "Baseline: before" in joined
    assert "Candidate: after" in joined
    assert f"k={K}" in joined
    assert "1 comparable, 1 improved, 0 regressed" in joined
