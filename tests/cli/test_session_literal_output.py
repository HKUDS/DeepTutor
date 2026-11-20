"""Session commands display saved text without interpreting console markup."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from rich.console import Console
from typer.testing import CliRunner

from deeptutor_cli import common, session_cmd
from deeptutor_cli.main import app

runner = CliRunner()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    client = SimpleNamespace(
        get_session=AsyncMock(return_value=None),
        list_sessions=AsyncMock(return_value=[]),
        rename_session=AsyncMock(return_value=True),
        delete_session=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(session_cmd, "DeepTutorApp", lambda: client)
    console = Console(force_terminal=False, color_system=None, width=240)
    monkeypatch.setattr(session_cmd, "console", console)
    monkeypatch.setattr(common, "console", console)
    return client


@pytest.mark.parametrize(
    "content",
    [
        "Use [bold]text[/bold] for emphasis.",
        "The closing tag is [/bold].",
        "Read [the notes](https://example.org/notes).",
        "Keep the shortcode :tada: in the example.",
        r"A literal backslash precedes \[draft].",
    ],
)
def test_show_preserves_message_text(client: SimpleNamespace, content: str) -> None:
    client.get_session.return_value = {
        "id": "session-1",
        "title": "Algebra",
        "messages": [{"role": "assistant", "content": content}],
    }

    result = runner.invoke(app, ["session", "show", "session-1"])

    assert result.exit_code == 0, result.exception
    assert content in result.stdout
    assert "ASSISTANT" in result.stdout


def test_show_preserves_session_metadata(client: SimpleNamespace) -> None:
    client.get_session.return_value = {
        "id": "session-[draft]",
        "title": "Fourier [/bold] :tada:",
        "capability": "[chat]",
        "status": "[completed]",
        "messages": [],
    }

    result = runner.invoke(app, ["session", "show", "session-[draft]"])

    assert result.exit_code == 0, result.exception
    assert "Fourier [/bold] :tada: (session-[draft])" in result.stdout
    assert "capability=[chat] status=[completed] messages=0" in result.stdout


def test_list_preserves_session_titles(client: SimpleNamespace) -> None:
    title = "[bold]Fourier[/bold] :tada:"
    client.list_sessions.return_value = [
        {
            "id": "session-1",
            "title": title,
            "capability": "chat",
            "status": "completed",
            "message_count": 4,
        }
    ]

    result = runner.invoke(app, ["session", "list"])

    assert result.exit_code == 0, result.exception
    assert title in result.stdout
    assert "session-1" in result.stdout


def test_rename_reports_the_saved_title(client: SimpleNamespace) -> None:
    title = "Fourier [/bold] :tada:"

    result = runner.invoke(app, ["session", "rename", "session-1", "--title", title])

    assert result.exit_code == 0, result.exception
    client.rename_session.assert_awaited_once_with("session-1", title)
    assert f"Renamed session-1 -> {title}" in result.stdout


@pytest.mark.parametrize("command", ["show", "delete", "rename"])
def test_missing_session_reports_the_literal_id(client: SimpleNamespace, command: str) -> None:
    client.delete_session.return_value = False
    client.rename_session.return_value = False
    session_id = "missing-[/bold]:tada:"
    arguments = ["session", command, session_id]
    if command == "rename":
        arguments.extend(["--title", "Algebra"])

    result = runner.invoke(app, arguments)

    assert result.exit_code == 1
    assert f"Session not found: {session_id}" in result.stdout


def test_delete_reports_the_literal_id(client: SimpleNamespace) -> None:
    session_id = "session-[draft]:tada:"

    result = runner.invoke(app, ["session", "delete", session_id])

    assert result.exit_code == 0, result.exception
    client.delete_session.assert_awaited_once_with(session_id)
    assert f"Deleted session {session_id}" in result.stdout
