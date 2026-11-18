"""How a flashcard review is scored, and when the card comes back.

Why this module is pure
-----------------------
Everything here is a function of its arguments and nothing else: no clock read,
no database, no randomness, no environment. That is the roadmap's "deterministic
review algorithm" requirement taken literally, because the alternative -- a
scheduler that reads ``time.time()`` internally -- cannot be tested for the
property that actually matters, which is that **the same review at the same
moment always produces the same next due date**. A learner's review history is
evidence; evidence that two runs can compute differently is not evidence.

Reuse, not a second policy
--------------------------
The interval sequences, the stability model and the desired-retention target
already exist in :mod:`deeptutor.learning.scheduler`. Phase 7 needs one thing
those do not provide: a four-button answer (again/hard/good/easy) rather than a
single inferred quality. So this module *translates* a rating into the
:class:`RepetitionState` the existing scheduler understands and delegates the
scheduling to it. Writing a second interval policy would have meant two answers
to "when is this due", which drift apart the first time one is tuned.

The rating-to-quality mapping is the only new policy, and it is deliberately
narrow: it decides *how strong* a review was, never *when* the card returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from deeptutor.learning.models import KnowledgeType, RepetitionState
from deeptutor.learning.scheduler import SpacedRepetitionScheduler

#: The four answers a learner can give. Deliberately coarse: a five-point scale
#: is a decision the learner is not equipped to make consistently, and
#: inconsistent input makes the schedule noise.
Rating = Literal["again", "hard", "good", "easy"]

RATINGS: tuple[Rating, ...] = ("again", "hard", "good", "easy")

#: Rating -> 0..1 review strength. ``again`` is a lapse (0.0), ``easy`` is a
#: clean recall (1.0). The middle two are partial credit, and the asymmetry
#: between them (0.4 vs 0.7, not 0.5/0.5) is intentional: "hard" means the
#: learner needed effort and should see the card sooner than "good".
_QUALITY: dict[str, float] = {
    "again": 0.0,
    "hard": 0.4,
    "good": 0.7,
    "easy": 1.0,
}

#: Seconds per day. Named rather than inlined so the conversion in ``due_at``
#: is not a magic number, and so tests can read it instead of hard-coding 86400.
SECONDS_PER_DAY = 86400.0


def validate_rating(rating: str) -> Rating:
    """Return *rating* normalised, or raise.

    Refusing an unknown rating rather than mapping it to a default is the same
    choice Phase 6 made for unknown answer keys: a value nobody expected is a
    bug upstream, and silently treating it as "good" would hide that bug behind
    a plausible-looking schedule.
    """
    value = str(rating or "").strip().lower()
    if value not in _QUALITY:
        raise ValueError(f"unknown rating {rating!r}; expected one of {list(RATINGS)}")
    return value  # type: ignore[return-value]


def quality_for(rating: str) -> float:
    """The 0..1 strength the scheduler consumes for this rating."""
    return _QUALITY[validate_rating(rating)]


def knowledge_type_for(value: str | None) -> KnowledgeType:
    """Coerce a stored knowledge-type string, defaulting to ``concept``.

    Unknown values fall back rather than raising: the column is free text and a
    card written before a taxonomy change must still be reviewable. This is the
    opposite of :func:`validate_rating` on purpose -- a bad *input* is an error,
    but a stored value is a past fact we must keep serving.
    """
    try:
        return KnowledgeType(str(value or "concept"))
    except ValueError:
        return KnowledgeType.CONCEPT


@dataclass(frozen=True)
class ReviewState:
    """The scheduling-relevant part of a card, as stored.

    A frozen snapshot so a caller cannot half-apply an update: the result of
    :func:`schedule` is a complete new state, and writing it is a single row
    update rather than a sequence of field mutations that a crash could
    interrupt.
    """

    interval_index: int
    consecutive_correct: int
    consecutive_wrong: int
    review_count: int
    lapse_count: int
    due_at: float
    last_reviewed_at: float | None = None


@dataclass(frozen=True)
class ReviewOutcome:
    """What a review did: the new state, and the evidence explaining why."""

    rating: Rating
    quality: float
    state: ReviewState
    interval_days: float
    #: True when the rating was ``again`` -- the card lapsed.
    lapsed: bool

    def as_evidence(self) -> dict[str, float | int | str | bool]:
        """A flat record for the review-history row."""
        return {
            "rating": self.rating,
            "quality": self.quality,
            "interval_index": self.state.interval_index,
            "interval_days": self.interval_days,
            "lapsed": self.lapsed,
        }


def schedule(
    state: ReviewState,
    knowledge_type: KnowledgeType,
    rating: Rating,
    *,
    now: float,
    desired_retention: float = 0.9,
) -> ReviewOutcome:
    """Compute the next review of one card.

    ``now`` is a parameter, not a clock read. That single choice is what makes
    the function testable for determinism and what lets a caller replay a
    history to check a stored schedule is what the policy would produce today
    (see :func:`replay`).

    The rating is translated into the scheduler's own evidence shape and the
    scheduling itself is delegated, so this function owns *interpretation* and
    the existing scheduler owns *arithmetic*.
    """
    checked = validate_rating(rating)
    quality = _QUALITY[checked]
    kind = knowledge_type

    # Map the stored card state onto the scheduler's state. ``stability`` is
    # derived by the scheduler from ``interval_index`` on demand, so we pass 0
    # and let ``hydrate`` do it -- passing a guessed stability here would make
    # the two implementations disagree about what round the card is on.
    rep = RepetitionState(
        interval_index=state.interval_index,
        consecutive_correct=state.consecutive_correct,
        consecutive_wrong=state.consecutive_wrong,
        next_review_at=state.due_at,
        review_count=state.review_count,
        lapse_count=state.lapse_count,
        last_review_at=state.last_reviewed_at,
    )

    scheduler = SpacedRepetitionScheduler(desired_retention=desired_retention)
    from deeptutor.learning.models import LearningEvidence

    evidence = LearningEvidence(
        knowledge_point_id="card",
        timestamp=now,
        source="flashcard",
        assessment_type="review",
        result="correct" if quality >= 0.7 else ("partial" if quality > 0 else "incorrect"),
        quality=quality,
    )
    updated = scheduler.schedule_review(rep, kind, evidence, now=now)

    interval_days = max(
        0.0, (updated.next_review_at - now) / SECONDS_PER_DAY
    )

    new_state = ReviewState(
        interval_index=updated.interval_index,
        consecutive_correct=updated.consecutive_correct,
        consecutive_wrong=updated.consecutive_wrong,
        review_count=updated.review_count,
        lapse_count=updated.lapse_count,
        due_at=updated.next_review_at,
        last_reviewed_at=now,
    )
    return ReviewOutcome(
        rating=checked,
        quality=quality,
        state=new_state,
        interval_days=interval_days,
        lapsed=checked == "again",
    )


def replay(
    initial: ReviewState,
    knowledge_type: KnowledgeType,
    ratings: list[Rating],
    *,
    start_at: float,
    gap_seconds: float = SECONDS_PER_DAY,
    desired_retention: float = 0.9,
) -> ReviewState:
    """Replay a rating history from ``start_at``, one review per gap.

    Used by the tests and by the audit endpoint: if replaying a card's stored
    history does not reproduce its stored state, then the stored state came
    from an older policy or was written by something that bypassed this module.
    Either way it must be *detectable*, not merely suspicious.
    """
    state = initial
    moment = start_at
    for rating in ratings:
        outcome = schedule(
            state, knowledge_type, rating, now=moment, desired_retention=desired_retention
        )
        state = outcome.state
        moment += gap_seconds
    return state


def is_due(state: ReviewState, *, now: float) -> bool:
    """Whether a card is due at ``now``. A pure predicate, no grace period."""
    return state.due_at <= now
