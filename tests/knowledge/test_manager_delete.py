from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager


def _create_kb(manager: KnowledgeBaseManager, name: str) -> Path:
    kb_dir = manager.base_dir / name
    (kb_dir / "raw").mkdir(parents=True, exist_ok=True)
    (kb_dir / "version-1").mkdir(parents=True, exist_ok=True)
    (kb_dir / "version-1" / "docstore.json").write_text("{}", encoding="utf-8")
    manager.config.setdefault("knowledge_bases", {})[name] = {
        "path": name,
        "description": "",
    }
    manager._save_config()
    return kb_dir


def _read_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_delete_knowledge_base_removes_config_and_directory(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    kb_dir = _create_kb(manager, "demo")

    assert manager.delete_knowledge_base("demo", confirm=True) is True

    assert not kb_dir.exists()
    assert "demo" not in _read_config(manager.config_file).get("knowledge_bases", {})


def test_delete_knowledge_base_clears_config_when_rmtree_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for issue #370.

    If a KB was left in a broken state (e.g. ``Initialization failed: RAG pipeline
    returned failure``) and its directory can no longer be fully removed (stale
    file handles, read-only bits on Windows bind mounts, etc.), deletion must
    still purge the config entry so the KB disappears from the list. Previously
    the raised OSError aborted the delete and the entry was stuck forever.
    """
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    _create_kb(manager, "broken")

    from deeptutor.knowledge import manager as manager_module

    def _rmtree_always_errors(path, onerror=None, **_kwargs):
        # Simulate a persistent OSError that chmod-retry cannot recover from.
        if onerror is not None:
            onerror(
                manager_module.shutil.rmtree,
                str(path),
                (OSError, OSError("busy"), None),
            )

    # manager_module.shutil is the global stdlib module object. Restore it
    # immediately after the behavior under test so pytest's tmp cleanup keeps
    # the real rmtree implementation.
    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(manager_module.shutil, "rmtree", _rmtree_always_errors)
        assert manager.delete_knowledge_base("broken", confirm=True) is True
    assert "broken" not in _read_config(manager.config_file).get("knowledge_bases", {})


def test_delete_knowledge_base_removes_orphan_config_when_directory_missing(
    tmp_path: Path,
) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    _create_kb(manager, "orphan")
    # Simulate the on-disk directory being wiped externally.
    import shutil as _shutil

    _shutil.rmtree(manager.base_dir / "orphan")

    assert manager.delete_knowledge_base("orphan", confirm=True) is True
    assert "orphan" not in _read_config(manager.config_file).get("knowledge_bases", {})
