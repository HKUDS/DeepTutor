"""The workspace note exposes logical paths only.

Issue #2621: the chat loop replays the workspace note as a runtime snapshot
inside the cached prompt prefix. The note must therefore be byte-identical
across the turns of a session; the exact per-turn output folder travels in
the trailing user message instead (see ``workspace_turn_note``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.agents._shared.workspace_prompt import workspace_system_note, workspace_turn_note
from deeptutor.core.context import TurnRuntimeContext, UnifiedContext, WorkspaceRuntimeContext


@pytest.mark.parametrize("language", ["en", "zh"])
def test_note_is_empty_without_runtime_workspace(language: str) -> None:
    pipeline = SimpleNamespace(_exec_enabled=True, language=language)
    assert AgenticChatPipeline._workspace_system_note(pipeline, object()) == ""


def _context_with_turn(turn: str) -> UnifiedContext:
    physical_root = "/private/host/learning-files"
    return UnifiedContext(
        runtime=TurnRuntimeContext(
            workspace=WorkspaceRuntimeContext(
                workspace_id="ws_test",
                root=physical_root,
                output_dir=f"{physical_root}/outputs/chat/s/{turn}",
                logical_output_dir=f"outputs/chat/s/{turn}",
            )
        )
    )


@pytest.mark.parametrize("language", ["en", "zh"])
def test_loop_note_is_byte_stable_across_turns(language: str) -> None:
    """The replayed note must not change when the turn changes."""
    first = workspace_system_note(
        _context_with_turn("t-1"), language=language, allow_export=True, state_turn_path=False
    )
    second = workspace_system_note(
        _context_with_turn("t-2"), language=language, allow_export=True, state_turn_path=False
    )

    assert first == second
    assert first
    # Turn-level state never enters the cached prefix...
    assert "t-1" not in first
    assert "outputs/chat/s" not in first
    # ...and the standing contract stays intact.
    assert "workspace_present" in first
    assert "workspace_export" in first
    assert "DEEPTUTOR_WORKSPACE_ROOT" in first


@pytest.mark.parametrize("language", ["en", "zh"])
def test_phase_note_still_names_the_turn_path(language: str) -> None:
    """Per-phase prompts embed the exact path and stay contract-complete."""
    physical_root = "/private/host/learning-files"
    context = UnifiedContext(
        runtime=TurnRuntimeContext(
            workspace=WorkspaceRuntimeContext(
                workspace_id="ws_test",
                root=physical_root,
                output_dir=f"{physical_root}/outputs/chat/s/t-1",
                logical_output_dir="outputs/chat/s/t-1",
            )
        )
    )

    note = workspace_system_note(context, language=language, allow_export=True)

    assert "outputs/chat/s/t-1" in note
    assert physical_root not in note
    assert "workspace_present" in note
    assert "workspace_export" in note
    assert "DEEPTUTOR_WORKSPACE_ROOT" in note


@pytest.mark.parametrize("language", ["en", "zh"])
def test_turn_note_carries_the_exact_per_turn_path(language: str) -> None:
    first = workspace_turn_note(_context_with_turn("t-1"), language=language)
    second = workspace_turn_note(_context_with_turn("t-2"), language=language)

    assert "outputs/chat/s/t-1" in first
    assert "outputs/chat/s/t-2" in second
    assert first != second


@pytest.mark.parametrize("language", ["en", "zh"])
def test_turn_note_is_empty_without_runtime_workspace(language: str) -> None:
    assert workspace_turn_note(UnifiedContext(), language=language) == ""
