"""Wire models for the account calendar.

The encodings follow RFC 5545 so an ICS file maps onto them one to one:
all-day events carry plain dates with an *exclusive* end date, timed events
carry UTC instants on the wire and local wall time in ``tzid`` in storage.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .recurrence import format_instant, format_rule, parse_date, parse_instant, parse_rule, zone

CalendarColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
CalendarName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
EventTitle = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
EventNotes = Annotated[str, StringConstraints(max_length=5000)]
EventLocation = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Scope = Literal["this", "following", "all"]
EventSource = Literal["user", "dito", "import"]

# Minutes before the start. All-day events may also go negative, down to one
# minute before the day ends: -540 reads "on the day at 09:00".
MIN_REMINDER = -1439
MAX_REMINDER = 40320  # four weeks
MAX_REMINDERS = 5


def _tzid(value: str) -> str:
    zone(value)
    return value


def _rrule(value: str | None) -> str | None:
    # Syntax only; UNTIL is normalised against the event's start in the store.
    return None if value is None else format_rule(parse_rule(value))


def _reminders(value: list[int]) -> list[int]:
    unique = sorted(set(value))
    if len(unique) > MAX_REMINDERS:
        raise ValueError(f"At most {MAX_REMINDERS} reminders.")
    if any(item < MIN_REMINDER or item > MAX_REMINDER for item in unique):
        raise ValueError(f"Reminders must be between {MIN_REMINDER} and {MAX_REMINDER} minutes.")
    return unique


TimeZoneId = Annotated[str, StringConstraints(min_length=1, max_length=64), AfterValidator(_tzid)]
RecurrenceRule = Annotated[str, StringConstraints(max_length=500), AfterValidator(_rrule)]
Reminders = Annotated[list[int], Field(max_length=20), AfterValidator(_reminders)]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=200)]


def _reject_null(value: object) -> object:
    if value is None:
        raise ValueError("This field cannot be null.")
    return value


class CalendarEntry(BaseModel):
    id: str
    # Empty for the default calendar: the UI shows its localized name.
    name: str
    color: str
    visible: bool
    position: int
    is_default: bool
    created_at: str
    updated_at: str


class CreateCalendar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: CalendarName
    color: CalendarColor


class UpdateCalendar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: CalendarName | None = None
    color: CalendarColor | None = None
    visible: bool | None = None
    position: int | None = Field(default=None, ge=0, le=100000)

    @field_validator("name", "color", "visible", "position", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        return _reject_null(value)


class EventInput(BaseModel):
    """A new event, or the merged result of a patch before it is stored."""

    model_config = ConfigDict(extra="forbid")
    calendar_id: Identifier | None = None  # None: the default calendar
    title: EventTitle = ""  # may be empty; the UI shows "Untitled"
    notes: EventNotes = ""
    location: EventLocation = ""
    all_day: bool = False
    # all_day: "YYYY-MM-DD" with an exclusive end; timed: instants with an
    # offset or Z, normalised to "YYYY-MM-DDTHH:MM:SSZ".
    start: str = Field(max_length=40)
    end: str = Field(max_length=40)
    tzid: TimeZoneId = "UTC"  # the browser's zone when the event was made
    rrule: RecurrenceRule | None = None  # RFC 5545 RRULE value, no "RRULE:"
    reminders: Reminders = Field(default_factory=list)
    color: CalendarColor | None = None
    task_id: Identifier | None = None  # a time block for a task card
    task_workspace_id: str | None = Field(default=None, max_length=200)  # "" = General

    @model_validator(mode="after")
    def check_times(self) -> EventInput:
        if self.all_day:
            start, end = parse_date(self.start), parse_date(self.end)
            self.start, self.end = start.isoformat(), end.isoformat()
        else:
            start, end = parse_instant(self.start), parse_instant(self.end)
            self.start, self.end = format_instant(start), format_instant(end)
        if end <= start:
            raise ValueError("The end must be after the start.")
        if not self.all_day and any(item < 0 for item in self.reminders):
            raise ValueError("Only all-day events take reminders after the day starts.")
        return self


class EventPatch(BaseModel):
    """Every field optional; explicit null clears rrule/color/task links only."""

    model_config = ConfigDict(extra="forbid")
    calendar_id: Identifier | None = None
    title: EventTitle | None = None
    notes: EventNotes | None = None
    location: EventLocation | None = None
    all_day: bool | None = None
    start: str | None = Field(default=None, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    tzid: TimeZoneId | None = None
    rrule: RecurrenceRule | None = None
    reminders: Reminders | None = None
    color: CalendarColor | None = None
    task_id: Identifier | None = None
    task_workspace_id: str | None = Field(default=None, max_length=200)

    @field_validator(
        "calendar_id",
        "title",
        "notes",
        "location",
        "all_day",
        "start",
        "end",
        "tzid",
        "reminders",
        mode="before",
    )
    @classmethod
    def reject_null(cls, value: object) -> object:
        return _reject_null(value)


class EventPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: EventPatch
    scope: Scope = "all"
    # The occurrence key being edited. With it, ``changes.start``/``end`` are
    # that occurrence's new times rather than the series' first instance.
    occurrence: str | None = Field(default=None, max_length=40)


class CalendarEvent(BaseModel):
    """A stored master or override row."""

    id: str
    calendar_id: str
    title: str
    notes: str
    location: str
    all_day: bool
    start: str
    end: str
    tzid: str
    rrule: str | None
    exdates: list[str]
    reminders: list[int]
    color: str | None
    task_id: str | None
    task_workspace_id: str | None
    series_id: str | None  # override rows: the master's id
    recurrence_id: str | None  # override rows: the occurrence key it replaces
    source: EventSource = "user"
    created_at: str
    updated_at: str


class Occurrence(BaseModel):
    """One rendered instance of a stored event."""

    id: str  # f"{event_id}:{occurrence}", unique per instance
    event_id: str  # the row to PATCH/DELETE: master, override or single event
    series_id: str | None  # the master when part of a recurring series
    occurrence: str  # all-day: original start date; timed: original start in UTC
    recurring: bool
    calendar_id: str
    title: str
    notes: str
    location: str
    all_day: bool
    start: str
    end: str
    tzid: str
    rrule: str | None  # the series' rule
    reminders: list[int]
    color: str | None
    task_id: str | None
    task_workspace_id: str | None
    source: EventSource = "user"

    reminder_times: list[str] = Field(default_factory=list)


class CalendarSearchHit(CalendarEvent):
    # The next instance at or after now; a past single event keeps its start.
    next_start: str | None = None


class CalendarList(BaseModel):
    calendars: list[CalendarEntry]
    revision: int


class CalendarResponse(BaseModel):
    calendar: CalendarEntry
    revision: int


class CalendarRevision(BaseModel):
    revision: int


class OccurrenceList(BaseModel):
    occurrences: list[Occurrence]
    revision: int


class CalendarEventResponse(BaseModel):
    event: CalendarEvent
    revision: int


class CalendarSearchResponse(BaseModel):
    events: list[CalendarSearchHit]


class ReviewPathCount(BaseModel):
    id: str
    title: str
    count: int


class ReviewDay(BaseModel):
    date: str
    mastery: int = 0
    practice: int = 0
    paths: list[ReviewPathCount] = Field(default_factory=list)


class AutomationRun(BaseModel):
    id: str  # f"{job_id}:{at}"
    job_id: str
    name: str
    message: str
    at: str  # UTC instant
    kind: Literal["at", "every", "cron"]
    expr: str | None = None
    every_seconds: int | None = None
    session_id: str | None = None
    enabled: bool = True


class FootprintSession(BaseModel):
    id: str
    title: str


class FootprintDay(BaseModel):
    date: str
    session_count: int = 0
    sessions: list[FootprintSession] = Field(default_factory=list)
    practice_reviews: int = 0
    mastery_evidence: int = 0


class CalendarLayers(BaseModel):
    workspace_id: str
    reviews: list[ReviewDay] = Field(default_factory=list)
    automations: list[AutomationRun] = Field(default_factory=list)
    footprints: list[FootprintDay] = Field(default_factory=list)


class CalendarOk(BaseModel):
    ok: bool = True
