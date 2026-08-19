from __future__ import annotations

from pathlib import Path
import time

import pytest

from deeptutor.book.kb_health import mark_drift_on_book, refresh_book_fingerprints
from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    Page,
    PageStatus,
    SourceAnchor,
    Spine,
)
import deeptutor.book.storage as storage_module
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.path_service import PathService


def _storage(tmp_path: Path, monkeypatch) -> storage_module.BookStorage:
    service = PathService(workspace_root=tmp_path / "book-data")
    storage_module._storages.clear()
    monkeypatch.setattr(storage_module, "get_path_service", lambda: service)
    return storage_module.get_book_storage()


def _page(page_id: str, anchor_ref: str) -> Page:
    return Page(
        id=page_id,
        book_id="bk_drift",
        chapter_id="ch_one",
        title=f"Page {page_id}",
        status=PageStatus.READY,
        updated_at=1000,
        blocks=[
            Block(
                id=f"blk_{page_id}",
                type=BlockType.TEXT,
                status=BlockStatus.READY,
                source_anchors=[
                    SourceAnchor(kind="kb", kb_name="kb", ref=anchor_ref, snippet="source")
                ],
            )
        ],
    )


def test_drift_marks_only_pages_anchored_to_changed_document(
    tmp_path: Path, monkeypatch
) -> None:
    storage = _storage(tmp_path, monkeypatch)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    raw = manager.base_dir / "kb" / "raw" / "docs"
    raw.mkdir(parents=True)
    manager.register_knowledge_base("kb")
    (raw / "hermes.md").write_text("Hermes old", encoding="utf-8")
    (raw / "other.md").write_text("Other", encoding="utf-8")

    book = Book(id="bk_drift", title="Book", knowledge_bases=["kb"])
    storage.save_book(book)
    storage.save_spine(Spine(book_id="bk_drift"))
    storage.save_page(_page("pg_hermes", "docs/hermes.md"))
    storage.save_page(_page("pg_other", "docs/other.md"))
    refresh_book_fingerprints("bk_drift", storage=storage, manager=manager)

    (raw / "hermes.md").write_text("Hermes new", encoding="utf-8")
    report = mark_drift_on_book("bk_drift", storage=storage, manager=manager)

    assert report is not None
    assert report.changed_documents == {"kb": ["docs/hermes.md"]}
    assert report.stale_page_ids == ["pg_hermes"]
    assert report.fallback_stale_pages is False


def test_refresh_fingerprints_requires_stale_pages_to_be_recompiled_after_drift(
    tmp_path: Path, monkeypatch
) -> None:
    storage = _storage(tmp_path, monkeypatch)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    raw = manager.base_dir / "kb" / "raw"
    raw.mkdir(parents=True)
    manager.register_knowledge_base("kb")
    source = raw / "guide.md"
    source.write_text("old", encoding="utf-8")

    storage.save_book(Book(id="bk_gate", title="Book", knowledge_bases=["kb"]))
    storage.save_spine(Spine(book_id="bk_gate"))
    page = _page("pg_gate", "guide.md")
    page.book_id = "bk_gate"
    storage.save_page(page)
    refresh_book_fingerprints("bk_gate", storage=storage, manager=manager)

    source.write_text("new", encoding="utf-8")
    mark_drift_on_book("bk_gate", storage=storage, manager=manager)

    with pytest.raises(ValueError, match="pg_gate"):
        refresh_book_fingerprints("bk_gate", storage=storage, manager=manager)

    page.updated_at = time.time() + 1
    storage.save_page(page)
    refreshed = refresh_book_fingerprints("bk_gate", storage=storage, manager=manager)

    assert refreshed is not None
    assert refreshed.stale_page_ids == []
    assert "guide.md" in refreshed.kb_document_fingerprints["kb"]


def test_legacy_book_without_document_baseline_falls_back_to_all_ready_pages(
    tmp_path: Path, monkeypatch
) -> None:
    storage = _storage(tmp_path, monkeypatch)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    raw = manager.base_dir / "kb" / "raw"
    raw.mkdir(parents=True)
    manager.register_knowledge_base("kb")
    (raw / "guide.md").write_text("old", encoding="utf-8")

    book = Book(id="bk_legacy", title="Book", knowledge_bases=["kb"])
    book.kb_fingerprints = {"kb": "old-aggregate"}
    storage.save_book(book)
    storage.save_spine(Spine(book_id="bk_legacy"))
    first = _page("pg_first", "guide.md")
    second = _page("pg_second", "guide.md")
    first.blocks[0].source_anchors = []
    second.blocks[0].source_anchors = []
    first.book_id = second.book_id = "bk_legacy"
    storage.save_page(first)
    storage.save_page(second)

    (raw / "guide.md").write_text("new", encoding="utf-8")
    report = mark_drift_on_book("bk_legacy", storage=storage, manager=manager)

    assert report is not None
    assert report.stale_page_ids == ["pg_first", "pg_second"]
    assert report.fallback_stale_pages is True


def test_unresolvable_kb_anchor_marks_page_stale_conservatively(
    tmp_path: Path, monkeypatch
) -> None:
    storage = _storage(tmp_path, monkeypatch)
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    raw = manager.base_dir / "kb" / "raw"
    raw.mkdir(parents=True)
    manager.register_knowledge_base("kb")
    (raw / "guide.md").write_text("old", encoding="utf-8")

    storage.save_book(Book(id="bk_anchor", title="Book", knowledge_bases=["kb"]))
    storage.save_spine(Spine(book_id="bk_anchor"))
    page = _page("pg_opaque", "opaque-doc-id")
    page.book_id = "bk_anchor"
    storage.save_page(page)
    refresh_book_fingerprints("bk_anchor", storage=storage, manager=manager)

    (raw / "guide.md").write_text("new", encoding="utf-8")
    report = mark_drift_on_book("bk_anchor", storage=storage, manager=manager)

    assert report is not None
    assert report.stale_page_ids == ["pg_opaque"]
    assert report.fallback_stale_pages is True
