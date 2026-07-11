from __future__ import annotations

import json
from pathlib import Path
import threading

import pytest

from deeptutor.knowledge.initializer import KnowledgeBaseInitializer
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


def test_delete_knowledge_base_replaces_canonical_default(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    _create_kb(manager, "first")
    _create_kb(manager, "second")
    manager._mutate_config(
        lambda config: config.setdefault("defaults", {}).update({"default_kb": "first"})
    )

    assert manager.delete_knowledge_base("first", confirm=True) is True

    persisted = _read_config(manager.config_file)
    assert persisted["defaults"]["default_kb"] == "second"


def test_custom_base_dir_uses_its_own_canonical_default(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "isolated-kbs"))
    _create_kb(manager, "alpha")
    _create_kb(manager, "zeta")

    manager.set_default("zeta")

    assert manager.get_default() == "zeta"
    assert manager.get_knowledge_base_path() == manager.base_dir / "zeta"


def test_late_status_update_does_not_resurrect_deleted_kb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "kbs"
    deleter = KnowledgeBaseManager(base_dir=str(base))
    updater = KnowledgeBaseManager(base_dir=str(base))
    _create_kb(deleter, "demo")

    removed_from_config = threading.Event()
    release_delete = threading.Event()
    original_mutate = deleter._mutate_config

    def pause_after_delete_commit(mutate):
        result = original_mutate(mutate)
        removed_from_config.set()
        assert release_delete.wait(10)
        return result

    monkeypatch.setattr(deleter, "_mutate_config", pause_after_delete_commit)
    delete_thread = threading.Thread(
        target=deleter.delete_knowledge_base,
        args=("demo",),
        kwargs={"confirm": True},
    )
    delete_thread.start()
    assert removed_from_config.wait(10)

    updater.update_kb_status("demo", "initializing", {"stage": "initializing"})
    release_delete.set()
    delete_thread.join(10)

    assert not delete_thread.is_alive()
    persisted = _read_config(deleter.config_file)
    assert "demo" not in persisted.get("knowledge_bases", {})
    assert "demo" in persisted["_deleted_knowledge_bases"]


def test_explicit_recreate_clears_delete_tombstone(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    _create_kb(manager, "demo")
    assert manager.delete_knowledge_base("demo", confirm=True) is True

    manager.update_kb_status("demo", "initializing", allow_recreate=True)

    persisted = _read_config(manager.config_file)
    assert "demo" in persisted["knowledge_bases"]
    assert "demo" not in persisted["_deleted_knowledge_bases"]


def test_stale_initializer_cannot_clear_delete_tombstone(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    _create_kb(manager, "demo")
    assert manager.delete_knowledge_base("demo", confirm=True) is True

    # Models an initializer queued before deletion and only reaching its
    # directory/registration step afterward.
    with pytest.raises(ValueError, match="was deleted"):
        KnowledgeBaseInitializer(
            kb_name="demo", base_dir=str(tmp_path)
        ).create_directory_structure()

    persisted = _read_config(manager.config_file)
    assert "demo" not in persisted["knowledge_bases"]
    assert "demo" in persisted["_deleted_knowledge_bases"]
    assert not (tmp_path / "demo").exists()


def test_old_initializer_generation_cannot_write_new_same_name_kb(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status("demo", "initializing", allow_recreate=True)
    old = KnowledgeBaseInitializer(kb_name="demo", base_dir=str(tmp_path), rag_provider="graphrag")
    old.create_directory_structure()

    assert manager.delete_knowledge_base("demo", confirm=True) is True
    manager.update_kb_status("demo", "initializing", allow_recreate=True)
    new = KnowledgeBaseInitializer(
        kb_name="demo", base_dir=str(tmp_path), rag_provider="llamaindex"
    )
    new.create_directory_structure()

    with pytest.raises(ValueError, match="recreated"):
        old._update_metadata_with_provider("graphrag")


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
    # The intentionally orphaned directory may still look indexable; it must
    # not be auto-discovered again after the delete committed its tombstone.
    assert "broken" not in manager.list_knowledge_bases()


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
