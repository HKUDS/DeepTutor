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
    entry = {
        "path": name,
        "description": "",
    }
    manager._mutate_config(
        lambda config: config.setdefault("knowledge_bases", {}).update({name: entry})
    )
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

    import shutil as _shutil

    def _rmtree_always_errors(path, onerror=None, **_kwargs):
        # Simulate a persistent OSError that chmod-retry cannot recover from.
        if onerror is not None:
            onerror(_shutil.rmtree, str(path), (OSError, OSError("busy"), None))

    monkeypatch.setattr(_shutil, "rmtree", _rmtree_always_errors)
    # The manager imports shutil at module level, so patch there too.
    from deeptutor.knowledge import manager as manager_mod

    monkeypatch.setattr(manager_mod.shutil, "rmtree", _rmtree_always_errors)

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
