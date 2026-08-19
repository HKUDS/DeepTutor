"""End-to-end cover for the book WebSocket protocol.

The bug this protects against was invisible to unit tests: the router created a
bus per action and closed it in ``finally``, so every event emitted by work that
outlived the action — i.e. all background compilation — was dropped on the
floor. Both halves have to be checked through the real socket:

1. a subscriber receives events published after any action has returned, and
2. finishing an action does not close the book's stream out from under it.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
import pytest
from starlette.testclient import TestClient

from deeptutor.api.routers import book as book_router
from deeptutor.book import event_hub
from deeptutor.book.event_hub import get_book_stream

BOOK_ID = "bk_ws_test"


@pytest.fixture(autouse=True)
def _clean_hub():
    event_hub._buses.clear()
    yield
    event_hub._buses.clear()


class _StubEngine:
    """Just enough engine for the socket to run an action."""

    def __init__(self, *, known: set[str] | None = None) -> None:
        self.compiled: list[str] = []
        # The socket verifies a book is visible to this user before attaching
        # its stream; anything not here behaves like another user's book.
        self.known = {BOOK_ID} if known is None else known

    def load_book(self, book_id: str):
        from deeptutor.book.models import Book

        return Book(id=book_id) if book_id in self.known else None

    async def compile_page(self, *, book_id, page_id, force=False):
        from deeptutor.book.models import Page

        self.compiled.append(page_id)
        # Publish the way the real compiler does — into the book's own stream.
        await get_book_stream(book_id).book_event(
            "block_ready", {"page_id": page_id, "block_id": "blk_1"}
        )
        return Page(id=page_id, book_id=book_id)


@pytest.fixture
def client(monkeypatch) -> TestClient:
    engine = _StubEngine()
    monkeypatch.setattr(book_router, "get_book_engine", lambda: engine)
    app = FastAPI()
    app.include_router(book_router.router, prefix="/api/v1/book")
    return TestClient(app)


def _drain_until(ws, predicate, *, limit=12):
    """Read frames until *predicate* matches; returns the matching frame."""
    for _ in range(limit):
        frame = ws.receive_json()
        if predicate(frame):
            return frame
    raise AssertionError("expected frame never arrived")


def test_subscribe_is_acknowledged(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/book/ws") as ws:
        ws.send_json({"type": "subscribe", "book_id": BOOK_ID})
        assert ws.receive_json() == {"type": "subscribed", "book_id": BOOK_ID}


def test_subscribe_without_a_book_id_is_rejected(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/book/ws") as ws:
        ws.send_json({"type": "subscribe"})
        frame = ws.receive_json()
        assert frame["type"] == "error"


def test_a_subscriber_receives_events_from_an_action(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/book/ws") as ws:
        ws.send_json({"type": "subscribe", "book_id": BOOK_ID})
        assert ws.receive_json()["type"] == "subscribed"

        ws.send_json({"type": "compile_page", "book_id": BOOK_ID, "page_id": "pg_1"})

        event = _drain_until(ws, lambda f: f.get("metadata", {}).get("kind") == "block_ready")
        assert event["metadata"]["page_id"] == "pg_1"


def test_the_book_stream_survives_the_action_that_used_it(client: TestClient) -> None:
    """The regression itself: work queued by an action keeps streaming after it."""
    with client.websocket_connect("/api/v1/book/ws") as ws:
        ws.send_json({"type": "subscribe", "book_id": BOOK_ID})
        assert ws.receive_json()["type"] == "subscribed"

        ws.send_json({"type": "compile_page", "book_id": BOOK_ID, "page_id": "pg_1"})
        _drain_until(ws, lambda f: f.get("type") == "compile_page_result")

        # The action has replied and its handler has unwound. Previously the bus
        # was closed at exactly this point and everything below was lost.
        bus = event_hub.get_book_bus(BOOK_ID)
        assert not bus._closed, "an action must not close the book's shared stream"

        async def _emit_later() -> None:
            await get_book_stream(BOOK_ID).book_event(
                "page_compiled", {"page_id": "pg_9", "status": "ready"}
            )

        asyncio.run(_emit_later())

        event = _drain_until(ws, lambda f: f.get("metadata", {}).get("kind") == "page_compiled")
        assert event["metadata"]["page_id"] == "pg_9"


def test_a_reconnecting_client_catches_up_on_replayed_history(client: TestClient) -> None:
    async def _emit_before_anyone_is_listening() -> None:
        stream = get_book_stream(BOOK_ID)
        await stream.book_event("page_planned", {"page_id": "pg_1"})
        await stream.book_event("block_ready", {"page_id": "pg_1", "block_id": "blk_1"})

    asyncio.run(_emit_before_anyone_is_listening())

    with client.websocket_connect("/api/v1/book/ws") as ws:
        ws.send_json({"type": "subscribe", "book_id": BOOK_ID})
        kinds = []
        for _ in range(6):
            frame = ws.receive_json()
            kind = frame.get("metadata", {}).get("kind")
            if kind:
                kinds.append(kind)
            if "page_planned" in kinds and "block_ready" in kinds:
                break
        assert "page_planned" in kinds and "block_ready" in kinds


def test_two_clients_watching_one_book_both_get_events(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/book/ws") as first:
        first.send_json({"type": "subscribe", "book_id": BOOK_ID})
        assert first.receive_json()["type"] == "subscribed"

        with client.websocket_connect("/api/v1/book/ws") as second:
            second.send_json({"type": "subscribe", "book_id": BOOK_ID})
            assert second.receive_json()["type"] == "subscribed"

            second.send_json({"type": "compile_page", "book_id": BOOK_ID, "page_id": "pg_1"})

            for ws in (first, second):
                event = _drain_until(
                    ws, lambda f: f.get("metadata", {}).get("kind") == "block_ready"
                )
                assert event["metadata"]["page_id"] == "pg_1"


def test_unknown_message_types_are_reported_not_ignored(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/book/ws") as ws:
        ws.send_json({"type": "nonsense", "book_id": BOOK_ID})
        frame = ws.receive_json()
        assert frame["type"] == "error"
        assert "nonsense" in frame["content"]


def test_subscribing_to_a_book_this_user_cannot_see_is_refused(
    monkeypatch,
) -> None:
    """Buses are keyed by book id alone, so the socket must check visibility."""
    engine = _StubEngine(known=set())
    monkeypatch.setattr(book_router, "get_book_engine", lambda: engine)
    app = FastAPI()
    app.include_router(book_router.router, prefix="/api/v1/book")

    with TestClient(app).websocket_connect("/api/v1/book/ws") as ws:
        ws.send_json({"type": "subscribe", "book_id": "bk_someone_else"})
        frame = ws.receive_json()
        assert frame["type"] == "error"
        assert "not found" in frame["content"].lower()
        assert "bk_someone_else" not in event_hub._buses, (
            "a refused subscribe must not create the book's bus"
        )
