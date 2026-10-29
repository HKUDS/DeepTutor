"""HTTP tests for notebook flashcard Anki export."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import deeptutor.services.config as _dt_config

_dt_config.load_config_with_main = lambda *_a, **_k: {
    "paths": {},
    "logging": {},
    "system": {"language": "en"},
}

from deeptutor.api.routers import co_writer as co_writer_router
from deeptutor.co_writer.storage import CoWriterStorage
from deeptutor.notes.anki_export import ANKI_HEADERS


class _StubPathService:
    def __init__(self, root: Path) -> None:
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


def _client(
    tmp_path: Path, monkeypatch, root: Path | None = None
) -> tuple[TestClient, CoWriterStorage]:
    storage = CoWriterStorage(path_service=_StubPathService(root or tmp_path))
    monkeypatch.setattr(co_writer_router, "get_co_writer_storage", lambda: storage)
    app = FastAPI()
    app.include_router(co_writer_router.router)
    return TestClient(app), storage


def _flash_blocks(*cards: dict) -> list[dict]:
    return [
        {
            "id": "flash",
            "type": "learning",
            "props": {"kind": "flashcards", "data": json.dumps({"cards": list(cards)})},
            "children": [],
        }
    ]


def test_export_one_note_and_all_notes(tmp_path, monkeypatch):
    client, storage = _client(tmp_path, monkeypatch)
    first = storage.create_document(
        title="Fourier",
        blocks=_flash_blocks({"front": "Frequency?", "back": "Cycles per second"}),
    )
    storage.create_document(
        title="Optics",
        blocks=_flash_blocks({"front": "What is light?", "back": "A wave"}),
    )
    storage.create_document(title="Empty", content="No cards here")

    one = client.get(f"/documents/{first.id}/flashcards/export")
    assert one.status_code == 200, one.text
    assert one.headers["content-type"].startswith("text/plain")
    assert "charset=utf-8" in one.headers["content-type"]
    disposition = one.headers["content-disposition"]
    assert 'filename="Fourier.txt"' in disposition
    assert "filename*=UTF-8''" in disposition
    body = one.text
    assert body.splitlines()[: len(ANKI_HEADERS)] == list(ANKI_HEADERS)
    assert "Frequency?" in body
    assert "What is light?" not in body
    assert "DeepTutor::Fourier" in body

    all_notes = client.get("/documents/flashcards/export")
    assert all_notes.status_code == 200, all_notes.text
    assert 'filename="deeptutor-flashcards.txt"' in all_notes.headers["content-disposition"]
    assert "Frequency?" in all_notes.text
    assert "What is light?" in all_notes.text
    assert "DeepTutor::Optics" in all_notes.text


def test_cardless_note_and_unknown_ids_are_404(tmp_path, monkeypatch):
    client, storage = _client(tmp_path, monkeypatch)
    empty = storage.create_document(title="Plain", content="# Hello")
    response = client.get(f"/documents/{empty.id}/flashcards/export")
    assert response.status_code == 404
    assert "flashcard" in response.json()["detail"].lower()

    missing = client.get("/documents/aaaaaaaaaaaa/flashcards/export")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Document not found"

    invalid = client.get("/documents/not-a-doc/flashcards/export")
    assert invalid.status_code == 404
    assert invalid.json()["detail"] == "Document not found"

    none = client.get("/documents/flashcards/export")
    assert none.status_code == 404
    assert "flashcard" in none.json()["detail"].lower()


def test_export_filename_survives_non_ascii_titles(tmp_path, monkeypatch):
    client, storage = _client(tmp_path, monkeypatch)
    doc = storage.create_document(
        title="傅里叶 分析",
        blocks=_flash_blocks({"front": "频率？", "back": "每秒周期数"}),
    )
    response = client.get(f"/documents/{doc.id}/flashcards/export")
    assert response.status_code == 200, response.text
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert "%E5%82%85" in disposition
    assert "频率？" in response.text


def test_flashcard_export_is_scoped_to_the_active_workspace(tmp_path, monkeypatch):
    alice = CoWriterStorage(path_service=_StubPathService(tmp_path / "alice"))
    bob = CoWriterStorage(path_service=_StubPathService(tmp_path / "bob"))
    alice_doc = alice.create_document(
        title="Alice notes",
        blocks=_flash_blocks({"front": "Alice?", "back": "Yes"}),
    )
    bob_doc = bob.create_document(
        title="Bob notes",
        blocks=_flash_blocks({"front": "Secret", "back": "Nope"}),
    )
    monkeypatch.setattr(co_writer_router, "get_co_writer_storage", lambda: alice)
    app = FastAPI()
    app.include_router(co_writer_router.router)
    client = TestClient(app)

    workspace = client.get("/documents/flashcards/export")
    assert workspace.status_code == 200
    assert "Alice?" in workspace.text
    assert "Secret" not in workspace.text
    assert client.get(f"/documents/{alice_doc.id}/flashcards/export").status_code == 200
    assert client.get(f"/documents/{bob_doc.id}/flashcards/export").status_code == 404
