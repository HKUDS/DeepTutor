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
    paths_module = importlib.import_module("deeptutor.multi_user.paths")
    migration_module = importlib.import_module("deeptutor.services.workspace.data_migration")
    paths = PathService(workspace_root=tmp_path / "runtime")
    paths.ensure_all_directories()
    service = ContentWorkspaceService()
    monkeypatch.setattr(service_module, "get_path_service", lambda: paths)
    # The migration lease and recovery journal resolve the account root via
    # separate imports. Keep both in this test's temporary workspace too.
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


def test_workspace_instructions_create_update_clear_and_validate(workspace_api):
    client, service = workspace_api
    endpoint = "/api/settings/workspace/registrations"
    created = client.post(
        endpoint, json={"name": "Algebra", "instructions": "Start with intuition"}
    )
    assert created.status_code == 200
    row = created.json()["workspace"]
    assert row["instructions"] == "Start with intuition"
    url = f"{endpoint}/{row['workspace_id']}"
    assert (
        client.patch(url, json={"name": "Linear algebra"}).json()["workspace"]["instructions"]
        == row["instructions"]
    )
    assert (
        client.patch(url, json={"instructions": "Use examples"}).json()["workspace"]["instructions"]
        == "Use examples"
    )
    assert client.patch(url, json={"instructions": ""}).json()["workspace"]["instructions"] == ""
    assert client.patch(url, json={"instructions": "x" * 10001}).status_code == 422
    assert (
        client.post(endpoint, json={"name": "Invalid", "instructions": "x" * 10001}).status_code
        == 422
    )
    general = service.general_binding().workspace_id
    assert (
        client.patch(
            f"{endpoint}/{general}", json={"instructions": "Default preferences"}
        ).status_code
        == 200
    )
    assert service.workspace_instructions("") == "Default preferences"
    assert (
        client.patch(
            f"{endpoint}/{service.system_binding().workspace_id}", json={"instructions": "Invalid"}
        ).status_code
        == 400
    )


def test_instruction_edits_can_be_saved_while_a_turn_holds_its_activity_lease(workspace_api):
    from deeptutor.services.workspace.activity import data_activity

    client, service = workspace_api
    row = service.create_workspace("Algebra")
    url = f"/api/settings/workspace/registrations/{row['workspace_id']}"
    with data_activity():
        saved = client.patch(url, json={"instructions": "Next-turn preferences"})
        assert saved.status_code == 200
        assert saved.json()["workspace"]["instructions"] == "Next-turn preferences"
        # Destructive lifecycle changes still need the exclusive lease.
        assert client.patch(url, json={"archived": True}).status_code == 400


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


def test_workspace_migration_api_blocks_active_turns_and_keeps_bindings(
    workspace_api, tmp_path, monkeypatch
):
    from unittest.mock import AsyncMock

    import deeptutor.services.session as sessions

    client, service = workspace_api
    store = AsyncMock()
    monkeypatch.setattr(sessions, "get_session_store", lambda: store)
    created = client.post("/api/settings/workspace/registrations", json={"name": "Research"})
    assert created.status_code == 200
    row = created.json()["workspace"]
    original = Path(row["path"])
    (original / "notes.txt").write_text("Keep this")
    destination = tmp_path / "new-root"
    store.list_nonterminal_turns.return_value = [{"turn_id": "active"}]
    blocked = client.post(
        "/api/settings/workspace/registrations/migrate-root", json={"path": str(destination)}
    )
    assert blocked.status_code == 409
    assert "running conversations" in blocked.json()["detail"]
    assert store.list_nonterminal_turns.await_count == 1
    assert service.describe_catalog()["migration"] is None
    assert not destination.exists()
    store.list_nonterminal_turns.return_value = []
    moved = client.post(
        "/api/settings/workspace/registrations/migrate-root", json={"path": str(destination)}
    )
    assert moved.status_code == 200
    assert store.list_nonterminal_turns.await_count == 2
    assert moved.json()["root"] == str(destination)
    binding = service.validate_chat_binding(row["workspace_id"])
    assert binding.root == destination / row["workspace_id"]
    assert (binding.root / "notes.txt").read_text() == "Keep this"
    assert (original / "notes.txt").read_text() == "Keep this"
    individual = tmp_path / "independent"
    result = client.post(
        f"/api/settings/workspace/registrations/{row['workspace_id']}/migrate",
        json={"path": str(individual)},
    )
    assert result.status_code == 200
    assert service.validate_chat_binding(row["workspace_id"]).root == individual
    assert client.post("/api/settings/workspace/registrations/system-snapshot").status_code == 200
