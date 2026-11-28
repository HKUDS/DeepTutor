"""Deleting KB content must reclaim its content-addressed parse cache.

The parse cache (``parse_cache/<hash[:2]>/<hash>/<signature>/``) is derived from
raw documents but used to outlive them: deleting a raw file or a whole
knowledge base left every parsed artifact on disk. These tests pin the
reclamation wired into both delete paths — scoped to the deleted documents'
content hashes, best-effort, and never fatal to the user's delete.

The cache root is derived from the knowledge-base directory (a sibling of
``knowledge_bases/``) rather than from the ambient path service: requests served
from the knowledge-base library run in the account workspace scope, so the
ambient root would name a different workspace than the KB being deleted.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

from deeptutor.knowledge.add_documents import remove_raw_document
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.parsing import cache


def _kb_root(tmp_path: Path) -> Path:
    """Knowledge-base root as ``path_service`` lays it out inside a workspace."""
    return tmp_path / "ws" / ".deeptutor" / "data" / "knowledge_bases"


def _cache_root(tmp_path: Path) -> Path:
    return tmp_path / "ws" / ".deeptutor" / "data" / "parse_cache"


def _seed_parse_cache(
    cache_root: Path, source: Path, *, signatures: tuple[str, ...] = ("sig",)
) -> Path:
    """Create ready-looking cache signatures for ``source``; return its shard."""
    source_hash = cache.source_hash_from_path(source)
    for signature in signatures:
        entry = cache.signature_dir(cache_root, source_hash, signature)
        entry.mkdir(parents=True)
        (entry / cache.MANIFEST_FILENAME).write_text(
            json.dumps({"created_at": "2026-01-01T00:00:00Z"}), encoding="utf-8"
        )
        (entry / f"{signature}.md").write_text("# parsed", encoding="utf-8")
    return cache.source_dir(cache_root, source_hash)


def _stage_raw_document(kb_dir: Path, relative: str, payload: bytes) -> Path:
    doc = kb_dir / "raw" / relative
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_bytes(payload)
    return doc


def _create_kb(manager: KnowledgeBaseManager, name: str) -> Path:
    kb_dir = manager.base_dir / name
    (kb_dir / "raw").mkdir(parents=True, exist_ok=True)
    manager.config.setdefault("knowledge_bases", {})[name] = {
        "path": name,
        "description": "",
    }
    manager._save_config()
    return kb_dir


def _fail_reclaim_only_under(cache_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make removing entries under ``cache_root`` raise, as a locked file would."""
    real_rmtree = shutil.rmtree

    def _locked(path, *args, **kwargs):
        if Path(path).is_relative_to(cache_root):
            raise OSError("locked by another process")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(cache.shutil, "rmtree", _locked)


# ---------------------------------------------------------------------------
# Per-document delete
# ---------------------------------------------------------------------------


def test_remove_raw_document_reclaims_only_the_deleted_document(tmp_path: Path) -> None:
    kb_dir = _create_kb(KnowledgeBaseManager(base_dir=str(_kb_root(tmp_path))), "kb")
    deleted = _stage_raw_document(kb_dir, "gone.pdf", b"gone-bytes")
    survivor = _stage_raw_document(kb_dir, "kept.pdf", b"kept-bytes")
    deleted_shard = _seed_parse_cache(_cache_root(tmp_path), deleted, signatures=("sig-a", "sig-b"))
    survivor_shard = _seed_parse_cache(_cache_root(tmp_path), survivor)

    remove_raw_document(kb_dir, deleted)

    assert not deleted.exists()
    assert not deleted_shard.exists(), "every signature for the deleted source is gone"
    assert survivor_shard.is_dir(), "another document's cache entry must survive"
    assert (survivor_shard / "sig" / "sig.md").is_file()


def test_reclaim_is_keyed_by_bytes_not_by_path(tmp_path: Path) -> None:
    """The hash comes from the file content, so a renamed copy hits the same shard."""
    cache_root = _cache_root(tmp_path)
    original = tmp_path / "original.pdf"
    original.write_bytes(b"shared-content")
    renamed = tmp_path / "renamed-copy.pdf"
    renamed.write_bytes(b"shared-content")
    shard = _seed_parse_cache(cache_root, original)

    assert cache.reclaim_sources([renamed], cache_root=cache_root) == 1

    assert not shard.exists()


# ---------------------------------------------------------------------------
# Whole-KB delete
# ---------------------------------------------------------------------------


def test_delete_knowledge_base_reclaims_every_raw_document(tmp_path: Path) -> None:
    cache_root = _cache_root(tmp_path)
    manager = KnowledgeBaseManager(base_dir=str(_kb_root(tmp_path)))
    kb_dir = _create_kb(manager, "doomed")
    top_level = _stage_raw_document(kb_dir, "a.pdf", b"first-doc")
    nested = _stage_raw_document(kb_dir, "papers/2024/b.pdf", b"second-doc")
    shards = [
        _seed_parse_cache(cache_root, top_level),
        _seed_parse_cache(cache_root, nested, signatures=("sig-a", "sig-b")),
    ]
    # A cache entry for a document that is not part of this KB must be untouched.
    outsider = tmp_path / "outside.pdf"
    outsider.write_bytes(b"not-in-this-kb")
    outsider_shard = _seed_parse_cache(cache_root, outsider)

    assert manager.delete_knowledge_base("doomed", confirm=True) is True

    assert not kb_dir.exists()
    for shard in shards:
        assert not shard.exists(), f"{shard} should have been reclaimed"
    assert outsider_shard.is_dir(), "unrelated cache entries must survive"


def test_kb_delete_reclaims_hidden_raw_files(tmp_path: Path) -> None:
    """``rmtree`` deletes dotfiles, so their cache must be reclaimed too."""
    cache_root = _cache_root(tmp_path)
    manager = KnowledgeBaseManager(base_dir=str(_kb_root(tmp_path)))
    kb_dir = _create_kb(manager, "doomed")
    hidden = _stage_raw_document(kb_dir, ".hidden.pdf", b"hidden-bytes")
    shard = _seed_parse_cache(cache_root, hidden)

    assert manager.delete_knowledge_base("doomed", confirm=True) is True

    assert not shard.exists(), "hidden raw file's cache must not outlive the KB"


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privileges on Windows")
def test_kb_delete_does_not_reclaim_a_symlinks_target(tmp_path: Path) -> None:
    """``rmtree`` removes only the link, so the target's cache must stay."""
    cache_root = _cache_root(tmp_path)
    manager = KnowledgeBaseManager(base_dir=str(_kb_root(tmp_path)))
    kb_dir = _create_kb(manager, "doomed")
    external = tmp_path / "external.pdf"
    external.write_bytes(b"external-bytes")
    (kb_dir / "raw" / "link.pdf").symlink_to(external)
    external_shard = _seed_parse_cache(cache_root, external)

    assert manager.delete_knowledge_base("doomed", confirm=True) is True

    assert external.exists(), "the symlink target itself is not deleted"
    assert external_shard.is_dir(), "the target's cache is out of scope and must survive"


def test_kb_delete_without_raw_dir(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(_kb_root(tmp_path)))
    kb_dir = _create_kb(manager, "no-raw")
    shutil.rmtree(kb_dir / "raw")

    assert manager.delete_knowledge_base("no-raw", confirm=True) is True
    assert not kb_dir.exists()


# ---------------------------------------------------------------------------
# The cache root belongs to the KB's workspace, not to the request scope
# ---------------------------------------------------------------------------


def test_kb_delete_ignores_the_ambient_path_service_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Library-view requests run in the account scope; the KB's own cache must win."""
    cache_root = _cache_root(tmp_path)
    manager = KnowledgeBaseManager(base_dir=str(_kb_root(tmp_path)))
    kb_dir = _create_kb(manager, "doomed")
    doc = _stage_raw_document(kb_dir, "a.pdf", b"doc-bytes")
    shard = _seed_parse_cache(cache_root, doc)

    def _ambient_scope_unavailable() -> SimpleNamespace:
        raise RuntimeError("no content workspace scope (library view)")

    monkeypatch.setattr(
        "deeptutor.services.path_service.get_path_service", _ambient_scope_unavailable
    )

    assert manager.delete_knowledge_base("doomed", confirm=True) is True
    assert not shard.exists(), "the KB's own workspace shard must be reclaimed"


def test_single_file_delete_ignores_the_ambient_path_service_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = _cache_root(tmp_path)
    manager = KnowledgeBaseManager(base_dir=str(_kb_root(tmp_path)))
    kb_dir = _create_kb(manager, "kb")
    doc = _stage_raw_document(kb_dir, "a.pdf", b"doc-bytes")
    shard = _seed_parse_cache(cache_root, doc)

    def _ambient_scope_unavailable() -> SimpleNamespace:
        raise RuntimeError("no content workspace scope (library view)")

    monkeypatch.setattr(
        "deeptutor.services.path_service.get_path_service", _ambient_scope_unavailable
    )

    remove_raw_document(kb_dir, doc)

    assert not shard.exists(), "the KB's own workspace shard must be reclaimed"


# ---------------------------------------------------------------------------
# No-op and failure cases
# ---------------------------------------------------------------------------


def test_missing_cache_root_is_a_noop(tmp_path: Path) -> None:
    kb_dir = _create_kb(KnowledgeBaseManager(base_dir=str(_kb_root(tmp_path))), "kb")
    doc = _stage_raw_document(kb_dir, "doc.pdf", b"bytes")

    assert cache.reclaim_sources([doc], cache_root=_cache_root(tmp_path)) == 0

    removal = remove_raw_document(kb_dir, doc)

    assert not doc.exists()
    assert removal.rel_path == "doc.pdf"
    assert not _cache_root(tmp_path).exists(), "reclaiming must not create the cache root"


def test_cache_root_that_is_a_file_is_a_noop(tmp_path: Path) -> None:
    cache_root = _cache_root(tmp_path)
    cache_root.parent.mkdir(parents=True)
    cache_root.write_text("not a directory", encoding="utf-8")
    kb_dir = _create_kb(KnowledgeBaseManager(base_dir=str(_kb_root(tmp_path))), "kb")
    doc = _stage_raw_document(kb_dir, "doc.pdf", b"bytes")

    assert cache.reclaim_sources([doc], cache_root=cache_root) == 0
    remove_raw_document(kb_dir, doc)
    assert not doc.exists()


def test_missing_cache_entry_is_a_noop(tmp_path: Path) -> None:
    cache_root = _cache_root(tmp_path)
    cache_root.mkdir(parents=True)  # root exists, but nothing cached for this document
    kb_dir = _create_kb(KnowledgeBaseManager(base_dir=str(_kb_root(tmp_path))), "kb")
    doc = _stage_raw_document(kb_dir, "doc.pdf", b"bytes")

    remove_raw_document(kb_dir, doc)

    assert not doc.exists()


def test_unhashable_source_does_not_block_the_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    cache_root = _cache_root(tmp_path)
    kb_dir = _create_kb(KnowledgeBaseManager(base_dir=str(_kb_root(tmp_path))), "kb")
    doc = _stage_raw_document(kb_dir, "broken.pdf", b"bytes")
    _seed_parse_cache(cache_root, doc)

    def _unreadable(_path: Path) -> str:
        raise OSError("source disappeared while being hashed")

    monkeypatch.setattr(cache, "source_hash_from_path", _unreadable)

    removal = remove_raw_document(kb_dir, doc)

    assert not doc.exists()
    assert removal.rel_path == "broken.pdf"
    assert any("Could not hash" in record.message for record in caplog.records)


def test_raw_document_delete_survives_reclamation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = _cache_root(tmp_path)
    kb_dir = _create_kb(KnowledgeBaseManager(base_dir=str(_kb_root(tmp_path))), "kb")
    doc = _stage_raw_document(kb_dir, "gone.pdf", b"gone-bytes")
    shard = _seed_parse_cache(cache_root, doc)
    _fail_reclaim_only_under(cache_root, monkeypatch)

    removal = remove_raw_document(kb_dir, doc)

    assert not doc.exists()
    assert removal.rel_path == "gone.pdf"
    assert shard.is_dir(), "the failed reclamation was skipped, not fatal"


def test_kb_delete_survives_reclamation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = _cache_root(tmp_path)
    manager = KnowledgeBaseManager(base_dir=str(_kb_root(tmp_path)))
    kb_dir = _create_kb(manager, "doomed")
    doc = _stage_raw_document(kb_dir, "a.pdf", b"doc-bytes")
    shard = _seed_parse_cache(cache_root, doc)
    _fail_reclaim_only_under(cache_root, monkeypatch)

    assert manager.delete_knowledge_base("doomed", confirm=True) is True

    assert not kb_dir.exists(), "the KB itself is still deleted"
    assert shard.is_dir(), "the failed reclamation was skipped, not fatal"
