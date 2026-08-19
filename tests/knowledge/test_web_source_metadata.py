"""Persistence tests for KB web source metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager


def _make_manager_with_kb(tmp_path: Path) -> tuple[KnowledgeBaseManager, Path, str]:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    kb_dir = manager.base_dir / "kb"
    kb_dir.mkdir()
    manager.register_knowledge_base("kb")
    return manager, kb_dir / "metadata.json", "kb"


def test_add_web_source_persists(tmp_path: Path) -> None:
    manager, metadata_file, kb = _make_manager_with_kb(tmp_path)
    info = manager.add_web_source(kb, "https://example.com/docs/")

    assert info["url"] == "https://example.com/docs/"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert len(metadata["web_sources"]) == 1


def test_add_web_source_persists_publish_gate_and_schedule_settings(
    tmp_path: Path,
) -> None:
    manager, metadata_file, kb = _make_manager_with_kb(tmp_path)

    info = manager.add_web_source(
        kb,
        "https://example.com/docs/",
        document_version="v2.0",
        validation_queries=["How do I configure authentication?"],
        sync_interval_hours=12,
    )
    manager.update_web_source_state(
        kb,
        info["id"],
        last_synced_at="2026-01-01T00:00:00+00:00",
    )

    decorated = manager.get_web_sources(kb)[0]
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert metadata["web_sources"][0]["validation_queries"] == [
        "How do I configure authentication?"
    ]
    assert decorated["document_version"] == "v2.0"
    assert decorated["sync_interval_hours"] == 12
    assert decorated["next_sync_at"] == "2026-01-01T12:00:00+00:00"


def test_add_web_source_rejects_invalid_schedule(tmp_path: Path) -> None:
    manager, _metadata_file, kb = _make_manager_with_kb(tmp_path)

    with pytest.raises(ValueError, match="sync interval"):
        manager.add_web_source(kb, "https://example.com/docs/", sync_interval_hours=0)


def test_add_web_source_is_idempotent(tmp_path: Path) -> None:
    manager, _, kb = _make_manager_with_kb(tmp_path)
    first = manager.add_web_source(kb, "https://example.com/docs/")
    second = manager.add_web_source(kb, "https://example.com/docs/")

    assert first["id"] == second["id"]
    assert len(manager.get_web_sources(kb)) == 1


def test_remove_web_source(tmp_path: Path) -> None:
    manager, _, kb = _make_manager_with_kb(tmp_path)
    info = manager.add_web_source(kb, "https://example.com/docs/")

    assert manager.remove_web_source(kb, info["id"]) is True
    assert manager.get_web_sources(kb) == []


def test_update_web_source_state_persists(tmp_path: Path) -> None:
    manager, metadata_file, kb = _make_manager_with_kb(tmp_path)
    info = manager.add_web_source(kb, "https://example.com/docs/")

    manager.update_web_source_state(
        kb_name=kb,
        source_id=info["id"],
        page_count=5,
        last_sync_status="success",
    )

    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert metadata["web_sources"][0]["page_count"] == 5


def test_get_all_web_sources_across_kbs(tmp_path: Path) -> None:
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    for name in ("kb-a", "kb-b"):
        (manager.base_dir / name).mkdir()
        manager.register_knowledge_base(name)

    manager.add_web_source("kb-a", "https://a.com/docs")
    manager.add_web_source("kb-b", "https://b.com/docs")

    kb_names = {kb_name for kb_name, _source in manager.get_all_web_sources()}
    assert kb_names == {"kb-a", "kb-b"}
