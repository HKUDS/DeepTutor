"""Tests for the reusable writable local-KB policy (KB-03).

``assert_kb_writable`` is the single gate knowledge-card publication uses
before any KB mutation. It must reject connected/external KBs, non-ready or
``needs_reindex`` KBs, missing/non-local KBs, KBs without a local raw document
set, and KBs without a ready provider index — before anything is touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.writable import (
    KbNotWritableError,
    assert_kb_writable,
    kb_has_local_raw_doc_set,
    kb_is_ready,
)


def _write_provider_index(kb_dir: Path) -> None:
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"provider": "llamaindex", "signature": "sig", "version": "version-1"}),
        encoding="utf-8",
    )


def _write_config(base: Path, entries: dict) -> None:
    (base / "kb_config.json").write_text(
        json.dumps({"knowledge_bases": entries}, ensure_ascii=False),
        encoding="utf-8",
    )


def _ready_kb(base: Path, name: str = "kb1") -> None:
    kb_dir = base / name
    (kb_dir / "raw").mkdir(parents=True)
    _write_provider_index(kb_dir)
    _write_config(base, {name: {"path": name, "rag_provider": "llamaindex", "status": "ready"}})


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def manager(base: Path) -> KnowledgeBaseManager:
    return KnowledgeBaseManager(base_dir=str(base))


def test_writable_local_ready_kb_passes(manager, base: Path) -> None:
    _ready_kb(base)
    entry = assert_kb_writable(manager, "kb1")
    assert entry["status"] == "ready"


def test_unregistered_kb_rejected(manager, base: Path) -> None:
    _write_config(base, {})
    with pytest.raises(KbNotWritableError) as excinfo:
        assert_kb_writable(manager, "missing")
    assert excinfo.value.error_code == "kb_not_writable"
    assert "not registered" in excinfo.value.reason


def test_connected_kb_rejected(manager, base: Path) -> None:
    vault = base / "vault"
    vault.mkdir()
    _write_config(
        base,
        {"obs": {"path": "obs", "type": "obsidian", "vault_path": str(vault), "status": "ready"}},
    )
    with pytest.raises(KbNotWritableError) as excinfo:
        assert_kb_writable(manager, "obs")
    assert "read-only" in excinfo.value.reason


def test_needs_reindex_kb_rejected(manager, base: Path) -> None:
    kb_dir = base / "kb1"
    (kb_dir / "raw").mkdir(parents=True)
    _write_provider_index(kb_dir)
    _write_config(base, {"kb1": {"path": "kb1", "status": "ready", "needs_reindex": True}})
    with pytest.raises(KbNotWritableError) as excinfo:
        assert_kb_writable(manager, "kb1")
    assert "needs reindex" in excinfo.value.reason


def test_non_ready_status_rejected(manager, base: Path) -> None:
    kb_dir = base / "kb1"
    (kb_dir / "raw").mkdir(parents=True)
    _write_provider_index(kb_dir)
    _write_config(base, {"kb1": {"path": "kb1", "status": "processing"}})
    with pytest.raises(KbNotWritableError) as excinfo:
        assert_kb_writable(manager, "kb1")
    assert "status is 'processing'" in excinfo.value.reason


def test_missing_kb_directory_rejected(manager, base: Path) -> None:
    _write_config(base, {"kb1": {"path": "kb1", "status": "ready"}})
    with pytest.raises(KbNotWritableError) as excinfo:
        assert_kb_writable(manager, "kb1")
    assert "directory is missing" in excinfo.value.reason


def test_missing_raw_document_set_rejected(manager, base: Path) -> None:
    kb_dir = base / "kb1"
    kb_dir.mkdir(parents=True)
    _write_provider_index(kb_dir)
    _write_config(base, {"kb1": {"path": "kb1", "status": "ready"}})
    assert kb_has_local_raw_doc_set(kb_dir) is False
    with pytest.raises(KbNotWritableError) as excinfo:
        assert_kb_writable(manager, "kb1")
    assert "no local raw document set" in excinfo.value.reason


def test_missing_provider_index_rejected(manager, base: Path) -> None:
    kb_dir = base / "kb1"
    (kb_dir / "raw").mkdir(parents=True)
    _write_config(base, {"kb1": {"path": "kb1", "status": "ready"}})
    with pytest.raises(KbNotWritableError) as excinfo:
        assert_kb_writable(manager, "kb1")
    assert "no ready provider index" in excinfo.value.reason


def test_kb_is_ready_only_for_confirmable_local_index(manager, base: Path) -> None:
    _ready_kb(base)
    assert kb_is_ready(manager, "kb1") is True
    # needs_reindex flips readiness off.
    manager.mark_needs_reindex("kb1", reason="test")
    assert kb_is_ready(manager, "kb1") is False
