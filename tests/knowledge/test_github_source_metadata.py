"""Persistence tests for KB GitHub source metadata."""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.knowledge.manager import KnowledgeBaseManager


def _make_manager_with_kb(tmp_path: Path) -> tuple[KnowledgeBaseManager, Path, str]:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    kb_dir = manager.base_dir / "kb"
    kb_dir.mkdir()
    manager.register_knowledge_base("kb")
    return manager, kb_dir / "metadata.json", "kb"


def test_add_github_source_persists(tmp_path: Path) -> None:
    manager, metadata_file, kb = _make_manager_with_kb(tmp_path)
    info = manager.add_github_source(kb, "owner/repo", branch="main", path="docs/")
    assert info["repo"] == "owner/repo"
    on_disk = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert len(on_disk["github_sources"]) == 1


def test_add_github_source_idempotent(tmp_path: Path) -> None:
    manager, _, kb = _make_manager_with_kb(tmp_path)
    info1 = manager.add_github_source(kb, "owner/repo")
    info2 = manager.add_github_source(kb, "owner/repo")
    assert info1["id"] == info2["id"]
    assert len(manager.get_github_sources(kb)) == 1


def test_remove_github_source(tmp_path: Path) -> None:
    manager, _, kb = _make_manager_with_kb(tmp_path)
    info = manager.add_github_source(kb, "owner/repo")
    assert manager.remove_github_source(kb, info["id"]) is True
    assert manager.get_github_sources(kb) == []


def test_update_github_source_state_persists(tmp_path: Path) -> None:
    manager, metadata_file, kb = _make_manager_with_kb(tmp_path)
    info = manager.add_github_source(kb, "owner/repo")
    manager.update_github_source_state(
        kb_name=kb, source_id=info["id"], last_synced_sha="abc", last_sync_status="success"
    )
    on_disk = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert on_disk["github_sources"][0]["last_synced_sha"] == "abc"


def test_get_all_github_sources_across_kbs(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    for name in ("kb-a", "kb-b"):
        (manager.base_dir / name).mkdir()
        manager.register_knowledge_base(name)
    manager.add_github_source("kb-a", "a/repo")
    manager.add_github_source("kb-b", "b/repo")
    all_sources = manager.get_all_github_sources()
    kb_names = {kb for kb, _s in all_sources}
    assert kb_names == {"kb-a", "kb-b"}
