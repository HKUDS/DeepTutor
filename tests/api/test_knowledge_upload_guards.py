"""Contract tests for the KB upload/delete route guards.

``deeptutor/api/routers/knowledge.py`` is the data-integrity entry point for
knowledge bases; the happy paths were covered but the guard rails were not.
Three contracts are locked here, matching the coverage-gap evidence card:

1. a rejected upload batch fails with 4xx and leaves nothing behind — no
   staged files under ``raw/``, no queued task, no status flip;
2. task IDs are idempotent per logical task key (a retried dispatch reuses
   its ID) while two accepted uploads never share one;
3. deleting a raw document (or a whole KB) keeps the file listing, the
   indexed-hash metadata and the disk consistent.

No product code is changed by this file.
"""

from __future__ import annotations

import importlib
import io
import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient

from deeptutor.api.utils.task_id_manager import TaskIDManager
from deeptutor.utils.document_validator import DocumentValidator

try:
    knowledge_router_module = importlib.import_module("deeptutor.api.routers.knowledge")
    router = knowledge_router_module.router
except Exception:  # pragma: no cover - optional heavy imports in lightweight envs
    knowledge_router_module = None
    router = None

pytestmark = pytest.mark.skipif(
    router is None, reason="deeptutor.api.routers.knowledge could not be imported"
)


@pytest.fixture(autouse=True)
def _disable_pocketbase(monkeypatch):
    monkeypatch.setattr("deeptutor.services.pocketbase_client.is_pocketbase_enabled", lambda: False)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _real_manager(monkeypatch, tmp_path: Path):
    """A real ``KnowledgeBaseManager`` on a throwaway base dir.

    The delete/listing contracts below are about actual disk and config
    consistency, so the real manager is used instead of a fake.
    """
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    return manager


def _seed_kb(
    manager,
    name: str = "kb",
    *,
    files: dict[str, str] | None = None,
    file_hashes: dict[str, str] | None = None,
) -> Path:
    """Create a ready llamaindex KB with raw files and indexed hashes."""
    kb_dir = manager.base_dir / name
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for rel_name, content in (files or {}).items():
        target = raw_dir / rel_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    manager.config.setdefault("knowledge_bases", {})[name] = {
        "path": name,
        "rag_provider": "llamaindex",
        "status": "ready",
    }
    manager._save_config()

    metadata: dict = {"rag_provider": "llamaindex", "needs_reindex": False}
    if file_hashes is not None:
        metadata["file_hashes"] = dict(file_hashes)
    (kb_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return kb_dir


def _upload(filename: str, payload: bytes) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (filename, payload, "application/octet-stream"))]


def _staged_files(raw_dir: Path) -> list[Path]:
    """Files left under ``raw/`` after a request (empty raw dir is fine)."""
    if not raw_dir.exists():
        return []
    return [path for path in raw_dir.rglob("*") if path.is_file()]


class _DispatchRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append(kwargs)
        return None


def _install_dispatch_recorder(monkeypatch) -> _DispatchRecorder:
    recorder = _DispatchRecorder()
    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", recorder)
    return recorder


# ---------------------------------------------------------------------------
# 1. Rejected upload batches leave nothing behind
# ---------------------------------------------------------------------------


def test_upload_rejects_unsupported_extension_without_side_effects(
    monkeypatch, tmp_path: Path
) -> None:
    manager = _real_manager(monkeypatch, tmp_path)
    _seed_kb(manager, files={})
    recorder = _install_dispatch_recorder(monkeypatch)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload",
            files=_upload("payload.unsupported", b"binary"),
        )

    assert response.status_code == 400
    assert "unsupported file type" in response.json()["detail"].lower()
    # Nothing staged on disk, no task dispatched, no status flip.
    assert _staged_files(manager.base_dir / "kb" / "raw") == []
    assert recorder.calls == []
    entry = json.loads((manager.base_dir / "kb_config.json").read_text(encoding="utf-8"))[
        "knowledge_bases"
    ]["kb"]
    assert entry["status"] == "ready"
    assert not entry.get("progress")


def test_upload_rejects_oversize_file_without_side_effects(monkeypatch, tmp_path: Path) -> None:
    manager = _real_manager(monkeypatch, tmp_path)
    _seed_kb(manager, files={})
    recorder = _install_dispatch_recorder(monkeypatch)
    monkeypatch.setattr(DocumentValidator, "MAX_FILE_SIZE", 32)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload", files=_upload("big.txt", b"x" * 100)
        )

    assert response.status_code == 400
    assert "too large" in response.json()["detail"].lower()
    assert _staged_files(manager.base_dir / "kb" / "raw") == []
    assert recorder.calls == []
    entry = json.loads((manager.base_dir / "kb_config.json").read_text(encoding="utf-8"))[
        "knowledge_bases"
    ]["kb"]
    assert entry["status"] == "ready"


def test_upload_rejects_duplicate_names_within_one_batch(monkeypatch, tmp_path: Path) -> None:
    manager = _real_manager(monkeypatch, tmp_path)
    _seed_kb(manager, files={})
    recorder = _install_dispatch_recorder(monkeypatch)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload",
            files=[*_upload("notes.txt", b"one"), *_upload("notes.txt", b"two")],
        )

    assert response.status_code == 400
    assert "duplicate filename" in response.json()["detail"].lower()
    assert _staged_files(manager.base_dir / "kb" / "raw") == []
    assert recorder.calls == []


def test_upload_rejects_provider_mismatch_with_kb(monkeypatch, tmp_path: Path) -> None:
    manager = _real_manager(monkeypatch, tmp_path)
    _seed_kb(manager, files={})
    recorder = _install_dispatch_recorder(monkeypatch)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload",
            data={"rag_provider": "pageindex"},
            files=_upload("demo.txt", b"hello"),
        )

    assert response.status_code == 400
    assert "does not match kb provider" in response.json()["detail"].lower()
    assert recorder.calls == []


def test_rejected_batch_member_rolls_back_earlier_writes(tmp_path: Path) -> None:
    """A failure on any member unlinks the files already written (unit level).

    The route-level batch pre-validation catches most of these earlier; this
    exercises the rollback inside ``_save_uploaded_files`` itself.
    """
    raw = tmp_path / "raw"
    raw.mkdir()
    batch = [
        UploadFile(filename="ok.txt", file=io.BytesIO(b"hello")),
        UploadFile(filename="bad.exe", file=io.BytesIO(b"binary")),
    ]

    with pytest.raises(knowledge_router_module.HTTPException) as exc_info:
        knowledge_router_module._save_uploaded_files(batch, raw, allowed_extensions={".txt"})

    assert exc_info.value.status_code == 400
    assert not any(raw.rglob("*"))  # ok.txt was written, then rolled back


def test_mid_write_size_limit_removes_the_partial_file(monkeypatch, tmp_path: Path) -> None:
    """A stream whose size cannot be probed is bounded while it is written."""

    class _SizeOpaqueStream(io.BytesIO):
        def tell(self):  # size probe fails -> validation skips the size check
            raise OSError("position unavailable")

    monkeypatch.setattr(DocumentValidator, "MAX_FILE_SIZE", 16)
    raw = tmp_path / "raw"
    raw.mkdir()
    upload = UploadFile(filename="huge.txt", file=_SizeOpaqueStream(b"x" * 100))

    with pytest.raises(knowledge_router_module.HTTPException) as exc_info:
        knowledge_router_module._save_uploaded_files([upload], raw, allowed_extensions={".txt"})

    assert exc_info.value.status_code == 400
    assert "exceeds maximum size" in exc_info.value.detail.lower()
    assert not any(raw.rglob("*"))  # the partial file was unlinked, not staged


# ---------------------------------------------------------------------------
# 2. Task ID idempotency
# ---------------------------------------------------------------------------


def _fresh_task_manager():
    manager = TaskIDManager()
    manager._task_ids = {}
    manager._task_metadata = {}
    return manager


def test_duplicate_task_key_maps_to_the_same_task_id() -> None:
    manager = _fresh_task_manager()

    first = manager.generate_task_id("kb_upload", "kb-upload-key")
    second = manager.generate_task_id("kb_upload", "kb-upload-key")

    assert first == second  # a retried dispatch reuses its task
    assert list(manager._task_metadata) == [first]
    assert manager.get_task_metadata(first)["status"] == "running"

    other = manager.generate_task_id("kb_upload", "kb-upload-other")
    assert other != first


def test_build_unique_task_id_never_collides_for_distinct_uploads(
    monkeypatch,
) -> None:
    fresh = _fresh_task_manager()
    monkeypatch.setattr(TaskIDManager, "get_instance", classmethod(lambda cls: fresh))

    first = knowledge_router_module._build_unique_task_id("kb_upload", "kb-a")
    second = knowledge_router_module._build_unique_task_id("kb_upload", "kb-a")

    assert first != second  # two accepted uploads never share a task
    assert first.startswith("kb_upload_") and second.startswith("kb_upload_")
    assert set(fresh._task_metadata) == {first, second}


def test_two_uploads_dispatch_two_distinct_tasks(monkeypatch, tmp_path: Path) -> None:
    manager = _real_manager(monkeypatch, tmp_path)
    _seed_kb(manager, files={})
    recorder = _install_dispatch_recorder(monkeypatch)
    fresh = _fresh_task_manager()
    monkeypatch.setattr(TaskIDManager, "get_instance", classmethod(lambda cls: fresh))

    with TestClient(_build_app()) as client:
        first = client.post("/api/knowledge-bases/kb/upload", files=_upload("one.txt", b"one"))
        second = client.post("/api/knowledge-bases/kb/upload", files=_upload("two.txt", b"two"))

    assert first.status_code == 200
    assert second.status_code == 200
    first_task = first.json()["task_id"]
    second_task = second.json()["task_id"]
    assert first_task != second_task
    assert first_task.startswith("kb_upload_")

    # Both uploads queued exactly one background task, each with its own ID.
    assert len(recorder.calls) == 2
    assert {call["task_id"] for call in recorder.calls} == {first_task, second_task}

    # The queued status points at the task that was actually dispatched.
    entry = json.loads((manager.base_dir / "kb_config.json").read_text(encoding="utf-8"))[
        "knowledge_bases"
    ]["kb"]
    assert entry["status"] == "processing"
    assert entry["progress"]["task_id"] == second_task


# ---------------------------------------------------------------------------
# 3. Delete keeps listing, metadata and disk consistent
# ---------------------------------------------------------------------------


def test_delete_raw_file_updates_listing_metadata_and_disk(monkeypatch, tmp_path: Path) -> None:
    manager = _real_manager(monkeypatch, tmp_path)
    kb_dir = _seed_kb(
        manager,
        files={"notes.txt": "hello", "docs/paper.md": "# paper"},
        file_hashes={"notes.txt": "h-notes", "docs/paper.md": "h-paper"},
    )

    with TestClient(_build_app()) as client:
        listing_before = client.get("/api/knowledge-bases/kb/files").json()["files"]
        removal = client.delete("/api/knowledge-bases/kb/files/notes.txt")
        listing_after = client.get("/api/knowledge-bases/kb/files").json()["files"]
        repeat = client.delete("/api/knowledge-bases/kb/files/notes.txt")

    assert {entry["name"] for entry in listing_before} == {
        "notes.txt",
        "docs",
        "docs/paper.md",
    }
    assert removal.status_code == 200
    assert removal.json() == {"status": "ok", "path": "notes.txt", "was_indexed": True}

    # Listing no longer shows the file…
    assert {entry["name"] for entry in listing_after} == {"docs", "docs/paper.md"}
    # …the disk copy is gone while siblings survive…
    assert not (kb_dir / "raw" / "notes.txt").exists()
    assert (kb_dir / "raw" / "docs" / "paper.md").read_text(encoding="utf-8") == "# paper"
    # …and the indexed-hash record was dropped with it.
    metadata = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["file_hashes"] == {"docs/paper.md": "h-paper"}

    assert repeat.status_code == 404
    assert repeat.json()["detail"] == "File not found"


def test_delete_whole_kb_updates_listing_and_disk(monkeypatch, tmp_path: Path) -> None:
    manager = _real_manager(monkeypatch, tmp_path)
    kb_dir = _seed_kb(manager, files={"notes.txt": "hello"})
    second_dir = _seed_kb(manager, "kb-two", files={"extra.md": "x"})

    with TestClient(_build_app()) as client:
        names_before = {item["name"] for item in client.get("/api/knowledge-bases").json()}
        path_route = client.delete("/api/knowledge-bases/kb")
        repeat = client.delete("/api/knowledge-bases/kb")
        body_route = client.post("/api/knowledge-bases/delete", json={"name": "kb-two"})
        listing = client.get("/api/knowledge-bases").json()

    assert names_before == {"kb", "kb-two"}
    assert path_route.status_code == 200
    assert path_route.json()["message"] == "Knowledge base 'kb' deleted successfully"
    assert repeat.status_code == 404
    assert body_route.status_code == 200
    assert body_route.json()["message"] == "Knowledge base 'kb-two' deleted successfully"

    # Both the config listing and the directories on disk are empty afterwards.
    assert listing == []
    assert not kb_dir.exists()
    assert not second_dir.exists()
    assert (
        json.loads((manager.base_dir / "kb_config.json").read_text(encoding="utf-8"))[
            "knowledge_bases"
        ]
        == {}
    )
