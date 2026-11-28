"""Reading upload behavior across the isolated worker boundary."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException, UploadFile
import pytest

from deeptutor.api.routers import reading
from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.models import MaterialNotFound, ReadingError, ReadingUpgradeConflict
from deeptutor.reading.store import ReadingStore
from deeptutor.runtime.isolated_worker import IsolatedWorkerError, IsolatedWorkerTimeout


@pytest.mark.asyncio
async def test_ingest_uses_a_child_and_the_explicit_workspace(
    tmp_path, monkeypatch, upload_store
) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    source = tmp_path / "source.pdf"
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "An isolated reading document.")
        doc.set_toc([[1, "Introduction", 1]])
        doc.save(source)
    store = upload_store
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "different-home"))

    def reject_parent_ingest(*_args, **_kwargs):
        pytest.fail("Reading ingestion ran in the API process")

    monkeypatch.setattr(ReadingStore, "ingest", reject_parent_ingest)
    detail = await reading.upload_material(
        BackgroundTasks(),
        UploadFile(io.BytesIO(source.read_bytes()), filename="uploaded.pdf"),
        reuse=True,
    )
    manifest = store.manifest(detail.material_id)

    assert detail.filename == manifest.filename == "uploaded.pdf"
    assert detail.unit_count == manifest.unit_count == 1
    assert detail.render_mode == manifest.render_mode == "pdf"
    assert "An isolated reading document." in store.unit_text(manifest.material_id, 1)
    assert store.outline(manifest.material_id)[0].title == "Introduction"
    assert store.raw_path(manifest.material_id).read_bytes() == source.read_bytes()
    assert not (tmp_path / "different-home").exists()


@pytest.mark.asyncio
async def test_real_worker_preserves_reading_errors(upload_store) -> None:
    with pytest.raises(HTTPException) as raised:
        await reading.upload_material(
            BackgroundTasks(),
            UploadFile(io.BytesIO(b"not a PDF"), filename="invalid.pdf"),
            reuse=True,
        )
    assert raised.value.status_code == 400
    assert "failed to read PDF" in raised.value.detail


@pytest.fixture
def upload_store(tmp_path, monkeypatch):
    store = ReadingStore(tmp_path / "reading")
    monkeypatch.setattr(reading, "_store", lambda: store)
    monkeypatch.setattr(reading, "_catalog", lambda: ReadingCatalogStore(store.root))
    monkeypatch.setattr(reading, "assert_learning_material", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(reading, "_schedule_media_captions", lambda *_args, **_kwargs: None)
    return store


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "status"),
    [
        (ReadingError, 400),
        (MaterialNotFound, 404),
        (ReadingUpgradeConflict, 409),
        (PermissionError, 403),
    ],
)
async def test_upload_preserves_remote_error_status_and_cleans_source(
    upload_store, monkeypatch, error_type, status
) -> None:
    sources: list[Path] = []

    async def fail(_callable_path, source_path, **_kwargs):
        source = Path(source_path)
        assert source.read_bytes() == b"document"
        sources.append(source)
        raise IsolatedWorkerError(
            "Cannot ingest this document",
            remote_module=error_type.__module__,
            remote_type=error_type.__name__,
        )

    monkeypatch.setattr(reading, "run_in_isolated_process", fail)
    with pytest.raises(HTTPException) as raised:
        await reading.upload_material(
            BackgroundTasks(), UploadFile(io.BytesIO(b"document"), filename="book.pdf"), reuse=True
        )

    assert raised.value.status_code == status
    assert raised.value.detail == "Cannot ingest this document"
    assert sources and not sources[0].parent.exists()
    assert not upload_store.root.exists()


@pytest.mark.asyncio
async def test_upload_timeout_is_504_without_registering_material(
    upload_store, monkeypatch
) -> None:
    sources: list[Path] = []

    async def timeout(_callable_path, source_path, **_kwargs):
        sources.append(Path(source_path))
        raise IsolatedWorkerTimeout("deadline reached")

    monkeypatch.setattr(reading, "run_in_isolated_process", timeout)
    with pytest.raises(HTTPException) as raised:
        await reading.upload_material(
            BackgroundTasks(), UploadFile(io.BytesIO(b"document"), filename="book.pdf"), reuse=True
        )

    assert raised.value.status_code == 504
    assert raised.value.detail == "deadline reached"
    assert sources and not sources[0].parent.exists()
    assert not upload_store.root.exists()


@pytest.mark.asyncio
async def test_cancelled_upload_keeps_source_until_worker_cleanup(
    upload_store, monkeypatch
) -> None:
    entered = asyncio.Event()
    sources: list[Path] = []
    cleaned = False

    async def wait_for_cancellation(_callable_path, source_path, **_kwargs):
        nonlocal cleaned
        source = Path(source_path)
        sources.append(source)
        entered.set()
        try:
            await asyncio.Future()
        finally:
            assert source.is_file(), "Upload removed its input before worker cleanup"
            cleaned = True

    monkeypatch.setattr(reading, "run_in_isolated_process", wait_for_cancellation)
    task = asyncio.create_task(
        reading.upload_material(
            BackgroundTasks(), UploadFile(io.BytesIO(b"document"), filename="book.pdf"), reuse=True
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleaned
    assert not sources[0].parent.exists()
    assert not upload_store.root.exists()
