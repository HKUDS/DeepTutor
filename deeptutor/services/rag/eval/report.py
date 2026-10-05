"""Report shape for a retrieval-evaluation run.

The report is plain data plus two renderings: :meth:`EvalReport.to_json` for a
stored artifact (diffable between engine or settings changes) and
:meth:`EvalReport.summary_lines` for a one-block CLI summary. Rich table building
stays in the CLI, so this module carries no rendering dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .matching import MatchPolicy
from .metrics import aggregate_query_metrics, metric_keys
from .runner import SOURCE_MODE_CONTEXT, QueryEvaluation

#: Decimals used when a metric is printed.
METRIC_DECIMALS = 3


def format_metric(value: float | int) -> str:
    """Format one metric for a table cell or a summary line."""
    return f"{float(value):.{METRIC_DECIMALS}f}"


@dataclass(frozen=True)
class EvalReport:
    """Everything one evaluation run produced."""

    dataset_name: str
    kb_name: str
    provider: str
    k: int
    mode: str | None
    policy: MatchPolicy
    evaluations: tuple[QueryEvaluation, ...]
    duration_seconds: float = 0.0

    @property
    def scored(self) -> tuple[QueryEvaluation, ...]:
        """Cases that produced a ranking and were scored."""
        return tuple(item for item in self.evaluations if not item.failed)

    @property
    def failed(self) -> tuple[QueryEvaluation, ...]:
        """Cases whose search failed, excluded from the aggregate."""
        return tuple(item for item in self.evaluations if item.failed)

    def metric_columns(self) -> tuple[str, ...]:
        """Column headers for the per-case metrics table."""
        return metric_keys(self.k)

    def format_metrics(self, evaluation: QueryEvaluation) -> dict[str, str]:
        """Formatted metric cells for one case, keyed by :meth:`metric_columns`."""
        values = evaluation.metrics.values()
        return {key: format_metric(values[key]) for key in self.metric_columns()}

    def aggregate(self) -> dict[str, float | int]:
        """Macro-averaged metrics over the scored cases, plus the case counts."""
        summary = aggregate_query_metrics([item.metrics for item in self.scored], self.k)
        summary["queries_scored"] = len(self.scored)
        summary["queries_failed"] = len(self.failed)
        return summary

    def to_dict(self) -> dict[str, Any]:
        """Full serializable report, including per-case detail."""
        return {
            "dataset": self.dataset_name,
            "kb": self.kb_name,
            "provider": self.provider,
            "k": self.k,
            "mode": self.mode or "",
            "duration_seconds": round(self.duration_seconds, 2),
            "match_policy": {
                "min_ratio": self.policy.min_ratio,
                "min_tokens": self.policy.min_tokens,
            },
            "metrics": self.aggregate(),
            "queries": [
                {
                    "query": item.query,
                    "error": item.error,
                    "context_only": item.source_mode == SOURCE_MODE_CONTEXT,
                    **item.to_dict(),
                }
                for item in self.evaluations
            ],
        }

    def to_json(self, *, indent: int = 2) -> str:
        """Serialize the report for ``--save`` or ``--format json``."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def summary_lines(self) -> list[str]:
        """The header lines a CLI prints under the per-case table."""
        summary = self.aggregate()
        lines = [
            f"dataset: {self.dataset_name}  kb: {self.kb_name}  provider: {self.provider or 'unknown'}",
            f"k: {self.k}  mode: {self.mode or 'engine default'}",
            f"cases: {len(self.evaluations)}  scored: {len(self.scored)}  failed: {len(self.failed)}",
        ]
        metrics = "  ".join(f"{key}={format_metric(summary[key])}" for key in self.metric_columns())
        lines.append(f"metrics (mean over scored cases): {metrics}")
        if self.failed:
            lines.append("failed cases carry no score and are excluded from the means")
        return lines


__all__ = ["EvalReport", "format_metric", "METRIC_DECIMALS"]
