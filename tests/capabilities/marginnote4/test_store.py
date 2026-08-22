"""Tests for the MarginNote 4 SQLite store: pairing, sync ingest, search."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.capabilities.marginnote4.models import (
    CARD,
    DOCUMENT,
    MINDMAP_NODE,
    NOTE,
    MarginNoteObject,
    SyncBatch,
)
from deeptutor.capabilities.marginnote4.store import (
    MarginNoteStore,
    default_db_path,
    resolve_db_path,
)
from deeptutor.services.path_service import PathService


def _seed_objects(device_id: str = "dev1") -> list[MarginNoteObject]:
    return [
        MarginNoteObject(
            object_id="note1",
            object_type=NOTE,
            title="Photosynthesis",
            content="Plants convert light into chemical energy.",
            excerpt="The process by which green plants use sunlight...",
            document_id="doc1",
            document_title="Biology Textbook",
            page=42,
            tags=["biology", "plants"],
            links=["card1"],
            color="yellow",
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-02T00:00:00Z",
            device_id=device_id,
        ),
        MarginNoteObject(
            object_id="card1",
            object_type=CARD,
            title="What is photosynthesis?",
            content="Process of converting light energy to chemical energy",
            tags=["biology"],
            links=["note1"],
            device_id=device_id,
        ),
        MarginNoteObject(
            object_id="node1",
            object_type=MINDMAP_NODE,
            title="Energy Conversion",
            content="Central concept linking photosynthesis and respiration",
            links=["note1", "card1"],
            device_id=device_id,
        ),
    ]


# ---- device pairing --------------------------------------------------------


def test_pair_device_returns_token(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    device, token = store.pair_device(device_name="MacBook", device_kind="macos")
    assert device.device_id
    assert len(token) > 20
    assert device.device_name == "MacBook"
    assert device.device_kind == "macos"


def test_verify_token_roundtrip(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    device, token = store.pair_device(device_name="iPad")
    assert store.verify_token(device.device_id, token) is True
    assert store.verify_token(device.device_id, "wrong") is False
    assert store.verify_token("nonexistent", token) is False


def test_revoke_device_blocks_token(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    device, token = store.pair_device()
    assert store.verify_token(device.device_id, token) is True
    assert store.revoke_device(device.device_id) is True
    assert store.verify_token(device.device_id, token) is False
    assert store.revoke_device(device.device_id) is False  # already revoked


# ---- sync ingest -----------------------------------------------------------


def test_ingest_stores_objects(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    objects = _seed_objects()
    batch = SyncBatch(device_id="dev1", objects=objects)
    result = store.ingest(batch)
    assert result.stored == 3
    assert result.updated == 0
    assert result.deleted == 0
    assert result.new_cursor
    assert store.count(device_id="dev1") == 3


def test_ingest_updates_existing(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    objects = _seed_objects()
    store.ingest(SyncBatch(device_id="dev1", objects=objects))
    # Re-sync with updated content
    updated = [
        MarginNoteObject(
            object_id="note1",
            object_type=NOTE,
            title="Photosynthesis Updated",
            content="New content",
            device_id="dev1",
        )
    ]
    result = store.ingest(SyncBatch(device_id="dev1", objects=updated))
    assert result.stored == 0
    assert result.updated == 1
    obj = store.get("note1")
    assert obj is not None
    assert obj.title == "Photosynthesis Updated"


def test_ingest_handles_deletions(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    store.ingest(SyncBatch(device_id="dev1", objects=_seed_objects()))
    result = store.ingest(SyncBatch(device_id="dev1", deleted_ids=["note1", "card1"]))
    assert result.deleted == 2
    assert store.count(device_id="dev1") == 1
    assert store.get("note1") is None


def test_ingest_skips_unknown_types(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    bad = [MarginNoteObject(object_id="bad1", object_type="unknown_type", device_id="dev1")]
    result = store.ingest(SyncBatch(device_id="dev1", objects=bad))
    assert result.stored == 0
    assert store.count() == 0


# ---- search ----------------------------------------------------------------


def test_search_finds_by_unique_term(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    store.ingest(SyncBatch(device_id="dev1", objects=_seed_objects()))
    # "chlorophyll" appears only in note1
    hits = store.search("chlorophyll")
    # Adjust: search for a term unique to one object
    hits = store.search("green plants")
    assert len(hits) == 1
    assert hits[0]["object_id"] == "note1"


def test_search_finds_common_term_across_objects(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    store.ingest(SyncBatch(device_id="dev1", objects=_seed_objects()))
    # "photosynthesis" appears in note1 title, card1 title, and node1 content
    hits = store.search("photosynthesis")
    assert len(hits) == 3
    ids = {h["object_id"] for h in hits}
    assert "note1" in ids
    assert "card1" in ids
    assert "node1" in ids


def test_search_includes_document_title(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    store.ingest(SyncBatch(device_id="dev1", objects=_seed_objects()))
    # "Biology Textbook" is a document_title, not in any note's content
    hits = store.search("Biology Textbook")
    assert len(hits) >= 1
    assert any(h["object_id"] == "note1" for h in hits)


def test_search_filters_by_type(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    store.ingest(SyncBatch(device_id="dev1", objects=_seed_objects()))
    hits = store.search("energy", object_type="card")
    assert len(hits) == 1
    assert hits[0]["object_type"] == "card"


def test_search_empty_query_returns_nothing(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    store.ingest(SyncBatch(device_id="dev1", objects=_seed_objects()))
    assert store.search("") == []


# ---- list / documents / tags ----------------------------------------------


def test_list_objects_by_type(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    store.ingest(SyncBatch(device_id="dev1", objects=_seed_objects()))
    cards = store.list_objects(object_type="card")
    assert len(cards) == 1
    assert cards[0]["object_id"] == "card1"


def test_list_documents_grouped(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    store.ingest(SyncBatch(device_id="dev1", objects=_seed_objects()))
    docs = store.list_documents()
    assert len(docs) == 1
    assert docs[0]["document_id"] == "doc1"
    assert docs[0]["title"] == "Biology Textbook"
    assert int(docs[0]["count"]) == 1


def test_collect_tags_ranked(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    store.ingest(SyncBatch(device_id="dev1", objects=_seed_objects()))
    tags = store.collect_tags()
    tag_map = {t["tag"]: t["count"] for t in tags}
    assert tag_map["biology"] == 2  # note1 + card1
    assert tag_map["plants"] == 1


# ---- links -----------------------------------------------------------------


def test_linked_objects_bidirectional(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    store.ingest(SyncBatch(device_id="dev1", objects=_seed_objects()))
    links = store.linked_objects("note1")
    linked_ids = {item["object_id"] for item in links}
    assert "card1" in linked_ids  # note1.links includes card1
    assert "node1" in linked_ids  # node1.links includes note1


# ---- cursor ----------------------------------------------------------------


def test_cursor_advances(tmp_path: Path) -> None:
    store = MarginNoteStore(tmp_path / "test.db")
    assert store.get_cursor("dev1") == ""
    result = store.ingest(SyncBatch(device_id="dev1", objects=_seed_objects()))
    cursor = store.get_cursor("dev1")
    assert cursor != ""
    assert cursor == result.new_cursor


def test_resolve_db_path_prefers_a_pinned_entry(tmp_path, monkeypatch) -> None:
    """One rule, so a paired token stays findable by the sync that presents it.

    The capability binding, the pairing endpoints and the device endpoints all
    have to land on the same file. A KB may pin ``db_path``; everything else
    derives it from the name.
    """
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    try:
        pinned = tmp_path / "elsewhere" / "lib.db"
        assert resolve_db_path("Lib", metadata={"db_path": str(pinned)}) == pinned
        assert resolve_db_path("Lib", metadata={}) == default_db_path("Lib")
        # A blank pin is not a pin.
        assert resolve_db_path("Lib", metadata={"db_path": "  "}) == default_db_path("Lib")
    finally:
        PathService.reset_instance()


def test_resolve_db_path_derives_when_no_kb_is_resolvable(tmp_path, monkeypatch) -> None:
    """No request context and no such KB must not raise — just derive."""
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    try:
        assert resolve_db_path("Nonexistent") == default_db_path("Nonexistent")
    finally:
        PathService.reset_instance()
