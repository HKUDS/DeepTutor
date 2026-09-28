"""Deterministic, daily spaced repetition with adaptive recall intervals.

This is an SM-2-style cold-start policy, not a fitted FSRS model. Review events
are retained so a future scheduler can replay them without losing evidence.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAY = 86400
Rating = Literal["again", "hard", "good", "easy"]


def day_bounds(timezone: str, now: float) -> tuple[float, float]:
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Unknown timezone") from exc
    today = datetime.fromtimestamp(now, zone).date()
    # Construct both midnights: a local day is not necessarily 24 hours (DST).
    return (
        datetime.combine(today, time.min, zone).timestamp(),
        datetime.combine(today + timedelta(days=1), time.min, zone).timestamp(),
    )


def schedule(state: dict, rating: Rating, now: float) -> dict:
    interval = float(state.get("interval_days", 1))
    ease = float(state.get("ease", 2.5))
    streak = int(state.get("streak", 0))
    lapses = int(state.get("lapses", 0))
    if rating == "again":
        interval, streak, lapses = 10 / 1440, 0, lapses + 1
        ease = max(1.3, ease - 0.2)
    elif rating == "hard":
        interval = max(1.0, interval * 1.2)
        ease = max(1.3, ease - 0.15)
        streak = 0
    elif rating in {"good", "easy"}:
        interval = 3.0 if interval <= 1 or not state.get("review_count") else interval * ease
        if rating == "easy":
            interval *= 1.3
            ease = min(3.0, ease + 0.15)
        streak += 1
    else:
        raise ValueError("Unknown review rating")
    interval = min(365.0, round(interval, 3))
    return {
        "interval_days": interval,
        "ease": ease,
        "streak": streak,
        "lapses": lapses,
        "due_at": now + interval * DAY,
        "last_review_at": now,
        "review_count": int(state.get("review_count", 0)) + 1,
        "version": int(state.get("version", 0)) + 1,
    }
