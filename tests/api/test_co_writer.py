"""Co-Writer backend tests: doc id validation, storage CRUD, history limits."""

from pathlib import Path

from fastapi import HTTPException
import pytest

from deeptutor.api.routers.co_writer import _validate_doc_id
from deeptutor.co_writer import edit_agent
from deeptutor.co_writer.storage import CoWriterStorage


class _StubPathService:
    def __init__(self, root: Path):
        self.root = root

    def get_co_writer_dir(self) -> Path:
        return self.root

    def get_co_writer_history_file(self) -> Path:
        return self.root / "history.json"

    def get_co_writer_tool_calls_dir(self) -> Path:
        return self.root / "tool_calls"

    def get_co_writer_docs_dir(self) -> Path:
        return self.root / "documents"

    def get_co_writer_doc_root(self, doc_id: str) -> Path:
        return self.get_co_writer_docs_dir() / f"doc_{doc_id}"

    def get_co_writer_doc_manifest(self, doc_id: str) -> Path:
        return self.get_co_writer_doc_root(doc_id) / "manifest.json"


# ── doc_id validation ────────────────────────────────────────────────────


def test_validate_doc_id_accepts_generated_ids():
    assert _validate_doc_id("a1b2c3d4e5f6") == "a1b2c3d4e5f6"


@pytest.mark.parametrize(
    "bad",
    [
        "../x",
        "a/../../etc",
        "a1b2c3d4e5f6/../../x",
        "doc_1; rm -rf",
        "A1B2C3D4E5F6",
        "",
        "a" * 40,
    ],
)
def test_validate_doc_id_rejects_traversal_and_junk(bad):
    with pytest.raises(HTTPException) as exc:
        _validate_doc_id(bad)
    assert exc.value.status_code == 404


# ── storage CRUD ─────────────────────────────────────────────────────────


def test_storage_crud_roundtrip(tmp_path):
    storage = CoWriterStorage(path_service=_StubPathService(tmp_path))

    doc = storage.create_document(title=None, content="# Hello\nWorld")
    assert doc.title == "Hello"
    assert _validate_doc_id(doc.id) == doc.id

    loaded = storage.load_document(doc.id)
    assert loaded is not None
    assert loaded.content.startswith("# Hello")

    # Explicit titles stick across content updates.
    updated = storage.update_document(doc.id, content="# Renamed\nBody")
    assert updated is not None
    assert updated.title == "Hello"

    assert storage.delete_document(doc.id) is True
    assert storage.load_document(doc.id) is None


def test_storage_untitled_doc_follows_first_heading(tmp_path):
    storage = CoWriterStorage(path_service=_StubPathService(tmp_path))
    doc = storage.create_document(title=None, content="")
    assert doc.title == "Untitled draft"

    updated = storage.update_document(doc.id, content="# Fresh title\nBody")
    assert updated is not None
    assert updated.title == "Fresh title"


def test_storage_list_sorted_by_recency(tmp_path):
    storage = CoWriterStorage(path_service=_StubPathService(tmp_path))
    first = storage.create_document(title="first", content="a")
    second = storage.create_document(title="second", content="b")
    storage.update_document(first.id, content="a updated")

    summaries = storage.list_documents()
    assert [s.id for s in summaries][0] == first.id
    assert {s.id for s in summaries} == {first.id, second.id}


# ── history limits ───────────────────────────────────────────────────────


def test_append_history_caps_entries(tmp_path, monkeypatch):
    stub = _StubPathService(tmp_path)
    monkeypatch.setattr(edit_agent, "get_path_service", lambda: stub)

    overflow = 5
    for i in range(edit_agent._HISTORY_MAX_ENTRIES + overflow):
        edit_agent.append_history({"id": str(i)})

    history = edit_agent.load_history()
    assert len(history) == edit_agent._HISTORY_MAX_ENTRIES
    assert history[-1]["id"] == str(edit_agent._HISTORY_MAX_ENTRIES + overflow - 1)
    assert history[0]["id"] == str(overflow)


def test_append_history_clips_long_texts(tmp_path, monkeypatch):
    stub = _StubPathService(tmp_path)
    monkeypatch.setattr(edit_agent, "get_path_service", lambda: stub)

    long_text = "x" * (edit_agent._HISTORY_TEXT_LIMIT + 500)
    edit_agent.append_history({"id": "clip", "input": {"original_text": long_text}})

    record = edit_agent.load_history()[-1]
    stored = record["input"]["original_text"]
    assert stored.endswith("…[truncated]")
    assert len(stored) < len(long_text)


def test_load_history_survives_corrupt_file(tmp_path, monkeypatch):
    stub = _StubPathService(tmp_path)
    monkeypatch.setattr(edit_agent, "get_path_service", lambda: stub)

    stub.get_co_writer_dir().mkdir(parents=True, exist_ok=True)
    stub.get_co_writer_history_file().write_text("{not json", encoding="utf-8")
    assert edit_agent.load_history() == []
