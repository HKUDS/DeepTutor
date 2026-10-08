from __future__ import annotations

from pathlib import Path
import pytest

from deeptutor.services.path_service import PathService
from deeptutor.services.workspace import ContentWorkspaceService, WorkspaceError


@pytest.fixture
def service(tmp_path, monkeypatch):
    from deeptutor.services.workspace import service as module

    paths = PathService(workspace_root=tmp_path / "runtime")
    paths.ensure_all_directories()
    monkeypatch.setattr(module, "get_path_service", lambda: paths)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)
    return ContentWorkspaceService()


def test_delete_workspace_cannot_delete_builtins(service):
    catalog = service.describe_catalog()
    system_ws = next(w for w in catalog["workspaces"] if w["kind"] == "system")
    general_ws = next(w for w in catalog["workspaces"] if w["kind"] == "general")

    with pytest.raises(WorkspaceError, match="Built-in workspaces cannot be deleted"):
        service.delete_workspace(system_ws["workspace_id"])

    with pytest.raises(WorkspaceError, match="Built-in workspaces cannot be deleted"):
        service.delete_workspace(general_ws["workspace_id"])


def test_delete_workspace_enforces_two_step_archive_first(service):
    ws = service.create_workspace("Chemistry")
    ws_id = ws["workspace_id"]
    folder = Path(ws["path"])
    assert folder.is_dir()

    # Step 1: Trying to delete an active (unarchived) workspace must fail
    with pytest.raises(
        WorkspaceError, match="Workspace must be archived before it can be permanently deleted"
    ):
        service.delete_workspace(ws_id)

    # Workspace and files should still exist
    assert folder.is_dir()
    assert any(w["workspace_id"] == ws_id for w in service.list_workspaces())

    # Step 2: Archive first
    service.update_workspace(ws_id, archived=True)
    archived_ws = next(w for w in service.list_workspaces() if w["workspace_id"] == ws_id)
    assert archived_ws["archived"] is True

    # Step 3: Now permanent deletion succeeds
    result = service.delete_workspace(ws_id)
    assert result == {"deleted": True, "workspace_id": ws_id}

    # Workspace folder must be deleted from disk
    assert not folder.exists()
    # Workspace must be removed from catalog
    assert not any(w["workspace_id"] == ws_id for w in service.list_workspaces())


def test_delete_workspace_preserves_external_folder(service, tmp_path):
    external_folder = tmp_path / "external-project"
    external_folder.mkdir()
    (external_folder / "project.py").write_text("print('hello')", encoding="utf-8")

    ws = service.create_workspace("External Project", path=str(external_folder))
    ws_id = ws["workspace_id"]

    # Archive first
    service.update_workspace(ws_id, archived=True)

    # Permanent delete
    result = service.delete_workspace(ws_id)
    assert result["deleted"] is True

    # Must be uncataloged
    assert not any(w["workspace_id"] == ws_id for w in service.list_workspaces())
    # External folder and files MUST NOT be deleted
    assert external_folder.is_dir()
    assert (external_folder / "project.py").is_file()


def test_deployment_workspace_is_locked(tmp_path, monkeypatch):
    from deeptutor.services.workspace import service as module

    paths = PathService(workspace_root=tmp_path / "runtime")
    paths.ensure_all_directories()
    deploy_root = tmp_path / "deploy_workspace"
    deploy_root.mkdir()
    monkeypatch.setattr(module, "get_path_service", lambda: paths)
    monkeypatch.setenv("DEEPTUTOR_WORKSPACE_ROOT", str(deploy_root))
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)

    svc = ContentWorkspaceService()
    workspaces = svc.list_workspaces()
    deploy_ws = next((w for w in workspaces if Path(w["path"]).resolve() == deploy_root.resolve()), None)
    assert deploy_ws is not None
    assert deploy_ws["locked"] is True
    assert deploy_ws["archived"] is False

    # Cannot archive
    with pytest.raises(WorkspaceError, match="cannot be renamed or archived"):
        svc.update_workspace(deploy_ws["workspace_id"], archived=True)

    # Cannot delete
    with pytest.raises(WorkspaceError, match="locked and cannot be deleted"):
        svc.delete_workspace(deploy_ws["workspace_id"])


def test_builtin_auto_heals_broken_path(tmp_path, monkeypatch):
    import json
    from deeptutor.services.workspace import service as module

    paths = PathService(workspace_root=tmp_path / "runtime")
    paths.ensure_all_directories()
    monkeypatch.setattr(module, "get_path_service", lambda: paths)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)

    svc = ContentWorkspaceService()
    workspaces = svc.list_workspaces()
    sys_ws = next(w for w in workspaces if w["kind"] == "system")

    # Corrupt the path in the database to a non-existent path
    with svc._catalog_connection() as conn:
        record = conn.execute("SELECT payload FROM workspaces WHERE id = ?", (sys_ws["workspace_id"],)).fetchone()
        row = json.loads(record[0])
        row["path"] = "/non/existent/path/ws_corrupt"
        conn.execute("UPDATE workspaces SET payload = ? WHERE id = ?", (json.dumps(row), sys_ws["workspace_id"]))

    # Call describe_catalog() which calls _ensure_builtin_workspaces()
    healed_catalog = svc.describe_catalog()
    healed_sys = next(w for w in healed_catalog["workspaces"] if w["kind"] == "system")
    assert Path(healed_sys["path"]).exists()
    assert healed_sys["status"] == "ready"

