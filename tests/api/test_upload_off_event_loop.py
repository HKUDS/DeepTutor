"""The upload path must never hold the event loop (issue #777).

Batch-uploading files stalled every other request — chat WebSockets included
— for the whole duration of the batch. Two distinct causes, both pinned here:

* ``_save_uploaded_files`` is blocking end to end (a chunked write of every
  uploaded byte, zip extraction, plus a synchronous HTTP upload per file when
  PocketBase is on) and was called inline from an ``async def`` route.
* the follow-up work runs in a FastAPI ``BackgroundTasks`` entry declared
  ``async def``, which starlette awaits ON the event loop — only *sync*
  callables get routed to its threadpool — so the staging hash/copy and the
  per-file re-hash blocked there too.

Each test asserts the work happens on a worker thread, and one asserts the
loop keeps serving unrelated work while an upload is being written.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import threading
from typing import Any

import pytest

from deeptutor.api.routers import knowledge as knowledge_router
from deeptutor.knowledge.add_documents import DocumentAdder


def test_saving_uploads_runs_on_a_worker_thread(monkeypatch, tmp_path: Path) -> None:
    recorded: dict[str, int] = {}

    def _fake_save(
        files: list[Any],
        target_dir: Path,
        **_kwargs: Any,
    ) -> tuple[list[str], list[str]]:
        recorded["thread"] = threading.get_ident()
        return (["a.pdf"], [str(target_dir / "a.pdf")])

    monkeypatch.setattr(knowledge_router, "_save_uploaded_files", _fake_save)

    uploaded, paths = asyncio.run(
        knowledge_router._save_uploaded_files_off_loop([], tmp_path, rel_paths=None)
    )

    assert (uploaded, paths) == (["a.pdf"], [str(tmp_path / "a.pdf")])
    assert recorded["thread"] != threading.get_ident()


@pytest.mark.asyncio
async def test_event_loop_keeps_serving_while_an_upload_is_written(
    monkeypatch, tmp_path: Path
) -> None:
    """The regression itself: unrelated work must progress mid-write."""
    started = threading.Event()
    release = threading.Event()

    def _blocking_save(*_args: Any, **_kwargs: Any) -> tuple[list[str], list[str]]:
        started.set()
        release.wait(timeout=5)
        return ([], [])

    monkeypatch.setattr(knowledge_router, "_save_uploaded_files", _blocking_save)

    ticks = 0

    async def _other_request_traffic() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.005)

    heartbeat = asyncio.create_task(_other_request_traffic())
    save = asyncio.create_task(knowledge_router._save_uploaded_files_off_loop([], tmp_path))
    try:
        await asyncio.to_thread(started.wait, 5)
        ticks_at_start = ticks
        await asyncio.sleep(0.05)
        assert ticks > ticks_at_start, "the event loop stalled while the upload was written"
    finally:
        release.set()
        heartbeat.cancel()
        await save


def test_recording_an_indexed_file_hash_runs_on_a_worker_thread(
    monkeypatch, tmp_path: Path
) -> None:
    """Re-hashes the whole file, once per indexed document."""
    kb_dir = tmp_path / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    version_dir = kb_dir / "version-1"
    version_dir.mkdir()
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"provider": "llamaindex", "signature": "llamaindex", "version": "version-1"}),
        encoding="utf-8",
    )
    doc = raw_dir / "ok.txt"
    doc.write_text("hello", encoding="utf-8")

    class _OkRagService:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def add_documents(self, *_args: Any, **_kwargs: Any) -> bool:
            return True

    monkeypatch.setattr("deeptutor.knowledge.add_documents.RAGService", _OkRagService)

    adder = DocumentAdder(kb_name="kb", base_dir=str(tmp_path))
    recorded: dict[str, int] = {}

    def _spy(file_path: Path) -> None:
        recorded["thread"] = threading.get_ident()

    monkeypatch.setattr(adder, "_record_successful_hash", _spy)

    result = asyncio.run(adder.process_new_documents([doc]))

    assert result.processed_files == [doc]
    assert recorded["thread"] != threading.get_ident()
