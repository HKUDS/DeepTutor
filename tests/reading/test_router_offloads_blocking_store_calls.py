"""Reading routes must not run blocking store work on the API event loop.

Immersive Reading extracts a document synchronously: parsing an EPUB walks every
spine member, and a PDF page is rendered through PyMuPDF. The router is an async
FastAPI surface, so calling that work directly parks the single event loop for
the whole extraction. Every other request on the same backend worker — the
session title and transcript a learner is switching to, progress polling,
cancellation — waits behind it, which is the "the document is still opening, so
the rest of the page has not updated yet" symptom reported in #2054.

The tests below drive the real routes over one event loop and assert that the
loop keeps ticking while a slow store call is in flight.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import time

from fastapi import FastAPI
import httpx
import pytest

from deeptutor.api.routers import reading as reading_router_module
from deeptutor.reading import ReadingStore
from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.services.path_service import PathService

# Long enough that a blocking implementation cannot finish inside it, and short
# enough that an offloaded one finishes well within the test's own budget.
_STORE_DELAY_SECONDS = 0.6


@pytest.fixture
def reading_home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    yield tmp_path
    PathService.reset_instance()


@pytest.fixture
def stored_material(reading_home: Path):
    source = reading_home / "notes.txt"
    source.write_text("A passage used to open the reader.", encoding="utf-8")
    return ReadingStore().ingest(source)


def _slow(original, window: dict[str, float]):
    """Wrap *original* so it blocks its caller and records when it ran."""

    def wrapper(*args, **kwargs):
        window["start"] = time.perf_counter()
        try:
            time.sleep(_STORE_DELAY_SECONDS)
            return original(*args, **kwargs)
        finally:
            window["end"] = time.perf_counter()

    return wrapper


def _client() -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(reading_router_module.router, prefix="/api/reading")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _ticks_during(window: dict[str, float], slow_request) -> tuple[int, int]:
    """Count loop heartbeats that land inside the slow store call's window.

    A sleep-driven heartbeat is the only reliable observer here: when the loop
    is parked by a synchronous call, the heartbeat coroutine is parked too, so
    the *absence* of ticks during ``window`` is the evidence. Timing an
    unrelated HTTP call cannot show it, because that call would be parked as
    well and its stopwatch would only start once the block lifted.
    """
    ticks: list[float] = []

    async def heartbeat() -> None:
        while True:
            ticks.append(time.perf_counter())
            await asyncio.sleep(0.01)

    async with _client() as client:
        beat = asyncio.create_task(heartbeat())
        try:
            # Warm up first: without a known-alive heartbeat, a total of zero
            # ticks would be indistinguishable from never having been scheduled.
            await asyncio.sleep(0.05)
            warm = len(ticks)
            await slow_request(client)
        finally:
            beat.cancel()

    start, end = window.get("start"), window.get("end")
    assert start is not None and end is not None, "the slow store call never ran"
    inside = sum(1 for tick in ticks if start < tick < end)
    return inside, warm


@pytest.mark.asyncio
async def test_upload_does_not_block_the_event_loop(
    reading_home: Path, stored_material, monkeypatch
) -> None:
    """A concurrent request must be answered during an upload's extraction."""
    window: dict[str, float] = {}
    real_store = ReadingStore()

    monkeypatch.setattr(reading_router_module, "_store", lambda: real_store)
    monkeypatch.setattr(reading_router_module, "_catalog", lambda: ReadingCatalogStore())
    # The route calls ``store.ingest`` on the instance, so patch the class.
    monkeypatch.setattr(ReadingStore, "ingest", _slow(ReadingStore.ingest, window))

    payload = (reading_home / "notes.txt").read_bytes()

    async def upload(client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/api/reading/materials",
            files={"file": ("notes.txt", payload, "text/plain")},
        )
        assert response.status_code in {200, 201}, response.text

    inside, total = await _ticks_during(window, upload)

    assert total > 0, "the heartbeat never ran"
    assert inside > 0, (
        "the event loop produced no heartbeat while the upload extracted the "
        "document; the synchronous store call is blocking it"
    )


@pytest.mark.asyncio
async def test_get_material_does_not_block_the_event_loop(
    reading_home: Path, stored_material, monkeypatch
) -> None:
    """Opening a material must not park the loop while its outline loads."""
    window: dict[str, float] = {}
    real_store = ReadingStore()

    monkeypatch.setattr(reading_router_module, "_store", lambda: real_store)
    monkeypatch.setattr(reading_router_module, "_catalog", lambda: ReadingCatalogStore())
    monkeypatch.setattr(ReadingStore, "outline", _slow(ReadingStore.outline, window))

    async def open_material(client: httpx.AsyncClient) -> None:
        response = await client.get(f"/api/reading/materials/{stored_material.material_id}")
        assert response.status_code == 200, response.text

    inside, total = await _ticks_during(window, open_material)

    assert total > 0, "the heartbeat never ran"
    assert inside > 0, (
        "the event loop produced no heartbeat while the material's outline "
        "loaded; the synchronous store call is blocking it"
    )


@pytest.mark.asyncio
async def test_material_detail_loads_the_outline_once(
    reading_home: Path, stored_material, monkeypatch
) -> None:
    """``_detail`` read the outline twice: once for ``outline`` and again inside
    ``render_outline``. For an EPUB each read can re-parse the package."""
    calls: list[str] = []
    real_outline = ReadingStore.outline

    def counting(self, material_id: str):
        calls.append(material_id)
        return real_outline(self, material_id)

    monkeypatch.setattr(reading_router_module, "_store", lambda: ReadingStore())
    monkeypatch.setattr(reading_router_module, "_catalog", lambda: ReadingCatalogStore())
    monkeypatch.setattr(ReadingStore, "outline", counting)

    async with _client() as client:
        response = await client.get(f"/api/reading/materials/{stored_material.material_id}")

    assert response.status_code == 200, response.text
    assert response.json()["outline"] is not None
    assert len(calls) == 1, f"the outline was read {len(calls)} times, expected 1"
