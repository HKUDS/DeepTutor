from __future__ import annotations

import pytest

from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.multi_user.paths import get_account_path_service, user_context
from deeptutor.services.workspace import ContentWorkspaceService, WorkspaceError
from deeptutor.services.workspace.models import MAX_WORKSPACE_INSTRUCTIONS_CHARS


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
    owner = CurrentUser("instructions-test", "test", "admin", UserScope("admin", "test", tmp_path))
    with user_context(owner):
        get_account_path_service().ensure_all_directories()
        yield ContentWorkspaceService()


def test_instructions_are_isolated_persistent_and_optional_on_existing_rows(service):
    a = service.create_workspace("A", instructions="  Explain intuitively.\nUse examples.  ")
    b = service.create_workspace("B")
    general = service.general_binding().workspace_id
    service.update_workspace(general, instructions="Default preferences")

    assert a["instructions"] == "Explain intuitively.\nUse examples."
    assert b["instructions"] == ""
    assert ContentWorkspaceService().workspace_instructions(a["workspace_id"]) == a["instructions"]
    assert service.workspace_instructions(b["workspace_id"]) == ""
    assert service.workspace_instructions("") == "Default preferences"
    service.update_workspace(a["workspace_id"], name="Renamed", resources={})
    assert service.workspace_instructions(a["workspace_id"]) == a["instructions"]
    assert service.create_workspace("Same folder", a["path"])["instructions"] == a["instructions"]
    service.update_workspace(a["workspace_id"], instructions=" \n ")
    assert service.workspace_instructions(a["workspace_id"]) == ""
    # Built-ins/registrations created by earlier versions have no instructions field.
    assert service.workspace_instructions(service.system_binding().workspace_id) == ""


def test_instructions_follow_owner_scope_and_cannot_modify_system_workspace(service, tmp_path):
    row = service.create_workspace("A", instructions="Private preferences")
    other = CurrentUser("other", "other", "admin", UserScope("admin", "other", tmp_path / "other"))
    with user_context(other):
        assert service.workspace_instructions(row["workspace_id"]) == ""
        with pytest.raises(WorkspaceError, match="not found"):
            service.update_workspace(row["workspace_id"], instructions="Changed")
    with pytest.raises(WorkspaceError, match="not found"):
        service.update_workspace(service.system_binding().workspace_id, instructions="Changed")


def test_runtime_instructions_are_frozen_and_survive_folder_migration(service, tmp_path):
    row = service.create_workspace("A", instructions="Old preferences")
    before = service.create_runtime_context(
        capability="chat", session_id="s", turn_id="one", workspace_id=row["workspace_id"]
    )
    service.update_workspace(row["workspace_id"], instructions="New preferences")
    after = service.create_runtime_context(
        capability="deep_solve", session_id="s", turn_id="two", workspace_id=row["workspace_id"]
    )
    admitted = service.create_runtime_context(
        capability="chat",
        session_id="s",
        turn_id="three",
        workspace_id=row["workspace_id"],
        instructions=before.instructions,
    )
    assert before.instructions == admitted.instructions == "Old preferences"
    assert after.instructions == "New preferences"
    service.migrate_workspace(row["workspace_id"], str(tmp_path / "moved"))
    assert service.workspace_instructions(row["workspace_id"]) == "New preferences"


def test_instruction_limit_is_enforced_without_overwriting_saved_preferences(service):
    row = service.create_workspace("A", instructions="Saved")
    oversized = "x" * (MAX_WORKSPACE_INSTRUCTIONS_CHARS + 1)
    with pytest.raises(WorkspaceError, match="at most"):
        service.update_workspace(row["workspace_id"], instructions=oversized)
    with pytest.raises(WorkspaceError, match="at most"):
        service.create_workspace("Invalid", instructions=oversized)
    assert service.workspace_instructions(row["workspace_id"]) == "Saved"
