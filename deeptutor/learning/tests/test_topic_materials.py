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


# ── the working-history sources added with the mastery goal rework ──────────


def test_a_hand_picked_knowledge_base_file_is_searchable_not_a_dead_end(monkeypatch):
    """Picking one document out of a library used to produce a material the
    tutor was told it could never read — so the careful selection was silently
    worse than selecting the whole base."""
    materials = build_topic_materials(
        [
            _source(
                TopicSourceKind.FILE,
                "papers/attention.pdf",
                "attention.pdf",
                metadata={"kb_name": "ml-papers"},
            )
        ]
    )
    row = materials.materials[0]
    assert row.available is True
    assert "ml-papers" in row.note
    assert "search with rag" in row.note

    manifest, index = render_topic_manifest(materials)
    # The header explains what an `unavailable` row means; this row must not be
    # one, so check the row itself rather than the whole block.
    file_row = next(line for line in manifest.splitlines() if "attention.pdf" in line)
    assert "unavailable" not in file_row
    assert index == {}


def test_a_chat_transcript_becomes_readable_material(monkeypatch):
    """Reuses chat's own reader, so a conversation attached to a goal reads
    exactly like one attached to a chat turn."""

    async def _fake_load(store, session_id, **kwargs):
        assert session_id == "sess_42"
        return "User: 什么是特征值\nAssistant: 一个向量方向不变的标量倍数…", "线性代数答疑"

    monkeypatch.setattr(
        "deeptutor.services.session.source_inventory._load_history_session", _fake_load
    )
    monkeypatch.setattr(
        "deeptutor.learning.topic_materials._session_store", lambda: SimpleNamespace()
    )

    materials = build_topic_materials([_source(TopicSourceKind.CHAT, "sess_42", "旧对话")])
    row = materials.materials[0]
    assert row.readable is True
    assert row.name == "线性代数答疑"
    assert "特征值" in row.full_text
    assert row.sid.startswith("tc-")
    assert render_topic_manifest(materials)[1] == {row.sid: row.full_text}


def test_a_question_bank_entry_becomes_readable_material(monkeypatch):
    async def _fake_entry(store, entry_id):
        assert entry_id == 7
        return "**Q:** 2+2?\n**Their answer:** 5 (wrong)", "2+2?"

    monkeypatch.setattr(
        "deeptutor.services.session.source_inventory._load_question_entry", _fake_entry
    )
    monkeypatch.setattr(
        "deeptutor.learning.topic_materials._session_store", lambda: SimpleNamespace()
    )

    materials = build_topic_materials([_source(TopicSourceKind.QUESTION_BANK, "7", "一道错题")])
    row = materials.materials[0]
    assert row.readable is True
    assert row.sid == "tq-7"
    assert "wrong" in row.full_text


def test_a_malformed_question_bank_reference_says_so_instead_of_raising():
    materials = build_topic_materials(
        [_source(TopicSourceKind.QUESTION_BANK, "not-a-number", "坏引用")]
    )
    row = materials.materials[0]
    assert row.available is False
    assert "valid entry id" in row.note


def test_a_cowriter_draft_becomes_readable_material(monkeypatch):
    monkeypatch.setattr(
        "deeptutor.co_writer.storage.get_co_writer_storage",
        lambda: SimpleNamespace(
            load_document=lambda doc_id: SimpleNamespace(
                title="RAG 综述初稿", content="第一节 检索增强的动机……"
            )
        ),
    )
    materials = build_topic_materials([_source(TopicSourceKind.COWRITER, "doc_1", "草稿")])
    row = materials.materials[0]
    assert row.readable is True
    assert row.name == "RAG 综述初稿"
    assert row.sid == "tw-doc_1"


def test_a_missing_cowriter_draft_degrades_to_unavailable(monkeypatch):
    monkeypatch.setattr(
        "deeptutor.co_writer.storage.get_co_writer_storage",
        lambda: SimpleNamespace(load_document=lambda doc_id: None),
    )
    materials = build_topic_materials([_source(TopicSourceKind.COWRITER, "gone", "草稿")])
    assert materials.materials[0].available is False
    assert "no longer exists" in materials.materials[0].note


def test_a_partner_group_conversation_becomes_readable_material(monkeypatch):
    monkeypatch.setattr(
        "deeptutor.services.session.source_inventory._load_partner_group_reference",
        lambda ref, language: (
            f"[{ref['group_id']}/{ref['session_key']}] 讨论记录",
            "读书会",
        ),
    )
    materials = build_topic_materials(
        [_source(TopicSourceKind.PARTNER_GROUP, "grp_1:sess_9", "小组讨论")]
    )
    row = materials.materials[0]
    assert row.readable is True
    assert row.name == "读书会"
    assert "grp_1/sess_9" in row.full_text


def test_a_malformed_partner_group_reference_says_so():
    materials = build_topic_materials(
        [_source(TopicSourceKind.PARTNER_GROUP, "no-session-key", "小组讨论")]
    )
    assert materials.materials[0].available is False
    assert "malformed" in materials.materials[0].note
