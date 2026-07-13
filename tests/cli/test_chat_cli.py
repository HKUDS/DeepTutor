"""CLI smoke tests for the standalone ``deeptutor-cli`` package."""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from deeptutor.app import DeepTutorApp, TurnRequest
from deeptutor.runtime.bootstrap.builtin_capabilities import BUILTIN_CAPABILITY_CLASSES
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

    capabilities = list(BUILTIN_CAPABILITY_CLASSES)

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

    assert len(captured_requests) == len(capabilities)
    assert captured_requests[0].capability == "chat"
    assert captured_requests[0].tools == ["rag"]
    assert captured_requests[0].knowledge_bases == ["demo-kb"]
    assert captured_requests[0].history_references == ["session-old"]
    assert captured_requests[0].notebook_references == [
        {"notebook_id": "nb1", "record_ids": ["rec1", "rec2"]}
    ]
    assert {request.capability for request in captured_requests} == set(capabilities)


def test_builtin_capability_aliases_resolve_to_canonical_names() -> None:
    runtime = DeepTutorApp()

    assert runtime.resolve_capability("solve") == "deep_solve"
    assert runtime.resolve_capability("quiz") == "deep_question"
    assert runtime.resolve_capability("research") == "deep_research"
    assert runtime.resolve_capability("viz") == "visualize"
    assert runtime.resolve_capability("animate") == "math_animator"
    assert runtime.resolve_capability("mastery") == "mastery_path"
    with pytest.raises(ValueError, match="Unknown capability `auto`"):
        runtime.resolve_capability("auto")


def test_run_command_rejects_removed_auto_capability() -> None:
    result = runner.invoke(app, ["run", "auto", "hello"])

    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    assert "Unknown capability `auto`" in str(result.exception)


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
            '{"mode":"report","depth":"deep"}',
        ],
    )

    assert result.exit_code == 0, result.output
    request = captured_requests[0]
    assert request.capability == "deep_research"
    assert request.config == {
        "mode": "report",
        "depth": "deep",
    }


def test_chat_repl_config_commands_match_docs_syntax(monkeypatch) -> None:
    captured_requests: list[TurnRequest] = []
    _install_fake_runtime(monkeypatch, captured_requests)

    result = runner.invoke(
        app,
        ["chat", "--config", "initial=true"],
        input=(
            "/config set num_questions 5\n"
            '/config set question_types \'["short_answer","mcq"]\'\n'
            "/refs\n"
            "Generate questions\n"
            "/quit\n"
        ),
    )

    assert result.exit_code == 0, result.output
    assert '"num_questions": 5' in result.output
    assert '"question_types"' in result.output
    assert captured_requests[0].config == {
        "initial": True,
        "num_questions": 5,
        "question_types": ["short_answer", "mcq"],
    }


def test_chat_repl_backslash_continuation_sends_single_message(monkeypatch) -> None:
    captured_requests: list[TurnRequest] = []
    _install_fake_runtime(monkeypatch, captured_requests)

    result = runner.invoke(
        app,
        ["chat"],
        input="Please review this code:\\\ndef fib(n): return n\n/quit\n",
    )

    assert result.exit_code == 0, result.output
    assert captured_requests[0].content == "Please review this code:\ndef fib(n): return n"


def test_plugin_info_includes_capability_aliases_and_availability() -> None:
    result = runner.invoke(app, ["plugin", "info", "deep_solve"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["name"] == "deep_solve"
    assert payload["cli_aliases"] == ["solve"]
    assert payload["availability"]["available"] is True


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


def test_start_command_delegates_to_runtime_launcher(monkeypatch) -> None:
    calls: list[object] = []

    def _fake_start(home=None):  # noqa: ANN001
        calls.append(home)

    monkeypatch.setattr("deeptutor.runtime.launcher.start", _fake_start)

    result = runner.invoke(app, ["start"])

    assert result.exit_code == 0, result.output
    assert calls == [None]
