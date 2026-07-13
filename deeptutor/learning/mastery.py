"""Mastery scoring policy — intentionally simple and swappable.

``compute_mastery`` maps a knowledge point's attempt history to a 0..1 mastery
score. The current policy is a recency-weighted accuracy with a low-confidence
cap: a single lucky answer cannot "master" a point — mastery is capped until
there is enough evidence.

This is the one place the pedagogy math lives. To plug in a richer model
(e.g. an IRT/BKT estimate or a tuned spec), replace ``compute_mastery`` alone;
callers (`LearningService.calculate_mastery`) need not change.
"""

from __future__ import annotations

# Recency weights for the most recent attempts (oldest -> newest). Newer
# attempts count more, so recovery after early mistakes is rewarded.
_RECENCY_WEIGHTS: tuple[float, ...] = (0.5, 0.7, 0.85, 0.95, 1.0)

# Mastery cannot exceed this until enough attempts accumulate, so one or two
# correct answers cannot declare a point "mastered".
_CONFIDENCE_CAP: dict[int, float] = {1: 0.5, 2: 0.8}


def compute_mastery(correctness: list[bool]) -> float:
    """Return a 0..1 mastery score from a knowledge point's attempt outcomes.

    Args:
        correctness: per-attempt correctness in chronological order.
    """
    if not correctness:
        return 0.0
    recent = correctness[-len(_RECENCY_WEIGHTS) :]
    weights = _RECENCY_WEIGHTS[-len(recent) :]
    score = sum(w * (1.0 if c else 0.0) for w, c in zip(recent, weights, strict=True)) / sum(
        weights
    )
    return min(score, _CONFIDENCE_CAP.get(len(recent), 1.0))


__all__ = ["compute_mastery"]
