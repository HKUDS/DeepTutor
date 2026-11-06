import json

import pytest

from deeptutor.agents._shared.tool_composition import AUTO_MOUNTED_TOOLS
from deeptutor.services.calendar.store import CalendarStore
from deeptutor.services.task_board import TaskBoardStore, workspace_board
from deeptutor.tools.builtin_specs import BUILTIN_TOOL_NAMES
from deeptutor.tools.planning_tools import CalendarTool, TasksTool


def test_planning_tools_are_registered_and_automounted():
    assert {"tasks", "calendar"}.issubset(BUILTIN_TOOL_NAMES)
    assert {"tasks", "calendar"}.issubset(AUTO_MOUNTED_TOOLS)


@pytest.mark.asyncio
async def test_tasks_tool_creates_links_lists_and_updates(tmp_path, monkeypatch):
    from deeptutor.services import task_board

    store = TaskBoardStore(tmp_path / "tasks.sqlite")
    monkeypatch.setattr(task_board, "get_task_board_store", lambda **_kwargs: store)
    tool = TasksTool()

    created = await tool.execute(
        action="create",
        title="Read antenna chapter",
        due_date="2026-11-03",
        _workspace_id="radio",
        _session_id="chat-1",
    )
    assert created.success
    task_id = created.metadata["task_id"]
    board = workspace_board(store.read(), "radio")
    assert board.cards[0].id == task_id
    assert board.session_links[0].task_ids == [task_id]

    updated = await tool.execute(
        action="update",
        task_id=task_id,
        status="done",
        _workspace_id="radio",
    )
    assert updated.success
    listed = await tool.execute(action="list", _workspace_id="radio")
    payload = json.loads(listed.content)
    assert payload["tasks"][0]["status"] == "done"

    assert not (await tool.execute(action="create", _workspace_id="radio")).success
    assert not (await tool.execute(action="update", _workspace_id="radio")).success
    assert not (await tool.execute(action="update", task_id=task_id, _workspace_id="radio")).success
    assert not (
        await tool.execute(action="update", task_id="missing", status="done", _workspace_id="radio")
    ).success
    assert not (await tool.execute(action="unknown", _workspace_id="radio")).success

    archived = await tool.execute(
        action="update", task_id=task_id, archived=True, _workspace_id="radio"
    )
    assert archived.success
    assert (
        json.loads((await tool.execute(action="list", _workspace_id="radio")).content)["tasks"]
        == []
    )
    with_archived = await tool.execute(action="list", include_archived=True, _workspace_id="radio")
    assert json.loads(with_archived.content)["tasks"][0]["archived"] is True


@pytest.mark.asyncio
async def test_calendar_tool_creates_and_lists_local_time(tmp_path, monkeypatch):
    from deeptutor.services import task_board
    from deeptutor.services.calendar import store as calendar_store

    store = CalendarStore(tmp_path / "calendar.sqlite")
    tasks = TaskBoardStore(tmp_path / "tasks.sqlite")
    monkeypatch.setattr(calendar_store, "get_calendar_store", lambda: store)
    monkeypatch.setattr(task_board, "get_task_board_store", lambda **_kwargs: tasks)
    tool = CalendarTool()

    created = await tool.execute(
        action="create",
        title="Radio physics study",
        start="2026-11-03T19:00",
        end="2026-11-03T20:30",
        tzid="Europe/Kyiv",
        reminders=[15],
        _workspace_id="radio",
    )
    assert created.success
    event_id = created.metadata["event_id"]
    assert event_id

    listed = await tool.execute(
        action="list",
        range_start="2026-11-03T00:00",
        range_end="2026-11-04T00:00",
        tzid="Europe/Kyiv",
        _workspace_id="radio",
    )
    payload = json.loads(listed.content)
    assert payload["events"][0]["title"] == "Radio physics study"
    assert payload["events"][0]["reminders"] == [15]

    updated = await tool.execute(
        action="update",
        event_id=event_id,
        title="Updated study session",
        _workspace_id="radio",
    )
    assert updated.success
    refreshed = await tool.execute(
        action="list",
        range_start="2026-11-03T00:00",
        range_end="2026-11-04T00:00",
        tzid="Europe/Kyiv",
        _workspace_id="radio",
    )
    assert json.loads(refreshed.content)["events"][0]["title"] == "Updated study session"

    all_day = await tool.execute(
        action="create",
        title="Review day",
        start="2026-11-05",
        end="2026-11-06",
        all_day=True,
        _workspace_id="radio",
    )
    moved = await tool.execute(
        action="update",
        event_id=all_day.metadata["event_id"],
        start="2026-11-06",
        end="2026-11-07",
        _workspace_id="radio",
    )
    assert moved.success

    assert not (await tool.execute(action="create", _workspace_id="radio")).success
    assert not (await tool.execute(action="update", _workspace_id="radio")).success
    assert not (
        await tool.execute(action="update", event_id=event_id, _workspace_id="radio")
    ).success
    assert not (
        await tool.execute(
            action="update",
            event_id="missing",
            title="No event",
            _workspace_id="radio",
        )
    ).success
    assert not (await tool.execute(action="unknown", _workspace_id="radio")).success
    assert (await tool.execute(action="list", _workspace_id="radio")).success
