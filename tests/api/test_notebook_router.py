from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
notebook_router = importlib.import_module(
    "deeptutor.api.routers.question_notebook"
).router
sessions_router = importlib.import_module("deeptutor.api.routers.sessions").router

from deeptutor.services.session.sqlite_store import SQLiteSessionStore


def _build_app(store: SQLiteSessionStore) -> FastAPI:
    app = FastAPI()
    app.include_router(notebook_router, prefix="/api/v1/question-notebook")
    app.include_router(sessions_router, prefix="/api/v1/sessions")
    return app


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> SQLiteSessionStore:
    instance = SQLiteSessionStore(db_path=tmp_path / "router-test.db")
    monkeypatch.setattr(
        "deeptutor.api.routers.question_notebook.get_sqlite_session_store",
        lambda: instance,
    )
    monkeypatch.setattr(
        "deeptutor.api.routers.sessions.get_sqlite_session_store",
        lambda: instance,
    )
    return instance


def _quiz_answers():
    return [
        {
            "question_id": "q1",
            "question": "Capital of France?",
            "question_type": "choice",
            "options": {"A": "Berlin", "B": "Paris"},
            "user_answer": "A",
            "correct_answer": "B",
            "explanation": "Paris is the capital.",
            "difficulty": "easy",
            "is_correct": False,
        },
        {
            "question_id": "q2",
            "question": "2+2?",
            "question_type": "choice",
            "options": {"A": "3", "B": "4"},
            "user_answer": "B",
            "correct_answer": "B",
            "is_correct": True,
        },
    ]


def test_list_entries_empty(store: SQLiteSessionStore) -> None:
    with TestClient(_build_app(store)) as client:
        resp = client.get("/api/v1/question-notebook/entries")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}


def test_quiz_results_populates_notebook(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session(title="Quiz Session"))
    sid = session["id"]

    with TestClient(_build_app(store)) as client:
        resp = client.post(
            f"/api/v1/sessions/{sid}/quiz-results",
            json={"answers": _quiz_answers()},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["recorded"] is True
        assert body["notebook_count"] == 2
        assert "[Quiz Performance]" in body["content"]

        listing = client.get("/api/v1/question-notebook/entries")
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert len(items) == 2


def test_quiz_results_upserts_on_retry(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    sid = session["id"]

    with TestClient(_build_app(store)) as client:
        client.post(f"/api/v1/sessions/{sid}/quiz-results", json={"answers": _quiz_answers()})
        updated = _quiz_answers()
        updated[0]["user_answer"] = "B"
        updated[0]["is_correct"] = True
        client.post(f"/api/v1/sessions/{sid}/quiz-results", json={"answers": updated})

        listing = client.get("/api/v1/question-notebook/entries").json()
        assert listing["total"] == 2
        q1 = next(e for e in listing["items"] if e["question_id"] == "q1")
        assert q1["is_correct"] is True
        assert q1["user_answer"] == "B"


def test_bookmark_toggle(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], [{
        "question_id": "q1", "question": "Q?", "is_correct": False,
    }]))
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]

    with TestClient(_build_app(store)) as client:
        resp = client.patch(
            f"/api/v1/question-notebook/entries/{eid}",
            json={"bookmarked": True},
        )
        assert resp.status_code == 200

        bm = client.get("/api/v1/question-notebook/entries?bookmarked=true").json()
        assert bm["total"] == 1

        client.patch(f"/api/v1/question-notebook/entries/{eid}", json={"bookmarked": False})
        bm2 = client.get("/api/v1/question-notebook/entries?bookmarked=true").json()
        assert bm2["total"] == 0


def test_delete_entry(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], [{
        "question_id": "q1", "question": "Q?", "is_correct": False,
    }]))
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]

    with TestClient(_build_app(store)) as client:
        assert client.delete(f"/api/v1/question-notebook/entries/{eid}").status_code == 200
        assert client.delete(f"/api/v1/question-notebook/entries/{eid}").status_code == 404


def test_category_crud_and_association(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], [{
        "question_id": "q1", "question": "Q?", "is_correct": False,
    }]))
    eid = asyncio.run(store.list_notebook_entries())["items"][0]["id"]

    with TestClient(_build_app(store)) as client:
        cat_resp = client.post(
            "/api/v1/question-notebook/categories",
            json={"name": "Math"},
        )
        assert cat_resp.status_code == 201
        cat_id = cat_resp.json()["id"]

        cats = client.get("/api/v1/question-notebook/categories").json()
        assert len(cats) == 1
        assert cats[0]["name"] == "Math"

        add_resp = client.post(
            f"/api/v1/question-notebook/entries/{eid}/categories",
            json={"category_id": cat_id},
        )
        assert add_resp.status_code == 200

        by_cat = client.get(f"/api/v1/question-notebook/entries?category_id={cat_id}").json()
        assert by_cat["total"] == 1

        rm_resp = client.delete(f"/api/v1/question-notebook/entries/{eid}/categories/{cat_id}")
        assert rm_resp.status_code == 200
        by_cat2 = client.get(f"/api/v1/question-notebook/entries?category_id={cat_id}").json()
        assert by_cat2["total"] == 0

        client.patch(f"/api/v1/question-notebook/categories/{cat_id}", json={"name": "Algebra"})
        cats2 = client.get("/api/v1/question-notebook/categories").json()
        assert cats2[0]["name"] == "Algebra"

        client.delete(f"/api/v1/question-notebook/categories/{cat_id}")
        assert client.get("/api/v1/question-notebook/categories").json() == []


def test_lookup_entry_by_question(store: SQLiteSessionStore) -> None:
    session = asyncio.run(store.create_session())
    asyncio.run(store.upsert_notebook_entries(session["id"], [{
        "question_id": "q1", "question": "Q?", "is_correct": False,
    }]))

    with TestClient(_build_app(store)) as client:
        resp = client.get(
            "/api/v1/question-notebook/entries/lookup/by-question",
            params={"session_id": session["id"], "question_id": "q1"},
        )
        assert resp.status_code == 200
        assert resp.json()["question_id"] == "q1"

        resp404 = client.get(
            "/api/v1/question-notebook/entries/lookup/by-question",
            params={"session_id": session["id"], "question_id": "nope"},
        )
        assert resp404.status_code == 404
