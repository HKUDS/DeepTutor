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


@pytest.fixture
def partner_workspace_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Two scopes behind one request: the human caller's, and a partner's.

    ``get_path_service`` is what the multi-user layer re-points when a scope is
    installed, so a scope-aware stand-in for it is what makes the partner
    lookup real rather than mocked.
    """
    from deeptutor.multi_user.context import get_current_user_or_none
    from deeptutor.services.partners.scope import partner_user_id

    module = importlib.import_module("deeptutor.api.routers.workspace")
    service_module = importlib.import_module("deeptutor.services.workspace.service")
    human = PathService(workspace_root=tmp_path / "human")
    partner = PathService(workspace_root=tmp_path / "partner")
    for paths in (human, partner):
        paths.ensure_all_directories()

    def scoped_path_service() -> PathService:
        current = get_current_user_or_none()
        if current is not None and current.id == partner_user_id("math-bot"):
            return partner
        return human

    monkeypatch.setattr(service_module, "get_path_service", scoped_path_service)
    monkeypatch.setattr(module, "get_content_workspace_service", ContentWorkspaceService)
    monkeypatch.setattr(module, "visible_partners", lambda: [{"partner_id": "math-bot"}])
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)

    app = FastAPI()
    app.include_router(module.files_router, prefix="/files/workspace-items")
    return TestClient(app), scoped_path_service


def _publish_in_partner_scope(paths: PathService, filename: str, body: str):
    from deeptutor.multi_user.paths import user_context
    from deeptutor.services.partners.scope import partner_user

    with user_context(partner_user("math-bot")):
        service = ContentWorkspaceService()
        binding = service.current_binding(ensure_output=True)
        (binding.root / filename).write_text(body, encoding="utf-8")
        return service.publish(binding, [{"path": filename}])[0]


def test_a_partner_chats_generated_file_downloads_for_the_person_who_asked(
    partner_workspace_api,
) -> None:
    """#1267: the attachment is published in the partner's scope, clicked in ours.

    A partner web chat runs as a synthetic user, so ``workspace_present``
    writes its manifest under ``data/partners/<id>/workspace``. Resolving the
    download against the caller's own bindings alone 404s a file the
    transcript is still offering them.
    """
    client, scoped = partner_workspace_api
    item = _publish_in_partner_scope(scoped(), "architecture.md", "godot notes")

    response = client.get(item.url)

    assert response.status_code == 200
    assert response.text == "godot notes"


def test_an_unpublished_item_is_still_not_found(partner_workspace_api) -> None:
    """The fallback widens the caller's reach, it does not open the store."""
    client, _ = partner_workspace_api

    response = client.get(f"/files/workspace-items/ws_{'0' * 32}/wsi_{'0' * 32}")

    assert response.status_code == 404
