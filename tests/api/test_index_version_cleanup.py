from threading import RLock
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from tests.services.rag.test_version_retention import publish


@pytest.fixture
def cleanup_api(tmp_path, monkeypatch):
    from deeptutor.api.routers import knowledge

    root = tmp_path / "kb"
    root.mkdir()
    for number in range(1, 5):
        publish(root, number)
    entry = {"rag_provider": "llamaindex", "status": "ready"}
    manager = SimpleNamespace(
        _catalog_lock=RLock(), _info_cache={"cached": True}, _config_cache=("cached",)
    )
    monkeypatch.setattr(knowledge, "_writable_kb", lambda name: (manager, "kb", tmp_path))
    monkeypatch.setattr(knowledge, "_load_kb_entry_or_404", lambda *args: entry)
    monkeypatch.setattr(knowledge, "_index_cleanup_databases", lambda: [])
    app = FastAPI()
    app.include_router(knowledge.router)
    return TestClient(app), root, entry, manager


def test_cleanup_requires_fresh_preview_and_invalidates_caches(cleanup_api):
    client, root, _, manager = cleanup_api
    url = "/knowledge-bases/kb/index-versions/cleanup"
    response = client.get(url)
    assert response.status_code == 200
    preview = response.json()
    assert preview["versions"] == ["version-1", "version-2"]
    assert (root / "version-1").exists()
    assert client.post(url, json={"fingerprint": "0" * 64}).status_code == 409
    assert client.post(url, json={"fingerprint": preview["fingerprint"]}).status_code == 200
    assert not (root / "version-1").exists()
    assert (root / "version-4").exists()
    assert manager._info_cache == {}
    assert manager._config_cache is None


def test_cleanup_blocks_live_or_connected_kbs(cleanup_api):
    client, _, entry, _ = cleanup_api
    entry["status"] = "processing"
    assert client.get("/knowledge-bases/kb/index-versions/cleanup").status_code == 409
    entry["status"] = "ready"
    entry["type"] = "obsidian"
    assert client.get("/knowledge-bases/kb/index-versions/cleanup").status_code == 409


def test_cleanup_applies_writable_resource_authorization(cleanup_api, monkeypatch):
    from deeptutor.api.routers import knowledge

    client, root, _, _ = cleanup_api

    def deny(name):
        raise HTTPException(status_code=403, detail="Read-only resource")

    monkeypatch.setattr(knowledge, "_writable_kb", deny)
    assert client.get("/knowledge-bases/kb/index-versions/cleanup").status_code == 403
    assert (
        client.post(
            "/knowledge-bases/kb/index-versions/cleanup", json={"fingerprint": "0" * 64}
        ).status_code
        == 403
    )
    assert (root / "version-1").exists()
