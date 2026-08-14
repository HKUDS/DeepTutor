"""Tests for the MarginNote 4 tools against an in-memory store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.capabilities.marginnote4.models import (
    CARD,
    NOTE,
    MarginNoteObject,
    SyncBatch,
)
from deeptutor.capabilities.marginnote4.store import MarginNoteStore
from deeptutor.capabilities.marginnote4.tools import (
    MarginNoteCardsTool,
    MarginNoteDocumentsTool,
    MarginNoteLinksTool,
    MarginNoteListTool,
    MarginNoteReadTool,
    MarginNoteSearchTool,
    MarginNoteTagsTool,
    _clear_store_cache,
)


def _seed_store(tmp_path: Path) -> str:
    """Seed a store with test data and return its db_path for tool calls."""
    _clear_store_cache()
    store = MarginNoteStore(tmp_path / "test.db")
    store.ingest(
        SyncBatch(
            device_id="dev1",
            objects=[
                MarginNoteObject(
                    object_id="note1",
                    object_type=NOTE,
                    title="Photosynthesis",
                    content="Plants convert light into chemical energy.",
                    excerpt="The process by which green plants use sunlight...",
                    document_id="doc1",
                    document_title="Biology Textbook",
                    page=42,
                    tags=["biology"],
                    links=["card1"],
                    device_id="dev1",
                ),
                MarginNoteObject(
                    object_id="card1",
                    object_type=CARD,
                    title="What is photosynthesis?",
                    content="Process of converting light to chemical energy",
                    tags=["biology"],
                    links=["note1"],
                    device_id="dev1",
                ),
            ],
        )
    )
    return str(tmp_path / "test.db")


@pytest.mark.asyncio
async def test_search_finds_results(tmp_path: Path) -> None:
    db_path = _seed_store(tmp_path)
    # "green plants" appears only in note1's excerpt
    res = await MarginNoteSearchTool().execute(query="green plants", _db_path=db_path)
    assert res.success
    data = json.loads(res.content)
    assert data["count"] == 1
    assert data["results"][0]["object_id"] == "note1"


@pytest.mark.asyncio
async def test_search_finds_common_term(tmp_path: Path) -> None:
    db_path = _seed_store(tmp_path)
    # "photosynthesis" appears in both note1 and card1 titles
    res = await MarginNoteSearchTool().execute(query="photosynthesis", _db_path=db_path)
    assert res.success
    data = json.loads(res.content)
    assert data["count"] >= 1


@pytest.mark.asyncio
async def test_search_empty_query_fails(tmp_path: Path) -> None:
    db_path = _seed_store(tmp_path)
    res = await MarginNoteSearchTool().execute(query="", _db_path=db_path)
    assert res.success is False


@pytest.mark.asyncio
async def test_read_returns_full_object(tmp_path: Path) -> None:
    db_path = _seed_store(tmp_path)
    res = await MarginNoteReadTool().execute(object_id="note1", _db_path=db_path)
    assert res.success
    data = json.loads(res.content)
    assert data["title"] == "Photosynthesis"
    assert data["document_title"] == "Biology Textbook"
    assert data["page"] == 42
    assert data["tags"] == ["biology"]


@pytest.mark.asyncio
async def test_read_missing_object_fails(tmp_path: Path) -> None:
    db_path = _seed_store(tmp_path)
    res = await MarginNoteReadTool().execute(object_id="nonexistent", _db_path=db_path)
    assert res.success is False


@pytest.mark.asyncio
async def test_list_by_type(tmp_path: Path) -> None:
    db_path = _seed_store(tmp_path)
    res = await MarginNoteListTool().execute(object_type="card", _db_path=db_path)
    assert res.success
    data = json.loads(res.content)
    assert data["count"] == 1
    assert data["objects"][0]["object_id"] == "card1"


@pytest.mark.asyncio
async def test_documents_lists_sources(tmp_path: Path) -> None:
    db_path = _seed_store(tmp_path)
    res = await MarginNoteDocumentsTool().execute(_db_path=db_path)
    assert res.success
    data = json.loads(res.content)
    assert data["count"] == 1
    assert data["documents"][0]["title"] == "Biology Textbook"


@pytest.mark.asyncio
async def test_links_finds_connections(tmp_path: Path) -> None:
    db_path = _seed_store(tmp_path)
    res = await MarginNoteLinksTool().execute(object_id="note1", _db_path=db_path)
    assert res.success
    data = json.loads(res.content)
    linked_ids = {item["object_id"] for item in data["links"]}
    assert "card1" in linked_ids


@pytest.mark.asyncio
async def test_tags_returns_ranked(tmp_path: Path) -> None:
    db_path = _seed_store(tmp_path)
    res = await MarginNoteTagsTool().execute(_db_path=db_path)
    assert res.success
    data = json.loads(res.content)
    assert any(t["tag"] == "biology" for t in data["tags"])


@pytest.mark.asyncio
async def test_cards_lists_flashcards(tmp_path: Path) -> None:
    db_path = _seed_store(tmp_path)
    res = await MarginNoteCardsTool().execute(_db_path=db_path)
    assert res.success
    data = json.loads(res.content)
    assert data["count"] == 1
    assert data["cards"][0]["object_type"] == "card"


@pytest.mark.asyncio
async def test_tools_fail_without_store() -> None:
    res = await MarginNoteSearchTool().execute(query="test")
    assert res.success is False
    assert "MarginNote" in res.content


@pytest.mark.asyncio
async def test_tools_fail_with_nonexistent_path(tmp_path: Path) -> None:
    res = await MarginNoteSearchTool().execute(
        query="test", _db_path=str(tmp_path / "nonexistent" / "missing.db")
    )
    assert res.success is False
