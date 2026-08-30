"""A topic's materials must reach the tutor, and be honest when they cannot."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.learning.models import TopicSource, TopicSourceKind
from deeptutor.learning.topic_materials import (
    build_topic_materials,
    render_topic_manifest,
)


class _FakeChapter(SimpleNamespace):
    pass


def _book_storage(chapters: list[_FakeChapter]):
    return SimpleNamespace(
        load_book=lambda book_id: SimpleNamespace(title="Agentic RAG", id=book_id),
        load_spine=lambda book_id: SimpleNamespace(chapters=chapters),
    )


def _chapter(cid: str, title: str, order: int, pages: list[str], summary: str = "") -> _FakeChapter:
    return _FakeChapter(
        id=cid,
        title=title,
        order=order,
        page_ids=pages,
        summary=summary,
        learning_objectives=[],
    )


def _source(kind: TopicSourceKind, source_id: str, label: str, **kwargs) -> TopicSource:
    return TopicSource(
        id=f"source_{source_id or label}",
        kind=kind,
        source_id=source_id,
        label=label,
        **kwargs,
    )


@pytest.fixture
def two_chapter_book(monkeypatch: pytest.MonkeyPatch) -> None:
    chapters = [
        _chapter("ch_a", "Beyond the Linear Pipeline", 0, ["p1"], summary="Why static RAG fails."),
        _chapter("ch_b", "The Agent OS", 1, ["p2", "p3"]),
    ]
    monkeypatch.setattr("deeptutor.book.storage.get_book_storage", lambda: _book_storage(chapters))
    monkeypatch.setattr(
        "deeptutor.book.context.build_book_context",
        lambda refs, **kwargs: SimpleNamespace(
            text="CONTENT " + ",".join(refs[0]["page_ids"]), references=[], warnings=[]
        ),
    )


def test_each_book_chapter_becomes_its_own_readable_source(two_chapter_book: None) -> None:
    """Per-chapter, not per-book: a whole book cannot be one tool result."""
    materials = build_topic_materials([_source(TopicSourceKind.BOOK, "bk_1", "Agentic RAG")])
    manifest, index = render_topic_manifest(materials)

    assert sorted(index) == ["bk-bk_1-ch_a", "bk-bk_1-ch_b"]
    assert index["bk-bk_1-ch_a"] == "CONTENT p1"
    assert index["bk-bk_1-ch_b"] == "CONTENT p2,p3"
    # The chapter's own summary is what lets the tutor pick a chapter without
    # reading all of them first.
    assert "Why static RAG fails." in manifest
    assert "1. Beyond the Linear Pipeline" in manifest


def test_goal_source_is_not_offered_as_readable_material() -> None:
    """The goal is the objective, not something to 'read'."""
    materials = build_topic_materials(
        [_source(TopicSourceKind.GOAL, "", "Learning goal", excerpt="Master RAG")]
    )
    assert materials.is_empty()
    assert render_topic_manifest(materials) == ("", {})


def test_knowledge_base_is_listed_as_searchable_but_never_readable() -> None:
    """A KB is searched with rag; listing it stops the tutor inventing it."""
    materials = build_topic_materials(
        [_source(TopicSourceKind.KNOWLEDGE_BASE, "mechanics-kb", "Mechanics KB")]
    )
    manifest, index = render_topic_manifest(materials)

    assert index == {}
    assert "search with rag" in manifest
    assert "mechanics-kb" in manifest


def test_unavailable_material_is_named_rather_than_dropped() -> None:
    """Silently dropping it is what let the tutor claim it had read the book."""
    materials = build_topic_materials(
        [_source(TopicSourceKind.BOOK, "bk_gone", "Missing book", available=False)]
    )
    manifest, index = render_topic_manifest(materials)

    assert index == {}
    assert "unavailable" in manifest
    assert "Missing book" in manifest
    # The instruction that actually prevents the hallucination.
    assert "Never describe or quote their contents" in manifest


def test_chapter_without_pages_is_listed_as_not_written_yet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'This chapter exists but is unwritten' is a fact the tutor must be able
    to state instead of inventing its contents."""
    chapters = [_chapter("ch_a", "Planned chapter", 0, [], summary="Coming soon.")]
    monkeypatch.setattr("deeptutor.book.storage.get_book_storage", lambda: _book_storage(chapters))
    materials = build_topic_materials([_source(TopicSourceKind.BOOK, "bk_1", "Agentic RAG")])
    manifest, index = render_topic_manifest(materials)

    assert index == {}
    assert "not written yet" in manifest


def test_one_failing_material_never_takes_the_turn_down(
    monkeypatch: pytest.MonkeyPatch, two_chapter_book: None
) -> None:
    """Losing a material degrades the lesson; raising would end the turn."""

    def _explode() -> None:
        raise RuntimeError("notebook store is down")

    monkeypatch.setattr("deeptutor.services.notebook.get_notebook_manager", _explode)

    materials = build_topic_materials(
        [
            _source(TopicSourceKind.NOTEBOOK, "nb_1", "Broken notebook", position=0),
            _source(TopicSourceKind.BOOK, "bk_1", "Agentic RAG", position=1),
        ]
    )
    manifest, index = render_topic_manifest(materials)

    assert materials.warnings == ["notebook:nb_1"]
    # The healthy book still arrived.
    assert sorted(index) == ["bk-bk_1-ch_a", "bk-bk_1-ch_b"]
    assert "could not be loaded" in manifest


def test_notebook_becomes_one_source_carrying_its_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        {"id": "r1", "title": "Multi-hop failure", "output": "Linear RAG cannot chain."},
        {"id": "r2", "title": "Agent OS", "output": "Planning, memory, tools."},
    ]
    monkeypatch.setattr(
        "deeptutor.services.notebook.get_notebook_manager",
        lambda: SimpleNamespace(get_records_by_references=lambda refs: records),
    )
    materials = build_topic_materials([_source(TopicSourceKind.NOTEBOOK, "nb_1", "Study log")])
    manifest, index = render_topic_manifest(materials)

    assert list(index) == ["nb-topic-nb_1"]
    assert "Linear RAG cannot chain." in index["nb-topic-nb_1"]
    assert "Planning, memory, tools." in index["nb-topic-nb_1"]
    assert "Study log (2 records)" in manifest
