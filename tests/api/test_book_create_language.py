"""Language fields must survive both book creation transports."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.testclient import TestClient

from deeptutor.api.routers import book as book_router
from deeptutor.book.models import Book, BookProposal


class _RecordingEngine:
    def __init__(self) -> None:
        self.kwargs: dict | None = None

    async def create_book(self, **kwargs):
        self.kwargs = kwargs
        return Book(id="bk_language", title="Language Test"), BookProposal(title="Language Test")


def _install(monkeypatch, engine: _RecordingEngine) -> FastAPI:
    monkeypatch.setattr(book_router, "get_book_engine", lambda: engine)
    monkeypatch.setattr(book_router, "can_create_book", lambda: True)
    app = FastAPI()
    app.include_router(book_router.router, prefix="/api")
    app.include_router(book_router.ws_router, prefix="/ws")
    return app


def test_rest_create_passes_requested_and_fallback_language(monkeypatch) -> None:
    engine = _RecordingEngine()
    app = _install(monkeypatch, engine)

    response = TestClient(app).post(
        "/api/books",
        json={
            "user_intent": "Create a book",
            "language": "auto",
            "fallback_language": "zh",
        },
    )

    assert response.status_code == 200
    assert engine.kwargs is not None
    assert engine.kwargs["language"] == "auto"
    assert engine.kwargs["fallback_language"] == "zh"


def test_websocket_create_passes_fallback_language(monkeypatch) -> None:
    engine = _RecordingEngine()
    app = _install(monkeypatch, engine)

    with TestClient(app).websocket_connect("/ws/books") as ws:
        ws.send_json(
            {
                "type": "create",
                "user_intent": "Create a book",
                "language": "auto",
                "fallback_language": "zh",
            }
        )
        result = ws.receive_json()

    assert result["type"] == "create_result"
    assert engine.kwargs is not None
    assert engine.kwargs["language"] == "auto"
    assert engine.kwargs["fallback_language"] == "zh"
