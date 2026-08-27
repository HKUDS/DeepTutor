"""Regression tests for bounded LlamaIndex indexing (issue #946).

Indexing steps run in a sync executor thread. An embedding provider that
accepts a request but never completes it (e.g. a blackholed keep-alive
connection) can stall the executor future forever: HTTP timeouts only bound
a single attempt, and provider retries extend the wait far past any
reasonable request budget. These tests pin the stall guard that fails such
operations with a clear error instead of hanging indefinitely.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest


def _llamaindex_modules() -> tuple[Any, Any, Any]:
    """Import the pipeline modules lazily, matching sibling test files."""
    from deeptutor.services.rag.pipelines.llamaindex import pipeline as pipeline_module
    from deeptutor.services.rag.pipelines.llamaindex import storage as storage_module
    from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

    return pipeline_module, storage_module, LlamaIndexPipeline


async def _async_noop(*args, **kwargs) -> None:
    """Async stand-in for connectivity checks that need no provider call."""


def _make_pipeline(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build a pipeline with provider calls neutralized for fast tests."""
    pipeline_module, _storage_module, LlamaIndexPipeline = _llamaindex_modules()
    monkeypatch.setattr(pipeline_module, "_INDEX_STALL_POLL_SECONDS", 0.05)
    monkeypatch.setattr(pipeline_module, "_INDEX_STALL_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(LlamaIndexPipeline, "_configure_settings", lambda self: None)
    monkeypatch.setattr(LlamaIndexPipeline, "_verify_embedding_connectivity", _async_noop)

    async def _fake_load(file_paths, **kwargs):
        del file_paths, kwargs
        return [SimpleNamespace(text="hello world")]

    monkeypatch.setattr(
        pipeline_module, "LlamaIndexDocumentLoader", lambda logger: SimpleNamespace(load=_fake_load)
    )
    return LlamaIndexPipeline(kb_base_dir=str(tmp_path), signature_provider=lambda: None)


@pytest.mark.asyncio
async def test_stall_guard_raises_when_no_progress_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An executor step that never reports progress must fail bounded."""
    pipeline_module, _, _ = _llamaindex_modules()
    monkeypatch.setattr(pipeline_module, "_INDEX_STALL_POLL_SECONDS", 0.05)

    def never_finishes():
        time.sleep(5)

    started = time.monotonic()
    with pytest.raises(pipeline_module.IndexingStallError, match="no progress"):
        await pipeline_module._run_with_stall_guard(
            never_finishes, progress_callback=None, stall_timeout=0.2
        )
    assert time.monotonic() - started < 10


@pytest.mark.asyncio
async def test_stall_guard_returns_when_progress_keeps_flowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow-but-moving step must not be mistaken for a stall."""
    pipeline_module, _, _ = _llamaindex_modules()
    monkeypatch.setattr(pipeline_module, "_INDEX_STALL_POLL_SECONDS", 0.05)
    captured: dict = {}
    monkeypatch.setattr(pipeline_module, "set_progress_callback", lambda cb: captured.update(cb=cb))

    def slow_but_moving():
        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            captured["cb"](1, 1)
            time.sleep(0.05)
        return "done"

    assert (
        await pipeline_module._run_with_stall_guard(
            slow_but_moving, progress_callback=None, stall_timeout=0.3
        )
        == "done"
    )


@pytest.mark.asyncio
async def test_stall_guard_survives_a_concurrent_job_taking_the_callback_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second indexing job must not make this one look stalled.

    ``set_progress_callback`` writes to the process-global LlamaIndex
    ``Settings`` embed model, which holds exactly one callback. A concurrent
    job overwrites ours, so without re-arming on each poll tick we would stop
    observing progress we are still making and kill a perfectly healthy job
    with a false ``IndexingStallError``.
    """
    pipeline_module, _, _ = _llamaindex_modules()
    monkeypatch.setattr(pipeline_module, "_INDEX_STALL_POLL_SECONDS", 0.05)
    slot: dict = {}
    monkeypatch.setattr(pipeline_module, "set_progress_callback", lambda cb: slot.update(cb=cb))

    def displaced_then_moving():
        # A concurrent indexing job claims the single shared slot.
        slot["cb"] = lambda *args, **kwargs: None
        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            # Batches notify whoever currently owns the slot.
            slot["cb"](1, 1)
            time.sleep(0.05)
        return "done"

    assert (
        await pipeline_module._run_with_stall_guard(
            displaced_then_moving, progress_callback=None, stall_timeout=0.3
        )
        == "done"
    )


@pytest.mark.asyncio
async def test_stall_guard_forwards_user_progress_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user-facing progress callback must keep receiving batch events."""
    pipeline_module, _, _ = _llamaindex_modules()
    monkeypatch.setattr(pipeline_module, "_INDEX_STALL_POLL_SECONDS", 0.05)
    captured: dict = {}
    monkeypatch.setattr(pipeline_module, "set_progress_callback", lambda cb: captured.update(cb=cb))
    events: list[tuple[int, int]] = []

    def user_callback(batch_num, total_batches):
        events.append((batch_num, total_batches))

    def reports_once():
        captured["cb"](2, 10)
        return "ok"

    assert (
        await pipeline_module._run_with_stall_guard(
            reports_once, progress_callback=user_callback, stall_timeout=1.0
        )
        == "ok"
    )
    assert events == [(2, 10)]


@pytest.mark.asyncio
async def test_initialize_fails_bounded_when_indexing_stalls(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """initialize() must raise IndexingStallError instead of hanging forever."""
    pipeline_module, storage_module, _ = _llamaindex_modules()
    pipeline = _make_pipeline(tmp_path, monkeypatch)

    def _blocking_create_index(*args, **kwargs):
        del args, kwargs
        time.sleep(5)

    monkeypatch.setattr(storage_module, "create_index", _blocking_create_index)

    started = time.monotonic()
    with pytest.raises(pipeline_module.IndexingStallError, match="no progress"):
        await pipeline.initialize("kb", ["doc.pdf"])
    assert time.monotonic() - started < 10


@pytest.mark.asyncio
async def test_add_documents_fails_bounded_when_new_index_stalls(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """add_documents() new-index path must also fail bounded on a stall."""
    pipeline_module, storage_module, _ = _llamaindex_modules()
    pipeline = _make_pipeline(tmp_path, monkeypatch)

    def _blocking_create_index(*args, **kwargs):
        del args, kwargs
        time.sleep(5)

    monkeypatch.setattr(storage_module, "create_index", _blocking_create_index)

    started = time.monotonic()
    with pytest.raises(pipeline_module.IndexingStallError, match="no progress"):
        await pipeline.add_documents("kb", ["doc.pdf"])
    assert time.monotonic() - started < 10


@pytest.mark.asyncio
async def test_initialize_succeeds_when_indexing_completes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The happy path must be unaffected by the stall guard."""
    _pipeline_module, storage_module, _ = _llamaindex_modules()
    pipeline = _make_pipeline(tmp_path, monkeypatch)
    monkeypatch.setattr(storage_module, "create_index", lambda *a, **k: 7)

    assert await pipeline.initialize("kb", ["doc.pdf"]) is True
