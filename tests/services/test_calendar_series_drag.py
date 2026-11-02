"""Regression coverage for whole-series calendar rescheduling."""

from pathlib import Path

import pytest

from deeptutor.services.calendar.models import EventInput, EventPatch, EventPatchRequest
from deeptutor.services.calendar.recurrence import parse_instant
from deeptutor.services.calendar.store import CalendarStore


@pytest.mark.parametrize(
    "target_start,target_end,expected",
    [
        (
            "2026-03-30T06:00:00Z",
            "2026-03-30T07:00:00Z",
            ["2026-03-23T07:00:00Z", "2026-03-30T06:00:00Z", "2026-04-06T06:00:00Z"],
        ),
        (
            "2026-03-30T08:00:00Z",
            "2026-03-30T09:00:00Z",
            ["2026-03-23T09:00:00Z", "2026-03-30T08:00:00Z", "2026-04-06T08:00:00Z"],
        ),
        (
            "2026-03-29T06:00:00Z",
            "2026-03-29T07:00:00Z",
            ["2026-03-22T07:00:00Z", "2026-03-29T06:00:00Z", "2026-04-05T06:00:00Z"],
        ),
    ],
)
def test_series_drag_uses_calendar_days_not_rounded_negative_timedelta(
    tmp_path: Path, target_start: str, target_end: str, expected: list[str]
) -> None:
    """A backwards hour must not silently turn Monday sessions into Sundays."""
    store = CalendarStore(tmp_path / "calendar.sqlite")
    event = store.create(
        EventInput(
            title="Monday class",
            start="2026-03-23T08:00:00Z",
            end="2026-03-23T09:00:00Z",
            tzid="Europe/Berlin",
            rrule="FREQ=WEEKLY;COUNT=3;BYDAY=MO",
        )
    )["event"]
    store.update(
        event.id,
        EventPatchRequest(
            changes=EventPatch(start=target_start, end=target_end),
            scope="all",
            occurrence="2026-03-30T07:00:00Z",
        ),
    )
    rows = CalendarStore(store.path).occurrences(
        parse_instant("2026-03-20T00:00:00Z"),
        parse_instant("2026-04-10T00:00:00Z"),
        "Europe/Berlin",
    )["occurrences"]
    assert [row.start for row in rows] == expected
    assert len(rows) == 3
    assert all(
        (parse_instant(row.end) - parse_instant(row.start)).total_seconds() == 3600 for row in rows
    )
