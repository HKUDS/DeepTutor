"""Calendar-day practice metrics, counted from durable source and review records."""

from datetime import datetime, timedelta
import sqlite3
from zoneinfo import ZoneInfo

from .scheduler import day_bounds


def analytics(
    conn: sqlite3.Connection, timezone: str, days: int, now: float, scope: str, params: list
) -> dict:
    if days not in {7, 30, 90}:
        raise ValueError("Choose 7, 30 or 90 days")
    day_bounds(timezone, now)
    zone = ZoneInfo(timezone)
    today = datetime.fromtimestamp(now, zone).date()
    first = today - timedelta(days=days - 1)
    start = datetime.combine(first, datetime.min.time(), zone).timestamp()
    daily = {
        (first + timedelta(days=i)).isoformat(): {"questions": 0, "mistakes": 0, "reviews": 0}
        for i in range(days)
    }
    sources: dict[str, dict] = {}
    conn.create_function(
        "practice_day", 1, lambda ts: datetime.fromtimestamp(ts, zone).date().isoformat()
    )
    # Membership is historical; resolving a mistake does not erase its first-wrong date.
    queries = {
        "questions": ("", "n.created_at", ""),
        "mistakes": (
            "JOIN practice_review_state r ON r.entry_id=n.id",
            "r.first_wrong_at",
            "AND r.is_mistake=1",
        ),
        "reviews": (
            "JOIN practice_review_events e ON e.entry_id=n.id",
            "e.reviewed_at",
            "",
        ),
    }
    for metric, (join, timestamp, extra) in queries.items():
        rows = conn.execute(
            f"""SELECT practice_day({timestamp}) AS day,
                COALESCE(NULLIF(n.source, ''), 'deep_question') AS source, COUNT(*) AS count
                FROM notebook_entries n LEFT JOIN sessions s ON s.id=n.session_id {join}
                WHERE {scope} {extra} AND {timestamp}>=? AND {timestamp}<=?
                GROUP BY day, source""",  # nosec B608 - identifiers and scope are internal literals
            [*params, start, now],
        )
        for row in rows:
            daily[row["day"]][metric] += row["count"]
            source = sources.setdefault(
                row["source"],
                {"source": row["source"], "questions": 0, "mistakes": 0, "reviews": 0},
            )
            source[metric] += row["count"]
    return {
        "timezone": timezone,
        "days": days,
        "start_date": first.isoformat(),
        "end_date": today.isoformat(),
        "updated_at": now,
        "daily": [{"date": date, **counts} for date, counts in daily.items()],
        "sources": sorted(sources.values(), key=lambda row: row["source"]),
        "totals": {key: sum(row[key] for row in daily.values()) for key in queries},
    }
