"""Tests for the CLI turn-stream renderer against the chat-loop protocol.

The chat agent loop (deeptutor/agents/chat/agent_loop.py) streams every
round's text as ``content`` chunks with ``trace_kind=llm_chunk`` and labels
the round afterwards via a ``call_status`` marker carrying ``call_role``
(``narration`` | ``finish``). These tests feed that exact event shape into
the renderer and assert the terminal output (narration demoted to dim text
before its tool calls, finish rendered as the answer, no stray blank
progress lines) plus the ``ask_user`` pause/resume flow.
"""

from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from deeptutor.app import TurnRequest
from deeptutor_cli import common as cli_common
from deeptutor_cli.common import _resolve_answer
from deeptutor_cli.main import app

runner = CliRunner()


def _chunk(call_id: str, text: str) -> dict[str, Any]:
    return {
        "type": "content",
        "content": text,
        "metadata": {
            "call_id": call_id,
            "call_kind": "agent_loop_round",
            "trace_kind": "llm_chunk",
        },
    }


def _running(call_id: str, label: str = "Exploring") -> dict[str, Any]:
    return {
        "type": "progress",
        "content": label,
        "metadata": {
            "call_id": call_id,
            "call_kind": "agent_loop_round",
            "trace_kind": "call_status",
            "call_state": "running",
        },
    }


def _marker(call_id: str, role: str) -> dict[str, Any]:
    return {
        "type": "progress",
        "content": "",
        "metadata": {
            "call_id": call_id,
            "call_kind": "agent_loop_round",
            "trace_kind": "call_status",
            "call_state": "complete",
            "call_role": role,
        },
    }


def _agent_loop_turn_events() -> list[dict[str, Any]]:
    """One narration round (with a tool call) followed by a finish round."""
    return [
        {"type": "stage_start", "stage": "responding", "source": "chat"},
        _running("r1"),
        _chunk("r1", "Let me check the knowledge base."),
        _marker("r1", "narration"),
        {
            "type": "tool_call",
            "content": "rag",
            "metadata": {"args": {"query": "spectral clustering"}},
        },
        {
            "type": "tool_result",
            "content": "retrieved passage",
            "metadata": {"tool": "rag"},
        },
        _running("r2"),
        _chunk("r2", "The answer is **42**."),
        _marker("r2", "finish"),
        {"type": "stage_end", "stage": "responding", "source": "chat"},
        {
            "type": "result",
            "metadata": {
                "response": "The answer is **42**.",
                "engine": "agent_loop",
                "rounds": 2,
                "tool_steps": 1,
                "metadata": {
                    "cost_summary": {
                        "total_cost_usd": 0.0042,
                        "total_tokens": 12345,
                        "total_calls": 2,
                    }
                },
            },
        },
        {"type": "done"},
    ]


def _install_fake_runtime(
    monkeypatch,
    events: list[dict[str, Any]],
    *,
    replies: list[dict[str, Any]] | None = None,
) -> None:
    async def _start_turn(self, request):  # noqa: ANN001
        if isinstance(request, dict):
            request = TurnRequest(**request)
        return {"id": request.session_id or "session-1"}, {"id": "turn-1"}

    async def _stream_turn(self, turn_id: str, after_seq: int = 0):  # noqa: ANN001
        for event in events:
            yield event

    async def _submit_user_reply(self, turn_id, text=None, *, answers=None):  # noqa: ANN001
        if replies is not None:
            replies.append({"turn_id": turn_id, "text": text, "answers": answers})
        return True

    monkeypatch.setattr("deeptutor.app.facade.DeepTutorApp.start_turn", _start_turn)
    monkeypatch.setattr("deeptutor.app.facade.DeepTutorApp.stream_turn", _stream_turn)
    monkeypatch.setattr("deeptutor.app.facade.DeepTutorApp.submit_user_reply", _submit_user_reply)


def test_narration_renders_before_tools_and_finish_is_answer(monkeypatch) -> None:
    _install_fake_runtime(monkeypatch, _agent_loop_turn_events())

    result = runner.invoke(app, ["run", "chat", "hello"])

    assert result.exit_code == 0, result.output
    narration_at = result.output.find("Let me check the knowledge base.")
    tool_at = result.output.find("rag(")
    answer_at = result.output.find("42")
    assert narration_at != -1 and tool_at != -1 and answer_at != -1
    # Narration belongs to the round BEFORE its tool calls; the finish
    # round's text is the answer and comes last.
    assert narration_at < tool_at < answer_at
    # The chat wrapper stage emits no banner.
    assert "▶ responding" not in result.output


def test_done_summary_line_includes_rounds_tools_tokens_cost(monkeypatch) -> None:
    _install_fake_runtime(monkeypatch, _agent_loop_turn_events())

    result = runner.invoke(app, ["run", "chat", "hello"])

    assert result.exit_code == 0, result.output
    assert "rounds=2" in result.output
    assert "tools=1" in result.output
    assert "tokens=12.3k" in result.output
    assert "cost=$0.0042" in result.output


def test_empty_call_status_markers_print_nothing(monkeypatch) -> None:
    _install_fake_runtime(monkeypatch, _agent_loop_turn_events())

    result = runner.invoke(app, ["run", "chat", "hello"])

    lines = result.output.splitlines()
    # The two call_status markers carry empty content; no bare dim lines
    # may leak out of them (a leaked line is whitespace-only).
    assert not any(line.strip() == "" and line != "" for line in lines)


def test_thinking_chunks_collapse_to_single_indicator(monkeypatch) -> None:
    events = _agent_loop_turn_events()
    thinking = [
        {
            "type": "thinking",
            "content": piece,
            "metadata": {
                "call_id": "r1",
                "call_kind": "agent_loop_round",
                "trace_kind": "llm_chunk",
            },
        }
        for piece in ("First ", "I ", "should ", "look ", "things ", "up.")
    ]
    events[2:2] = thinking  # before r1's content chunk

    _install_fake_runtime(monkeypatch, events)
    result = runner.invoke(app, ["run", "chat", "hello"])

    assert result.exit_code == 0, result.output
    assert result.output.count("thinking…") == 1
    # Raw reasoning text must not splatter into the transcript.
    assert "should" not in result.output


def test_legacy_capability_content_still_renders(monkeypatch) -> None:
    events = [
        {"type": "stage_start", "stage": "planning", "source": "deep_research"},
        {"type": "content", "content": "Plan text here."},
        {"type": "stage_end", "stage": "planning", "source": "deep_research"},
        {"type": "done"},
    ]
    _install_fake_runtime(monkeypatch, events)

    result = runner.invoke(app, ["run", "deep_research", "question"])

    assert result.exit_code == 0, result.output
    assert "▶ planning" in result.output
    assert "Plan text here." in result.output


def _ask_user_events() -> list[dict[str, Any]]:
    return [
        {"type": "stage_start", "stage": "responding", "source": "chat"},
        {
            "type": "tool_result",
            "content": "[awaiting user reply to: Which topic?]",
            "metadata": {
                "tool": "ask_user",
                "tool_metadata": {
                    "ask_user": {
                        "intro": "Quick check",
                        "questions": [
                            {
                                "id": "q1",
                                "prompt": "Which topic?",
                                "options": [
                                    {"label": "Algebra", "description": "Linear systems"},
                                    {"label": "Geometry", "description": None},
                                ],
                                "multi_select": False,
                                "allow_free_text": True,
                            }
                        ],
                    }
                },
            },
        },
        _running("r2"),
        _chunk("r2", "Algebra it is."),
        _marker("r2", "finish"),
        {"type": "stage_end", "stage": "responding", "source": "chat"},
        {"type": "done"},
    ]


def test_ask_user_interactive_submits_selected_option(monkeypatch) -> None:
    replies: list[dict[str, Any]] = []
    _install_fake_runtime(monkeypatch, _ask_user_events(), replies=replies)
    monkeypatch.setattr(cli_common, "_stdin_interactive", lambda: True)
    monkeypatch.setattr(cli_common.console, "input", lambda prompt="": "1")

    result = runner.invoke(app, ["run", "chat", "hello"])

    assert result.exit_code == 0, result.output
    assert "Which topic?" in result.output
    assert "Algebra" in result.output
    assert replies == [
        {
            "turn_id": "turn-1",
            "text": None,
            "answers": [{"questionId": "q1", "text": "Algebra"}],
        }
    ]


def test_ask_user_non_interactive_sends_empty_reply(monkeypatch) -> None:
    replies: list[dict[str, Any]] = []
    _install_fake_runtime(monkeypatch, _ask_user_events(), replies=replies)
    monkeypatch.setattr(cli_common, "_stdin_interactive", lambda: False)

    result = runner.invoke(app, ["run", "chat", "hello"])

    assert result.exit_code == 0, result.output
    assert replies == [{"turn_id": "turn-1", "text": "", "answers": None}]


def test_ask_user_json_mode_sends_empty_reply_and_streams_events(monkeypatch) -> None:
    replies: list[dict[str, Any]] = []
    _install_fake_runtime(monkeypatch, _ask_user_events(), replies=replies)

    result = runner.invoke(app, ["run", "chat", "hello", "--format", "json"])

    assert result.exit_code == 0, result.output
    lines = [json.loads(line) for line in result.output.splitlines() if line.strip()]
    assert any(line.get("type") == "tool_result" for line in lines)
    assert replies == [{"turn_id": "turn-1", "text": "", "answers": None}]


def test_terminator_llm_output_renders_after_buffered_chunks(monkeypatch) -> None:
    events = [
        {"type": "stage_start", "stage": "responding", "source": "chat"},
        _chunk("r1", "Buffered narration."),
        {
            "type": "content",
            "content": "Terminator final text.",
            "metadata": {
                "call_id": "chat-final-response-1",
                "call_kind": "llm_final_response",
                "trace_kind": "llm_output",
            },
        },
        {"type": "stage_end", "stage": "responding", "source": "chat"},
        {"type": "done"},
    ]
    _install_fake_runtime(monkeypatch, events)

    result = runner.invoke(app, ["run", "chat", "hello"])

    assert result.exit_code == 0, result.output
    buffered_at = result.output.find("Buffered narration.")
    final_at = result.output.find("Terminator final text.")
    assert buffered_at != -1 and final_at != -1
    assert buffered_at < final_at


def test_resolve_answer_maps_numbers_to_labels() -> None:
    labels = ["Algebra", "Geometry", "Calculus"]
    assert _resolve_answer("2", labels, multi=False) == "Geometry"
    assert _resolve_answer("free text", labels, multi=False) == "free text"
    assert _resolve_answer("", labels, multi=False) == ""
    assert _resolve_answer("1, 3", labels, multi=True) == "Algebra, Calculus"
    assert _resolve_answer("1, custom", labels, multi=True) == "Algebra, custom"
    # Out-of-range numbers fall through as text rather than crashing.
    assert _resolve_answer("9", labels, multi=False) == "9"


def test_sources_render_compact_list(monkeypatch) -> None:
    events = _agent_loop_turn_events()
    events.insert(
        -2,
        {
            "type": "sources",
            "metadata": {
                "sources": [
                    {"title": "Paper A", "url": "https://example.com/a"},
                    {"title": "Paper A", "url": "https://example.com/a"},  # dedupe
                    {"filename": "notes.pdf", "file_path": "/tmp/notes.pdf"},
                ]
            },
        },
    )
    _install_fake_runtime(monkeypatch, events)

    result = runner.invoke(app, ["run", "chat", "hello"])

    assert result.exit_code == 0, result.output
    assert "sources (2):" in result.output
    assert "Paper A" in result.output
    assert "notes.pdf" in result.output
