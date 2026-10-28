"""Account-local calendar persistence. Every mutation is one SQLite transaction."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .models import (
    CalendarEntry,
    CalendarEvent,
    CreateCalendar,
    EventInput,
    EventPatchRequest,
    Occurrence,
    UpdateCalendar,
)
from .recurrence import (
    Timing,
    continuation,
    expand,
    format_instant,
    normalize_rule,
    parse_date,
    parse_instant,
    shift_weekdays,
    truncate_before,
    zone,
)


def now() -> str:
    return format_instant(datetime.now(timezone.utc))


def timing(event: CalendarEvent) -> Timing:
    return Timing.from_api(**event.model_dump(include={"all_day", "start", "end", "tzid", "rrule"}))


class CalendarStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
                INSERT OR IGNORE INTO state VALUES(1,0);
                CREATE TABLE IF NOT EXISTS calendars(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, calendar_id TEXT NOT NULL REFERENCES calendars(id), series_id TEXT, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_calendar ON events(calendar_id);
                CREATE INDEX IF NOT EXISTS events_series ON events(series_id);
                CREATE TABLE IF NOT EXISTS undo(token TEXT PRIMARY KEY, created_at TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL);
            """)
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM calendars LIMIT 1").fetchone():
                stamp = now()
                entry = CalendarEntry(
                    id="default",
                    name="",
                    color="#2f6fde",
                    visible=True,
                    position=0,
                    is_default=True,
                    created_at=stamp,
                    updated_at=stamp,
                )
                db.execute("INSERT INTO calendars VALUES(?,?)", (entry.id, entry.model_dump_json()))

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _revision(db):
        return db.execute("SELECT revision FROM state WHERE id=1").fetchone()[0]

    @staticmethod
    def _changed(db):
        db.execute("UPDATE state SET revision=revision+1 WHERE id=1")
        return CalendarStore._revision(db)

    def revision(self):
        with self.connect() as db:
            return self._revision(db)

    def calendars(self):
        with self.connect() as db:
            db.execute("BEGIN")
            return {
                "calendars": [
                    CalendarEntry.model_validate_json(r[0])
                    for r in db.execute("SELECT payload FROM calendars")
                ],
                "revision": self._revision(db),
            }

    def create_calendar(self, payload: CreateCalendar):
        stamp = now()
        entry = CalendarEntry(
            **payload.model_dump(),
            id=uuid4().hex,
            visible=True,
            position=0,
            is_default=False,
            created_at=stamp,
            updated_at=stamp,
        )
        with self.connect(write=True) as db:
            entry.position = db.execute("SELECT COUNT(*) FROM calendars").fetchone()[0]
            db.execute("INSERT INTO calendars VALUES(?,?)", (entry.id, entry.model_dump_json()))
            return {"calendar": entry, "revision": self._changed(db)}

    def update_calendar(self, id: str, payload: UpdateCalendar):
        with self.connect(write=True) as db:
            row = db.execute("SELECT payload FROM calendars WHERE id=?", (id,)).fetchone()
            if row is None:
                raise KeyError(id)
            entry = CalendarEntry.model_validate_json(row[0]).model_copy(
                update={**payload.model_dump(exclude_unset=True), "updated_at": now()}
            )
            db.execute("UPDATE calendars SET payload=? WHERE id=?", (entry.model_dump_json(), id))
            return {"calendar": entry, "revision": self._changed(db)}

    def delete_calendar(self, id: str):
        with self.connect(write=True) as db:
            row = db.execute("SELECT payload FROM calendars WHERE id=?", (id,)).fetchone()
            if row is None:
                raise KeyError(id)
            if CalendarEntry.model_validate_json(row[0]).is_default:
                raise ValueError("The default calendar cannot be deleted.")
            db.execute("DELETE FROM events WHERE calendar_id=?", (id,))
            db.execute("DELETE FROM calendars WHERE id=?", (id,))
            return {"revision": self._changed(db)}

    @staticmethod
    def _get(db, id):
        row = db.execute("SELECT payload FROM events WHERE id=?", (id,)).fetchone()
        if row is None:
            raise KeyError(id)
        return CalendarEvent.model_validate_json(row[0])

    @staticmethod
    def _put(db, event):
        db.execute(
            "INSERT INTO events VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET calendar_id=excluded.calendar_id,series_id=excluded.series_id,payload=excluded.payload",
            (event.id, event.calendar_id, event.series_id, event.model_dump_json()),
        )

    @staticmethod
    def _validated(db, data):
        payload = EventInput.model_validate(data)
        payload.calendar_id = payload.calendar_id or "default"
        if not db.execute("SELECT 1 FROM calendars WHERE id=?", (payload.calendar_id,)).fetchone():
            raise ValueError("Calendar not found.")
        if payload.rrule:
            payload.rrule = normalize_rule(
                payload.rrule,
                Timing.from_api(
                    **payload.model_dump(include={"all_day", "start", "end", "tzid", "rrule"})
                ),
            )
        return payload.model_dump()

    def _new(self, db, data, **extra):
        event = CalendarEvent(
            **self._validated(db, data),
            id=uuid4().hex,
            exdates=[],
            series_id=None,
            recurrence_id=None,
            created_at=now(),
            updated_at=now(),
        )
        event = event.model_copy(update=extra)
        self._put(db, event)
        return event

    def create(self, payload: EventInput):
        with self.connect(write=True) as db:
            event = self._new(db, payload.model_dump())
            return {"event": event, "revision": self._changed(db)}

    @staticmethod
    def _fields(event):
        return event.model_dump(include=set(EventInput.model_fields))

    def _patch(self, db, event, changes):
        updated = event.model_copy(
            update={**self._validated(db, {**self._fields(event), **changes}), "updated_at": now()}
        )
        self._put(db, updated)
        return updated

    def update(self, id: str, request: EventPatchRequest):
        with self.connect(write=True) as db:
            event = self._get(db, id)
            master = self._get(db, event.series_id) if event.series_id else event
            changes = request.changes.model_dump(exclude_unset=True)
            key = request.occurrence or event.recurrence_id
            scope = request.scope
            rule = timing(master)
            if not master.rrule:
                self._patch(db, event, changes)
            else:
                if not key and scope != "all":
                    raise ValueError("An occurrence is required.")
                if key and not rule.is_instance(key):
                    raise ValueError("Occurrence does not belong to this series.")
                if scope == "following" and key == rule.first_key():
                    scope = "all"
                if scope == "this":
                    instance = rule.instance(rule.at_key(key), zone(master.tzid))
                    override = db.execute(
                        "SELECT id FROM events WHERE series_id=? AND json_extract(payload,'$.recurrence_id')=?",
                        (master.id, key),
                    ).fetchone()
                    if override:
                        self._patch(db, self._get(db, override[0]), {**changes, "rrule": None})
                    else:
                        self._new(
                            db,
                            {
                                **self._fields(master),
                                "start": instance.start,
                                "end": instance.end,
                                **changes,
                                "rrule": None,
                            },
                            series_id=master.id,
                            recurrence_id=key,
                        )
                elif scope == "following":
                    instance = rule.instance(rule.at_key(key), zone(master.tzid))
                    if (
                        "start" in changes
                        and "rrule" not in changes
                        and changes.get("all_day", master.all_day) == master.all_day
                    ):
                        origin = (
                            parse_date(instance.start)
                            if master.all_day
                            else parse_instant(instance.start).astimezone(zone(master.tzid)).date()
                        )
                        target = (
                            parse_date(changes["start"])
                            if master.all_day
                            else parse_instant(changes["start"])
                            .astimezone(zone(master.tzid))
                            .date()
                        )
                        changes["rrule"] = shift_weekdays(
                            continuation(rule, key), (target - origin).days
                        )
                    new = self._new(
                        db,
                        {
                            **self._fields(master),
                            "start": instance.start,
                            "end": instance.end,
                            "rrule": continuation(rule, key),
                            **changes,
                        },
                    )
                    # Existing exceptions stay attached to their original instances when
                    # only descriptive fields change. A reschedule intentionally resets them.
                    reset = any(k in changes for k in ("start", "all_day", "tzid", "rrule"))
                    later = [
                        r
                        for r in self._series(db, master.id)
                        if r.series_id and r.recurrence_id >= key
                    ]
                    for row in later:
                        if reset:
                            db.execute("DELETE FROM events WHERE id=?", (row.id,))
                        else:
                            self._put(
                                db,
                                row.model_copy(
                                    update={"series_id": new.id, "calendar_id": new.calendar_id}
                                ),
                            )
                    new.exdates = [] if reset else [x for x in master.exdates if x >= key]
                    self._put(db, new)
                    master.exdates = [x for x in master.exdates if x < key]
                    self._patch(db, master, {"rrule": truncate_before(rule, key)})
                else:
                    # Dragging an occurrence shifts the series in its own wall clock.
                    if key and ("start" in changes or "end" in changes):
                        instance = rule.instance(rule.at_key(key), zone(master.tzid))
                        changes.setdefault("start", instance.start)
                        changes.setdefault("end", instance.end)
                    if (
                        key
                        and "start" in changes
                        and changes.get("all_day", master.all_day) == master.all_day
                    ):
                        if master.all_day:
                            delta = parse_date(changes["start"]) - parse_date(key)
                            duration = parse_date(changes.get("end", master.end)) - parse_date(
                                changes["start"]
                            )
                            start = parse_date(master.start) + delta
                            changes.update(
                                start=start.isoformat(), end=(start + duration).isoformat()
                            )
                        else:
                            tz = zone(master.tzid)
                            target = parse_instant(changes["start"]).astimezone(tz)
                            origin = parse_instant(key).astimezone(tz)
                            delta = target.replace(tzinfo=None) - origin.replace(tzinfo=None)
                            duration = parse_instant(
                                changes.get("end", master.end)
                            ) - parse_instant(changes["start"])
                            start = parse_instant(master.start).astimezone(tz) + delta
                            changes.update(
                                start=format_instant(start),
                                end=format_instant(start.astimezone(timezone.utc) + duration),
                            )
                        if "rrule" not in changes:
                            changes["rrule"] = shift_weekdays(master.rrule, delta.days)
                    reset = any(k in changes for k in ("start", "all_day", "tzid", "rrule"))
                    if reset:
                        db.execute("DELETE FROM events WHERE series_id=?", (master.id,))
                        master.exdates = []
                    self._patch(db, master, changes)
                    if not reset:
                        for row in self._series(db, master.id):
                            if row.series_id:
                                self._patch(db, row, changes)
            return {"revision": self._changed(db)}

    @staticmethod
    def _series(db, id):
        return [
            CalendarEvent.model_validate_json(r[0])
            for r in db.execute("SELECT payload FROM events WHERE id=? OR series_id=?", (id, id))
        ]

    def delete(self, id: str, scope="all", occurrence=None):
        with self.connect(write=True) as db:
            event = self._get(db, id)
            master = self._get(db, event.series_id) if event.series_id else event
            key = occurrence or event.recurrence_id
            before = self._series(db, master.id)
            rule = timing(master)
            if master.rrule and scope != "all":
                if not key or not rule.is_instance(key):
                    raise ValueError("A valid occurrence is required.")
                if scope == "following" and key == rule.first_key():
                    scope = "all"
            if not master.rrule or scope == "all":
                db.execute("DELETE FROM events WHERE id=? OR series_id=?", (master.id, master.id))
            elif scope == "this":
                master.exdates = sorted(set([*master.exdates, key]))
                self._put(db, master)
                for row in before:
                    if row.series_id and row.recurrence_id == key:
                        db.execute("DELETE FROM events WHERE id=?", (row.id,))
            else:
                self._patch(db, master, {"rrule": truncate_before(rule, key)})
                for row in before:
                    if row.series_id and row.recurrence_id >= key:
                        db.execute("DELETE FROM events WHERE id=?", (row.id,))
            token = uuid4().hex
            after = self._series(db, master.id)

            def dump(rows):
                return json.dumps([r.model_dump() for r in rows], sort_keys=True)

            db.execute(
                "DELETE FROM undo WHERE created_at<?",
                (format_instant(datetime.now(timezone.utc) - timedelta(minutes=15)),),
            )
            db.execute(
                "INSERT INTO undo VALUES(?,?,?,?)", (token, now(), dump(before), dump(after))
            )
            return {"revision": self._changed(db), "undo_token": token}

    def restore(self, token):
        with self.connect(write=True) as db:
            row = db.execute(
                "SELECT before_json,after_json,created_at FROM undo WHERE token=?", (token,)
            ).fetchone()
            if not row or parse_instant(row[2]) < datetime.now(timezone.utc) - timedelta(
                minutes=15
            ):
                raise KeyError(token)
            before, after = json.loads(row[0]), json.loads(row[1])
            master_id = next(r["id"] for r in before if not r["series_id"])
            current = [r.model_dump() for r in self._series(db, master_id)]
            if sorted(current, key=lambda r: r["id"]) != sorted(after, key=lambda r: r["id"]):
                raise ValueError(
                    "This series changed since deletion; undo would overwrite newer edits."
                )
            if not all(
                db.execute("SELECT 1 FROM calendars WHERE id=?", (r["calendar_id"],)).fetchone()
                for r in before
            ):
                raise ValueError("The calendar has been deleted.")
            db.execute("DELETE FROM events WHERE id=? OR series_id=?", (master_id, master_id))
            for data in before:
                self._put(db, CalendarEvent.model_validate(data))
            db.execute("DELETE FROM undo WHERE token=?", (token,))
            return {"revision": self._changed(db)}

    def occurrences(self, start, end, tzid):
        with self.connect() as db:
            db.execute("BEGIN")
            rows = [
                CalendarEvent.model_validate_json(r[0])
                for r in db.execute("SELECT payload FROM events")
            ]
            revision = self._revision(db)
        masters = {row.id: row for row in rows if not row.series_id}
        excluded = {id: set(row.exdates) for id, row in masters.items()}
        for row in rows:
            if row.series_id in excluded:
                excluded[row.series_id].add(row.recurrence_id)
        result = []
        for row in rows:
            master = masters.get(row.series_id) if row.series_id else row
            if master is None or (row.series_id and row.recurrence_id in master.exdates):
                continue
            for item in expand(
                timing(row), start, end, zone(tzid), exclude=excluded.get(row.id, set())
            ):
                result.append(
                    Occurrence(
                        **{
                            **self._fields(row),
                            "rrule": master.rrule,
                            "start": item.start,
                            "end": item.end,
                        },
                        id=f"{row.id}:{row.recurrence_id or item.key}",
                        event_id=row.id,
                        series_id=master.id if master.rrule else None,
                        occurrence=row.recurrence_id or item.key,
                        recurring=bool(master.rrule),
                        source=row.source,
                        reminder_times=[
                            format_instant(
                                (
                                    datetime.combine(parse_date(item.start), time(), zone(row.tzid))
                                    if row.all_day
                                    else parse_instant(item.start)
                                )
                                - timedelta(minutes=minutes)
                            )
                            for minutes in row.reminders
                        ],
                    )
                )
        result.sort(key=lambda r: (r.start, r.id))
        return {"occurrences": result, "revision": revision}

    def task_blocks(self, workspace_id):
        with self.connect() as db:
            counts = {}
            for row in db.execute("SELECT payload FROM events WHERE series_id IS NULL"):
                event = CalendarEvent.model_validate_json(row[0])
                if event.task_id and event.task_workspace_id == workspace_id:
                    counts[event.task_id] = counts.get(event.task_id, 0) + 1
            return counts

    def search(self, query, limit=50):
        with self.connect() as db:
            rows = [
                CalendarEvent.model_validate_json(r[0])
                for r in db.execute("SELECT payload FROM events")
            ]
        excluded = {row.id: set(row.exdates) for row in rows if not row.series_id}
        for row in rows:
            if row.series_id in excluded:
                excluded[row.series_id].add(row.recurrence_id)
        hits = []
        moment = datetime.now(timezone.utc)
        for event in rows:
            if (
                query.casefold()
                not in "\n".join((event.title, event.notes, event.location)).casefold()
            ):
                continue
            future = expand(
                timing(event),
                moment,
                moment + timedelta(days=3660),
                zone(event.tzid),
                exclude=excluded.get(event.id, set()),
                limit=1,
            )
            hits.append(
                {
                    **event.model_dump(),
                    "next_start": future[0].start
                    if future
                    else (None if event.rrule else event.start),
                }
            )

        def order(hit):
            value = hit["next_start"] or hit["start"]
            timestamp = (
                datetime.combine(parse_date(value), time(), zone(hit["tzid"])).timestamp()
                if hit["all_day"]
                else parse_instant(value).timestamp()
            )
            return (0, timestamp) if timestamp >= moment.timestamp() else (1, -timestamp)

        return {"events": sorted(hits, key=order)[:limit]}


def get_calendar_store():
    from deeptutor.multi_user.paths import get_account_path_service

    return CalendarStore(
        get_account_path_service().get_runtime_state_dir() / "calendar" / "calendar.sqlite"
    )
