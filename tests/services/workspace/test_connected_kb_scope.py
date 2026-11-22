"""Connected knowledge bases are registered in the viewing workspace."""

from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import knowledge as router
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.knowledge import library_request, library_viewer
from tests.services.workspace.test_data_scope import account as account


def test_library_connect_request_uses_viewer_workspace(account, tmp_path, monkeypatch):
    from deeptutor.api.routers.auth import _install_request_workspace

    workspace_id = account.create_workspace("Study")["workspace_id"]
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(router, "assert_path_allowed", lambda path: vault)

    async def install_scope(request: Request):
        _install_request_workspace(request)

    app = FastAPI()
    app.include_router(router.router, prefix="/api", dependencies=[Depends(install_scope)])
    with TestClient(app) as client:
        response = client.post(
            "/api/knowledge-bases/connect-obsidian",
            params={"dt_workspace": workspace_id, "resource_library": "true"},
            json={"name": "notes", "vault_path": str(vault)},
        )
    assert response.status_code == 200
    assert response.json()["id"] == f"workspace:{workspace_id}:kb:notes"
    with workspace_context(workspace_id):
        assert "notes" in router.get_kb_manager().list_knowledge_bases()
    with workspace_context(""):
        assert "notes" not in router.get_kb_manager().list_knowledge_bases()


@pytest.mark.asyncio
async def test_connect_obsidian_uses_library_viewer_scope(account, tmp_path, monkeypatch):
    workspace_id = account.create_workspace("Study")["workspace_id"]
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(router, "assert_path_allowed", lambda path: vault)
    payload = router.ConnectObsidianRequest(name="notes", vault_path=str(vault))

    request_token = library_request.set(True)
    viewer_token = library_viewer.set(workspace_id)
    try:
        response = await router.connect_obsidian_vault(payload)
        assert library_request.get() is True
        assert library_viewer.get() == workspace_id
        with pytest.raises(HTTPException) as duplicate:
            await router.connect_obsidian_vault(payload)
        assert duplicate.value.status_code == 400
    finally:
        library_viewer.reset(viewer_token)
        library_request.reset(request_token)

    with workspace_context(workspace_id):
        assert "notes" in router.get_kb_manager().list_knowledge_bases()
    assert response["id"] == f"workspace:{workspace_id}:kb:notes"
    with workspace_context(""):
        assert "notes" not in router.get_kb_manager().list_knowledge_bases()
        await router.connect_obsidian_vault(payload)
        assert "notes" in router.get_kb_manager().list_knowledge_bases()


@pytest.mark.asyncio
async def test_archived_library_workspace_rejects_connect_without_account_write(
    account, tmp_path, monkeypatch
):
    workspace_id = account.create_workspace("Archived")["workspace_id"]
    account.update_workspace(workspace_id, archived=True)
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(router, "assert_path_allowed", lambda path: vault)
    request_token = library_request.set(True)
    viewer_token = library_viewer.set(workspace_id)
    try:
        with pytest.raises(HTTPException) as error:
            await router.connect_obsidian_vault(
                router.ConnectObsidianRequest(name="notes", vault_path=str(vault))
            )
        assert error.value.status_code == 409
        assert library_request.get() is True
    finally:
        library_viewer.reset(viewer_token)
        library_request.reset(request_token)
    with workspace_context(""):
        assert "notes" not in router.get_kb_manager().list_knowledge_bases()


@pytest.mark.asyncio
async def test_connect_without_library_viewer_keeps_existing_scope(account, tmp_path, monkeypatch):
    workspace_id = account.create_workspace("Study")["workspace_id"]
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(router, "assert_path_allowed", lambda path: vault)
    with workspace_context(workspace_id):
        result = await router.connect_obsidian_vault(
            router.ConnectObsidianRequest(name="local", vault_path=str(vault))
        )
        assert result["id"] == f"workspace:{workspace_id}:kb:local"
        request = library_request.set(True)
        try:
            result = await router.connect_obsidian_vault(
                router.ConnectObsidianRequest(name="account", vault_path=str(vault))
            )
            assert result["id"] == "account:kb:account"
        finally:
            library_request.reset(request)
        assert "local" in router.get_kb_manager().list_knowledge_bases()
        assert "account" not in router.get_kb_manager().list_knowledge_bases()
    with workspace_context(""):
        assert "account" in router.get_kb_manager().list_knowledge_bases()
        assert "local" not in router.get_kb_manager().list_knowledge_bases()


@pytest.mark.asyncio
async def test_connect_does_not_reuse_a_moved_knowledge_id(account, tmp_path, monkeypatch):
    from deeptutor.multi_user.paths import get_account_path_service

    workspace_id = account.create_workspace("Study")["workspace_id"]
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(router, "assert_path_allowed", lambda path: vault)
    aliases = get_account_path_service().get_runtime_state_dir() / "knowledge-move-aliases.json"
    aliases.parent.mkdir(parents=True, exist_ok=True)
    old_id = f"workspace:{workspace_id}:kb:notes"
    aliases.write_text(json.dumps({old_id: "account:kb:moved"}), encoding="utf-8")
    request = library_request.set(True)
    viewer = library_viewer.set(workspace_id)
    try:
        with pytest.raises(HTTPException) as error:
            await router.connect_obsidian_vault(
                router.ConnectObsidianRequest(name="notes", vault_path=str(vault))
            )
        assert error.value.status_code == 409
    finally:
        library_viewer.reset(viewer)
        library_request.reset(request)
    with workspace_context(workspace_id):
        assert "notes" not in router.get_kb_manager().list_knowledge_bases()


@pytest.mark.asyncio
async def test_other_connected_routes_register_in_viewing_workspace(account, tmp_path, monkeypatch):
    from deeptutor.services.rag.pipelines.ima import probe as ima_probe
    from deeptutor.services.rag.pipelines.kiwix import client as kiwix_client
    from deeptutor.services.rag.pipelines.lightrag_server import probe as lightrag_probe
    from deeptutor.services.rag.pipelines.weknora import probe as weknora_probe

    workspace_id = account.create_workspace("Study")["workspace_id"]
    folder = tmp_path / "index"
    folder.mkdir()
    monkeypatch.setattr(router, "assert_path_allowed", lambda path: folder)
    monkeypatch.setattr(
        router,
        "probe_linked_folder",
        lambda *_: SimpleNamespace(
            ok=True,
            provider="lightrag",
            embedding=SimpleNamespace(index_model="model"),
            doc_count=0,
            warnings=[],
        ),
    )

    async def probe_lightrag(*_args):
        return SimpleNamespace(ok=True, base_url="http://localhost:9621")

    async def probe_weknora(*_args):
        return SimpleNamespace(
            ok=True, base_url="http://localhost:8080", knowledge_base_id="remote"
        )

    async def probe_ima(*_args):
        return SimpleNamespace(ok=True, description="test")

    async def probe_kiwix(_self):
        return "Archive"

    monkeypatch.setattr(lightrag_probe, "probe_server", probe_lightrag)
    monkeypatch.setattr(weknora_probe, "probe_weknora", probe_weknora)
    monkeypatch.setattr(ima_probe, "probe_knowledge_base", probe_ima)
    monkeypatch.setattr(kiwix_client.KiwixClient, "probe", probe_kiwix)

    cases = [
        (router.connect_marginnote4, router.ConnectMarginNote4Request(name="margin")),
        (
            router.connect_linked_folder_route,
            router.ConnectFolderRequest(name="folder", folder_path=str(folder)),
        ),
        (
            router.connect_lightrag_server_route,
            router.ConnectLightRagServerRequest(
                name="light", server_url="http://localhost:9621", api_key="dummy"
            ),
        ),
        (
            router.connect_weknora_route,
            router.ConnectWeKnoraRequest(
                name="weknora",
                server_url="http://localhost:8080",
                api_key="dummy",
                knowledge_base_id="remote",
            ),
        ),
        (
            router.connect_kiwix_route,
            router.ConnectKiwixRequest(
                name="kiwix", server_url="http://localhost:8080", zim_name="test"
            ),
        ),
        (
            router.connect_ima_route,
            router.ConnectImaRequest(
                name="ima", client_id="dummy", api_key="dummy", knowledge_base_id="remote"
            ),
        ),
    ]
    request_token = library_request.set(True)
    viewer_token = library_viewer.set(workspace_id)
    try:
        for endpoint, payload in cases:
            response = await endpoint(payload)
            assert response["id"] == f"workspace:{workspace_id}:kb:{payload.name}"
            assert library_request.get() is True
    finally:
        library_viewer.reset(viewer_token)
        library_request.reset(request_token)
    with workspace_context(workspace_id):
        assert {payload.name for _, payload in cases} <= set(
            router.get_kb_manager().list_knowledge_bases()
        )
    with workspace_context(""):
        assert not set(router.get_kb_manager().list_knowledge_bases())
