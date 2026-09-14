"""Grok CLI's native JSONL contract, failures, and connection defaults."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from deeptutor.services.subagent.config import (
    SubagentSettings,
    default_backend_config,
    settings_from_dict,
)
from deeptutor.services.subagent.grok import GrokBackend


async def _consult(monkeypatch, *events: Any, exit_code: str = "0", **kwargs):
    async def stream(cmd, cwd=None):  # noqa: ARG001
        for event in events:
            if isinstance(event, tuple):
                yield event
            else:
                yield "stdout", json.dumps(event)
        yield "exit", exit_code

    monkeypatch.setattr("deeptutor.services.subagent.grok.stream_process_lines", stream)
    seen = []

    async def on_event(event):
        seen.append(event)

    result = await GrokBackend().consult("question", on_event=on_event, **kwargs)
    return result, seen


def test_commands_use_native_protocol_and_explicit_session_resume():
    config = default_backend_config("grok")
    config.model = "model-from-grok-models"
    config.effort = "high"
    config.system_prompt = "Ask one question at a time."
    config.extra_args = ["--disable-web-search"]
    backend = GrokBackend()
    for sid in (None, "session-for-this-connection"):
        cmd = backend._build_command("--literal prompt\n你好", session_id=sid, config=config)
        assert cmd[0] == "grok"
        assert cmd[cmd.index("--output-format") + 1] == "streaming-json"
        assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
        assert cmd[cmd.index("--model") + 1] == config.model
        assert cmd[cmd.index("--reasoning-effort") + 1] == "high"
        assert cmd[cmd.index("--rules") + 1] == config.system_prompt
        assert cmd[-1] == "--single=--literal prompt\n你好"
        assert "--no-memory" in cmd and "--verbatim" in cmd
        assert "--disable-web-search" in cmd
        assert "--continue" not in cmd and "--session-id" not in cmd
        if sid:
            assert cmd[cmd.index("--resume") + 1] == sid
        else:
            assert "--resume" not in cmd


@pytest.mark.parametrize("raw", [{}, {"backends": {"grok": {}}}, {"backends": {"grok": None}}])
def test_missing_grok_permissions_default_to_dont_ask(raw):
    settings = settings_from_dict(raw)
    assert settings.backend("grok").permission_mode == "dontAsk"
    assert SubagentSettings().backend("grok").permission_mode == "dontAsk"
    assert settings.backend("claude_code").permission_mode == "bypassPermissions"


def test_explicit_grok_permissions_survive_settings_roundtrip():
    settings = settings_from_dict({"backends": {"grok": {"permission_mode": "acceptEdits"}}})
    restored = settings_from_dict(settings.to_dict())
    assert restored.backend("grok").permission_mode == "acceptEdits"


@pytest.mark.asyncio
async def test_streamed_answer_session_and_private_payload_filtering(monkeypatch):
    result, seen = await _consult(
        monkeypatch,
        {"type": "available_commands", "tools": ["ignored"]},
        {"type": "thought", "data": "private reasoning marker"},
        {"type": "text", "data": "你好，"},
        {"type": "text", "data": "world"},
        {"type": "usage", "signature": "opaque signature marker"},
        {"type": "end", "sessionId": "session-1", "stopReason": "end_turn"},
    )
    assert result.success is True
    assert result.final_text == "你好，world"
    assert result.session_id == "session-1"
    assert result.event_count == len(seen) == 2
    assert [e.text for e in seen] == ["你好，", "你好，world"]
    assert seen[0].meta["merge_id"] == seen[1].meta["merge_id"]
    assert "private reasoning marker" not in repr(seen)
    assert "opaque signature marker" not in repr(seen)


@pytest.mark.asyncio
async def test_tool_events_and_final_answer_do_not_reuse_preamble(monkeypatch):
    result, seen = await _consult(
        monkeypatch,
        {"type": "text", "data": "Let me read the file."},
        {
            "type": "tool_call",
            "toolCallId": "t1",
            "toolName": "read_file",
            "status": "in_progress",
            "rawInput": {"path": "textbook.txt"},
        },
        {
            "type": "tool_call_update",
            "toolCallId": "t1",
            "status": "completed",
            "rawOutput": {"text": "Chapter 1"},
        },
        {"type": "usage", "stopReason": "tool_use"},
        {"type": "text", "data": "The answer is "},
        {"type": "text", "data": "42."},
        {"type": "end", "sessionId": "session-1", "stopReason": "end_turn"},
    )
    assert result.success is True
    assert result.final_text == "The answer is 42."
    tools = [e for e in seen if e.kind in ("tool", "tool_result")]
    assert len(tools) == 2
    assert "read_file" in tools[0].text and "textbook.txt" in tools[0].text
    assert "Chapter 1" in tools[1].text
    assert "read_file" in tools[1].text and "textbook.txt" in tools[1].text
    assert tools[0].meta["merge_id"] == tools[1].meta["merge_id"]
    assert seen[0].meta["merge_id"] != seen[-1].meta["merge_id"]


@pytest.mark.asyncio
async def test_late_tool_update_does_not_reset_an_answer(monkeypatch):
    result, _ = await _consult(
        monkeypatch,
        {"type": "tool_call", "toolCallId": "t1", "toolName": "read_file"},
        {"type": "text", "data": "The answer is "},
        {"type": "tool_call_update", "toolCallId": "t1", "status": "completed"},
        {"type": "text", "data": "42."},
        {"type": "end", "stopReason": "end_turn"},
    )
    assert result.success and result.final_text == "The answer is 42."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["cancelled", "max_tokens", "max_turn_requests", "refusal", "", None]
)
async def test_abnormal_stop_is_failure_even_with_partial_text(monkeypatch, reason):
    result, _ = await _consult(
        monkeypatch,
        {"type": "text", "data": "partial"},
        {"type": "end", "stopReason": reason},
    )
    assert result.success is False
    assert "without completing" in result.error


@pytest.mark.asyncio
async def test_nonzero_exit_does_not_succeed_with_an_answer(monkeypatch):
    result, _ = await _consult(
        monkeypatch,
        {"type": "text", "data": "partial answer"},
        {"type": "end", "stopReason": "end_turn"},
        exit_code="1",
    )
    assert result.success is False
    assert "code 1" in result.error


@pytest.mark.asyncio
async def test_error_is_preserved_and_stderr_cannot_spoof_protocol(monkeypatch):
    result, seen = await _consult(
        monkeypatch,
        ("stderr", '{"type":"end","stopReason":"end_turn","sessionId":"wrong"}'),
        {"type": "error", "message": "Authentication required; run grok login"},
        exit_code="1",
        session_id="original",
    )
    assert result.success is False
    assert "grok login" in result.error
    assert result.session_id == "original"
    assert seen[0].kind == "log"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "events,error",
    [
        ([], "without a completion"),
        ([{"type": "text", "data": "partial"}], "without a completion"),
        ([{"type": "end", "stopReason": "end_turn"}], "without an answer"),
        ([("stdout", '{"type":"thought","data":"private truncated')], "invalid streaming JSON"),
        ([[]], "invalid streaming event"),
    ],
)
async def test_empty_truncated_or_malformed_streams_fail(monkeypatch, events, error):
    result, seen = await _consult(monkeypatch, *events)
    assert result.success is False
    assert error in result.error
    assert "private truncated" not in repr(seen)


@pytest.mark.asyncio
async def test_future_events_log_only_the_type(monkeypatch):
    _, seen = await _consult(monkeypatch, {"type": "future_event", "data": "private marker"})
    assert seen[0].text == "Grok CLI: future_event"
    assert "private marker" not in repr(seen)


@pytest.mark.asyncio
async def test_images_fail_explicitly_without_starting_cli(monkeypatch):
    async def stream(*args, **kwargs):
        pytest.fail("unsupported images must not start Grok")
        yield

    monkeypatch.setattr("deeptutor.services.subagent.grok.stream_process_lines", stream)
    seen = []

    async def on_event(event):
        seen.append(event)

    result = await GrokBackend().consult("describe", on_event=on_event, images=["/tmp/a.png"])
    assert result.success is False
    assert "image forwarding" in result.error
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_cancellation_propagates_and_closes_process_stream(monkeypatch):
    closed = False

    async def stream(*args, **kwargs):
        nonlocal closed
        try:
            raise asyncio.CancelledError
            yield
        finally:
            closed = True

    monkeypatch.setattr("deeptutor.services.subagent.grok.stream_process_lines", stream)

    async def on_event(event):
        pytest.fail("cancellation must not become an error result")

    with pytest.raises(asyncio.CancelledError):
        await GrokBackend().consult("question", on_event=on_event)
    assert closed


@pytest.mark.asyncio
async def test_consult_passes_cwd_and_resume_to_the_process(monkeypatch):
    captured = {}

    async def stream(cmd, cwd=None):
        captured.update(cmd=cmd, cwd=cwd)
        yield "stdout", '{"type":"text","data":"ok"}'
        yield "stdout", '{"type":"end","stopReason":"end_turn"}'
        yield "exit", "0"

    monkeypatch.setattr("deeptutor.services.subagent.grok.stream_process_lines", stream)

    async def on_event(event):
        pass

    result = await GrokBackend().consult(
        "follow up",
        on_event=on_event,
        cwd="/project",
        session_id="saved-session",
    )
    assert result.success and result.session_id == "saved-session"
    assert captured["cwd"] == "/project"
    assert captured["cmd"][captured["cmd"].index("--resume") + 1] == "saved-session"
    assert captured["cmd"][captured["cmd"].index("--permission-mode") + 1] == "dontAsk"


@pytest.mark.asyncio
@pytest.mark.parametrize("installed,compatible", [(True, True), (True, False), (False, False)])
async def test_registry_detection_and_options_use_grok_protocol(monkeypatch, installed, compatible):
    from deeptutor.services.subagent.models import sync_backend_options
    from deeptutor.services.subagent.registry import get_backend, list_backend_kinds

    async def probe(cmd):
        assert cmd[0] == "grok"
        if cmd[-1] == "--version":
            return installed, "grok 1.0.3" if installed else "not installed"
        return (
            True,
            "--single --resume --permission-mode streaming-json" if compatible else "other CLI",
        )

    monkeypatch.setattr("deeptutor.services.subagent.grok.probe_version", probe)
    assert "grok" in list_backend_kinds()
    assert get_backend("grok").local_cli is True
    detected = await get_backend("grok").detect()
    options = await sync_backend_options("grok")
    assert detected.available is options.available is (installed and compatible)
    assert options.kind == "grok"
    assert options.allow_custom_model and options.models == [] and options.efforts == []
    if not options.available:
        assert "xAI" in options.detail and "grok login" in options.detail
