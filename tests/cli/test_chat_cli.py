"""CLI smoke tests for the standalone ``deeptutor-cli`` package."""

from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from deeptutor.app import TurnRequest
from deeptutor_cli.main import app

runner = CliRunner()


def _install_fake_runtime(monkeypatch, captured_requests: list[TurnRequest]) -> None:
    async def _start_turn(self, request):  # noqa: ANN001
        if isinstance(request, dict):
            request = TurnRequest(**request)
        captured_requests.append(request)
        return {"id": request.session_id or "session-1"}, {"id": "turn-1"}

    async def _stream_turn(self, turn_id: str, after_seq: int = 0):  # noqa: ANN001
        yield {"type": "session", "turn_id": turn_id, "seq": after_seq}
        yield {"type": "stage_start", "stage": "responding"}
        yield {"type": "content", "content": "response body"}
        yield {"type": "result", "metadata": {"response": "response body"}}
        yield {"type": "done"}

    monkeypatch.setattr("deeptutor.app.facade.DeepTutorApp.start_turn", _start_turn)
    monkeypatch.setattr("deeptutor.app.facade.DeepTutorApp.stream_turn", _stream_turn)


def test_run_command_json_mode(monkeypatch) -> None:
    captured_requests: list[TurnRequest] = []
    _install_fake_runtime(monkeypatch, captured_requests)

    capabilities = ["chat", "deep_solve", "deep_question", "deep_research"]

    for cap in capabilities:
        result = runner.invoke(
            app,
            [
                "run",
                cap,
                "hello world",
                "--format",
                "json",
                "--tool",
                "rag",
                "--kb",
                "demo-kb",
                "--history-ref",
                "session-old",
                "--notebook-ref",
                "nb1:rec1,rec2",
            ],
        )

        assert result.exit_code == 0, result.output
        lines = [json.loads(line) for line in result.output.splitlines() if line.strip()]
        assert any(line["type"] == "result" for line in lines)

    assert len(captured_requests) == 4
    assert captured_requests[0].capability == "chat"
    assert captured_requests[0].tools == ["rag"]
    assert captured_requests[0].knowledge_bases == ["demo-kb"]
    assert captured_requests[0].history_references == ["session-old"]
    assert captured_requests[0].notebook_references == [
        {"notebook_id": "nb1", "record_ids": ["rec1", "rec2"]}
    ]
    assert captured_requests[-1].capability == "deep_research"


def test_run_command_rich_mode(monkeypatch) -> None:
    captured_requests: list[TurnRequest] = []
    _install_fake_runtime(monkeypatch, captured_requests)

    result = runner.invoke(app, ["run", "chat", "hello rich"])

    assert result.exit_code == 0, result.output
    assert "response body" in result.output
    assert captured_requests[0].capability == "chat"


def test_run_command_with_config(monkeypatch) -> None:
    captured_requests: list[TurnRequest] = []
    _install_fake_runtime(monkeypatch, captured_requests)

    result = runner.invoke(
        app,
        [
            "run",
            "deep_research",
            "compare retrieval stacks",
            "--config-json",
            '{"mode":"report","depth":"deep","sources":["web","papers"]}',
        ],
    )

    assert result.exit_code == 0, result.output
    request = captured_requests[0]
    assert request.capability == "deep_research"
    assert request.config == {
        "mode": "report",
        "depth": "deep",
        "sources": ["web", "papers"],
    }


def test_session_list_command_uses_shared_store(monkeypatch) -> None:
    async def _list_sessions(self, limit: int = 50, offset: int = 0):  # noqa: ANN001
        return [
            {
                "id": "session-1",
                "title": "Algebra",
                "capability": "chat",
                "status": "completed",
                "message_count": 4,
            }
        ]

    monkeypatch.setattr("deeptutor.app.facade.DeepTutorApp.list_sessions", _list_sessions)

    result = runner.invoke(app, ["session", "list"])

    assert result.exit_code == 0, result.output
    assert "session-1" in result.output
    assert "Algebra" in result.output


def test_start_command_propagates_start_web_exit_code(monkeypatch) -> None:
    class Result:
        returncode = 7

    def _fake_run(cmd, check=False):  # noqa: ANN001
        assert check is False
        assert cmd[0]
        assert cmd[1].endswith("scripts/start_web.py")
        return Result()

    monkeypatch.setattr("subprocess.run", _fake_run)

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 7
