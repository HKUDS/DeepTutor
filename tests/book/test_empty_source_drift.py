from pathlib import Path

import pytest

from deeptutor.book.kb_health import mark_drift_on_book, refresh_book_fingerprints
from deeptutor.book.models import Book, Chapter, Page, PageStatus, SourceAnchor, Spine
from deeptutor.book.storage import BookStorage
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.path_service import PathService


@pytest.mark.parametrize("remove_kb", [False, True])
def test_losing_all_source_documents_marks_existing_book_stale(
    tmp_path: Path, remove_kb: bool
) -> None:
    storage = BookStorage(path_service=PathService(workspace_root=tmp_path / "books"))
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    raw = manager.base_dir / "kb" / "raw"
    raw.mkdir(parents=True)
    source = raw / "guide.md"
    source.write_text("A source used by the generated chapter", encoding="utf-8")
    manager.register_knowledge_base("kb")
    storage.save_book(Book(id="bk_empty", knowledge_bases=["kb"]))
    storage.save_spine(
        Spine(
            book_id="bk_empty",
            chapters=[
                Chapter(
                    id="ch_one",
                    source_anchors=[SourceAnchor(kind="kb", kb_name="kb", ref="guide.md")],
                )
            ],
        )
    )
    storage.save_page(
        Page(id="pg_one", book_id="bk_empty", chapter_id="ch_one", status=PageStatus.READY)
    )
    refresh_book_fingerprints("bk_empty", storage=storage, manager=manager)

    if remove_kb:
        assert manager.delete_knowledge_base("kb", confirm=True)
    else:
        source.unlink()

    report = mark_drift_on_book("bk_empty", storage=storage, manager=manager)

    assert report is not None
    assert report.has_drift
    assert report.changed_documents == {"kb": ["guide.md"]}
    assert report.stale_page_ids == ["pg_one"]
    persisted = storage.load_book("bk_empty")
    assert persisted is not None
    assert persisted.stale_page_ids == ["pg_one"]
    with pytest.raises(ValueError, match="pg_one"):
        refresh_book_fingerprints("bk_empty", storage=storage, manager=manager)
