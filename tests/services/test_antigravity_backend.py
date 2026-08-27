"""Antigravity CLI (``agy``) subagent backend (#828).

Google retired Gemini CLI on 2026-06-18, so for plan-based users the `gemini`
backend has no CLI left to detect. These tests pin the replacement's wire
contract: the `agy` command line, and its stream-json event vocabulary — which
is *not* Gemini CLI's despite the shared lineage.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deeptutor.services.subagent.antigravity import AntigravityBackend
from deeptutor.services.subagent.config import BackendConfig


def _stream(*events: dict[str, Any], exit_code: str = "0"):
    """Replay a canned stdout stream in stream_process_lines' shape."""

    async def _fake(cmd, cwd=None, **kwargs):  # noqa: ARG001
        for event in events:
            yield "stdout", json.dumps(event)
        yield "exit", exit_code

    return _fake


async def _consult(backend: AntigravityBackend, monkeypatch, *events, exit_code: str = "0"):
    monkeypatch.setattr(
        "deeptutor.services.subagent.antigravity.stream_process_lines",
        _stream(*events, exit_code=exit_code),
    )
    seen: list[Any] = []

    async def on_event(event):
        seen.append(event)

    result = await backend.consult("q", on_event=on_event)
    return result, seen


# ---- command line ------------------------------------------------------------


def test_fresh_command_carries_prompt_stream_format_model_and_effort() -> None:
    cmd = AntigravityBackend()._build_command(
        "hi",
        session_id=None,
        config=BackendConfig(system_prompt="be brief", model="gemini-3-pro", effort="high"),
    )

    assert cmd[:3] == ["agy", "-p", "be brief\n\nhi"]
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert cmd[cmd.index("--model") + 1] == "gemini-3-pro"
    assert cmd[cmd.index("--effort") + 1] == "high"
    assert "--conversation" not in cmd


def test_resume_uses_conversation_and_drops_the_system_prompt() -> None:
    """The resumed conversation already carries the delegate instruction."""
    cmd = AntigravityBackend()._build_command(
        "again",
        session_id="conv-1",
        config=BackendConfig(system_prompt="be brief"),
    )

    assert cmd[:3] == ["agy", "-p", "again"]
    assert cmd[cmd.index("--conversation") + 1] == "conv-1"


@pytest.mark.parametrize("mode", ["bypassPermissions", "acceptEdits"])
def test_permissive_modes_waive_approval(mode: str) -> None:
    cmd = AntigravityBackend()._build_command(
        "hi", session_id=None, config=BackendConfig(permission_mode=mode)
    )

    assert "--dangerously-skip-permissions" in cmd


@pytest.mark.parametrize("mode", ["default", "plan"])
def test_cautious_modes_keep_the_clis_soft_deny(mode: str) -> None:
    """Headless `agy` soft-denies rather than blocking, so this cannot stall."""
    cmd = AntigravityBackend()._build_command(
        "hi", session_id=None, config=BackendConfig(permission_mode=mode)
    )

    assert "--dangerously-skip-permissions" not in cmd


def test_unknown_effort_is_dropped_rather_than_passed_through() -> None:
    """`--effort` only accepts low/medium/high; anything else exits non-zero."""
    cmd = AntigravityBackend()._build_command(
        "hi", session_id=None, config=BackendConfig(effort="ultra")
    )

    assert "--effort" not in cmd


def test_images_are_named_as_paths_for_the_agents_own_read_tools() -> None:
    cmd = AntigravityBackend()._build_command(
        "describe", session_id=None, config=BackendConfig(), images=["/tmp/a.png"]
    )

    assert "/tmp/a.png" in cmd[2]


# ---- event stream ------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_deltas_accumulate_into_the_final_answer(monkeypatch) -> None:
    """`step_update.text_delta` chunks have no aggregate event to fall back on."""
    result, _ = await _consult(
        AntigravityBackend(),
        monkeypatch,
        {"event": "init", "conversation_id": "c1", "init": {"model": "gemini-3-pro"}},
        {"event": "step_update", "step_update": {"step_index": 0, "text_delta": "4 is "}},
        {"event": "step_update", "step_update": {"step_index": 0, "text_delta": "the answer."}},
    )

    assert result.final_text == "4 is the answer."
    assert result.success is True


@pytest.mark.asyncio
async def test_conversation_id_is_captured_for_resume(monkeypatch) -> None:
    result, _ = await _consult(
        AntigravityBackend(),
        monkeypatch,
        {"event": "init", "conversation_id": "conv-42", "init": {}},
        {"event": "step_update", "step_update": {"step_index": 0, "text_delta": "hi"}},
    )

    assert result.session_id == "conv-42"


@pytest.mark.asyncio
async def test_result_event_response_wins_over_accumulated_deltas(monkeypatch) -> None:
    result, _ = await _consult(
        AntigravityBackend(),
        monkeypatch,
        {"event": "step_update", "step_update": {"step_index": 0, "text_delta": "partial"}},
        {"event": "result", "result": {"status": "SUCCESS", "response": "the whole answer"}},
    )

    assert result.final_text == "the whole answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ERROR", "CANCELED", "INTERRUPTED", "INVALID"])
async def test_failing_result_status_marks_the_consult_failed(monkeypatch, status: str) -> None:
    result, _ = await _consult(
        AntigravityBackend(),
        monkeypatch,
        {"event": "result", "result": {"status": status, "error": "boom"}},
    )

    assert result.success is False
    assert "boom" in result.error


@pytest.mark.asyncio
async def test_tool_steps_surface_with_a_readable_header(monkeypatch) -> None:
    _, seen = await _consult(
        AntigravityBackend(),
        monkeypatch,
        {
            "event": "step_update",
            "step_update": {
                "step_index": 1,
                "state": "ACTIVE",
                "tool_name": "Shell",
                "tool_info": {"args": {"command": "ls -la"}},
            },
        },
    )

    assert any(e.kind == "tool" and e.text == "Shell(ls -la)" for e in seen)


@pytest.mark.asyncio
async def test_a_tool_starts_a_new_text_block(monkeypatch) -> None:
    """Prose after a tool call reads as its own row, not glued to the earlier one."""
    result, _ = await _consult(
        AntigravityBackend(),
        monkeypatch,
        {"event": "step_update", "step_update": {"step_index": 0, "text_delta": "Looking…"}},
        {"event": "step_update", "step_update": {"step_index": 1, "tool_name": "Shell"}},
        {"event": "step_update", "step_update": {"step_index": 2, "text_delta": "Found it."}},
    )

    assert result.final_text == "Looking…\n\nFound it."


@pytest.mark.asyncio
async def test_empty_stream_is_reported_not_returned_as_a_blank_answer(monkeypatch) -> None:
    """antigravity-cli#76: `-p` can emit nothing when stdout is not a TTY.

    Silence must not reach the caller as the agent having nothing to say — the
    model in the sidebar would look like it answered with an empty message.
    """
    result, seen = await _consult(AntigravityBackend(), monkeypatch)

    assert result.success is False
    assert "#76" in result.error
    assert any(e.kind == "error" for e in seen)


@pytest.mark.asyncio
async def test_nonzero_exit_without_output_is_surfaced(monkeypatch) -> None:
    result, _ = await _consult(AntigravityBackend(), monkeypatch, exit_code="1")

    assert result.success is False


@pytest.mark.asyncio
async def test_non_json_stdout_becomes_a_log_line_not_a_crash(monkeypatch) -> None:
    async def _fake(cmd, cwd=None, **kwargs):  # noqa: ARG001
        yield "stdout", "warning: something plain"
        yield (
            "stdout",
            json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "ok"}}),
        )
        yield "exit", "0"

    monkeypatch.setattr("deeptutor.services.subagent.antigravity.stream_process_lines", _fake)
    seen: list[Any] = []

    async def on_event(event):
        seen.append(event)

    result = await AntigravityBackend().consult("q", on_event=on_event)

    assert result.final_text == "ok"
    assert any(e.kind == "log" for e in seen)


# ---- registry ----------------------------------------------------------------


def test_backend_is_registered_as_a_local_cli() -> None:
    from deeptutor.services.subagent import get_backend

    backend = get_backend("antigravity")

    assert backend is not None
    assert backend.cli_command == "agy"
    assert backend.local_cli is True


def test_gemini_cli_is_kept_alongside_it() -> None:
    """#828 asked to replace Gemini CLI; API-key users still have a working one."""
    from deeptutor.services.subagent import get_backend

    assert get_backend("gemini") is not None


@pytest.mark.asyncio
async def test_options_expose_the_effort_flag_and_free_text_models() -> None:
    from deeptutor.services.subagent.models import sync_backend_options

    options = await sync_backend_options("antigravity")

    assert options.kind == "antigravity"
    assert [e for e in options.efforts] == ["low", "medium", "high"]
    assert options.allow_custom_model is True


def test_missing_cli_detail_says_something_the_status_chip_does_not() -> None:
    """`probe_version` returns a bare "not installed", which told the reader nothing.

    The Gemini CLI page in #828 showed exactly that, leaving the reporter to work
    out on their own that Google had retired the CLI.
    """
    from deeptutor.services.subagent.process import not_found_detail

    assert not_found_detail("not installed", "go install it") == "go install it"
    assert not_found_detail("", "go install it") == "go install it"
    # Real probe output is more informative and still wins.
    assert not_found_detail("permission denied", "go install it") == "permission denied"


@pytest.mark.asyncio
async def test_retired_gemini_cli_points_at_its_successor() -> None:
    from deeptutor.services.subagent.models import sync_backend_options

    detail = (await sync_backend_options("gemini")).detail

    # Skipped where a Gemini CLI really is installed — then there is no detail.
    if detail:
        assert "Antigravity" in detail
