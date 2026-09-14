from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - optional dependency in lightweight envs
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)

if FastAPI is not None and TestClient is not None:
    import importlib

    knowledge_router_module = importlib.import_module("deeptutor.api.routers.knowledge")
    router = knowledge_router_module.router
else:  # pragma: no cover - optional dependency in lightweight envs
    knowledge_router_module = None
    router = None


class _FolderManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.config = {
            "knowledge_bases": {
                "kb": {
                    "path": "kb",
                    "rag_provider": "llamaindex",
                    "needs_reindex": False,
                    "status": "ready",
                }
            }
        }
        self.config_file = base_dir / "kb_config.json"
        self.folder = {
            "id": "folder-1",
            "path": str(base_dir / "notes"),
            "added_at": "2026-09-09T10:00:00",
            "file_count": 2,
            "last_sync": None,
        }
        self.update_calls: list[tuple[str, str, list[str]]] = []
        self.detect_result = {
            "new_files": [],
            "modified_files": [],
            "new_count": 0,
            "modified_count": 0,
        }

    def _load_config(self) -> dict:
        return self.config

    def list_knowledge_bases(self) -> list[str]:
        return list(self.config["knowledge_bases"])

    def get_default(self) -> str:
        return "kb"

    def get_linked_folders(self, _kb_name: str) -> list[dict]:
        return [self.folder]

    def link_folder(self, _kb_name: str, _folder_path: str) -> dict:
        return self.folder

    def unlink_folder(self, _kb_name: str, _folder_id: str) -> bool:
        return True

    def detect_folder_changes(self, _kb_name: str, _folder_id: str) -> dict:
        return self.detect_result

    def update_folder_sync_state(self, kb_name: str, folder_id: str, files: list[str]) -> None:
        self.update_calls.append((kb_name, folder_id, files))

    def update_kb_status(self, name: str, status: str, progress: dict | None = None) -> None:
        self.config["knowledge_bases"][name]["status"] = status
        self.config["knowledge_bases"][name]["progress"] = progress or {}


def _build_app() -> FastAPI:
    if FastAPI is None or router is None:  # pragma: no cover - guarded by pytestmark
        raise RuntimeError("fastapi is not installed")
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _patch_manager(monkeypatch: pytest.MonkeyPatch, manager: _FolderManager) -> None:
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(
        knowledge_router_module,
        "get_current_user",
        lambda: None,
    )
    monkeypatch.setattr(
        knowledge_router_module,
        "resolve_kb",
        lambda _name: SimpleNamespace(name="kb", base_dir=manager.base_dir),
    )
    monkeypatch.setattr(
        knowledge_router_module,
        "manager_for_resource",
        lambda _resource: manager,
    )


def test_linked_folder_routes_return_explicit_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = _FolderManager(tmp_path)
    _patch_manager(monkeypatch, manager)

    with TestClient(_build_app()) as client:
        linked = client.post(
            "/api/knowledge-bases/kb/link-folder",
            json={"folder_path": str(tmp_path / "notes")},
        )
        listed = client.get("/api/knowledge-bases/kb/linked-folders")

    assert linked.status_code == 200
    assert linked.json()["last_sync"] is None
    assert listed.status_code == 200
    assert listed.json()[0]["last_sync"] is None


def test_noop_sync_records_success_and_returns_sync_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = _FolderManager(tmp_path)
    _patch_manager(monkeypatch, manager)

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/kb/sync-folder/folder-1")

    assert response.status_code == 200
    assert response.json() == {
        "message": "No new or modified files to sync",
        "folder_path": str(tmp_path / "notes"),
        "files": [],
        "new_files": 0,
        "modified_files": 0,
        "file_count": 0,
        "task_id": None,
    }
    assert manager.update_calls == [("kb", "folder-1", [])]


def test_queued_sync_returns_counts_and_task_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = _FolderManager(tmp_path)
    manager.detect_result = {
        "new_files": [str(tmp_path / "notes" / "new.md")],
        "modified_files": [str(tmp_path / "notes" / "changed.md")],
        "new_count": 1,
        "modified_count": 1,
    }
    _patch_manager(monkeypatch, manager)
    monkeypatch.setattr(
        knowledge_router_module,
        "_build_unique_task_id",
        lambda *_args: "sync-task",
    )

    async def _noop_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop_task)

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/kb/sync-folder/folder-1")

    assert response.status_code == 200
    assert response.json()["new_files"] == 1
    assert response.json()["modified_files"] == 1
    assert response.json()["file_count"] == 2
    assert response.json()["files"] == [
        str(tmp_path / "notes" / "new.md"),
        str(tmp_path / "notes" / "changed.md"),
    ]
    assert response.json()["task_id"] == "sync-task"


def test_link_folder_rejects_connected_kb(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = _FolderManager(tmp_path)
    manager.config["knowledge_bases"]["kb"]["type"] = "linked"
    _patch_manager(monkeypatch, manager)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/link-folder",
            json={"folder_path": str(tmp_path / "notes")},
        )

    assert response.status_code == 409


def test_unlink_folder_rejects_connected_kb(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = _FolderManager(tmp_path)
    manager.config["knowledge_bases"]["kb"]["type"] = "linked"
    _patch_manager(monkeypatch, manager)

    with TestClient(_build_app()) as client:
        response = client.delete("/api/knowledge-bases/kb/linked-folders/folder-1")

    assert response.status_code == 409


def test_completed_folder_task_records_source_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = _FolderManager(tmp_path)
    _patch_manager(monkeypatch, manager)
    source_root = tmp_path / "notes"
    source_path = source_root / "nested" / "note.md"
    staged_path = tmp_path / "kb" / "raw" / "nested" / "note.md"

    class _SuccessfulAdder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def add_documents(self, _paths, **_kwargs):
            return [staged_path]

        async def process_new_documents(self, _staged):
            return SimpleNamespace(
                processed_files=[staged_path],
                processed_count=1,
                has_failures=False,
            )

        def update_metadata(self, _count) -> None:
            pass

    monkeypatch.setattr(knowledge_router_module, "DocumentAdder", _SuccessfulAdder)

    asyncio.run(
        knowledge_router_module.run_upload_processing_task(
            kb_name="kb",
            base_dir=str(tmp_path),
            uploaded_file_paths=[str(source_path)],
            task_id="folder-success-test",
            rag_provider="llamaindex",
            folder_id="folder-1",
            folder_root=str(source_root),
        )
    )

    assert manager.update_calls == [("kb", "folder-1", [str(source_path)])]


def test_empty_completed_folder_task_advances_sync_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = _FolderManager(tmp_path)
    _patch_manager(monkeypatch, manager)
    source_path = tmp_path / "notes" / "note.md"

    class _EmptyAdder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def add_documents(self, _paths, **_kwargs):
            return []

        def update_metadata(self, _count) -> None:
            raise AssertionError("empty tasks do not need metadata updates")

    monkeypatch.setattr(knowledge_router_module, "DocumentAdder", _EmptyAdder)

    asyncio.run(
        knowledge_router_module.run_upload_processing_task(
            kb_name="kb",
            base_dir=str(tmp_path),
            uploaded_file_paths=[str(source_path)],
            task_id="folder-empty-test",
            rag_provider="llamaindex",
            folder_id="folder-1",
            folder_root=str(tmp_path / "notes"),
        )
    )

    assert manager.update_calls == [("kb", "folder-1", [str(source_path)])]


def test_failed_folder_task_does_not_advance_sync_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = _FolderManager(tmp_path)
    manager.folder["last_sync"] = "previous-success"
    _patch_manager(monkeypatch, manager)
    staged_path = tmp_path / "kb" / "raw" / "note.md"

    class _FailingAdder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def add_documents(self, _paths, **_kwargs):
            return [staged_path]

        async def process_new_documents(self, _staged):
            return SimpleNamespace(
                processed_files=[],
                processed_count=0,
                has_failures=True,
                failed_count=1,
                failure_summary=lambda: "note.md: indexing failed",
                failures=[SimpleNamespace(file_path=staged_path, error="indexing failed")],
            )

        def update_metadata(self, _count) -> None:
            raise AssertionError("failed tasks must not update metadata")

    monkeypatch.setattr(knowledge_router_module, "DocumentAdder", _FailingAdder)

    asyncio.run(
        knowledge_router_module.run_upload_processing_task(
            kb_name="kb",
            base_dir=str(tmp_path),
            uploaded_file_paths=[str(tmp_path / "notes" / "note.md")],
            task_id="folder-failure-test",
            rag_provider="llamaindex",
            folder_id="folder-1",
            folder_root=str(tmp_path / "notes"),
        )
    )

    assert manager.update_calls == []
    assert manager.folder["last_sync"] == "previous-success"
