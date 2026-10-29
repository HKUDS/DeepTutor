"""Render stored calendar events as RFC 5545 iCalendar text.

Timed events use local wall time with ``TZID`` and a ``VTIMEZONE`` per used
zone. Offsets come from ``zoneinfo`` transitions in a window covering the
exported events (padded by a year; spans over 40 years are rejected). UTC timed events use
the ``Z`` form and skip ``VTIMEZONE``. All-day events use ``VALUE=DATE`` with
the store's exclusive end date.

A series is one ``VEVENT`` (UID ``<id>@deeptutor``) plus ``EXDATE`` for deleted
occurrences and separate ``VEVENT``s with ``RECURRENCE-ID`` for per-occurrence
overrides. Workspace overlay layers are not stored as events and are omitted.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from .models import CalendarEntry, CalendarEvent
from .recurrence import Timing, parse_instant, to_wall, zone

PRODID = "-//HKUDS//DeepTutor//EN"
UID_HOST = "deeptutor"
DEFAULT_CALENDAR_NAME = "DeepTutor"
_FOLD = 75
_TZ_PAD_YEARS = 1
_TZ_MAX_SPAN = 40
_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_UNTIL_YEAR = re.compile(r"UNTIL=(\d{4})")


def ics_filename(name: str) -> str:
    """Return a sanitised ``.ics`` attachment name for ``name``."""
    cleaned = _UNSAFE_FILENAME.sub("-", name).strip(" .")[:80] or "calendar"
    if not cleaned.lower().endswith(".ics"):
        cleaned = f"{cleaned}.ics"
    return cleaned


def render_calendar(
    calendars: Sequence[CalendarEntry],
    events: Sequence[CalendarEvent],
    *,
    calendar_name: str | None = None,
) -> str:
    """Return RFC 5545 text (CRLF, folded) for the given calendars and events.

    Args:
        calendars: Calendar rows included in the file (used only for naming
            when ``calendar_name`` is omitted).
        events: Master rows and override rows to serialise.
        calendar_name: ``X-WR-CALNAME``. Defaults to the sole calendar's name
            or ``DeepTutor``.
    """
    title = calendar_name or _calendar_title(calendars)
    masters = [event for event in events if not event.series_id]
    overrides: dict[str, list[CalendarEvent]] = {}
    master_ids = {event.id for event in masters}
    for event in events:
        if event.series_id and event.series_id in master_ids:
            overrides.setdefault(event.series_id, []).append(event)
    for group in overrides.values():
        group.sort(key=lambda item: (item.recurrence_id or "", item.id))
    masters.sort(key=lambda item: (item.start, item.id))

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        _text("X-WR-CALNAME", title),
    ]
    for tzid in _used_zones(events):
        lines.extend(_vtimezone(tzid, events))
    for event in masters:
        lines.extend(_vevent(event, overrides.get(event.id, ())))
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _calendar_title(calendars: Sequence[CalendarEntry]) -> str:
    if len(calendars) == 1 and calendars[0].name.strip():
        return calendars[0].name.strip()
    return DEFAULT_CALENDAR_NAME


def _used_zones(events: Sequence[CalendarEvent]) -> list[str]:
    zones = {
        event.tzid for event in events if not event.all_day and event.tzid and event.tzid != "UTC"
    }
    return sorted(zones)


def _timing(event: CalendarEvent) -> Timing:
    return Timing.from_api(
        all_day=event.all_day,
        start=event.start,
        end=event.end,
        tzid=event.tzid,
        rrule=event.rrule,
    )


def _uid(event_id: str) -> str:
    return f"{event_id}@{UID_HOST}"


def _vevent(master: CalendarEvent, exceptions: Sequence[CalendarEvent]) -> list[str]:
    lines = _event_body(
        master,
        uid=_uid(master.id),
        rrule=master.rrule,
        exdates=master.exdates,
    )
    for item in exceptions:
        if not item.recurrence_id:
            continue
        lines.extend(
            _event_body(
                item,
                uid=_uid(master.id),
                recurrence_id=item.recurrence_id,
                recurrence_all_day=master.all_day,
                recurrence_tzid=master.tzid,
            )
        )
    return lines


def _event_body(
    event: CalendarEvent,
    *,
    uid: str,
    rrule: str | None = None,
    exdates: Sequence[str] = (),
    recurrence_id: str | None = None,
    recurrence_all_day: bool = False,
    recurrence_tzid: str = "UTC",
) -> list[str]:
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{_stamp(event.updated_at)}"]
    if recurrence_id:
        lines.append(_recurrence_stamp(recurrence_id, recurrence_all_day, recurrence_tzid))
    lines.extend(_dtstart_dtend(event))
    lines.append(_text("SUMMARY", event.title))
    if event.notes:
        lines.append(_text("DESCRIPTION", event.notes))
    if event.location:
        lines.append(_text("LOCATION", event.location))
    if rrule:
        lines.append(f"RRULE:{rrule}")
    for key in exdates:
        lines.append(_recurrence_stamp(key, event.all_day, event.tzid, name="EXDATE"))
    for minutes in event.reminders:
        lines.extend(_valarm(minutes, event.all_day, event.title))
    lines.append("END:VEVENT")
    return lines


def _dtstart_dtend(event: CalendarEvent) -> list[str]:
    timing = _timing(event)
    if event.all_day:
        return [
            _prop("DTSTART", _ics_date(timing.dtstart), VALUE="DATE"),
            _prop("DTEND", _ics_date(timing.dtend), VALUE="DATE"),
        ]
    if event.tzid == "UTC":
        return [
            _prop("DTSTART", f"{_ics_datetime(timing.dtstart)}Z"),
            _prop("DTEND", f"{_ics_datetime(timing.dtend)}Z"),
        ]
    return [
        _prop("DTSTART", _ics_datetime(timing.dtstart), TZID=event.tzid),
        _prop("DTEND", _ics_datetime(timing.dtend), TZID=event.tzid),
    ]


def _recurrence_stamp(key: str, all_day: bool, tzid: str, *, name: str = "RECURRENCE-ID") -> str:
    if all_day:
        return _prop(name, _ics_date(key), VALUE="DATE")
    wall = to_wall(parse_instant(key), tzid)
    if tzid == "UTC":
        return _prop(name, f"{_ics_datetime(wall)}Z")
    return _prop(name, _ics_datetime(wall), TZID=tzid)


def _valarm(minutes: int, all_day: bool, title: str) -> list[str]:
    if all_day and minutes < 0:
        trigger = f"PT{abs(minutes)}M"
    elif minutes == 0:
        trigger = "PT0M"
    else:
        trigger = f"-PT{minutes}M"
    return [
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        _text("DESCRIPTION", title or "Reminder"),
        f"TRIGGER:{trigger}",
        "END:VALARM",
    ]


def _stamp(instant: str) -> str:
    return parse_instant(instant).strftime("%Y%m%dT%H%M%SZ")


def _ics_date(value: str) -> str:
    return value.replace("-", "")


def _ics_datetime(wall: str) -> str:
    return f"{wall[:4]}{wall[5:7]}{wall[8:10]}T{wall[11:13]}{wall[14:16]}{wall[17:19]}"


def _text(name: str, value: str) -> str:
    return _prop(name, _escape(value))


def _prop(name: str, value: str, **params: str) -> str:
    extra = "".join(f";{key}={raw}" for key, raw in params.items())
    return f"{name}{extra}:{value}"


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """Fold ``line`` to 75 UTF-8 octets, splitting on character boundaries."""
    data = line.encode("utf-8")
    if len(data) <= _FOLD:
        return line
    chunks: list[bytes] = []
    limit = _FOLD
    rest = data
    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break
        n = limit
        while n > 0 and rest[n] & 0xC0 == 0x80:
            n -= 1
        if n == 0:
            n = limit
        chunks.append(rest[:n])
        rest = rest[n:]
        limit = _FOLD - 1
    first, *more = chunks
    return "\r\n".join([first.decode("utf-8"), *[f" {piece.decode('utf-8')}" for piece in more]])


def _vtimezone(tzid: str, events: Sequence[CalendarEvent]) -> list[str]:
    tz = zone(tzid)
    start, end = _tz_window([event for event in events if event.tzid == tzid])
    lines = ["BEGIN:VTIMEZONE", f"TZID:{tzid}"]
    initial_offset = start.astimezone(tz).utcoffset() or timedelta(0)
    lines.extend(
        _observance(
            start + initial_offset,
            initial_offset,
            initial_offset,
            bool(start.astimezone(tz).dst()),
            start.astimezone(tz).tzname() or "",
        )
    )
    for onset, from_off, to_off, is_dst, name in _transitions(tz, start, end):
        lines.extend(_observance(onset + from_off, from_off, to_off, is_dst, name))
    lines.append("END:VTIMEZONE")
    return lines


def _observance(
    local_onset: datetime,
    offset_from: timedelta,
    offset_to: timedelta,
    is_dst: bool,
    tzname: str,
) -> list[str]:
    kind = "DAYLIGHT" if is_dst else "STANDARD"
    onset = local_onset.replace(tzinfo=None).strftime("%Y%m%dT%H%M%S")
    lines = [
        f"BEGIN:{kind}",
        f"DTSTART:{onset}",
        f"TZOFFSETFROM:{_offset_text(offset_from)}",
        f"TZOFFSETTO:{_offset_text(offset_to)}",
    ]
    if tzname:
        lines.append(_text("TZNAME", tzname))
    lines.append(f"END:{kind}")
    return lines


def _offset_text(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, rem = divmod(total, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{sign}{hours:02d}{minutes:02d}"


def _tz_window(events: Sequence[CalendarEvent]) -> tuple[datetime, datetime]:
    years: list[int] = []
    unbounded = False
    for event in events:
        years.extend([int(event.start[:4]), int(event.end[:4])])
        if not event.rrule:
            continue
        until = _UNTIL_YEAR.search(event.rrule)
        if until:
            years.append(int(until.group(1)))
        elif "COUNT=" in event.rrule:
            timing = _timing(event)
            # COUNT is validated and bounded by the calendar recurrence layer.
            for occurrence in timing.starts():
                years.append((occurrence + timing.duration).year)
        else:
            unbounded = True
    now_year = datetime.now(timezone.utc).year
    lo = max(1, min(years, default=now_year) - _TZ_PAD_YEARS)
    hi = min(9999, max(years, default=now_year) + _TZ_PAD_YEARS + 1)
    if unbounded:
        hi = max(hi, now_year + 15)
    if hi - lo > _TZ_MAX_SPAN:
        raise ValueError("Calendar export cannot cover more than 40 years of timezone transitions.")
    return (
        datetime(lo, 1, 1, tzinfo=timezone.utc),
        datetime(hi, 1, 1, tzinfo=timezone.utc),
    )


def _transitions(
    tz: ZoneInfo, start: datetime, end: datetime
) -> list[tuple[datetime, timedelta, timedelta, bool, str]]:
    """UTC onsets in ``(start, end]`` where the zone offset changes."""
    found: list[tuple[datetime, timedelta, timedelta, bool, str]] = []
    step = timedelta(hours=1)
    prev = start
    prev_off = prev.astimezone(tz).utcoffset() or timedelta(0)
    moment = start + step
    while moment <= end:
        off = moment.astimezone(tz).utcoffset() or timedelta(0)
        if off != prev_off:
            onset = _first_changed(tz, prev, moment, prev_off)
            new_off = onset.astimezone(tz).utcoffset() or timedelta(0)
            found.append(
                (
                    onset,
                    prev_off,
                    new_off,
                    bool(onset.astimezone(tz).dst()),
                    onset.astimezone(tz).tzname() or "",
                )
            )
            prev_off = new_off
            prev = onset
            moment = onset + step
        else:
            prev = moment
            moment += step
    return found


def _first_changed(tz: ZoneInfo, start: datetime, end: datetime, previous: timedelta) -> datetime:
    lo, hi = start, end
    while hi - lo > timedelta(seconds=1):
        mid = lo + timedelta(seconds=int((hi - lo).total_seconds() // 2))
        if (mid.astimezone(tz).utcoffset() or timedelta(0)) == previous:
            lo = mid
        else:
            hi = mid
    return hi
