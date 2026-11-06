"""Chat tools for the account calendar and workspace task board."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        default=lambda item: item.model_dump() if hasattr(item, "model_dump") else str(item),
    )


def _local_zone_name() -> str:
    try:
        from tzlocal import get_localzone_name

        return get_localzone_name()
    except Exception:
        return "UTC"


def _instant(value: str, tzid: str) -> str:
    """Accept a friendly local ISO time and return an aware ISO instant."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(tzid))
    return parsed.isoformat()


class TasksTool(BaseTool):
    """Read and mutate the current workspace's visible task cards."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="tasks",
            description=(
                "Manage the learner's real Tasks board in the current workspace. "
                "Use action='list' before changing an existing task, action='create' "
                "for a new task, and action='update' to change title, note, due date, "
                "status (todo/doing/done), or archive state. Created tasks are linked "
                "to this conversation by default. A due date also appears on Calendar."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    enum=["list", "create", "update"],
                    description="Task-board action.",
                ),
                ToolParameter(name="task_id", type="string", required=False),
                ToolParameter(name="title", type="string", required=False),
                ToolParameter(name="note", type="string", required=False),
                ToolParameter(
                    name="due_date",
                    type="string",
                    required=False,
                    nullable=True,
                    description="Local due day as YYYY-MM-DD; null clears it.",
                ),
                ToolParameter(
                    name="status",
                    type="string",
                    required=False,
                    enum=["todo", "doing", "done"],
                ),
                ToolParameter(name="archived", type="boolean", required=False),
                ToolParameter(
                    name="include_archived",
                    type="boolean",
                    required=False,
                    description="list: include archived cards (default false).",
                ),
                ToolParameter(
                    name="link_to_chat",
                    type="boolean",
                    required=False,
                    description="create: link the task to this conversation (default true).",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.services.task_board import (
            CreateCard,
            LinkTasks,
            UpdateCard,
            get_task_board_store,
            workspace_board,
        )

        action = str(kwargs.get("action") or "").strip().lower()
        workspace_id = str(kwargs.get("_workspace_id") or "")
        session_id = str(kwargs.get("_session_id") or "")
        store = get_task_board_store(migrate_legacy=False)
        try:
            if action == "list":
                board = workspace_board(store.read(), workspace_id)
                cards = [
                    card.model_dump()
                    for card in board.cards
                    if kwargs.get("include_archived") or not card.archived
                ]
                return ToolResult(
                    content=_json({"tasks": cards, "revision": board.revision}),
                    metadata={"count": len(cards)},
                )

            if action == "create":
                title = str(kwargs.get("title") or "").strip()
                if not title:
                    return ToolResult(content="create needs a non-empty title.", success=False)
                before = {card.id for card in store.read().cards}
                board = store.create(
                    CreateCard(
                        title=title,
                        note=str(kwargs.get("note") or ""),
                        due_date=kwargs.get("due_date"),
                    ),
                    workspace_id,
                )
                created = next((card for card in board.cards if card.id not in before), None)
                if created is None:
                    return ToolResult(
                        content="Task was created but could not be reloaded.", success=False
                    )
                if session_id and kwargs.get("link_to_chat", True):
                    scoped = workspace_board(board, workspace_id)
                    linked = next(
                        (
                            list(row.task_ids)
                            for row in scoped.session_links
                            if row.session_id == session_id
                        ),
                        [],
                    )
                    if created.id not in linked:
                        linked.append(created.id)
                    store.link_tasks(
                        session_id,
                        LinkTasks(workspace_id=workspace_id, task_ids=linked),
                    )
                return ToolResult(
                    content="Created task:\n" + _json(created),
                    metadata={"task_id": created.id},
                )

            if action == "update":
                task_id = str(kwargs.get("task_id") or "").strip()
                if not task_id:
                    return ToolResult(
                        content="update needs task_id; use list first.", success=False
                    )
                changes = {
                    key: kwargs[key]
                    for key in ("title", "note", "due_date", "status", "archived")
                    if key in kwargs
                }
                if not changes:
                    return ToolResult(
                        content="update needs at least one changed field.", success=False
                    )
                board = workspace_board(
                    store.update(
                        task_id, UpdateCard.model_validate(changes), workspace_id=workspace_id
                    ),
                    workspace_id,
                )
                card = next((item for item in board.cards if item.id == task_id), None)
                return ToolResult(
                    content="Updated task:\n" + _json(card),
                    metadata={"task_id": task_id},
                )

            return ToolResult(content=f"Unknown task action {action!r}.", success=False)
        except (KeyError, OSError, ValueError, ValidationError) as exc:
            return ToolResult(content=f"Task action failed: {exc}", success=False)


class CalendarTool(BaseTool):
    """Read and mutate stored calendar events."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="calendar",
            description=(
                "Manage real Calendar events. Use action='list' to inspect calendars and "
                "events (defaults to the next 90 days), action='create' to add an event, "
                "and action='update' to change an existing event. Timed start/end values "
                "are ISO 8601; a missing offset is interpreted in tzid. All-day values are "
                "YYYY-MM-DD and end is exclusive. Use the cron tool instead when the user "
                "asks for an instruction to run later or recur automatically."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    enum=["list", "create", "update"],
                    description="Calendar action.",
                ),
                ToolParameter(name="event_id", type="string", required=False),
                ToolParameter(name="title", type="string", required=False),
                ToolParameter(name="notes", type="string", required=False),
                ToolParameter(name="location", type="string", required=False),
                ToolParameter(name="start", type="string", required=False),
                ToolParameter(name="end", type="string", required=False),
                ToolParameter(
                    name="tzid",
                    type="string",
                    required=False,
                    description="IANA time zone, e.g. Europe/Kyiv.",
                ),
                ToolParameter(name="all_day", type="boolean", required=False),
                ToolParameter(name="calendar_id", type="string", required=False),
                ToolParameter(name="color", type="string", required=False, nullable=True),
                ToolParameter(name="rrule", type="string", required=False, nullable=True),
                ToolParameter(
                    name="reminders",
                    type="array",
                    items={"type": "integer"},
                    required=False,
                    description="Minutes before start, at most five.",
                ),
                ToolParameter(
                    name="task_id",
                    type="string",
                    required=False,
                    nullable=True,
                    description="Optional task card to time-block; null clears the link.",
                ),
                ToolParameter(
                    name="range_start",
                    type="string",
                    required=False,
                    description="list: inclusive ISO instant.",
                ),
                ToolParameter(
                    name="range_end",
                    type="string",
                    required=False,
                    description="list: exclusive ISO instant, up to 400 days later.",
                ),
                ToolParameter(
                    name="scope",
                    type="string",
                    required=False,
                    enum=["this", "following", "all"],
                    description="update recurring event scope (default all).",
                ),
                ToolParameter(
                    name="occurrence",
                    type="string",
                    required=False,
                    description="Occurrence key when updating this/following in a series.",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.services.calendar import models as m
        from deeptutor.services.calendar.recurrence import parse_instant
        from deeptutor.services.calendar.store import get_calendar_store
        from deeptutor.services.task_board import get_task_board_store, workspace_board

        action = str(kwargs.get("action") or "").strip().lower()
        workspace_id = str(kwargs.get("_workspace_id") or "")
        tzid = str(kwargs.get("tzid") or _local_zone_name())
        store = get_calendar_store()

        def validate_task(task_id: str | None) -> None:
            if not task_id:
                return
            board = workspace_board(get_task_board_store(migrate_legacy=False).read(), workspace_id)
            if not any(card.id == task_id and not card.archived for card in board.cards):
                raise ValueError("Task not found in the current workspace.")

        try:
            if action == "list":
                now = datetime.now(timezone.utc).replace(microsecond=0)
                start = (
                    _instant(str(kwargs["range_start"]), tzid)
                    if kwargs.get("range_start")
                    else now.isoformat()
                )
                end = (
                    _instant(str(kwargs["range_end"]), tzid)
                    if kwargs.get("range_end")
                    else (now + timedelta(days=90)).isoformat()
                )
                occurrences = store.occurrences(parse_instant(start), parse_instant(end), tzid)
                calendars = store.calendars()
                return ToolResult(
                    content=_json(
                        {
                            "timezone": tzid,
                            "range": {"start": start, "end": end},
                            "calendars": calendars["calendars"],
                            "events": occurrences["occurrences"],
                        }
                    ),
                    metadata={"count": len(occurrences["occurrences"])},
                )

            if action == "create":
                title = str(kwargs.get("title") or "").strip()
                start_raw, end_raw = kwargs.get("start"), kwargs.get("end")
                if not title or not start_raw or not end_raw:
                    return ToolResult(content="create needs title, start, and end.", success=False)
                sample_time = kwargs.get("start") or kwargs.get("end")
                all_day = (
                    bool(kwargs["all_day"])
                    if "all_day" in kwargs
                    else bool(sample_time and "T" not in str(sample_time))
                )
                task_id = kwargs.get("task_id")
                validate_task(task_id)
                payload = {
                    "title": title,
                    "notes": str(kwargs.get("notes") or ""),
                    "location": str(kwargs.get("location") or ""),
                    "all_day": all_day,
                    "start": str(start_raw) if all_day else _instant(str(start_raw), tzid),
                    "end": str(end_raw) if all_day else _instant(str(end_raw), tzid),
                    "tzid": tzid,
                    "reminders": list(kwargs.get("reminders") or []),
                }
                for key in ("calendar_id", "color", "rrule", "task_id"):
                    if key in kwargs:
                        payload[key] = kwargs[key]
                if task_id:
                    payload["task_workspace_id"] = workspace_id
                response = store.create(m.EventInput.model_validate(payload))
                event = response["event"]
                return ToolResult(
                    content="Created calendar event:\n" + _json(event),
                    metadata={"event_id": event.id},
                )

            if action == "update":
                event_id = str(kwargs.get("event_id") or "").strip()
                if not event_id:
                    return ToolResult(
                        content="update needs event_id; use list first.", success=False
                    )
                changes: dict[str, Any] = {}
                sample_time = kwargs.get("start") or kwargs.get("end")
                all_day = (
                    bool(kwargs["all_day"])
                    if "all_day" in kwargs
                    else bool(sample_time and "T" not in str(sample_time))
                )
                for key in (
                    "title",
                    "notes",
                    "location",
                    "all_day",
                    "calendar_id",
                    "color",
                    "rrule",
                    "reminders",
                    "task_id",
                ):
                    if key in kwargs:
                        changes[key] = kwargs[key]
                for key in ("start", "end"):
                    if key in kwargs:
                        changes[key] = (
                            str(kwargs[key]) if all_day else _instant(str(kwargs[key]), tzid)
                        )
                if "tzid" in kwargs:
                    changes["tzid"] = tzid
                if "task_id" in kwargs:
                    validate_task(kwargs.get("task_id"))
                    changes["task_workspace_id"] = workspace_id if kwargs.get("task_id") else None
                if not changes:
                    return ToolResult(
                        content="update needs at least one changed field.", success=False
                    )
                response = store.update(
                    event_id,
                    m.EventPatchRequest(
                        changes=m.EventPatch.model_validate(changes),
                        scope=str(kwargs.get("scope") or "all"),
                        occurrence=kwargs.get("occurrence"),
                    ),
                )
                return ToolResult(
                    content="Updated calendar event.",
                    metadata={"event_id": event_id, **response},
                )

            return ToolResult(content=f"Unknown calendar action {action!r}.", success=False)
        except (KeyError, OSError, ValueError, ValidationError) as exc:
            return ToolResult(content=f"Calendar action failed: {exc}", success=False)


__all__ = ["CalendarTool", "TasksTool"]
