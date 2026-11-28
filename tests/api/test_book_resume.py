"""Recovery of a background run requested from an on-demand book."""

import asyncio

import httpx
import pytest

from deeptutor.api.routers import book as book_router
from deeptutor.book import engine as engine_module
from deeptutor.book.engine import BookEngine
from deeptutor.book.event_hub import close_book_bus
from deeptutor.book.models import BookStatus, PageStatus
from tests.api.test_book_chapter_crud import _client, _seed


@pytest.mark.asyncio
async def test_reopen_requeues_an_explicitly_resumed_on_demand_book(tmp_path, monkeypatch):
    test_client, storage = _client(tmp_path, monkeypatch)
    _seed(storage)
    book = storage.load_book("bk")
    book.status = BookStatus.COMPILING
    book.metadata["lazy_compile"] = True
    storage.save_book(book)
    owed = storage.load_page("bk", "pg_1")
    owed.status = PageStatus.PENDING
    storage.save_page(owed)
    original_ready = storage.load_page("bk", "pg_0")

    engine = book_router.get_book_engine()
    monkeypatch.setattr(engine_module, "get_book_engine", lambda: engine)
    started = asyncio.Event()
    calls = []

    async def interrupted_compile(*, page, **kwargs):
        calls.append(page.id)
        page.status = PageStatus.GENERATING
        storage.save_page(page)
        started.set()
        await asyncio.Future()

    monkeypatch.setattr(engine.compiler, "compile_page", interrupted_compile)
    transport = httpx.ASGITransport(app=test_client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            unopened = await client.get("/api/books/bk")
            assert unopened.status_code == 200
            assert not engine.is_worker_live("bk")
            assert storage.load_page("bk", owed.id).status == PageStatus.PENDING

            resumed = await client.post("/api/books/resume", json={"book_id": "bk"})
            assert resumed.status_code == 200
            await asyncio.wait_for(started.wait(), timeout=3)
            assert storage.load_page("bk", owed.id).status == PageStatus.GENERATING
            # Simulate losing the process's worker without mutating stored state.
            await engine._halt_compilation("bk")
            engine = BookEngine(storage=storage)
            monkeypatch.setattr(book_router, "get_book_engine", lambda: engine)
            finished = asyncio.Event()

            async def finish_compile(*, page, **kwargs):
                calls.append(page.id)
                page.status = PageStatus.READY
                storage.save_page(page)
                finished.set()
                return page

            monkeypatch.setattr(engine.compiler, "compile_page", finish_compile)
            reopened = await client.get("/api/books/bk")
            assert reopened.status_code == 200
            assert reopened.json()["generation"]["working"] or finished.is_set()
            await asyncio.wait_for(finished.wait(), timeout=3)
            assert storage.load_page("bk", owed.id).status == PageStatus.READY
            assert storage.load_page("bk", original_ready.id) == original_ready
            assert calls == [owed.id, owed.id]
        finally:
            await engine._halt_compilation("bk")
            close_book_bus("bk")
