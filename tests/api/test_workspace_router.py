from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from deeptutor.services.path_service import PathService
from deeptutor.services.workspace import ContentWorkspaceService

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - optional in the CLI-only package
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)


@pytest.fixture
def workspace_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = importlib.import_module("deeptutor.api.routers.workspace")
    service_module = importlib.import_module("deeptutor.services.workspace.service")
    paths = PathService(workspace_root=tmp_path / "runtime")
    paths.ensure_all_directories()
    service = ContentWorkspaceService()
    monkeypatch.setattr(service_module, "get_path_service", lambda: paths)
    monkeypatch.setattr(module, "get_content_workspace_service", lambda: service)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)

    app = FastAPI()
    app.include_router(module.settings_router, prefix="/api/settings/workspace")
    app.include_router(module.files_router, prefix="/files/workspace-items")
    return TestClient(app), service


def test_workspace_settings_select_and_reset(workspace_api, tmp_path: Path) -> None:
    client, service = workspace_api
    custom = tmp_path / "learning-materials"
    custom.mkdir()

    selected = client.put("/api/settings/workspace", json={"path": str(custom)})
    assert selected.status_code == 200
    assert selected.json()["path"] == str(custom.resolve())
    assert selected.json()["is_default"] is False
    assert service.current_binding().root == custom.resolve()

    reset = client.put("/api/settings/workspace", json={"path": None})
    assert reset.status_code == 200
    assert reset.json()["is_default"] is True


def test_workspace_item_endpoint_serves_the_published_snapshot(workspace_api) -> None:
    client, service = workspace_api
    binding = service.current_binding(ensure_output=True)
    source = binding.root / "notes.md"
    source.write_text("version one", encoding="utf-8")
    item = service.publish(binding, [{"path": "notes.md"}])[0]
    source.write_text("version two", encoding="utf-8")

    response = client.get(item.url)

    assert response.status_code == 200
    assert response.text == "version one"
    assert response.headers["etag"] == f'"{item.sha256}"'
    assert "inline" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"].startswith("sandbox;")
