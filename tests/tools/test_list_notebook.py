"""Unit tests for the ``list_notebook`` tool's pure rendering logic."""

from __future__ import annotations

import hashlib
import json

import pytest

from deeptutor.services.notebook import NotebookManager
from deeptutor.tools.builtin import ListFavoritesTool
from deeptutor.tools.list_notebook import (
    MAX_FAVORITE_BODY_PAGE_CHARS,
    MAX_NOTEBOOKS_RENDERED,
    MAX_RECORDS_RENDERED,
    list_notebooks_or_records,
    read_favorite_record,
)


class _FakeManager:
    """Minimal NotebookManager stand-in for unit tests."""

    def __init__(self, notebooks=(), records_by_nb=None):
        self._notebooks = list(notebooks)
        self._records = dict(records_by_nb or {})

    def list_notebooks(self):
        return list(self._notebooks)

    def get_records(self, notebook_id):
        return list(self._records.get(notebook_id, []))


# ---------------------------------------------------------------------------
# Index mode (no notebook_id)
# ---------------------------------------------------------------------------


def test_index_returns_empty_message_when_user_has_no_notebooks() -> None:
    outcome = list_notebooks_or_records(notebook_manager=_FakeManager())
    assert outcome.ok is True
    assert "no notebooks" in outcome.text.lower()
    assert outcome.summary == {"mode": "index", "count": 0}


def test_index_renders_id_name_count_for_each_notebook() -> None:
    manager = _FakeManager(
        notebooks=[
            {
                "id": "nb-1",
                "name": "Math",
                "description": "Calculus + linear algebra",
                "record_count": 12,
                "updated_at": 1_700_000_000.0,
            },
            {
                "id": "nb-2",
                "name": "Physics",
                "record_count": 3,
                "updated_at": 1_700_000_010.0,
            },
        ],
    )
    outcome = list_notebooks_or_records(notebook_manager=manager)
    assert outcome.ok is True
    assert "`nb-1`" in outcome.text
    assert "**Math**" in outcome.text
    assert "12 records" in outcome.text
    assert "Calculus + linear algebra" in outcome.text
    assert "`nb-2`" in outcome.text
    assert "Physics" in outcome.text
    assert outcome.summary == {"mode": "index", "count": 2}


def test_index_caps_huge_notebook_lists() -> None:
    manager = _FakeManager(
        notebooks=[
            {"id": f"nb-{i}", "name": f"NB {i}", "record_count": i}
            for i in range(MAX_NOTEBOOKS_RENDERED + 10)
        ],
    )
    outcome = list_notebooks_or_records(notebook_manager=manager)
    assert outcome.ok is True
    assert "showing" in outcome.text.lower()
    assert outcome.summary["count"] == MAX_NOTEBOOKS_RENDERED + 10


# ---------------------------------------------------------------------------
# Drill-down mode (notebook_id given)
# ---------------------------------------------------------------------------


def test_drilldown_rejects_unknown_notebook_id() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Math"}],
    )
    outcome = list_notebooks_or_records(notebook_id="bogus", notebook_manager=manager)
    assert outcome.ok is False
    assert "Unknown notebook_id" in outcome.error
    assert "`nb-1`" in outcome.error  # tells the LLM the right id to use


def test_drilldown_empty_records() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Math"}],
        records_by_nb={"nb-1": []},
    )
    outcome = list_notebooks_or_records(notebook_id="nb-1", notebook_manager=manager)
    assert outcome.ok is True
    assert "no records" in outcome.text.lower()
    assert outcome.summary == {"mode": "records", "notebook_id": "nb-1", "count": 0}


def test_drilldown_renders_records_newest_first() -> None:
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Math"}],
        records_by_nb={
            "nb-1": [
                {
                    "id": "r-old",
                    "title": "Old",
                    "summary": "old summary",
                    "type": "chat",
                    "created_at": 1_700_000_000.0,
                },
                {
                    "id": "r-new",
                    "title": "New",
                    "summary": "new summary",
                    "type": "chat",
                    "created_at": 1_700_001_000.0,
                },
            ]
        },
    )
    outcome = list_notebooks_or_records(notebook_id="nb-1", notebook_manager=manager)
    assert outcome.ok is True
    # Newest first — "r-new" appears before "r-old" in the rendered text.
    assert outcome.text.index("`r-new`") < outcome.text.index("`r-old`")
    assert "new summary" in outcome.text


def test_drilldown_caps_huge_record_lists() -> None:
    big_records = [
        {"id": f"r-{i}", "title": f"R{i}", "summary": "", "created_at": float(i)}
        for i in range(MAX_RECORDS_RENDERED + 20)
    ]
    manager = _FakeManager(
        notebooks=[{"id": "nb-1", "name": "Math"}],
        records_by_nb={"nb-1": big_records},
    )
    outcome = list_notebooks_or_records(notebook_id="nb-1", notebook_manager=manager)
    assert outcome.ok is True
    assert "showing" in outcome.text.lower()
    assert outcome.summary["count"] == MAX_RECORDS_RENDERED + 20


def test_favorite_read_pages_restore_original_without_writing(tmp_path) -> None:
    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Saved sources")["id"]
    body = "ORCHID-7391\n\n中文🙂" + ("x\n\n文🙂" * 4000)
    record_id = manager.add_record(
        [notebook_id], "chat", "Example", "question", body, summary="brief"
    )["record"]["id"]
    notebook_file = manager._get_notebook_file(notebook_id)
    digest_before = hashlib.sha256(notebook_file.read_bytes()).hexdigest()

    listing = list_notebooks_or_records(notebook_id=notebook_id, notebook_manager=manager)
    assert "ORCHID-7391" not in listing.text
    pages = []
    offset = 0
    while True:
        outcome = read_favorite_record(
            notebook_id=notebook_id,
            record_id=record_id,
            offset=offset,
            notebook_manager=manager,
        )
        assert outcome.ok
        assert outcome.summary["total_chars"] == len(body)
        assert outcome.summary["offset"] == offset
        page_length = min(MAX_FAVORITE_BODY_PAGE_CHARS, len(body) - offset)
        pages.append(outcome.text[-page_length:])
        if outcome.summary["next_offset"] is None:
            assert outcome.summary["truncated"] is False
            break
        assert outcome.summary["truncated"] is True
        offset = outcome.summary["next_offset"]

    assert len(pages) > 2
    assert all(len(page) <= MAX_FAVORITE_BODY_PAGE_CHARS for page in pages)
    assert "".join(pages) == body
    assert hashlib.sha256(notebook_file.read_bytes()).hexdigest() == digest_before


def test_favorite_read_rejects_invalid_offsets_and_missing_ids(tmp_path) -> None:
    manager = NotebookManager(base_dir=str(tmp_path / "alice"))
    own_id = manager.create_notebook("Alice")["id"]
    record_id = manager.add_record([own_id], "chat", "T", "Q", "secret")["record"]["id"]
    other = NotebookManager(base_dir=str(tmp_path / "bob"))
    other_id = other.create_notebook("Bob")["id"]
    other_record_id = other.add_record([other_id], "chat", "Bob", "Q", "bob-secret")["record"]["id"]
    for notebook_id, rid, offset in [
        (own_id, record_id, -1),
        (own_id, record_id, True),
        (own_id, record_id, "1"),
        (own_id, record_id, 6),
        (own_id, "missing", 0),
        (other_id, other_record_id, 0),
        ("../bob/" + other_id, other_record_id, 0),
        ("", record_id, 0),
        (own_id, "", 0),
    ]:
        outcome = read_favorite_record(
            notebook_id=notebook_id,
            record_id=rid,
            offset=offset,
            notebook_manager=manager,
        )
        assert not outcome.ok
        assert "secret" not in outcome.error
        assert "bob-secret" not in outcome.text + outcome.error


def test_favorite_read_empty_body(tmp_path) -> None:
    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Empty")["id"]
    record_id = manager.add_record([notebook_id], "chat", "T", "Q", "")["record"]["id"]
    outcome = read_favorite_record(
        notebook_id=notebook_id, record_id=record_id, notebook_manager=manager
    )
    assert outcome.ok and "empty body" in outcome.text
    assert outcome.summary["total_chars"] == 0
    assert outcome.summary["truncated"] is False
    assert outcome.summary["next_offset"] is None
    assert not read_favorite_record(
        notebook_id=notebook_id, record_id=record_id, offset=1, notebook_manager=manager
    ).ok


def test_favorite_read_does_not_repair_legacy_summary_or_missing_index(tmp_path) -> None:
    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Legacy")["id"]
    record_id = manager.add_record([notebook_id], "chat", "T", "Q", "ORCHID-7391")["record"]["id"]
    notebook_file = manager._get_notebook_file(notebook_id)
    raw = json.loads(notebook_file.read_text(encoding="utf-8"))
    raw["records"][0]["summary"] = "<think>private</think>\nbrief"
    notebook_file.write_text(json.dumps(raw), encoding="utf-8")
    manager.index_file.unlink()
    before = hashlib.sha256(notebook_file.read_bytes()).hexdigest()

    outcome = read_favorite_record(
        notebook_id=notebook_id, record_id=record_id, notebook_manager=manager
    )
    assert outcome.ok and "ORCHID-7391" in outcome.text
    assert "private" not in outcome.text
    assert hashlib.sha256(notebook_file.read_bytes()).hexdigest() == before
    assert not manager.index_file.exists()

    # The default service path retains its existing persisted repair behavior.
    assert manager.get_record(notebook_id, record_id)["summary"] == "brief"
    assert hashlib.sha256(notebook_file.read_bytes()).hexdigest() != before


@pytest.mark.asyncio
async def test_list_favorites_schema_and_execution_keep_legacy_calls(tmp_path, monkeypatch) -> None:
    manager = NotebookManager(base_dir=str(tmp_path))
    notebook_id = manager.create_notebook("Saved sources")["id"]
    record_id = manager.add_record([notebook_id], "chat", "T", "Q", "body-only-marker")["record"][
        "id"
    ]
    monkeypatch.setattr("deeptutor.services.notebook.get_notebook_manager", lambda: manager)
    tool = ListFavoritesTool()
    schema = tool.get_definition().to_openai_schema()["function"]["parameters"]
    assert set(schema["properties"]) == {"notebook_id", "record_id", "offset"}
    assert schema["properties"]["offset"]["minimum"] == 0
    assert not schema["required"]

    index = await tool.execute()
    records = await tool.execute(notebook_id=notebook_id)
    assert index.metadata["mode"] == "index"
    assert records.metadata["mode"] == "records"
    assert "body-only-marker" not in index.content + records.content

    read = await tool.execute(notebook_id=notebook_id, record_id=record_id)
    assert "body-only-marker" in read.content
    assert read.metadata["mode"] == "record"
    assert read.metadata["next_offset"] is None
    invalid = await tool.execute(notebook_id=notebook_id, record_id=record_id, offset=True)
    assert invalid.success is False
