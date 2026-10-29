"""RFC 5545 recurrence: wall-clock expansion, occurrence keys and series splits.

Timed events are stored as local wall time in their ``tzid`` and expanded on
that wall clock, then converted to UTC per instance — "every Monday 09:00
Europe/Berlin" stays at 09:00 across DST. A timed event's duration is kept in
absolute minutes; an all-day event's in days.

An *occurrence key* names one generated instance by its original start: the
date for all-day events, the UTC instant (``%Y-%m-%dT%H:%M:%SZ``) for timed
ones. Exdates and override rows refer to instances by this key.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrule as RecurrenceRule
from dateutil.rrule import rruleset, rrulestr

UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
WALL_FORMAT = "%Y-%m-%dT%H:%M:%S"
MAX_INSTANCES = 1000  # per series per query
MAX_COUNT = 10000
# A date is a different instant in every zone (UTC-12 … UTC+14); stored spans
# of all-day events are widened by this much so one index serves every zone.
ALL_DAY_PAD = timedelta(hours=14)

_RULE_KEYS = (
    "FREQ",
    "UNTIL",
    "COUNT",
    "INTERVAL",
    "BYSECOND",
    "BYMINUTE",
    "BYHOUR",
    "BYDAY",
    "BYMONTHDAY",
    "BYYEARDAY",
    "BYWEEKNO",
    "BYMONTH",
    "BYSETPOS",
    "WKST",
)
# Sub-hourly rules are not calendar events, and walking one from an old start
# to the requested range would cost more than the 1000-instance cap saves.
_FREQUENCIES = {"YEARLY", "MONTHLY", "WEEKLY", "DAILY", "HOURLY"}
_WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def zone(tzid: str) -> ZoneInfo:
    try:
        return ZoneInfo(tzid)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError(f"Unknown time zone {tzid!r}.") from exc


def parse_date(value: str) -> date:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ValueError("All-day times must be dates (YYYY-MM-DD).")
    return date.fromisoformat(value)


def parse_instant(value: str) -> datetime:
    """An ISO-8601 instant with an offset or Z, as an aware UTC datetime."""
    try:
        moment = datetime.fromisoformat(value) if "T" in value else None
    except (TypeError, ValueError):
        moment = None
    if moment is None or moment.tzinfo is None:
        raise ValueError("Times must be ISO-8601 instants with an offset or Z.")
    return moment.astimezone(timezone.utc).replace(microsecond=0)


def format_instant(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(UTC_FORMAT)


def to_wall(moment: datetime, tzid: str) -> str:
    return moment.astimezone(zone(tzid)).strftime(WALL_FORMAT)


def from_wall(wall: str, tzid: str, fold: int = 0) -> datetime:
    # Ambiguous wall times resolve to their first occurrence (fold=0), as
    # RFC 5545 prescribes for DTSTART;TZID.
    return (
        datetime.fromisoformat(wall).replace(tzinfo=zone(tzid), fold=fold).astimezone(timezone.utc)
    )


# ── RRULE text ───────────────────────────────────────────────────────────────


def parse_rule(value: str) -> dict[str, str]:
    """Validate one RRULE value and return its parts, FREQ first."""
    text = value.strip()
    if text.upper().startswith("RRULE:"):
        text = text[6:]
    if not text or any(char in text for char in "\r\n:"):
        raise ValueError("Give a single RRULE value without DTSTART.")
    parts: dict[str, str] = {}
    for item in filter(None, text.split(";")):
        key, separator, raw = item.partition("=")
        key, raw = key.strip().upper(), raw.strip().upper()
        if not separator or not raw:
            raise ValueError(f"Malformed recurrence part {item!r}.")
        if key == "DTSTART":
            raise ValueError("DTSTART cannot be part of the recurrence rule.")
        if key not in _RULE_KEYS:
            raise ValueError(f"Unsupported recurrence part {key}.")
        if key in parts:
            raise ValueError(f"Duplicate recurrence part {key}.")
        parts[key] = raw
    if parts.get("FREQ") not in _FREQUENCIES:
        raise ValueError("FREQ must be HOURLY, DAILY, WEEKLY, MONTHLY or YEARLY.")
    if "INTERVAL" in parts and not (
        parts["INTERVAL"].isdigit() and 0 < int(parts["INTERVAL"]) <= 10000
    ):
        raise ValueError("INTERVAL must be between 1 and 10000.")
    if "COUNT" in parts and "UNTIL" in parts:
        raise ValueError("COUNT and UNTIL cannot be combined.")
    if "COUNT" in parts and not (parts["COUNT"].isdigit() and 0 < int(parts["COUNT"]) <= MAX_COUNT):
        raise ValueError(f"COUNT must be between 1 and {MAX_COUNT}.")
    if "UNTIL" in parts:
        _parse_until(parts["UNTIL"])
    # dateutil checks the remaining syntax against a neutral, naive start.
    probe = {key: raw for key, raw in parts.items() if key != "UNTIL"}
    try:
        rrulestr("RRULE:" + format_rule(probe), dtstart=datetime(2000, 1, 3))
    except Exception as exc:  # dateutil raises ValueError, TypeError, KeyError…
        raise ValueError(f"Invalid recurrence rule: {exc}") from exc
    return {"FREQ": parts.pop("FREQ"), **parts}


def format_rule(parts: dict[str, str]) -> str:
    return ";".join(f"{key}={raw}" for key, raw in parts.items())


def _parse_until(raw: str) -> date | datetime:
    try:
        if re.fullmatch(r"\d{8}", raw):
            return datetime.strptime(raw, "%Y%m%d").date()
        if re.fullmatch(r"\d{8}T\d{6}", raw):
            return datetime.strptime(raw, "%Y%m%dT%H%M%S")
        if re.fullmatch(r"\d{8}T\d{6}Z", raw):
            return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    raise ValueError("UNTIL must be YYYYMMDD or YYYYMMDDTHHMMSS[Z].")


def _until_text(value: date | datetime, *, all_day: bool, tzid: str) -> str:
    """UNTIL in the value type RFC 5545 requires for this DTSTART."""
    if all_day:
        if isinstance(value, datetime):
            value = value.astimezone(zone(tzid)).date() if value.tzinfo else value.date()
        return value.strftime("%Y%m%d")
    if not isinstance(value, datetime):
        value = datetime.combine(value, time(23, 59, 59))
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone(tzid))
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def shift_weekdays(rule_text: str, days: int) -> str:
    """Move BYDAY/BYMONTHDAY along with a start that moved by ``days``.

    Without this, dragging a "weekly on Monday" instance to Tuesday would
    leave a Tuesday DTSTART that the rule itself never generates.
    """
    parts = parse_rule(rule_text)
    if "BYDAY" in parts and days % 7:
        shifted = []
        for item in parts["BYDAY"].split(","):
            match = re.fullmatch(r"([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)", item)
            if match is None:
                return rule_text
            index = (_WEEKDAYS.index(match.group(2)) + days) % 7
            shifted.append((match.group(1) or "") + _WEEKDAYS[index])
        parts["BYDAY"] = ",".join(shifted)
    if "BYMONTHDAY" in parts and days:
        values = [int(item) for item in parts["BYMONTHDAY"].split(",")]
        if all(0 < item + days <= 31 and item > 0 for item in values):
            parts["BYMONTHDAY"] = ",".join(str(item + days) for item in values)
    return format_rule(parts)


# ── Timing ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Instance:
    key: str
    start: str  # API encoding: date or UTC instant
    end: str
    start_at: datetime  # UTC; all-day dates resolve in the request's zone
    end_at: datetime


@dataclass(frozen=True)
class Timing:
    """The stored, RFC 5545-shaped time of one event row."""

    all_day: bool
    dtstart: str  # all-day: YYYY-MM-DD; timed: wall time in tzid
    dtend: str
    tzid: str
    rrule: str | None = None
    start_fold: int = 0
    end_fold: int = 0

    @classmethod
    def from_api(
        cls, *, all_day: bool, start: str, end: str, tzid: str, rrule: str | None
    ) -> Timing:
        if all_day:
            return cls(True, start, end, tzid, rrule)
        return cls(
            False,
            to_wall(parse_instant(start), tzid),
            to_wall(parse_instant(end), tzid),
            tzid,
            rrule,
            parse_instant(start).astimezone(zone(tzid)).fold,
            parse_instant(end).astimezone(zone(tzid)).fold,
        )

    @property
    def api_start(self) -> str:
        return (
            self.dtstart
            if self.all_day
            else format_instant(from_wall(self.dtstart, self.tzid, self.start_fold))
        )

    @property
    def api_end(self) -> str:
        return (
            self.dtend
            if self.all_day
            else format_instant(from_wall(self.dtend, self.tzid, self.end_fold))
        )

    @property
    def first(self) -> datetime:
        """DTSTART in rule space: naive midnight, or aware wall time."""
        if self.all_day:
            return datetime.combine(date.fromisoformat(self.dtstart), time())
        return datetime.fromisoformat(self.dtstart).replace(
            tzinfo=zone(self.tzid), fold=self.start_fold
        )

    @property
    def duration(self) -> timedelta:
        if self.all_day:
            return date.fromisoformat(self.dtend) - date.fromisoformat(self.dtstart)
        return from_wall(self.dtend, self.tzid, self.end_fold) - from_wall(
            self.dtstart, self.tzid, self.start_fold
        )

    def rule(self) -> RecurrenceRule | rruleset | None:
        if not self.rrule:
            return None
        return rrulestr("RRULE:" + self.rrule, dtstart=self.first)

    def key(self, start: datetime) -> str:
        return start.date().isoformat() if self.all_day else format_instant(start)

    def at_key(self, key: str) -> datetime:
        """The rule-space start an occurrence key names (not checked)."""
        if self.all_day:
            return datetime.combine(parse_date(key), time())
        return parse_instant(key).astimezone(zone(self.tzid))

    def instance(self, start: datetime, tz: ZoneInfo) -> Instance:
        if self.all_day:
            first = start.date()
            last = first + self.duration
            return Instance(
                first.isoformat(),
                first.isoformat(),
                last.isoformat(),
                datetime.combine(first, time(), tz).astimezone(timezone.utc),
                datetime.combine(last, time(), tz).astimezone(timezone.utc),
            )
        begin = start.astimezone(timezone.utc)
        finish = begin + self.duration
        key = format_instant(begin)
        return Instance(key, key, format_instant(finish), begin, finish)

    def starts(self, after: datetime | None = None) -> Iterator[datetime]:
        """Rule-space instance starts at or after ``after``, in order."""
        rule = self.rule()
        if rule is None:
            if after is None or not self.first < _rule_bound(after, self.all_day):
                yield self.first
            return
        yield from (
            rule if after is None else rule.xafter(_rule_bound(after, self.all_day), inc=True)
        )

    def is_instance(self, key: str) -> bool:
        try:
            target = self.at_key(key)
        except ValueError:
            return False
        for start in self.starts(target - timedelta(seconds=1)):
            return self.key(start) == key
        return False

    def first_key(self) -> str | None:
        return next((self.key(start) for start in self.starts()), None)

    def count_before(self, key: str) -> int:
        bound = _rule_bound(self.at_key(key), self.all_day)
        count = 0
        for start in self.starts():
            if start >= bound:
                break
            count += 1
        return count

    def span(self) -> tuple[str, str | None]:
        """A UTC superset of every instance, for the indexed range query."""
        pad = ALL_DAY_PAD if self.all_day else timedelta(0)
        first = _as_utc(self.first)
        last = first
        if self.rrule:
            parts = parse_rule(self.rrule)
            if "UNTIL" in parts:
                until = _parse_until(parts["UNTIL"])
                last = _as_utc(
                    until if isinstance(until, datetime) else datetime.combine(until, time())
                )
            elif "COUNT" in parts:
                last = _as_utc(list(self.starts())[-1])
            else:
                return format_instant(first - pad), None
        return format_instant(first - pad), format_instant(last + self.duration + pad)


def _as_utc(moment: datetime) -> datetime:
    """Naive all-day midnights read as UTC; the stored span pads for zones."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _rule_bound(moment: datetime, all_day: bool) -> datetime:
    """Comparable in rule space: naive for all-day, UTC-aware for timed.

    Comparing two datetimes that share one ZoneInfo compares wall clocks and
    ignores ``fold``; converting to UTC keeps timed comparisons absolute.
    """
    return moment.replace(tzinfo=None) if all_day else _as_utc(moment)


def normalize_rule(value: str, timing: Timing) -> str:
    """Canonical RRULE for ``timing``'s DTSTART; rejects rules that never occur."""
    parts = parse_rule(value)
    if "UNTIL" in parts:
        parts["UNTIL"] = _until_text(
            _parse_until(parts["UNTIL"]), all_day=timing.all_day, tzid=timing.tzid
        )
    text = format_rule(parts)
    rule = rrulestr("RRULE:" + text, dtstart=timing.first)
    if rule.after(_rule_bound(timing.first, timing.all_day), inc=True) is None:
        raise ValueError("This recurrence never occurs.")
    return text


def expand(
    timing: Timing,
    range_start: datetime,
    range_end: datetime,
    tz: ZoneInfo,
    *,
    exclude: frozenset[str] | set[str] = frozenset(),
    limit: int = MAX_INSTANCES,
) -> list[Instance]:
    """Instances overlapping [range_start, range_end), minus ``exclude`` keys.

    All-day date D spans [D 00:00, D+1 00:00) in the request zone ``tz``.
    """
    duration = timing.duration
    if timing.all_day:
        after = datetime.combine(range_start.astimezone(tz).date(), time()) - duration
        before = datetime.combine(range_end.astimezone(tz).date() + timedelta(days=1), time())
    else:
        after, before = range_start - duration, range_end
    instances: list[Instance] = []
    for start in timing.starts(after):
        if _rule_bound(start, timing.all_day) > _rule_bound(before, timing.all_day):
            break
        instance = timing.instance(start, tz)
        if instance.key in exclude:
            continue
        if instance.start_at < range_end and instance.end_at > range_start:
            instances.append(instance)
            if len(instances) >= limit:
                break
    return instances


# ── Scope splits ─────────────────────────────────────────────────────────────


def truncate_before(timing: Timing, key: str) -> str:
    """The series' rule ending just before occurrence ``key`` (COUNT → UNTIL)."""
    assert timing.rrule
    parts = parse_rule(timing.rrule)
    parts.pop("COUNT", None)
    start = timing.at_key(key)
    if timing.all_day:
        parts["UNTIL"] = (start.date() - timedelta(days=1)).strftime("%Y%m%d")
    else:
        parts["UNTIL"] = (start.astimezone(timezone.utc) - timedelta(seconds=1)).strftime(
            "%Y%m%dT%H%M%SZ"
        )
    return format_rule(parts)


def continuation(timing: Timing, key: str) -> str:
    """The series' rule for a new series starting at occurrence ``key``.

    UNTIL stays an absolute bound; COUNT becomes the instances still to come.
    """
    assert timing.rrule
    parts = parse_rule(timing.rrule)
    if "COUNT" in parts:
        parts["COUNT"] = str(max(1, int(parts["COUNT"]) - timing.count_before(key)))
    return format_rule(parts)
