"""Router-level tests for the per-KB write coordinator (KB-01).

Demonstrates the frozen acceptance contract v1 through the knowledge router:
concurrent mutations on the same KB return a retryable ``kb_busy``, expired
leases are reconciled before new work, and connected KBs stay read-only (no
coordinator write record is created for them).
"""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

from deeptutor.knowledge.write_coordinator import KbWriteCoordinator

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
    knowledge_router_module = importlib.import_module("deeptutor.api.routers.knowledge")
    router = knowledge_router_module.router
else:  # pragma: no cover - guarded by pytestmark
    knowledge_router_module = None
    router = None


def _build_app() -> FastAPI:
    if FastAPI is None or router is None:  # pragma: no cover - guarded
        raise RuntimeError("fastapi is not installed")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/knowledge")
    return app


class _FakeKBManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.base_dir / "kb_config.json"
        self.config: dict = {"knowledge_bases": {}}

    def _load_config(self) -> dict:
        return self.config

    def _save_config(self) -> None:
        pass

    def list_knowledge_bases(self) -> list[str]:
        return sorted(self.config.get("knowledge_bases", {}).keys())

    def get_kb_entry(self, name: str) -> dict | None:
        entry = self.config.get("knowledge_bases", {}).get(name)
        return dict(entry) if isinstance(entry, dict) else None

    def update_kb_status(self, name: str, status: str, progress: dict | None = None) -> None:
        entry = self.config.setdefault("knowledge_bases", {}).setdefault(name, {"path": name})
        entry["status"] = status
        entry["progress"] = progress or {}

    def get_default(self) -> str | None:
        names = self.list_knowledge_bases()
        return names[0] if names else None

    def get_knowledge_base_path(self, name: str) -> Path:
        kb_dir = self.base_dir / name
        kb_dir.mkdir(parents=True, exist_ok=True)
        return kb_dir


def _ready_kb_manager(tmp_path: Path, name: str = "kb") -> "_FakeKBManager":
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"][name] = {
        "path": name,
        "rag_provider": "llamaindex",
        "needs_reindex": False,
        "status": "ready",
    }
    (manager.base_dir / name / "raw").mkdir(parents=True, exist_ok=True)
    return manager


def _upload_payload() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", ("demo.txt", b"hello", "text/plain"))]


def _ledger_ops(manager: _FakeKBManager) -> dict:
    ledger = manager.base_dir / "kb_write_operations.json"
    if not ledger.exists():
        return {}
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    return payload.get("operations", {})


def _patch_upload_task_noop(monkeypatch) -> None:
    async def _noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop)


def _patch_signature(monkeypatch, signature_hash: str = "sig") -> None:
    class _Signature:
        def hash(self) -> str:
            return signature_hash

    embedding_signature = importlib.import_module("deeptutor.services.rag.embedding_signature")
    index_versioning = importlib.import_module("deeptutor.services.rag.index_versioning")
    monkeypatch.setattr(
        embedding_signature, "signature_from_embedding_config", lambda: _Signature()
    )
    monkeypatch.setattr(index_versioning, "find_matching_version", lambda *_a, **_k: None)


# ---------------------------------------------------------------------------
# One mutation at a time
# ---------------------------------------------------------------------------


def test_upload_then_second_upload_returns_kb_busy(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)
    _patch_upload_task_noop(monkeypatch)

    with TestClient(_build_app()) as client:
        first = client.post("/api/v1/knowledge/kb/upload", files=_upload_payload())
        assert first.status_code == 200

        second = client.post("/api/v1/knowledge/kb/upload", files=_upload_payload())

    assert second.status_code == 409
    assert "kb_busy" in second.json()["detail"]


def test_upload_then_delete_file_returns_kb_busy(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)
    _patch_upload_task_noop(monkeypatch)

    with TestClient(_build_app()) as client:
        first = client.post("/api/v1/knowledge/kb/upload", files=_upload_payload())
        assert first.status_code == 200
        # The uploaded file exists under raw/; deleting it is a coordinated mutation.
        deleted = client.delete("/api/v1/knowledge/kb/files/demo.txt")

    assert deleted.status_code == 409
    assert "kb_busy" in deleted.json()["detail"]


def test_upload_then_reindex_returns_kb_busy(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)
    _patch_upload_task_noop(monkeypatch)
    _patch_signature(monkeypatch)

    async def _noop_reindex(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(knowledge_router_module, "run_reindex_task", _noop_reindex)

    with TestClient(_build_app()) as client:
        first = client.post("/api/v1/knowledge/kb/upload", files=_upload_payload())
        assert first.status_code == 200

        reindex = client.post("/api/v1/knowledge/kb/reindex")

    assert reindex.status_code == 409
    assert "kb_busy" in reindex.json()["detail"]


# ---------------------------------------------------------------------------
# Lease expiry reconciles before new work
# ---------------------------------------------------------------------------


def test_expired_lease_reconciled_before_new_upload(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)
    _patch_upload_task_noop(monkeypatch)

    # Simulate a crashed upload: a running operation whose lease expired long ago.
    ledger = manager.base_dir / "kb_write_operations.json"
    ledger.write_text(
        json.dumps(
            {
                "version": 1,
                "operations": {
                    "kb": {
                        "id": "old-upload",
                        "kb_name": "kb",
                        "operation_type": "upload",
                        "status": "running",
                        "lease_owner": "crashed-worker",
                        "lease_expires_at": "2020-01-01T00:00:00Z",
                        "created_at": "2020-01-01T00:00:00Z",
                        "updated_at": "2020-01-01T00:00:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/kb/upload", files=_upload_payload())

    assert response.status_code == 200
    op = _ledger_ops(manager)["kb"]
    assert op["status"] == "running"
    assert op["reconciles_operation_id"] == "old-upload"


def test_crash_reconcile_preserves_raw_and_hash_via_router(monkeypatch, tmp_path: Path) -> None:
    """A crashed upload leaves a staged raw file + stale hash; the next upload
    reconciles (stale hash pruned, raw file preserved) and proceeds."""
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)
    _patch_upload_task_noop(monkeypatch)

    kb_dir = manager.base_dir / "kb"
    raw_dir = kb_dir / "raw"
    staged = raw_dir / "staged.txt"
    staged.write_text("content", encoding="utf-8")
    (kb_dir / "metadata.json").write_text(
        json.dumps({"file_hashes": {"staged.txt": "abc", "missing.pdf": "dead"}}),
        encoding="utf-8",
    )
    ledger = manager.base_dir / "kb_write_operations.json"
    ledger.write_text(
        json.dumps(
            {
                "version": 1,
                "operations": {
                    "kb": {
                        "id": "crashed",
                        "kb_name": "kb",
                        "operation_type": "upload",
                        "status": "running",
                        "lease_owner": "crashed-worker",
                        "lease_expires_at": "2020-01-01T00:00:00Z",
                        "created_at": "2020-01-01T00:00:00Z",
                        "updated_at": "2020-01-01T00:00:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/kb/upload", files=_upload_payload())

    assert response.status_code == 200
    # The stale hash was pruned during reconciliation; the live one is kept.
    metadata = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["file_hashes"] == {"staged.txt": "abc"}
    # The staged raw file is preserved.
    assert staged.exists()


# ---------------------------------------------------------------------------
# Connected KBs stay read-only and create no coordinator records
# ---------------------------------------------------------------------------


def _connected_kb_manager(tmp_path: Path) -> "_FakeKBManager":
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["obsidian-kb"] = {
        "path": "obsidian-kb",
        "type": "obsidian",
        "vault_path": str(tmp_path / "vault"),
        "status": "ready",
    }
    return manager


def test_connected_kb_upload_is_read_only(monkeypatch, tmp_path: Path) -> None:
    manager = _connected_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/obsidian-kb/upload", files=_upload_payload())

    assert response.status_code == 409
    assert "read-only" in response.json()["detail"].lower()
    # No coordinator write record is created for a connected KB.
    assert _ledger_ops(manager) == {}


def test_connected_kb_reindex_is_read_only(monkeypatch, tmp_path: Path) -> None:
    manager = _connected_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/obsidian-kb/reindex")

    assert response.status_code == 409
    assert "read-only" in response.json()["detail"].lower()
    assert _ledger_ops(manager) == {}


def test_connected_kb_delete_file_is_read_only(monkeypatch, tmp_path: Path) -> None:
    manager = _connected_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    with TestClient(_build_app()) as client:
        response = client.delete("/api/v1/knowledge/obsidian-kb/files/anything.txt")

    assert response.status_code == 409
    assert "read-only" in response.json()["detail"].lower()
    assert _ledger_ops(manager) == {}


# ---------------------------------------------------------------------------
# Successful coordinated mutations write terminal ledger records
# ---------------------------------------------------------------------------


def test_delete_file_acquires_and_completes(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    raw = manager.base_dir / "kb" / "raw"
    (raw / "demo.txt").write_text("hi", encoding="utf-8")
    (manager.base_dir / "kb" / "metadata.json").write_text(
        json.dumps({"file_hashes": {"demo.txt": "abc"}}), encoding="utf-8"
    )
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    with TestClient(_build_app()) as client:
        response = client.delete("/api/v1/knowledge/kb/files/demo.txt")

    assert response.status_code == 200
    assert not (raw / "demo.txt").exists()
    op = _ledger_ops(manager)["kb"]
    assert op["operation_type"] == "delete"
    assert op["subject_id"] == "demo.txt"
    assert op["status"] == "succeeded"


def test_reindex_acquires_running_op(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)
    _patch_signature(monkeypatch, signature_hash="sig-target")

    async def _noop_reindex(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(knowledge_router_module, "run_reindex_task", _noop_reindex)

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/kb/reindex")

    assert response.status_code == 200
    op = _ledger_ops(manager)["kb"]
    assert op["operation_type"] == "reindex"
    assert op["input_snapshot_hash"] == "sig-target"
    assert op["status"] == "running"


# ---------------------------------------------------------------------------
# Background heartbeat integration (blocker #3)
# ---------------------------------------------------------------------------


def _write_ready_llamaindex_version(kb_dir: Path) -> None:
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"provider": "llamaindex", "signature": "sig", "version": "version-1"}),
        encoding="utf-8",
    )


def test_upload_task_initial_renew_reports_ownership_loss(monkeypatch, tmp_path: Path) -> None:
    """A stale writer whose lease was already taken over must stop immediately.

    The initial renew reports ownership loss; the task marks itself failed and
    does NOT write a new ledger record under the new holder.
    """
    manager = _ready_kb_manager(tmp_path)
    base_dir = manager.base_dir
    coordinator = KbWriteCoordinator(base_dir=base_dir)
    op = coordinator.acquire("kb", "upload", owner="holder-a")
    # Simulate a crash + takeover: the ledger is gone entirely, so the old
    # operation id can no longer be renewed.
    (base_dir / "kb_write_operations.json").unlink()

    asyncio.run(
        knowledge_router_module.run_upload_processing_task(
            kb_name="kb",
            base_dir=str(base_dir),
            uploaded_file_paths=[],
            task_id="stale-task",
            rag_provider="llamaindex",
            operation_id=op.id,
            lease_owner="holder-a",
        )
    )

    # The stale task stopped without re-creating a ledger record for the new
    # holder to clobber.
    assert not (base_dir / "kb_write_operations.json").exists()


def test_upload_task_renews_and_completes_its_own_lease(monkeypatch, tmp_path: Path) -> None:
    """A healthy writer renews through the heartbeat and closes its own lease."""
    manager = _ready_kb_manager(tmp_path)
    base_dir = manager.base_dir
    _write_ready_llamaindex_version(base_dir / "kb")
    source = tmp_path / "ok.txt"
    source.write_text("ok", encoding="utf-8")

    coordinator = KbWriteCoordinator(base_dir=base_dir)
    op = coordinator.acquire("kb", "upload", owner="holder-a")
    op_id = op.id

    class _OkRagService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def add_documents(self, *_args, **_kwargs) -> bool:
            return True

    monkeypatch.setattr("deeptutor.knowledge.add_documents.RAGService", _OkRagService)

    asyncio.run(
        knowledge_router_module.run_upload_processing_task(
            kb_name="kb",
            base_dir=str(base_dir),
            uploaded_file_paths=[str(source)],
            task_id="ok-task",
            rag_provider="llamaindex",
            operation_id=op_id,
            lease_owner="holder-a",
        )
    )

    ledger = _ledger_ops(manager)["kb"]
    assert ledger["id"] == op_id
    assert ledger["status"] == "succeeded"
    assert ledger["index_task_id"] == "ok-task"
    # The raw file staged by the writer is present and indexed.
    assert (base_dir / "kb" / "raw" / "ok.txt").exists()


# ---------------------------------------------------------------------------
# Fail-closed final write checkpoints (KB-01 P0 hardening)
# ---------------------------------------------------------------------------


def test_upload_returns_503_when_ledger_corrupt(monkeypatch, tmp_path: Path) -> None:
    """A corrupt ledger never starts a second writer: the route fails closed."""
    manager = _ready_kb_manager(tmp_path)
    (manager.base_dir / "kb_write_operations.json").write_text("{corrupt", encoding="utf-8")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    with TestClient(_build_app()) as client:
        response = client.post("/api/v1/knowledge/kb/upload", files=_upload_payload())

    assert response.status_code == 503
    assert "write coordination state is unavailable" in response.json()["detail"]
    # The corrupt ledger is not overwritten.
    assert (manager.base_dir / "kb_write_operations.json").read_text(encoding="utf-8") == "{corrupt"


def test_upload_task_fails_closed_when_ownership_lost_before_final_writes(
    monkeypatch, tmp_path: Path
) -> None:
    """A newer holder taking over right before the completion status writes must
    stop the stale writer before it marks the task / KB successful."""
    import uuid as _uuid

    from deeptutor.knowledge.add_documents import DocumentAdder
    from deeptutor.knowledge.write_coordinator import KbWriteOperation

    manager = _ready_kb_manager(tmp_path)
    base_dir = manager.base_dir
    _write_ready_llamaindex_version(base_dir / "kb")
    source = tmp_path / "ok.txt"
    source.write_text("ok", encoding="utf-8")

    coordinator = KbWriteCoordinator(base_dir=base_dir)
    op = coordinator.acquire("kb", "upload", owner="holder-a")
    op_id = op.id

    task_manager = knowledge_router_module.TaskIDManager.get_instance()
    task_id = task_manager.generate_task_id("kb_upload", f"stale-final-write-{_uuid.uuid4().hex}")

    class _OkRagService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def add_documents(self, *_args, **_kwargs) -> bool:
            return True

    monkeypatch.setattr("deeptutor.knowledge.add_documents.RAGService", _OkRagService)

    real_update_metadata = DocumentAdder.update_metadata

    def _takeover_update_metadata(self, added_count: int) -> None:
        # A newer holder replaced the operation while the stale writer was
        # between the metadata write and the completion status writes.
        new_op = KbWriteOperation.from_dict(
            {
                "id": "new-holder-op",
                "kb_name": "kb",
                "operation_type": "reindex",
                "status": "running",
                "lease_owner": "holder-b",
                "lease_expires_at": "2099-01-01T00:00:00Z",
                "created_at": "2026-08-04T12:00:00Z",
                "updated_at": "2026-08-04T12:00:00Z",
            }
        )
        coordinator._save({"kb": new_op})
        real_update_metadata(self, added_count)

    monkeypatch.setattr(DocumentAdder, "update_metadata", _takeover_update_metadata)

    asyncio.run(
        knowledge_router_module.run_upload_processing_task(
            kb_name="kb",
            base_dir=str(base_dir),
            uploaded_file_paths=[str(source)],
            task_id=task_id,
            rag_provider="llamaindex",
            operation_id=op_id,
            lease_owner="holder-a",
        )
    )

    # The stale writer did NOT close its own operation as succeeded — the new
    # holder's op is preserved intact in the ledger.
    ledger = _ledger_ops(manager)["kb"]
    assert ledger["id"] == "new-holder-op"
    assert ledger["status"] == "running"
    # The task was marked failed (ownership lost), not completed.
    metadata = task_manager.get_task_metadata(task_id)
    assert metadata["status"] == "error"
    assert metadata.get("error") == "kb_ownership_lost"


def test_reindex_task_fails_closed_when_ownership_lost_before_status_write(
    monkeypatch, tmp_path: Path
) -> None:
    """Ownership taken over mid-reindex stops the stale task before it writes
    the metadata / status / config completion state."""
    import uuid as _uuid

    from deeptutor.knowledge.write_coordinator import KbWriteOperation

    manager = _ready_kb_manager(tmp_path)
    base_dir = manager.base_dir
    (base_dir / "kb" / "raw" / "doc.txt").write_text("hello", encoding="utf-8")

    coordinator = KbWriteCoordinator(base_dir=base_dir)
    op = coordinator.acquire("kb", "reindex", owner="holder-a", input_snapshot_hash="sig")
    op_id = op.id

    task_manager = knowledge_router_module.TaskIDManager.get_instance()
    task_id = task_manager.generate_task_id("kb_reindex", f"stale-reindex-{_uuid.uuid4().hex}")

    class _TakeoverRagService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def initialize(self, **_kwargs) -> bool:
            # A newer holder replaced the operation mid-run, before the
            # metadata / status / config completion writes.
            new_op = KbWriteOperation.from_dict(
                {
                    "id": "new-holder-op",
                    "kb_name": "kb",
                    "operation_type": "upload",
                    "status": "running",
                    "lease_owner": "holder-b",
                    "lease_expires_at": "2099-01-01T00:00:00Z",
                    "created_at": "2026-08-04T12:00:00Z",
                    "updated_at": "2026-08-04T12:00:00Z",
                }
            )
            coordinator._save({"kb": new_op})
            return True

    monkeypatch.setattr("deeptutor.services.rag.service.RAGService", _TakeoverRagService)

    asyncio.run(
        knowledge_router_module.run_reindex_task(
            kb_name="kb",
            base_dir=str(base_dir),
            task_id=task_id,
            signature_hash="sig",
            operation_id=op_id,
            lease_owner="holder-a",
        )
    )

    ledger = _ledger_ops(manager)["kb"]
    assert ledger["id"] == "new-holder-op"
    assert ledger["status"] == "running"
    metadata = task_manager.get_task_metadata(task_id)
    assert metadata["status"] == "error"
    assert metadata.get("error") == "kb_ownership_lost"
