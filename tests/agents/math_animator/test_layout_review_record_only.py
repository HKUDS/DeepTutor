from __future__ import annotations

from deeptutor.agents.math_animator.models import VisualReviewResult
from deeptutor.agents.math_animator.pipeline import _record_only_review


def test_record_only_review_keeps_the_report_without_asking_for_a_retry() -> None:
    review = VisualReviewResult(
        passed=False,
        summary="text overlaps text",
        suggested_fix="move the label",
    )

    result = _record_only_review(review)

    assert result is review
    assert result.passed is True
    assert result.summary == "Layout issues remain after repair rounds: text overlaps text"
    assert result.suggested_fix == "move the label"


def test_record_only_review_passes_through_an_unavailable_probe() -> None:
    assert _record_only_review(None) is None
