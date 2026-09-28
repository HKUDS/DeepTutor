from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
import pytest
from starlette.testclient import TestClient

from deeptutor.api.routers import book as book_router
from deeptutor.book.models import Progress
import deeptutor.services.session as session_package
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


class _FakeLearningStore:
    def __init__(self) -> None:
        self.saved: list[Progress] = []
        self.current: Progress | None = None

    def load_progress(self, book_id: str) -> Progress:
        return self.current or Progress(book_id=book_id)

    def save_progress(self, progress: Progress) -> None:
        self.current = progress
        self.saved.append(progress)


class _FakeResolvedBook:
    def __init__(self) -> None:
        question = {
            "question_id": "q1",
            "question": "Which chapter?",
            "question_type": "choice",
            "options": {"A": "One", "B": "Two"},
            "correct_answer": "B",
            "explanation": "The book has two chapters.",
            "difficulty": "easy",
        }
        block = SimpleNamespace(
            title="Focus check",
            payload={"questions": [question]},
        )
        self.page = SimpleNamespace(
            id="page-1",
            title="Page 1",
            chapter_id="",
            block_by_id=lambda _: block,
        )
        self.book = SimpleNamespace(
            title="Compiled Book",
            chat_session_id="",
            metadata={"page_chat_sessions": {"page-1": "page-chat-1"}},
        )
        self.engine = SimpleNamespace(
            load_book=lambda _: self.book,
            list_pages=lambda _: [self.page],
        )
        self.learning = _FakeLearningStore()

    def load_progress(self, book_id: str) -> Progress:
        return self.learning.load_progress(book_id)


@pytest.mark.parametrize(
    ("question_type", "correct_answer", "submitted", "expected"),
    [
        ("choice", "B", "B", True),
        ("multiple_choice", "Two", "B", True),
        ("mcq", "Two", "A", False),
        ("written", "Two", "B", None),
    ],
)
def test_book_linked_choice_grade_matches_supported_ui_answers(
    question_type: str, correct_answer: str, submitted: str, expected: bool | None
) -> None:
    assert (
        book_router._verified_choice_grade(
            {
                "question_type": question_type,
                "options": {"A": "One", "B": "Two"},
                "correct_answer": correct_answer,
            },
            submitted,
        )
        is expected
    )


def test_quiz_attempt_syncs_focus_check_to_question_bank(tmp_path, monkeypatch) -> None:
    store = SQLiteSessionStore(db_path=tmp_path / "sessions.db")
    asyncio.run(store.create_session(session_id="page-chat-1", title="Page 1 chat"))
    resolved = _FakeResolvedBook()
    monkeypatch.setattr(book_router, "_resolve_book_or_404", lambda _: resolved)
    monkeypatch.setattr(session_package, "get_sqlite_session_store", lambda: store)

    app = FastAPI()
    app.include_router(book_router.router, prefix="/api")

    payload = {
        "book_id": "book-1",
        "page_id": "page-1",
        "block_id": "block-1",
        "question_id": "q1",
        "user_answer": "A",
        "is_correct": False,
    }
    with TestClient(app) as client:
        response = client.post("/api/books/quiz-attempt", json=payload)

    assert response.status_code == 200
    assert len(resolved.learning.saved) == 1
    entries = asyncio.run(store.list_notebook_entries(source="book"))
    assert entries["total"] == 1
    entry = entries["items"][0]
    assert entry["session_id"] == "page-chat-1"
    assert entry["session_title"] == "Page 1 chat"
    assert entry["question"] == "Which chapter?"
    assert entry["source"] == "book"
    assert entry["assessment_type"] == "focus_check"
    assert entry["result"] == "incorrect"
    assert entry["material_id"] == "book-1"
    assert entry["material_title"] == "Compiled Book"
    assert entry["section_id"] == "page-1"
    assert entry["section_title"] == "Page 1"
    assert entry["score_trend"] == "new"
    assert entry["resolved"] is False


def test_quiz_attempt_does_not_create_a_synthetic_chat_session(tmp_path, monkeypatch) -> None:
    store = SQLiteSessionStore(db_path=tmp_path / "sessions.db")
    resolved = _FakeResolvedBook()
    resolved.book.metadata = {}
    monkeypatch.setattr(book_router, "_resolve_book_or_404", lambda _: resolved)
    monkeypatch.setattr(session_package, "get_sqlite_session_store", lambda: store)

    app = FastAPI()
    app.include_router(book_router.router, prefix="/api")
    with TestClient(app) as client:
        response = client.post(
            "/api/books/quiz-attempt",
            json={
                "book_id": "book-1",
                "page_id": "page-1",
                "block_id": "block-1",
                "question_id": "q1",
                "user_answer": "A",
                "is_correct": False,
            },
        )

    assert response.status_code == 200
    assert len(resolved.learning.saved) == 1
    assert asyncio.run(store.get_session("book_book-1")) is None
    entries = asyncio.run(store.list_notebook_entries(source="book"))
    assert entries["total"] == 1
    assert entries["items"][0]["session_id"] == ""
    assert entries["items"][0]["origin_type"] == "document_analysis"
    assert entries["items"][0]["origin_ref"] == "book:book-1"


def test_book_submission_retry_is_idempotent_but_new_submission_is_evidence(
    tmp_path, monkeypatch
) -> None:
    store = SQLiteSessionStore(db_path=tmp_path / "sessions.db")
    asyncio.run(store.create_session(session_id="page-chat-1", title="Page 1 chat"))
    resolved = _FakeResolvedBook()
    monkeypatch.setattr(book_router, "_resolve_book_or_404", lambda _: resolved)
    monkeypatch.setattr(session_package, "get_sqlite_session_store", lambda: store)
    app = FastAPI()
    app.include_router(book_router.router, prefix="/api")
    payload = {
        "book_id": "book-1",
        "page_id": "page-1",
        "block_id": "block-1",
        "question_id": "q1",
        "user_answer": "A",
        "is_correct": False,
        "submission_id": "click-1",
    }
    with TestClient(app) as client:
        assert client.post("/api/books/quiz-attempt", json=payload).status_code == 200
        assert client.post("/api/books/quiz-attempt", json=payload).status_code == 200
        assert (
            client.post(
                "/api/books/quiz-attempt", json={**payload, "submission_id": "click-2"}
            ).status_code
            == 200
        )

    assert len(resolved.learning.current.quiz_attempts) == 2
    attempts = asyncio.run(store.list_assessment_attempts("page-chat-1", question_id="q1"))
    assert len(attempts) == 2
    assert [item["attempt_count"] for item in attempts] == [1, 2]
