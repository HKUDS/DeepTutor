"""Read-only projections of the selected workspace onto calendar days."""

from __future__ import annotations

from datetime import datetime, timezone
import math

from .models import (
    AutomationRun,
    CalendarLayers,
    FootprintDay,
    FootprintSession,
    ReviewDay,
    ReviewPathCount,
)
from .recurrence import format_instant, zone


def owner_key():
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.services.cron.service import CronOwner

    return CronOwner(kind="chat", user_id=get_current_user().id).key


def read_layers(workspace_id, start, end, tzid):
    from deeptutor.modules.catalog import module_enabled
    from deeptutor.services.cron.service import compute_next_run, get_cron_service
    from deeptutor.services.practice.storage import _DUE_AT_SQL, PracticeStore
    from deeptutor.services.session import get_sqlite_session_store

    tz = zone(tzid)
    lo, hi = start.timestamp(), end.timestamp()

    def day(ts):
        return datetime.fromtimestamp(ts, tz).date().isoformat()

    reviews, footprints = {}, {}

    def review(ts):
        key = day(ts)
        return reviews.setdefault(key, ReviewDay(date=key))

    def footprint(ts):
        key = day(ts)
        return footprints.setdefault(key, FootprintDay(date=key))

    if module_enabled("mastery"):
        from deeptutor.learning.policy import path_display_name
        from deeptutor.learning.scheduler import SpacedRepetitionScheduler
        from deeptutor.learning.storage import LearningStore

        learning = LearningStore()
        scheduler = SpacedRepetitionScheduler()
        for progress, _topic, _count, _interaction in learning.list_topic_snapshots():
            counts = {}
            for task in scheduler.build_review_queue(progress):
                if lo <= task.due_at < hi:
                    key = day(task.due_at)
                    counts[key] = counts.get(key, 0) + 1
            for key, count in counts.items():
                row = reviews.setdefault(key, ReviewDay(date=key))
                row.mastery += count
                row.paths.append(
                    ReviewPathCount(
                        id=progress.book_id, title=path_display_name(progress), count=count
                    )
                )
        with learning._connect() as db:
            for row in db.execute(
                "SELECT timestamp FROM mastery_learning_evidence WHERE timestamp>=? AND timestamp<?",
                (lo, hi),
            ):
                footprint(row[0]).mastery_evidence += 1

    practice = PracticeStore(get_sqlite_session_store().db_path)
    # The database is already workspace-scoped; match PracticeStore’s live-entry filter.
    scope = "(n.session_id IS NULL OR s.deleted_at IS NULL)"
    with practice.connect() as db:
        # SQL fragments are local constants; both time bounds use parameters.
        for row in db.execute(
            f"SELECT {_DUE_AT_SQL} AS due FROM notebook_entries n LEFT JOIN sessions s ON s.id=n.session_id LEFT JOIN practice_review_state r ON r.entry_id=n.id WHERE {scope} AND {_DUE_AT_SQL}>=? AND {_DUE_AT_SQL}<?",  # nosec B608
            (lo, hi),
        ):
            review(row[0]).practice += 1
        for row in db.execute(
            f"SELECT e.reviewed_at FROM practice_review_events e JOIN notebook_entries n ON n.id=e.entry_id LEFT JOIN sessions s ON s.id=n.session_id WHERE {scope} AND e.reviewed_at>=? AND e.reviewed_at<?",  # nosec B608
            (lo, hi),
        ):
            footprint(row[0]).practice_reviews += 1
        sessions_by_day = {}
        for row in db.execute(
            "SELECT m.created_at,s.id,s.title FROM messages m JOIN sessions s ON s.id=m.session_id WHERE s.deleted_at IS NULL AND m.role='user' AND m.created_at>=? AND m.created_at<?",
            (lo, hi),
        ):
            key = day(row[0])
            sessions_by_day.setdefault(key, {})[row[1]] = row[2] or ""
        for key, sessions in sessions_by_day.items():
            row = footprints.setdefault(key, FootprintDay(date=key))
            row.session_count = len(sessions)
            row.sessions = [
                FootprintSession(id=id, title=title) for id, title in list(sessions.items())[:20]
            ]

    automations = []
    for job in get_cron_service().list_jobs(owner_key()):
        if job.owner.kind != "chat" or job.owner.workspace_id != workspace_id or not job.enabled:
            continue
        at = job.state.next_run_at_ms
        if at is None:
            continue
        lower = max(int(lo * 1000), int(datetime.now(timezone.utc).timestamp() * 1000))
        if at < lower:
            if job.schedule.kind == "every":
                step = job.schedule.every_seconds * 1000
                at += max(0, math.ceil((lower - at) / step)) * step
            else:
                at = compute_next_run(job.schedule, lower - 1)
        for _ in range(1000):
            if at is None or at >= hi * 1000:
                break
            when = format_instant(datetime.fromtimestamp(at / 1000, timezone.utc))
            automations.append(
                AutomationRun(
                    id=f"{job.id}:{at}",
                    job_id=job.id,
                    name=job.name,
                    message=job.message,
                    at=when,
                    kind=job.schedule.kind,
                    expr=job.schedule.expr,
                    every_seconds=job.schedule.every_seconds,
                    session_id=job.owner.session_id,
                )
            )
            at = compute_next_run(job.schedule, at)
    return CalendarLayers(
        workspace_id=workspace_id,
        reviews=sorted(reviews.values(), key=lambda r: r.date),
        footprints=sorted(footprints.values(), key=lambda r: r.date),
        automations=automations,
    )
