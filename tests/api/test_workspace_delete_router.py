from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from deeptutor.services.path_service import PathService
from deeptutor.services.workspace import ContentWorkspaceService

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)


@pytest.fixture
def workspace_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = importlib.import_module("deeptutor.api.routers.workspace")
    service_module = importlib.import_module("deeptutor.services.workspace.service")
    paths_module = importlib.import_module("deeptutor.multi_user.paths")
    migration_module = importlib.import_module("deeptutor.services.workspace.data_migration")
    paths = PathService(workspace_root=tmp_path / "runtime")
    paths.ensure_all_directories()
    service = ContentWorkspaceService()
    monkeypatch.setattr(service_module, "get_path_service", lambda: paths)
    monkeypatch.setattr(paths_module, "get_account_path_service", lambda: paths)
    monkeypatch.setattr(migration_module, "get_account_path_service", lambda: paths)
    monkeypatch.setattr(migration_module, "get_path_service", lambda: paths)
    monkeypatch.setattr(module, "get_content_workspace_service", lambda: service)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)

    app = FastAPI()
    from deeptutor.services.workspace.activity import WorkspaceActivityMiddleware

    app.add_middleware(WorkspaceActivityMiddleware)
    app.include_router(module.settings_router, prefix="/api/settings/workspace")
    return TestClient(app), service


def test_api_two_step_workspace_deletion(workspace_api):
    client, service = workspace_api

    # 1. Create a workspace
    create_resp = client.post("/api/settings/workspace/registrations", json={"name": "Physics"})
    assert create_resp.status_code == 200
    ws_id = create_resp.json()["workspace"]["workspace_id"]
    ws_path = Path(create_resp.json()["workspace"]["path"])
    assert ws_path.is_dir()

    # 2. DELETE without archive should return 400
    del_unarchived = client.delete(f"/api/settings/workspace/registrations/{ws_id}")
    assert del_unarchived.status_code == 400
    assert "Workspace must be archived before it can be permanently deleted" in del_unarchived.json()["detail"]
    assert ws_path.is_dir()

    # 3. Archive the workspace
    patch_resp = client.patch(f"/api/settings/workspace/registrations/{ws_id}", json={"archived": True})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["workspace"]["archived"] is True

    # 4. Now DELETE succeeds
    del_archived = client.delete(f"/api/settings/workspace/registrations/{ws_id}")
    assert del_archived.status_code == 200
    assert del_archived.json() == {"deleted": True, "workspace_id": ws_id}
    assert not ws_path.exists()

    # 5. Check catalog no longer has this workspace
    cat_resp = client.get("/api/settings/workspace/registrations")
    assert cat_resp.status_code == 200
    assert not any(w["workspace_id"] == ws_id for w in cat_resp.json()["workspaces"])
