"""The mastery dashboard's arithmetic and its policy choices.

Two things are worth testing apart from the endpoint, because they are the
claims the roadmap makes: that suggestions follow *evidence*, and that "no
evidence" is not reported as "bad".
"""

from __future__ import annotations

import pytest

from deeptutor.services.review.mastery import (
    Evidence,
    evidence_from_exam_attempt,
    evidence_from_reviews,
    group_mastery,
    suggest_practice,
)


def test_a_group_with_no_observations_is_absent():
    """Not a zero score: the dashboard must be able to say 'unknown'."""
    assert group_mastery([]) == []


def test_mastery_is_scored_by_the_shared_policy():
    """Reuse, not a second opinion about what mastery means."""
    from deeptutor.learning.mastery import compute_mastery

    groups = group_mastery(
        [Evidence("فصل ۱", 1.0, "exam"), Evidence("فصل ۱", 0.0, "exam")]
    )
    assert groups[0].mastery == compute_mastery([1.0, 0.0])


def test_groups_are_ordered_by_name():
    groups = group_mastery(
        [Evidence("ب", 1.0, "exam"), Evidence("الف", 1.0, "exam")]
    )
    assert [group.name for group in groups] == ["الف", "ب"]


def test_confidence_grows_with_the_number_of_observations():
    one = group_mastery([Evidence("x", 1.0, "exam")])[0]
    three = group_mastery([Evidence("x", 1.0, "exam")] * 3)[0]
    many = group_mastery([Evidence("x", 1.0, "exam")] * 8)[0]

    assert one.confidence == "low"
    assert three.confidence == "medium"
    assert many.confidence == "high"


def test_a_thin_history_cannot_look_mastered():
    """The existing policy's low-confidence cap, surfaced in the dashboard."""
    group = group_mastery([Evidence("x", 1.0, "exam")])[0]
    assert group.mastery == pytest.approx(0.5)


def test_sources_are_counted_per_group():
    groups = group_mastery(
        [Evidence("x", 1.0, "exam"), Evidence("x", 0.5, "review")]
    )
    assert groups[0].sources == {"exam": 1, "review": 1}


def test_a_suggestion_is_ranked_by_observed_mistakes():
    groups = group_mastery(
        [
            Evidence("خوب", 1.0, "exam"),
            Evidence("بد", 0.0, "exam"),
            Evidence("بد", 0.0, "exam"),
        ]
    )
    suggestions = suggest_practice(groups)
    assert suggestions[0]["name"] == "بد"
    assert "نادرست" in suggestions[0]["reason"]


def test_a_perfect_record_is_not_suggested_as_a_weakness():
    groups = group_mastery([Evidence("کامل", 1.0, "exam")] * 5)
    suggestions = suggest_practice(groups)
    # It may appear as thin... but never as "wrong answers".
    assert all("نادرست" not in s["reason"] for s in suggestions)


def test_nothing_is_suggested_without_evidence():
    assert suggest_practice([]) == []


def test_suggestions_are_capped():
    groups = group_mastery([Evidence(f"فصل {index}", 0.0, "exam") for index in range(10)])
    assert len(suggest_practice(groups, limit=3)) == 3


# ---------------------------------------------------------------------------
# Evidence extraction
# ---------------------------------------------------------------------------


def test_an_exam_attempt_yields_chapter_and_topic_evidence():
    attempt = {
        "items": [
            {"question_id": "q1", "outcome": "wrong", "points_awarded": 0.0, "points_possible": 3.0}
        ]
    }
    snapshot = [{"question_id": "q1", "chapter_title": "فصل ۱", "topic": "جمع"}]

    observations = evidence_from_exam_attempt(attempt, snapshot)
    names = {item.group for item in observations}
    assert names == {"فصل ۱", "جمع"}
    assert all(item.correctness == 0.0 for item in observations)


def test_a_voided_item_is_not_evidence():
    """An ungradeable question says nothing about the student."""
    attempt = {
        "items": [
            {"question_id": "q1", "outcome": "voided", "points_awarded": 0.0, "points_possible": 3.0}
        ]
    }
    snapshot = [{"question_id": "q1", "chapter_title": "فصل ۱"}]
    assert evidence_from_exam_attempt(attempt, snapshot) == []


def test_a_needs_review_item_is_not_evidence():
    attempt = {
        "items": [
            {"question_id": "q1", "outcome": "needs_review", "points_awarded": 2.0, "points_possible": 4.0}
        ]
    }
    snapshot = [{"question_id": "q1", "chapter_title": "فصل ۱"}]
    assert evidence_from_exam_attempt(attempt, snapshot) == []


def test_partial_credit_is_scaled_not_binarised():
    attempt = {
        "items": [
            {"question_id": "q1", "outcome": "correct", "points_awarded": 2.0, "points_possible": 4.0}
        ]
    }
    snapshot = [{"question_id": "q1", "chapter_title": "فصل ۱"}]
    assert evidence_from_exam_attempt(attempt, snapshot)[0].correctness == pytest.approx(0.5)


def test_a_review_becomes_weaker_evidence_under_its_own_label():
    reviews = [{"card_id": "c1", "quality": 0.7, "rating": "good"}]
    cards = {"c1": {"chapter_title": "فصل ۱"}}
    observations = evidence_from_reviews(reviews, cards)

    assert len(observations) == 1
    assert observations[0].source == "review"
    assert observations[0].correctness == pytest.approx(0.7)


def test_a_review_with_no_chapter_is_skipped():
    reviews = [{"card_id": "c1", "quality": 1.0, "rating": "easy"}]
    cards = {"c1": {"chapter_title": ""}}
    assert evidence_from_reviews(reviews, cards) == []
