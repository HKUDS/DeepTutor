"""The workspace note exposes logical paths only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.agents._shared.workspace_prompt import workspace_system_note
from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import TurnRuntimeContext, UnifiedContext, WorkspaceRuntimeContext


@pytest.mark.parametrize("language", ["en", "zh"])
def test_note_is_empty_without_runtime_workspace(language: str) -> None:
    pipeline = SimpleNamespace(_exec_enabled=True, language=language)
    assert AgenticChatPipeline._workspace_system_note(pipeline, object()) == ""


@pytest.mark.parametrize("language", ["en", "zh"])
def test_runtime_note_exposes_only_stable_workspace_guidance(language: str) -> None:
    physical_root = "/private/host/learning-files"
    context = UnifiedContext(
        runtime=TurnRuntimeContext(
            workspace=WorkspaceRuntimeContext(
                workspace_id="ws_test",
                root=physical_root,
                output_dir=f"{physical_root}/outputs/chat/s/t",
                logical_output_dir="outputs/chat/s/t",
            )
        )
    )
    pipeline = SimpleNamespace(language=language)

    note = AgenticChatPipeline._workspace_system_note(pipeline, context)

    assert "outputs/" in note
    assert "outputs/chat/s/t" not in note
    assert physical_root not in note
    assert "workspace_present" in note
    assert "workspace_export" in note
    assert "DEEPTUTOR_WORKSPACE_ROOT" in note


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("allow_export", [False, True])
def test_workspace_note_is_identical_across_turns(language: str, allow_export: bool) -> None:
    def context(turn_id: str) -> UnifiedContext:
        return UnifiedContext(
            runtime=TurnRuntimeContext(
                turn_id=turn_id,
                workspace=WorkspaceRuntimeContext(
                    root="/private/host/workspace",
                    output_dir=f"/private/host/workspace/outputs/chat/session/{turn_id}",
                    logical_output_dir=f"outputs/chat/session/{turn_id}",
                ),
            )
        )

    first, second = context("turn-1"), context("turn-2")
    assert workspace_system_note(first, language=language, allow_export=allow_export) == (
        workspace_system_note(second, language=language, allow_export=allow_export)
    )
    assert first.runtime.workspace.logical_output_dir == "outputs/chat/session/turn-1"
    assert second.runtime.workspace.logical_output_dir == "outputs/chat/session/turn-2"
