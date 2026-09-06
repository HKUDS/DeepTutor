"""The workspace note exposes logical paths only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import TurnRuntimeContext, UnifiedContext, WorkspaceRuntimeContext


@pytest.mark.parametrize("language", ["en", "zh"])
def test_note_is_empty_without_runtime_workspace(language: str) -> None:
    pipeline = SimpleNamespace(_exec_enabled=True, language=language)
    assert AgenticChatPipeline._workspace_system_note(pipeline, object()) == ""


@pytest.mark.parametrize("language", ["en", "zh"])
def test_runtime_note_exposes_only_the_logical_output_path(language: str) -> None:
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

    assert "outputs/chat/s/t" in note
    assert physical_root not in note
    assert "workspace_present" in note
    assert "workspace_export" in note
    assert "DEEPTUTOR_WORKSPACE_ROOT" in note
