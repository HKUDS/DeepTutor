"""The mastery dashboard: per chapter and per topic, from stored evidence.

What "mastery" is allowed to mean here
-------------------------------------
The roadmap's acceptance criterion is "practice suggestion based on *evidence*,
not a model estimate". So this module computes mastery by counting stored facts
-- exam item outcomes and review events -- and never by asking a model how well
it thinks the learner knows something.

That decision has a visible cost: a learner who has done nothing has **no**
mastery score, not a low one. :func:`chapter_mastery` returns ``None`` rather
than ``0.0`` when there is no evidence, because "we have never seen you answer a
question about this chapter" and "you answer every question about this chapter
wrongly" are different facts, and collapsing them lets a dashboard lie.

Which policy
------------
The 0..1 score itself comes from :func:`deeptutor.learning.mastery.compute_mastery`,
which already exists, is already tested, and already encodes the recency
weighting and the low-confidence cap. Phase 7 does not get a second opinion
about how mastery is computed -- it gets a second *view* of the same policy,
grouped by the dimensions the roadmap asks for (chapter, topic).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from deeptutor.learning.mastery import compute_mastery

#: Confidence in a mastery figure, derived from how much evidence supports it.
#: These are thresholds on *counts*, not statistical claims: three observations
#: is still thin no matter what model you run over them.
_MINIMUM_FOR_MEDIUM = 3
_MINIMUM_FOR_HIGH = 6


@dataclass
class Evidence:
    """One observation about a chapter or topic.

    ``correctness`` is 0..1 so partial credit from an essay and a binary
    right/wrong from a multiple-choice question share one scale.
    """

    group: str
    correctness: float
    source: str
    detail: str = ""


@dataclass
class GroupMastery:
    """Mastery for one chapter or topic."""

    name: str
    mastery: float | None
    observations: int
    correct: int
    incorrect: int
    confidence: str
    sources: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            # None, not 0.0: no evidence is not the same as poor performance.
            "mastery": self.mastery,
            "observations": self.observations,
            "correct": self.correct,
            "incorrect": self.incorrect,
            "confidence": self.confidence,
            "sources": dict(self.sources),
        }


def _confidence(count: int) -> str:
    if count <= 0:
        return "none"
    if count < _MINIMUM_FOR_MEDIUM:
        return "low"
    if count < _MINIMUM_FOR_HIGH:
        return "medium"
    return "high"


def group_mastery(evidence: Sequence[Evidence]) -> list[GroupMastery]:
    """Group evidence by name and score each group with the shared policy.

    Ordering is by name so two dashboards built from the same rows agree; a
    dashboard whose rows move between refreshes is a dashboard nobody trusts.
    """
    buckets: dict[str, list[Evidence]] = {}
    for item in evidence:
        buckets.setdefault(item.group, []).append(item)

    groups: list[GroupMastery] = []
    for name in sorted(buckets):
        items = buckets[name]
        scores = [max(0.0, min(1.0, float(item.correctness))) for item in items]
        sources: dict[str, int] = {}
        for item in items:
            sources[item.source] = sources.get(item.source, 0) + 1
        groups.append(
            GroupMastery(
                name=name,
                mastery=compute_mastery(scores),
                observations=len(items),
                correct=sum(1 for score in scores if score >= 0.7),
                incorrect=sum(1 for score in scores if score < 0.7),
                confidence=_confidence(len(items)),
                sources=sources,
            )
        )
    return groups


def evidence_from_exam_attempt(attempt: Mapping[str, Any], snapshot: Sequence[Mapping[str, Any]]) -> list[Evidence]:
    """Chapter/topic evidence from one graded attempt.

    Built from the attempt's own item rows and its snapshot, so it describes what
    happened on that paper rather than what the bank says today -- the same rule
    Phase 6 applied to grading.
    """
    meta_by_question = {str(q.get("question_id")): q for q in snapshot}
    observations: list[Evidence] = []
    for item in attempt.get("items") or []:
        question_id = str(item.get("question_id"))
        meta = meta_by_question.get(question_id, {})
        outcome = str(item.get("outcome") or "")
        if outcome in {"voided", "needs_review"}:
            # A voided or unreviewed item is not evidence of anything: the
            # question was ungradeable, so the student's answer says nothing
            # about their understanding.
            continue
        points = float(item.get("points_possible") or 0.0)
        awarded = float(item.get("points_awarded") or 0.0)
        correctness = (awarded / points) if points > 0 else 0.0
        detail = f"{outcome} {awarded:g}/{points:g}"
        chapter = str(meta.get("chapter_title") or "").strip()
        topic = str(meta.get("topic") or "").strip()
        if chapter:
            observations.append(Evidence(chapter, correctness, "exam", detail))
        if topic:
            observations.append(Evidence(topic, correctness, "exam", detail))
    return observations


def evidence_from_reviews(reviews: Iterable[Mapping[str, Any]], cards: Mapping[str, Mapping[str, Any]]) -> list[Evidence]:
    """Chapter evidence from flashcard reviews.

    A review is weaker evidence than an exam and is labelled as such
    (``source="review"``), because self-assessment is not the same as being
    tested. The dashboard can weight them differently without this module
    deciding for it.
    """
    observations: list[Evidence] = []
    for review in reviews:
        card = cards.get(str(review.get("card_id")))
        if card is None:
            continue
        chapter = str(card.get("chapter_title") or "").strip()
        if not chapter:
            continue
        quality = float(review.get("quality") or 0.0)
        observations.append(Evidence(chapter, quality, "review", str(review.get("rating") or "")))
    return observations


def suggest_practice(groups: Sequence[GroupMastery], *, limit: int = 3) -> list[dict[str, Any]]:
    """Which groups to practise next, with the evidence that justifies it.

    Ranking is by *evidence*, in this order:

    1. groups with observed mistakes come first -- a wrong answer is a fact;
    2. then thin coverage, because a chapter with one observation is unknown
       rather than mastered;
    3. then lower mastery.

    A group with no observations is never suggested: there is nothing to
    practise against, and recommending it would be the model estimate this
    feature exists to avoid.
    """
    candidates = [group for group in groups if group.observations > 0]
    candidates.sort(
        key=lambda group: (
            -group.incorrect,
            group.observations,
            group.mastery if group.mastery is not None else 1.0,
            group.name,
        )
    )
    suggestions: list[dict[str, Any]] = []
    for group in candidates[:limit]:
        if group.incorrect:
            reason = f"{group.incorrect} پاسخ نادرست از {group.observations} مشاهده"
        else:
            reason = f"شواهد کم است: تنها {group.observations} مشاهده"
        suggestions.append(
            {
                "name": group.name,
                "mastery": group.mastery,
                "observations": group.observations,
                "confidence": group.confidence,
                "reason": reason,
            }
        )
    return suggestions


__all__ = [
    "Evidence",
    "GroupMastery",
    "evidence_from_exam_attempt",
    "evidence_from_reviews",
    "group_mastery",
    "suggest_practice",
]
