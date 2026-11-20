"""The review algorithm: deterministic, and monotone in the right places.

`now` is a parameter everywhere here, which is what makes these tests possible.
A scheduler that read the clock internally could only be tested for "produces
something", and "produces something" is not the property the roadmap asks for --
it asks for a *deterministic* algorithm with tests.
"""

from __future__ import annotations

import pytest

from deeptutor.learning.models import KnowledgeType
from deeptutor.services.review.schedule import (
    RATINGS,
    SECONDS_PER_DAY,
    ReviewState,
    is_due,
    knowledge_type_for,
    quality_for,
    replay,
    schedule,
    validate_rating,
)

NOW = 1_700_000_000.0  # a fixed instant, so nothing depends on the wall clock


def _fresh(due_at: float = NOW) -> ReviewState:
    return ReviewState(
        interval_index=0,
        consecutive_correct=0,
        consecutive_wrong=0,
        review_count=0,
        lapse_count=0,
        due_at=due_at,
        last_reviewed_at=None,
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_the_same_review_at_the_same_moment_gives_the_same_schedule():
    """The acceptance criterion, stated as simply as it can be."""
    state = _fresh()
    first = schedule(state, KnowledgeType.CONCEPT, "good", now=NOW)
    second = schedule(state, KnowledgeType.CONCEPT, "good", now=NOW)

    assert first == second
    assert first.state.due_at == second.state.due_at


def test_replaying_a_history_reproduces_the_state():
    """Replay is how a stored schedule is audited against today's policy."""
    ratings = ["good", "good", "hard", "again", "good"]
    state = _fresh()
    moment = NOW
    for rating in ratings:
        state = schedule(state, KnowledgeType.CONCEPT, rating, now=moment).state
        moment += SECONDS_PER_DAY

    replayed = replay(
        _fresh(), KnowledgeType.CONCEPT, ratings, start_at=NOW, gap_seconds=SECONDS_PER_DAY
    )
    assert replayed == state


def test_a_different_rating_gives_a_different_schedule():
    """Determinism must not be achieved by ignoring the input."""
    state = _fresh()
    good = schedule(state, KnowledgeType.CONCEPT, "good", now=NOW)
    again = schedule(state, KnowledgeType.CONCEPT, "again", now=NOW)
    assert good.state.due_at != again.state.due_at


# ---------------------------------------------------------------------------
# Ordering properties -- the behaviour a learner would notice
# ---------------------------------------------------------------------------


def test_a_lapse_brings_the_card_back_sooner_than_a_success():
    state = _fresh()
    lapse = schedule(state, KnowledgeType.CONCEPT, "again", now=NOW)
    success = schedule(state, KnowledgeType.CONCEPT, "easy", now=NOW)

    assert lapse.state.due_at < success.state.due_at
    assert lapse.lapsed is True
    assert success.lapsed is False


def test_easy_comes_back_later_than_good_which_comes_later_than_hard():
    state = _fresh()
    hard = schedule(state, KnowledgeType.CONCEPT, "hard", now=NOW)
    good = schedule(state, KnowledgeType.CONCEPT, "good", now=NOW)
    easy = schedule(state, KnowledgeType.CONCEPT, "easy", now=NOW)

    assert hard.state.due_at <= good.state.due_at <= easy.state.due_at


def test_successive_reviews_push_the_card_further_out():
    """A learner who keeps succeeding should see the card less often.

    This is the whole premise of spaced repetition, so it is worth asserting
    directly rather than inferring it from interval indices.
    """
    state = _fresh()
    moment = NOW
    intervals = []
    for _ in range(4):
        outcome = schedule(state, KnowledgeType.CONCEPT, "good", now=moment)
        intervals.append(outcome.interval_days)
        state = outcome.state
        moment = outcome.state.due_at

    assert intervals == sorted(intervals), f"intervals must not shrink: {intervals}"
    assert intervals[-1] > intervals[0]


def test_a_lapse_resets_the_streak_but_not_the_history():
    """Forgetting is recorded, not erased.

    ``consecutive_correct`` is not a lifetime tally: the shared scheduler uses
    it as a short-term booster (every second success adds growth, then it
    resets). What must survive a lapse is ``review_count``, and what must
    increment is ``lapse_count`` -- those are the figures the dashboard reads.
    """
    state = _fresh()
    moment = NOW
    for _ in range(3):
        outcome = schedule(state, KnowledgeType.CONCEPT, "good", now=moment)
        state = outcome.state
        moment = outcome.state.due_at
    assert state.review_count == 3
    assert state.consecutive_correct >= 1

    lapsed = schedule(state, KnowledgeType.CONCEPT, "again", now=moment)
    assert lapsed.state.consecutive_correct == 0, "a failure ends the streak"
    assert lapsed.state.consecutive_wrong == 1, "the failure is itself a streak"
    assert lapsed.state.lapse_count == state.lapse_count + 1
    assert lapsed.state.review_count == state.review_count + 1, "history is kept"


def test_memory_cards_are_scheduled_differently_from_design_cards():
    """Knowledge type is an input, not decoration."""
    state = _fresh()
    memory = schedule(state, KnowledgeType.MEMORY, "good", now=NOW)
    design = schedule(state, KnowledgeType.DESIGN, "good", now=NOW)
    assert memory.state.due_at != design.state.due_at


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------


def test_every_declared_rating_is_accepted():
    state = _fresh()
    for rating in RATINGS:
        outcome = schedule(state, KnowledgeType.CONCEPT, rating, now=NOW)
        assert outcome.rating == rating
        assert 0.0 <= outcome.quality <= 1.0


def test_an_unknown_rating_is_refused_rather_than_defaulted():
    """Silently treating 'goodish' as 'good' would hide a client bug."""
    with pytest.raises(ValueError, match="unknown rating"):
        validate_rating("goodish")
    with pytest.raises(ValueError):
        quality_for("nope")


def test_ratings_are_normalised_for_case_and_whitespace():
    assert validate_rating("  GOOD ") == "good"


def test_quality_increases_with_the_rating():
    qualities = [quality_for(rating) for rating in RATINGS]
    assert qualities == sorted(qualities)
    assert qualities[0] == 0.0
    assert qualities[-1] == 1.0


def test_an_unknown_stored_knowledge_type_falls_back_instead_of_raising():
    """A stored value is a past fact; serving it must not start failing.

    This is deliberately the opposite of rating validation: bad *input* is an
    error, but a card written before a taxonomy change must stay reviewable.
    """
    assert knowledge_type_for("nonsense") == KnowledgeType.CONCEPT
    assert knowledge_type_for(None) == KnowledgeType.CONCEPT
    assert knowledge_type_for("memory") == KnowledgeType.MEMORY


def test_is_due_is_inclusive_at_the_due_instant():
    state = _fresh(due_at=NOW)
    assert is_due(state, now=NOW) is True
    assert is_due(state, now=NOW - 1) is False
    assert is_due(state, now=NOW + 1) is True


def test_the_outcome_reports_the_evidence_it_was_derived_from():
    outcome = schedule(_fresh(), KnowledgeType.CONCEPT, "hard", now=NOW)
    evidence = outcome.as_evidence()
    assert evidence["rating"] == "hard"
    assert evidence["quality"] == pytest.approx(0.4)
    assert evidence["lapsed"] is False
