"""Pagination and machine-readable output for session listings."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from typer.testing import CliRunner

from deeptutor_cli import session_cmd
from deeptutor_cli.main import app

runner = CliRunner()
SESSIONS = [
    {
        "id": f"session-full-id-00000000-0000-0000-0000-{index:012d}",
        "title": f"会话 {index}: [bold]literal[/bold] [/unknown] :tada:",
        "capability": "chat",
        "status": "completed",
        "message_count": index,
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    for index in range(5)
]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    async def list_sessions(limit: int = 50, offset: int = 0) -> list[dict]:
        return SESSIONS[offset : offset + limit]

    client = SimpleNamespace(list_sessions=AsyncMock(side_effect=list_sessions))
    monkeypatch.setattr(session_cmd, "DeepTutorApp", lambda: client)
    return client


def test_json_adjacent_pages_preserve_summaries(client: SimpleNamespace) -> None:
    pages = []
    for offset in (0, 2, 4):
        result = runner.invoke(
            app, ["session", "list", "--limit", "2", "--offset", str(offset), "--format", "json"]
        )
        assert result.exit_code == 0, result.exception
        assert result.stderr == ""
        page = json.loads(result.stdout)
        assert page == SESSIONS[offset : offset + 2]
        assert page[0]["title"] in result.stdout
        pages.extend(page)
    assert pages == SESSIONS
    assert client.list_sessions.await_count == 3
    client.list_sessions.assert_awaited_with(limit=2, offset=4)


@pytest.mark.parametrize("offset", [5, 100])
def test_json_empty_page(client: SimpleNamespace, offset: int) -> None:
    result = runner.invoke(app, ["session", "list", "--offset", str(offset), "--format", "json"])
    assert result.exit_code == 0, result.exception
    assert result.stdout.strip() == "[]"
    assert result.stderr == ""
    client.list_sessions.assert_awaited_once_with(limit=20, offset=offset)


@pytest.mark.parametrize("arguments", [[], ["--format", "rich", "--limit", "2", "--offset", "2"]])
def test_rich_listing(
    client: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, arguments: list
) -> None:
    table = Mock()
    monkeypatch.setattr(session_cmd, "print_session_table", table)
    result = runner.invoke(app, ["session", "list", *arguments])
    assert result.exit_code == 0, result.exception
    limit, offset = (2, 2) if arguments else (20, 0)
    client.list_sessions.assert_awaited_once_with(limit=limit, offset=offset)
    table.assert_called_once_with(SESSIONS[offset : offset + limit])


@pytest.mark.parametrize(
    "arguments", [["--offset", "-1"], ["--limit", "0"], ["--limit", "-1"], ["--format", "xml"]]
)
def test_invalid_options_report_to_stderr(client: SimpleNamespace, arguments: list) -> None:
    result = runner.invoke(app, ["session", "list", *arguments])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Invalid value" in result.stderr
    client.list_sessions.assert_not_awaited()


def test_list_help_documents_options() -> None:
    result = runner.invoke(app, ["session", "list", "--help"], color=False)
    assert result.exit_code == 0
    for option in ("--limit", "--offset", "--format", "rich", "json"):
        assert option in result.stdout
