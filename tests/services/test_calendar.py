"""Calendar behavior: recurrence identities, DST, transactional edits and undo."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3

from pydantic import ValidationError
import pytest

from deeptutor.services.calendar.models import (
    CreateCalendar,
    EventInput,
    EventPatch,
    EventPatchRequest,
)
from deeptutor.services.calendar.recurrence import parse_instant
from deeptutor.services.calendar.store import CalendarStore


@pytest.fixture
def store(tmp_path):
    return CalendarStore(tmp_path / "calendar.sqlite")


def create(store, **changes):
    return store.create(
        EventInput(
            **{
                "title": "Study",
                "start": "2026-03-22T08:00:00Z",
                "end": "2026-03-22T09:00:00Z",
                "tzid": "Europe/Berlin",
                **changes,
            }
        )
    )["event"]


def occurrences(
    store, start="2026-03-01T00:00:00Z", end="2026-05-01T00:00:00Z", tz="Europe/Berlin"
):
    return store.occurrences(parse_instant(start), parse_instant(end), tz)["occurrences"]


def patch(store, event, scope="all", key=None, **changes):
    return store.update(
        event.id, EventPatchRequest(changes=EventPatch(**changes), scope=scope, occurrence=key)
    )


def test_weekly_wall_time_survives_dst_and_reload(store):
    create(store, rrule="FREQ=WEEKLY;COUNT=3")
    assert [x.start for x in occurrences(CalendarStore(store.path))] == [
        "2026-03-22T08:00:00Z",
        "2026-03-29T07:00:00Z",
        "2026-04-05T07:00:00Z",
    ]


def test_all_day_exclusive_range_and_local_zone(store):
    create(store, all_day=True, start="2026-03-22", end="2026-03-24")
    assert (
        len(occurrences(store, "2026-03-21T16:00:00Z", "2026-03-22T16:00:00Z", "Asia/Shanghai"))
        == 1
    )
    assert not occurrences(store, "2026-03-23T16:00:00Z", "2026-03-24T16:00:00Z", "Asia/Shanghai")


def test_moved_override_does_not_leave_ghost_and_is_found_at_destination(store):
    event = create(store, rrule="FREQ=WEEKLY;COUNT=3")
    patch(
        store,
        event,
        "this",
        "2026-03-29T07:00:00Z",
        start="2026-05-10T07:00:00Z",
        end="2026-05-10T08:00:00Z",
    )
    assert len(occurrences(store)) == 2
    moved = occurrences(store, "2026-05-10T00:00:00Z", "2026-05-11T00:00:00Z")[0]
    assert moved.occurrence == "2026-03-29T07:00:00Z"
    store.delete(moved.event_id, "this")
    assert len(occurrences(store)) == 2


def test_following_split_preserves_remaining_count(store):
    event = create(store, rrule="FREQ=WEEKLY;COUNT=4")
    patch(store, event, "following", "2026-03-29T07:00:00Z", title="New study")
    rows = occurrences(store)
    assert [x.title for x in rows] == ["Study", "New study", "New study", "New study"]
    assert len({x.series_id for x in rows}) == 2


def test_all_edit_uses_occurrence_wall_delta_across_dst(store):
    event = create(store, rrule="FREQ=WEEKLY;COUNT=3;BYDAY=SU")
    patch(
        store,
        event,
        "all",
        "2026-03-29T07:00:00Z",
        start="2026-03-30T08:00:00Z",
        end="2026-03-30T09:00:00Z",
    )
    assert [r.start for r in occurrences(store)] == [
        "2026-03-23T09:00:00Z",
        "2026-03-30T08:00:00Z",
        "2026-04-06T08:00:00Z",
    ]


@pytest.mark.parametrize("scope,remaining", [("this", 2), ("following", 1), ("all", 0)])
def test_delete_and_undo_every_scope(store, scope, remaining):
    event = create(store, rrule="FREQ=WEEKLY;COUNT=3")
    result = store.delete(event.id, scope, "2026-03-29T07:00:00Z")
    assert len(occurrences(store)) == remaining
    store.restore(result["undo_token"])
    assert len(occurrences(store)) == 3
    with pytest.raises(KeyError):
        store.restore(result["undo_token"])


def test_undo_does_not_overwrite_concurrent_edit(store):
    event = create(store, rrule="FREQ=WEEKLY;COUNT=3")
    token = store.delete(event.id, "this", "2026-03-29T07:00:00Z")["undo_token"]
    patch(store, event, title="Changed elsewhere")
    with pytest.raises(ValueError, match="changed since"):
        store.restore(token)
    assert all(x.title == "Changed elsewhere" for x in occurrences(store))


def test_invalid_patch_rolls_back_and_revision_is_atomic(store):
    event = create(store)
    before = store.revision()
    with pytest.raises(ValidationError):
        patch(store, event, end="2026-03-21T00:00:00Z")
    assert store.revision() == before
    assert occurrences(store)[0].end == event.end


def test_concurrent_writes_do_not_lose_events(store):
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: create(store, title=str(i)), range(12)))
    assert len(occurrences(store)) == 12
    assert store.revision() == 12


def test_multiple_calendars_and_default_guard(store):
    other = store.create_calendar(CreateCalendar(name="School", color="#001122"))["calendar"]
    create(store, calendar_id=other.id)
    with pytest.raises(ValueError):
        store.delete_calendar("default")
    store.delete_calendar(other.id)
    assert not occurrences(store)


@pytest.mark.parametrize(
    "rule",
    [
        "FREQ=DAILY;INTERVAL=0",
        "FREQ=DAILY;INTERVAL=-1",
        "FREQ=DAILY;COUNT=0",
        "FREQ=DAILY;COUNT=2;UNTIL=20261231",
    ],
)
def test_invalid_repeat_rejected_before_expansion(store, rule):
    with pytest.raises((ValueError, ValidationError)):
        create(store, rrule=rule)


def test_legacy_task_database_gets_due_date_without_losing_cards(tmp_path):
    from deeptutor.services.task_board import TaskBoardStore, UpdateCard

    path = tmp_path / "tasks.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE cards(id TEXT PRIMARY KEY,title TEXT,note TEXT,status TEXT,archived INTEGER,created_at TEXT,updated_at TEXT,workspace_id TEXT); INSERT INTO cards VALUES('old','Old task','','todo',0,'2026-01-01','2026-01-01','');"
        )
    store = TaskBoardStore(path)
    assert store.read().cards[0].due_date is None
    store.update("old", UpdateCard(due_date="2026-10-17"), workspace_id="")
    assert store.read().cards[0].due_date == "2026-10-17"
    assert store.read().cards[0].title == "Old task"


def test_following_drag_moves_weekday_and_preserves_count(store):
    event = create(store, rrule="FREQ=WEEKLY;COUNT=3;BYDAY=SU")
    patch(
        store,
        event,
        "following",
        "2026-03-29T07:00:00Z",
        start="2026-03-30T07:00:00Z",
        end="2026-03-30T08:00:00Z",
    )
    assert [r.start for r in occurrences(store)] == [
        "2026-03-22T08:00:00Z",
        "2026-03-30T07:00:00Z",
        "2026-04-06T07:00:00Z",
    ]


def test_all_day_reminders_use_event_wall_clock_on_dst_day(store):
    create(store, all_day=True, start="2026-03-29", end="2026-03-30", reminders=[-540, 900])
    assert occurrences(store)[0].reminder_times == ["2026-03-29T07:00:00Z", "2026-03-28T08:00:00Z"]


def test_resize_later_occurrence_for_whole_series(store):
    event = create(store, rrule="FREQ=WEEKLY;COUNT=3")
    patch(store, event, "all", "2026-03-29T07:00:00Z", end="2026-03-29T09:00:00Z")
    assert [
        (parse_instant(r.end) - parse_instant(r.start)).total_seconds() for r in occurrences(store)
    ] == [7200] * 3


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-10-25T01:30:00Z", "2026-10-25T02:30:00Z"),
        ("2026-10-25T00:45:00Z", "2026-10-25T01:15:00Z"),
    ],
)
def test_explicit_instants_survive_repeated_dst_hour(store, start, end):
    event = create(store, start=start, end=end)
    row = occurrences(store, "2026-10-25T00:00:00Z", "2026-10-26T00:00:00Z")[0]
    assert (row.start, row.end) == (event.start, event.end)
