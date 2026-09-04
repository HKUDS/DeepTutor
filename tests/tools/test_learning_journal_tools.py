"""Tests for learning_status / learning_update tools (#740)."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.path_service import PathService
from deeptutor.tools.learning_journal_tools import LearningStatusTool, LearningUpdateTool


@pytest.fixture()
def journal_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PathService:
    service = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(
        "deeptutor.services.learning_journal.store.get_path_service",
        lambda: service,
    )
    return service


@pytest.mark.asyncio
async def test_learning_update_and_status_tools(journal_workspace: PathService) -> None:
    update = LearningUpdateTool()
    status = LearningStatusTool()

    assert update.name == "learning_update"
    assert status.name == "learning_status"

    mission = await update.execute(
        op="set_mission",
        topic="Linear algebra",
        why="ML foundations",
        level="beginner",
    )
    assert mission.success
    assert "mission set" in mission.content

    note = await update.execute(
        op="note_session",
        summary="Vectors and linear combinations.",
        next_focus="Matrices as linear maps",
    )
    assert note.success

    record = await update.execute(
        op="add_record",
        title="Span",
        insight="Span is the set of all linear combinations of the generators.",
    )
    assert record.success
    assert record.metadata.get("record_id") == "lr_0001"

    snapshot = await status.execute()
    assert snapshot.success
    assert "Linear algebra" in snapshot.content
    assert "Matrices as linear maps" in snapshot.content
    assert "lr_0001" in snapshot.content
    assert journal_workspace.get_learning_journal_file().exists()


@pytest.mark.asyncio
async def test_learning_update_rejects_bad_op(journal_workspace: PathService) -> None:
    result = await LearningUpdateTool().execute(op="wipe")
    assert not result.success
