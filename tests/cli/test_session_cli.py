"""CLI tests for session commands scoped to a registered workspace."""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from deeptutor_cli.main import app

runner = CliRunner()


class _FakeApp:
    """Stand-in for ``DeepTutorApp`` that records the workspace it was built with."""

    created: list["_FakeApp"] = []

    def __init__(self, *, workspace_id: str | None = None) -> None:
        self.workspace_id = workspace_id
        self.calls: list[tuple[str, Any]] = []
        _FakeApp.created.append(self)

    async def list_sessions(self, limit: int = 50, offset: int = 0):
        self.calls.append(("list_sessions", limit))
        return []

    async def get_session(self, session_id: str):
        self.calls.append(("get_session", session_id))
        return {"id": session_id, "title": "Demo", "messages": [], "status": "idle"}

    async def delete_session(self, session_id: str) -> bool:
        self.calls.append(("delete_session", session_id))
        return False

    async def rename_session(self, session_id: str, title: str) -> bool:
        self.calls.append(("rename_session", (session_id, title)))
        return True


@pytest.fixture(autouse=True)
def fake_app(monkeypatch) -> type[_FakeApp]:
    _FakeApp.created = []
    monkeypatch.setattr("deeptutor_cli.session_cmd.DeepTutorApp", _FakeApp)
    return _FakeApp


def test_session_list_forwards_workspace(fake_app: type[_FakeApp]) -> None:
    result = runner.invoke(app, ["session", "list", "--workspace", "ws-lab"])

    assert result.exit_code == 0, result.output
    assert [row.workspace_id for row in fake_app.created] == ["ws-lab"]
    assert fake_app.created[0].calls == [("list_sessions", 20)]


def test_session_list_without_workspace_keeps_default_scope(fake_app: type[_FakeApp]) -> None:
    result = runner.invoke(app, ["session", "list"])

    assert result.exit_code == 0, result.output
    assert [row.workspace_id for row in fake_app.created] == [None]


def test_session_show_forwards_workspace_and_emits_json(fake_app: type[_FakeApp]) -> None:
    result = runner.invoke(
        app, ["session", "show", "sess-1", "--workspace", "ws-lab", "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    assert fake_app.created[0].workspace_id == "ws-lab"
    assert fake_app.created[0].calls == [("get_session", "sess-1")]
    assert json.loads(result.output)["id"] == "sess-1"


def test_session_open_forwards_workspace_to_chat_state(monkeypatch) -> None:
    seen: list[Any] = []

    async def _fake_repl(state):  # noqa: ANN001
        seen.append(state)

    monkeypatch.setattr("deeptutor_cli.session_cmd._chat_repl", _fake_repl)

    result = runner.invoke(app, ["session", "open", "sess-1", "--workspace", "ws-lab"])

    assert result.exit_code == 0, result.output
    assert seen and seen[0].session_id == "sess-1"
    assert seen[0].workspace_id == "ws-lab"


def test_session_delete_reports_missing_session_and_forwards_workspace(
    fake_app: type[_FakeApp],
) -> None:
    result = runner.invoke(app, ["session", "delete", "sess-gone", "--workspace", "ws-lab"])

    assert result.exit_code == 1
    assert fake_app.created[0].workspace_id == "ws-lab"
    assert fake_app.created[0].calls == [("delete_session", "sess-gone")]


def test_session_rename_forwards_workspace(fake_app: type[_FakeApp]) -> None:
    result = runner.invoke(
        app, ["session", "rename", "sess-1", "--title", "New name", "--workspace", "ws-lab"]
    )

    assert result.exit_code == 0, result.output
    assert fake_app.created[0].workspace_id == "ws-lab"
    assert fake_app.created[0].calls == [("rename_session", ("sess-1", "New name"))]
