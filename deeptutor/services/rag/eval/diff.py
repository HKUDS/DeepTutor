"""Compare two retrieval-evaluation reports to quantify a settings change.

A single ``kb eval`` run reports absolute metrics; it cannot tell you whether a
change to the retrieval stack (an embedding model, a reranker, chunk size, or the
query-rewrite layer) actually helped. This module answers that by diffing two
stored reports: a *baseline* recorded before the change and a *candidate* recorded
after. It aligns the two by query id and reports the per-metric delta plus the
per-case movement, so a reordered or truncated set still compares like-for-like.

Nothing here calls a model: every number is recomputed from the two reports, so
the diff is reproducible and cannot drift.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .metrics import metric_keys
from .report import format_metric

#: A delta above this magnitude counts as a move (symmetric for regressions).
_IMPROVE_EPSILON = 1e-9


@dataclass(frozen=True)
class _Normalized:
    """A report reduced to just what a diff needs: ``k``, metric keys, metrics, cases.

    Both a live :class:`~deeptutor.services.rag.eval.report.EvalReport` object and a
    serialized ``to_dict`` (e.g. loaded from a ``--save`` JSON file) normalize to the
    same shape, so a diff works without reconstructing report objects.
    """

    k: int
    keys: tuple[str, ...]
    metrics: dict[str, float]
    cases: dict[str, dict[str, Any]]


def _normalize(report: Any) -> _Normalized:
    """Reduce a report object or its ``to_dict`` to the fields a diff compares.

    Args:
        report: A report object or its serialized ``to_dict`` mapping.

    Returns:
        A :class:`_Normalized` holding the macro metrics and per-case scores.

    Raises:
        TypeError: If ``report`` is neither a report object nor a mapping.
    """
    if isinstance(report, dict):
        k = int(report.get("k") or 0)
        aggregate: dict[str, Any] = report.get("metrics") or {}
        raw_cases: Sequence[Any] = report.get("queries") or []
        object_form = False
    else:
        k = int(getattr(report, "k", 0) or 0)
        aggregate = dict(report.aggregate())
        raw_cases = list(getattr(report, "evaluations", ()))
        object_form = True

    keys = metric_keys(k) if k >= 1 else ()
    metrics = {key: float(aggregate.get(key, 0.0) or 0.0) for key in keys}

    cases: dict[str, dict[str, Any]] = {}
    for case in raw_cases:
        if object_form:
            case_id = str(case.case_id)
            query = str(case.query)
            failed = case.failed
            values = case.metrics.values()
        else:
            case_id = str(case.get("case_id") or case.get("query_id") or case.get("query"))
            query = str(case.get("query") or case_id)
            failed = bool(case.get("error"))
            values = case
        metrics_by_key = {key: float(values.get(key, 0.0) or 0.0) for key in keys}
        cases[case_id] = {"query": query, "failed": failed, "metrics": metrics_by_key}

    return _Normalized(k=k, keys=keys, metrics=metrics, cases=cases)


@dataclass(frozen=True)
class MetricDelta:
    """One metric's baseline value, candidate value, and signed change."""

    key: str
    baseline: float
    candidate: float

    @property
    def delta(self) -> float:
        """``candidate - baseline``; positive means the change improved this metric."""
        return self.candidate - self.baseline

    @property
    def improved(self) -> bool:
        """Whether the metric went up by more than a rounding epsilon."""
        return self.delta > _IMPROVE_EPSILON

    @property
    def regressed(self) -> bool:
        """Whether the metric went down by more than a rounding epsilon."""
        return self.delta < -_IMPROVE_EPSILON

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serializable row for this metric's delta."""
        return {
            "metric": self.key,
            "baseline": round(self.baseline, 6),
            "candidate": round(self.candidate, 6),
            "delta": round(self.delta, 6),
            "direction": "improved" if self.improved else "regressed" if self.regressed else "flat",
        }


@dataclass(frozen=True)
class CaseDelta:
    """One query's metric deltas, comparing only where both runs scored it."""

    query: str
    baseline_failed: bool
    candidate_failed: bool
    metrics: dict[str, MetricDelta] = field(default_factory=dict)

    @property
    def comparable(self) -> bool:
        """Whether both runs produced a score for this query."""
        return not (self.baseline_failed or self.candidate_failed)

    @property
    def worst_key(self) -> str | None:
        """The metric with the most negative delta, if the case has metrics."""
        if not self.metrics:
            return None
        return min(self.metrics, key=lambda key: self.metrics[key].delta)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serializable row for this case's per-metric deltas."""
        return {
            "query": self.query,
            "comparable": self.comparable,
            "baseline_failed": self.baseline_failed,
            "candidate_failed": self.candidate_failed,
            "metrics": {key: delta.to_dict() for key, delta in self.metrics.items()},
        }


@dataclass(frozen=True)
class EvalDiff:
    """The per-metric and per-case movement between a baseline and a candidate run.

    Macro deltas cover the scored cases of each run. Per-case deltas are only
    computed where *both* runs scored the query; a case one run failed (a transient
    engine error) is reported as added/removed rather than pretending a zero-vs-score
    delta is meaningful.
    """

    baseline_label: str
    candidate_label: str
    k: int
    metrics: dict[str, MetricDelta] = field(default_factory=dict)
    cases: dict[str, CaseDelta] = field(default_factory=dict)
    added_cases: tuple[str, ...] = ()
    removed_cases: tuple[str, ...] = ()

    @property
    def comparable_cases(self) -> tuple[CaseDelta, ...]:
        """Cases both runs scored, the ones whose per-case movement is meaningful."""
        return tuple(case for case in self.cases.values() if case.comparable)

    @property
    def improved_cases(self) -> tuple[CaseDelta, ...]:
        """Comparable cases where some metric rose and none fell."""
        return tuple(
            case
            for case in self.comparable_cases
            if any(delta.improved for delta in case.metrics.values())
            and not any(delta.regressed for delta in case.metrics.values())
        )

    @property
    def regressed_cases(self) -> tuple[CaseDelta, ...]:
        """Comparable cases where any metric fell."""
        return tuple(
            case
            for case in self.comparable_cases
            if any(delta.regressed for delta in case.metrics.values())
        )

    @property
    def has_regression(self) -> bool:
        """Whether any macro metric or comparable case regressed."""
        if any(delta.regressed for delta in self.metrics.values()):
            return True
        return bool(self.regressed_cases)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serializable form of the whole diff."""
        return {
            "baseline": self.baseline_label,
            "candidate": self.candidate_label,
            "k": self.k,
            "metrics": {key: delta.to_dict() for key, delta in self.metrics.items()},
            "cases": {case_id: case.to_dict() for case_id, case in self.cases.items()},
            "added_cases": list(self.added_cases),
            "removed_cases": list(self.removed_cases),
        }

    def summary_lines(self) -> list[str]:
        """Plain-text lines suitable for a CLI: macro table then case movement."""
        lines = [
            f"Baseline: {self.baseline_label}",
            f"Candidate: {self.candidate_label}",
            f"k={self.k}",
            "",
            f"{'metric':<12} {'baseline':>10} {'candidate':>10} {'delta':>10}",
        ]
        for key, delta in self.metrics.items():
            lines.append(
                f"{key:<12} "
                f"{format_metric(delta.baseline):>10} "
                f"{format_metric(delta.candidate):>10} "
                f"{format_metric(delta.delta):>10}  {delta.to_dict()['direction']}"
            )
        lines.append("")
        lines.append(
            f"cases: {len(self.comparable_cases)} comparable, "
            f"{len(self.improved_cases)} improved, {len(self.regressed_cases)} regressed"
        )
        if self.added_cases:
            lines.append(f"added (candidate only): {', '.join(self.added_cases)}")
        if self.removed_cases:
            lines.append(f"removed (baseline only): {', '.join(self.removed_cases)}")
        return lines


def diff_reports(
    baseline: Any,
    candidate: Any,
    *,
    baseline_label: str = "baseline",
    candidate_label: str = "candidate",
) -> EvalDiff:
    """Diff two evaluation reports (objects or ``to_dict`` mappings).

    Args:
        baseline: The pre-change report (object or serialized mapping).
        candidate: The post-change report (object or serialized mapping).
        baseline_label: Human label for the baseline in the summary.
        candidate_label: Human label for the candidate in the summary.

    Returns:
        An :class:`EvalDiff` with per-metric and per-case movement. Cases are
        aligned by query id; a case scored by only one run is reported as
        added/removed rather than as a spurious delta.

    Raises:
        ValueError: If the two reports were evaluated at different ``k`` and so
            cannot be compared like-for-like.
    """
    base = _normalize(baseline)
    cand = _normalize(candidate)
    if base.k != cand.k:
        raise ValueError(
            f"reports use different k (baseline k={base.k}, candidate k={cand.k}); "
            "re-evaluate both at the same k to compare"
        )

    metrics = {
        key: MetricDelta(
            key=key, baseline=base.metrics.get(key, 0.0), candidate=cand.metrics.get(key, 0.0)
        )
        for key in base.keys
    }

    base_ids = set(base.cases)
    cand_ids = set(cand.cases)
    shared = sorted(base_ids & cand_ids)

    cases: dict[str, CaseDelta] = {}
    for case_id in shared:
        base_case = base.cases[case_id]
        cand_case = cand.cases[case_id]
        comparable = not (base_case["failed"] or cand_case["failed"])
        per_metric = {
            key: MetricDelta(
                key=key,
                baseline=base_case["metrics"].get(key, 0.0),
                candidate=cand_case["metrics"].get(key, 0.0),
            )
            for key in base.keys
        }
        cases[case_id] = CaseDelta(
            query=cand_case["query"] or base_case["query"],
            baseline_failed=base_case["failed"],
            candidate_failed=cand_case["failed"],
            metrics=per_metric if comparable else {},
        )

    return EvalDiff(
        baseline_label=baseline_label,
        candidate_label=candidate_label,
        k=base.k,
        metrics=metrics,
        cases=cases,
        added_cases=tuple(sorted(cand_ids - base_ids)),
        removed_cases=tuple(sorted(base_ids - cand_ids)),
    )
