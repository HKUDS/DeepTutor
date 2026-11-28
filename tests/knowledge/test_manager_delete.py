from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import stat
from threading import Event

import pytest

from deeptutor.knowledge.catalog import KnowledgeBaseDeletionInProgress
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


def test_delete_preserves_catalog_changes_during_storage_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.knowledge import manager as manager_module

    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    slow_kb = _create_kb(manager, "slow")
    _create_kb(manager, "other")
    concurrent_manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    started, release = Event(), Event()
    real_rmtree = manager_module.shutil.rmtree

    def slow_rmtree(path, *args, **kwargs):
        if path == slow_kb:
            started.set()
            assert release.wait(timeout=5)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(manager_module.shutil, "rmtree", slow_rmtree)
    with ThreadPoolExecutor(max_workers=1) as executor:
        deletion = executor.submit(manager.delete_knowledge_base, "slow", confirm=True)
        try:
            assert started.wait(timeout=3)
            assert concurrent_manager.delete_knowledge_base("other", confirm=True)
            _create_kb(concurrent_manager, "new")
        finally:
            release.set()
        assert deletion.result(timeout=3)

    assert set(_read_config(manager.config_file)["knowledge_bases"]) == {"new"}


def test_same_name_stays_reserved_until_delete_finishes(tmp_path, monkeypatch):
    from deeptutor.knowledge import manager as manager_module
    from deeptutor.knowledge.initializer import KnowledgeBaseInitializer

    manager = KnowledgeBaseManager(tmp_path)
    original = _create_kb(manager, "shared-name")
    other = KnowledgeBaseManager(tmp_path)
    initializer = KnowledgeBaseInitializer("shared-name", base_dir=str(tmp_path))
    removed, release = Event(), Event()
    real_rmtree = manager_module.shutil.rmtree

    def pause_after_removal(path, *args, **kwargs):
        result = real_rmtree(path, *args, **kwargs)
        if path == original:
            removed.set()
            assert release.wait(5)
        return result

    monkeypatch.setattr(manager_module.shutil, "rmtree", pause_after_removal)
    with ThreadPoolExecutor(max_workers=1) as executor:
        deletion = executor.submit(manager.delete_knowledge_base, "shared-name", confirm=True)
        try:
            assert removed.wait(3)
            assert "shared-name" in other.list_knowledge_bases()
            with pytest.raises(KnowledgeBaseDeletionInProgress, match="already being deleted"):
                other.delete_knowledge_base("shared-name", confirm=True)
            with pytest.raises(KnowledgeBaseDeletionInProgress, match="already being deleted"):
                initializer.create_directory_structure()
            assert not other.register_connected_entry(
                "shared-name", {"type": "obsidian", "vault_path": str(tmp_path)}
            )
        finally:
            release.set()
        assert deletion.result(3)

    assert "shared-name" not in other.list_knowledge_bases()
    initializer.create_directory_structure()
    assert initializer.kb_dir.exists()
    assert "shared-name" in _read_config(other.config_file)["knowledge_bases"]


def test_deletion_reservation_uses_platform_name_equivalence(tmp_path, monkeypatch):
    from deeptutor.knowledge import catalog

    monkeypatch.setattr(catalog, "normcase", str.casefold)
    registry = catalog.kb_catalog(tmp_path)
    with registry.reserve_deletion("Report"):
        assert registry.deleting_names() == {"Report"}
        assert registry.is_deleting("report")
        with pytest.raises(KnowledgeBaseDeletionInProgress):
            with registry.reserve_deletion("report"):
                pytest.fail("Case aliases must share the deletion reservation")


def test_catalog_service_update_survives_delete_commit(tmp_path, monkeypatch):
    from deeptutor.services.config.knowledge_base_config import KnowledgeBaseConfigService

    manager = KnowledgeBaseManager(tmp_path)
    _create_kb(manager, "deleted")
    _create_kb(manager, "kept")
    service = KnowledgeBaseConfigService(manager.config_file)
    saving, allow_save, updating, updated = Event(), Event(), Event(), Event()
    save_config = manager._save_config

    def pause_delete_save():
        saving.set()
        assert allow_save.wait(5)
        save_config()

    def update_other_kb():
        updating.set()
        service.set_kb_config("kept", {"description": "edited during delete"})
        updated.set()

    monkeypatch.setattr(manager, "_save_config", pause_delete_save)
    with ThreadPoolExecutor(max_workers=2) as executor:
        deletion = executor.submit(manager.delete_knowledge_base, "deleted", confirm=True)
        try:
            assert saving.wait(3)
            update = executor.submit(update_other_kb)
            assert updating.wait(3)
            assert not updated.wait(0.2)
        finally:
            allow_save.set()
        assert deletion.result(3)
        update.result(3)

    entries = _read_config(manager.config_file)["knowledge_bases"]
    assert set(entries) == {"kept"}
    assert entries["kept"]["description"] == "edited during delete"


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
        else:
            raise OSError("busy")

    # manager_module.shutil is the global stdlib module object. Restore it
    # immediately after the behavior under test so pytest's tmp cleanup keeps
    # the real rmtree implementation.
    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(manager_module.shutil, "rmtree", _rmtree_always_errors)
        assert manager.delete_knowledge_base("broken", confirm=True) is True
    assert "broken" not in _read_config(manager.config_file).get("knowledge_bases", {})
    # A failed POSIX directory retry must preserve traversal permission so a
    # later cleanup pass can remove the orphan.
    assert (manager.base_dir / "broken").stat().st_mode & stat.S_IXUSR


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
