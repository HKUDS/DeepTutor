from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.rag.index_versioning import resolve_storage_dir_for_read
import deeptutor.services.rag.service as rag_service_module
from deeptutor.services.web_source import index_rebuild


def _version(kb_dir: Path, name: str, *, published: bool = True) -> Path:
    path = kb_dir / name
    path.mkdir(parents=True)
    (path / "docstore.json").write_text("{}", encoding="utf-8")
    (path / "meta.json").write_text(
        json.dumps({"version": name, "signature": "sig", "published": published}),
        encoding="utf-8",
    )
    return path


@pytest.mark.asyncio
async def test_rebuild_publishes_candidate_only_after_validation(
    monkeypatch, tmp_path: Path
) -> None:
    base_dir = tmp_path / "kbs"
    kb_dir = base_dir / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "guide.md").write_text("# Hermes Agent Guide\nUse Hermes.", encoding="utf-8")
    old = _version(kb_dir, "version-1")

    class FakeRAGService:
        def __init__(self, **kwargs):
            pass

        async def initialize(self, **kwargs):
            assert kwargs["published"] is False
            candidate = _version(kb_dir, "version-2", published=False)
            (candidate / "index_store.json").write_text("{}", encoding="utf-8")
            return True

    async def fake_validate(*args, **kwargs):
        return None

    monkeypatch.setattr(rag_service_module, "RAGService", FakeRAGService)
    monkeypatch.setattr(index_rebuild, "validate_candidate_index", fake_validate)

    assert resolve_storage_dir_for_read(kb_dir, None) == old
    assert await index_rebuild.rebuild_index_async("kb", str(base_dir), raw_dir) == 1

    assert resolve_storage_dir_for_read(kb_dir, None) == kb_dir / "version-2"
    meta = json.loads((kb_dir / "version-2" / "meta.json").read_text(encoding="utf-8"))
    assert meta["published"] is True
    assert meta["previous_version"] == "version-1"
    assert meta["validation_queries"]


@pytest.mark.asyncio
async def test_failed_candidate_is_quarantined_and_old_version_stays_active(
    monkeypatch, tmp_path: Path
) -> None:
    base_dir = tmp_path / "kbs"
    kb_dir = base_dir / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "guide.md").write_text("# Guide\nBroken candidate.", encoding="utf-8")
    old = _version(kb_dir, "version-1")

    class FakeRAGService:
        def __init__(self, **kwargs):
            pass

        async def initialize(self, **kwargs):
            candidate = _version(kb_dir, "version-2", published=False)
            (candidate / "index_store.json").write_text("{}", encoding="utf-8")
            return True

    async def fake_validate(*args, **kwargs):
        raise RuntimeError("empty retrieval")

    monkeypatch.setattr(rag_service_module, "RAGService", FakeRAGService)
    monkeypatch.setattr(index_rebuild, "validate_candidate_index", fake_validate)

    with pytest.raises(RuntimeError, match="empty retrieval"):
        await index_rebuild.rebuild_index_async("kb", str(base_dir), raw_dir)

    assert resolve_storage_dir_for_read(kb_dir, None) == old
    assert (kb_dir / "failed-version-2").is_dir()
    assert not (kb_dir / "version-2").exists()
    metadata = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["needs_reindex"] is True
    assert "empty retrieval" in metadata["last_index_error"]
