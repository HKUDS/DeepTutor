"""QTI API endpoints must expose preview, commit, and export as one flow."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import practice, practice_qti
from deeptutor.services.question_content import normalize_question_document
from deeptutor.services.question_content.exchange import build_package
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = SQLiteSessionStore(tmp_path / "practice.db")
    for module in (practice, practice_qti):
        monkeypatch.setattr(module, "get_sqlite_session_store", lambda: store)
    app = FastAPI()
    app.include_router(practice.router, prefix="/practice")
    app.include_router(practice_qti.router, prefix="/practice")
    with TestClient(app) as test_client:
        yield store, test_client


def _package(count: int = 2) -> bytes:
    documents = [
        normalize_question_document(
            {
                "question_id": f"q{index}",
                "question": f"Question {index}",
                "question_type": "single_choice",
                "options": {"A": "yes", "B": "no"},
                "correct_answer": "A",
                "explanation": "",
            },
            source_format="bank-v1",
        )
        for index in range(1, count + 1)
    ]
    built = build_package(
        [{"document": document} for document in documents], asset_bytes={}, version="3.0"
    )
    assert built["packageValidation"] == "valid", built["diagnostics"]
    return built["zip"]


def test_qti_preview_commit_export_roundtrip(client):
    _store, test_client = client
    response = test_client.post(
        "/practice/import/qti/preview",
        files={"file": ("bank.zip", _package(), "application/zip")},
    )
    assert response.status_code == 200
    preview = response.json()
    assert preview["version"] == "3.0"
    assert preview["counts"]["ready"] == 2

    report = test_client.get(f"/practice/import/qti/previews/{preview['token']}")
    assert report.status_code == 200
    assert report.json()["packageValidation"] == "valid"

    source = test_client.get(f"/practice/import/qti/previews/{preview['token']}/source")
    assert source.status_code == 200
    assert source.headers["content-type"] == "application/octet-stream"

    commit = test_client.post(
        "/practice/import/qti/commit",
        json={"token": preview["token"], "selected": ["item_1"]},
    )
    assert commit.status_code == 200
    assert commit.json()["created"] == 1

    exported = test_client.post(
        "/practice/export/qti",
        json={"entry_ids": [1], "version": "3.0", "format": "zip"},
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    assert "attachment" in exported.headers["content-disposition"]


def test_qti_export_supports_single_item_xml(client):
    _store, test_client = client
    preview = test_client.post(
        "/practice/import/qti/preview",
        files={"file": ("bank.zip", _package(1), "application/zip")},
    ).json()
    test_client.post(
        "/practice/import/qti/commit",
        json={"token": preview["token"], "selected": ["item_1"]},
    )

    exported = test_client.post(
        "/practice/export/qti",
        json={"entry_ids": [1], "version": "3.0", "format": "xml"},
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/xml"
    assert b"qti-assessment-item" in exported.content


def test_qti_unknown_preview_is_not_found(client):
    _store, test_client = client
    response = test_client.get("/practice/import/qti/previews/" + "0" * 32)
    assert response.status_code == 404


def test_qti_import_honors_mistakes_target(client):
    store, test_client = client
    preview = test_client.post(
        "/practice/import/qti/preview",
        files={"file": ("bank.zip", _package(1), "application/zip")},
        data={"target": "mistakes"},
    )
    assert preview.status_code == 200
    committed = test_client.post(
        "/practice/import/qti/commit",
        json={"token": preview.json()["token"], "selected": ["item_1"]},
    )
    assert committed.status_code == 200
    from deeptutor.services.practice.storage import PracticeStore

    entry = PracticeStore(store.db_path).entries_by_id([1])[0]
    assert entry["result"] == "incorrect"
    assert PracticeStore(store.db_path).state(1)["is_mistake"]
