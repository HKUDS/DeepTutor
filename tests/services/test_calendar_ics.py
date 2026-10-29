"""iCalendar rendering of stored events, exceptions, reminders and folding."""

from __future__ import annotations

import pytest

from deeptutor.services.calendar.ics import ics_filename, render_calendar
from deeptutor.services.calendar.models import (
    CreateCalendar,
    EventInput,
    EventPatch,
    EventPatchRequest,
    UpdateCalendar,
)
from deeptutor.services.calendar.store import CalendarStore


@pytest.fixture
def store(tmp_path):
    return CalendarStore(tmp_path / "calendar.sqlite")


def unfold(text: str) -> list[str]:
    combined = text.replace("\r\n ", "").replace("\r\n\t", "")
    return [line for line in combined.split("\r\n") if line]


def vevents(text: str) -> list[dict[str, list[str]]]:
    events: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] | None = None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            events.append(current)
            current = None
        elif current is not None:
            name, _, value = line.partition(":")
            key = name.split(";", 1)[0]
            current.setdefault(name, []).append(value)
            if key != name:
                current.setdefault(key, []).append(value)
    return events


def ics(store: CalendarStore, calendar_id: str | None = None) -> str:
    calendars, events = store.export(calendar_id)
    name = calendars[0].name.strip() if len(calendars) == 1 else "DeepTutor"
    return render_calendar(calendars, events, calendar_name=name or "DeepTutor")


def create(store: CalendarStore, **changes):
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


def test_empty_calendar_is_valid_vcalendar(store):
    text = ics(store)
    assert text.startswith("BEGIN:VCALENDAR\r\n")
    assert text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")
    lines = unfold(text)
    assert "VERSION:2.0" in lines
    assert "PRODID:-//HKUDS//DeepTutor//EN" in lines
    assert "CALSCALE:GREGORIAN" in lines
    assert "X-WR-CALNAME:DeepTutor" in lines
    assert not vevents(text)


def test_timed_event_uses_tzid_wall_time_and_vtimezone(store):
    event = create(store, title="Berlin study")
    text = ics(store)
    assert "BEGIN:VTIMEZONE" in text
    assert "TZID:Europe/Berlin" in text
    block = vevents(text)[0]
    assert block["UID"] == [f"{event.id}@deeptutor"]
    assert block["SUMMARY"] == ["Berlin study"]
    assert "DTSTART;TZID=Europe/Berlin" in block
    assert block["DTSTART;TZID=Europe/Berlin"] == ["20260322T090000"]
    assert block["DTEND;TZID=Europe/Berlin"] == ["20260322T100000"]
    assert block["DTSTAMP"][0].endswith("Z")


def test_all_day_multi_day_uses_exclusive_date_end(store):
    create(store, all_day=True, start="2026-03-22", end="2026-03-24", title="Trip")
    block = vevents(ics(store))[0]
    assert block["DTSTART;VALUE=DATE"] == ["20260322"]
    assert block["DTEND;VALUE=DATE"] == ["20260324"]


def test_weekly_rrule_count_and_until(store):
    counted = create(store, rrule="FREQ=WEEKLY;COUNT=3")
    until = create(
        store,
        title="Until series",
        start="2026-03-23T08:00:00Z",
        end="2026-03-23T09:00:00Z",
        rrule="FREQ=WEEKLY;UNTIL=20260420T080000Z",
    )
    blocks = {event["UID"][0]: event for event in vevents(ics(store))}
    assert blocks[f"{counted.id}@deeptutor"]["RRULE"] == ["FREQ=WEEKLY;COUNT=3"]
    rule = blocks[f"{until.id}@deeptutor"]["RRULE"][0]
    assert rule.startswith("FREQ=WEEKLY;UNTIL=")
    assert "COUNT=" not in rule
    assert rule.endswith("Z") or "UNTIL=20260420" in rule


def test_edited_occurrence_emits_recurrence_id(store):
    event = create(store, rrule="FREQ=WEEKLY;COUNT=3")
    store.update(
        event.id,
        EventPatchRequest(
            changes=EventPatch(
                start="2026-05-10T07:00:00Z",
                end="2026-05-10T08:00:00Z",
                title="Moved",
            ),
            scope="this",
            occurrence="2026-03-29T07:00:00Z",
        ),
    )
    blocks = vevents(ics(store))
    master = next(block for block in blocks if "RRULE" in block)
    override = next(block for block in blocks if "RECURRENCE-ID" in block)
    assert master["UID"] == override["UID"]
    assert override["RECURRENCE-ID;TZID=Europe/Berlin"] == ["20260329T090000"]
    assert override["DTSTART;TZID=Europe/Berlin"] == ["20260510T090000"]
    assert override["SUMMARY"] == ["Moved"]
    assert "RRULE" not in override


def test_deleted_occurrence_emits_exdate(store):
    event = create(store, rrule="FREQ=WEEKLY;COUNT=3")
    store.delete(event.id, "this", "2026-03-29T07:00:00Z")
    text = ics(store)
    blocks = vevents(text)
    assert len(blocks) == 1
    assert blocks[0]["EXDATE;TZID=Europe/Berlin"] == ["20260329T090000"]
    assert "RECURRENCE-ID" not in text


def test_reminders_timed_and_negative_all_day(store):
    create(store, reminders=[30, 0])
    create(
        store,
        title="All day",
        all_day=True,
        start="2026-03-22",
        end="2026-03-23",
        reminders=[-540, 1440],
    )
    text = ics(store)
    assert "TRIGGER:-PT30M" in text
    assert "TRIGGER:PT0M" in text
    assert "TRIGGER:PT540M" in text
    assert "TRIGGER:-PT1440M" in text
    assert text.count("BEGIN:VALARM") == 4
    assert "ACTION:DISPLAY" in text


def test_text_escaping(store):
    create(
        store,
        title="Meet; now, tomorrow",
        notes="Line 1\nLine 2\\slash",
        location="Hall A, Room 1; east",
    )
    text = ics(store)
    block = vevents(text)[0]
    assert block["SUMMARY"] == ["Meet\\; now\\, tomorrow"]
    assert block["DESCRIPTION"] == ["Line 1\\nLine 2\\\\slash"]
    assert block["LOCATION"] == ["Hall A\\, Room 1\\; east"]


def test_long_cjk_description_folds_on_utf8_boundaries(store):
    notes = "学习" * 40
    create(store, notes=notes)
    text = ics(store)
    assert "\r\n " in text
    for folded in text.split("\r\n"):
        folded.encode("utf-8")
        assert len(folded.encode("utf-8")) <= 75
    restored = next(line for line in unfold(text) if line.startswith("DESCRIPTION:"))
    assert restored == "DESCRIPTION:" + notes
    assert vevents(text)[0]["DESCRIPTION"] == [notes]


def test_untitled_event_emits_empty_summary(store):
    create(store, title="")
    assert vevents(ics(store))[0]["SUMMARY"] == [""]


def test_hidden_calendars_are_omitted_from_full_export(store):
    other = store.create_calendar(CreateCalendar(name="Hidden", color="#001122"))["calendar"]
    create(store, title="Visible")
    create(store, title="Secret", calendar_id=other.id)
    store.update_calendar(other.id, UpdateCalendar(visible=False))
    titles = [block["SUMMARY"][0] for block in vevents(ics(store))]
    assert titles == ["Visible"]
    secret = ics(store, other.id)
    assert vevents(secret)[0]["SUMMARY"] == ["Secret"]


def test_ics_filename_strips_path_chars():
    assert ics_filename("School/Work") == "School-Work.ics"
    assert ics_filename("  ") == "calendar.ics"
    assert ics_filename("数学") == "数学.ics"


def test_exported_timezone_roundtrips_both_dst_boundaries(store):
    from datetime import datetime
    from io import StringIO
    from zoneinfo import ZoneInfo

    from dateutil.tz import tzical

    create(store, tzid="America/New_York")
    timezone_text = "\r\n".join(
        line
        for line in unfold(ics(store))
        if not line.startswith(("X-WR-CALNAME", "PRODID", "CALSCALE"))
    )
    # dateutil parses the actual VTIMEZONE observances, independent of zoneinfo.
    parsed = tzical(StringIO(timezone_text)).get("America/New_York")
    expected = ZoneInfo("America/New_York")
    for wall in ["2026-03-08T01:30", "2026-03-08T03:30", "2026-11-01T00:30", "2026-11-01T02:30"]:
        instant = datetime.fromisoformat(wall)
        assert (
            instant.replace(tzinfo=parsed).utcoffset()
            == instant.replace(tzinfo=expected).utcoffset()
        )


def test_count_recurrence_timezone_covers_last_year(store):
    from deeptutor.services.calendar.ics import _tz_window

    create(store, tzid="America/New_York", rrule="FREQ=YEARLY;COUNT=10")
    _, events = store.export(None)
    _, end = _tz_window(events)
    assert end.year >= 2036
    assert "DTSTART:20350311T020000" in ics(store)


def test_long_timezone_span_fails_instead_of_silently_truncating(store):
    create(store, tzid="America/New_York", rrule="FREQ=YEARLY;COUNT=50")
    with pytest.raises(ValueError, match="40 years"):
        ics(store)
