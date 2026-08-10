import asyncio

import pytest

from deeptutor.book import engine as engine_module
from deeptutor.book.engine import BookEngine, _BookRuntime


@pytest.mark.asyncio
async def test_idle_background_runtime_is_released(monkeypatch) -> None:
    engine = BookEngine.__new__(BookEngine)
    engine._global_lock = asyncio.Lock()
    runtime = _BookRuntime()
    engine._runtimes = {"book-1": runtime}

    async def _timeout(*args, **kwargs):
        raise asyncio.TimeoutError

    monkeypatch.setattr(engine_module.asyncio, "wait_for", _timeout)

    await engine._worker_loop("book-1")

    assert "book-1" not in engine._runtimes
    assert runtime.worker is None
    assert runtime.stream is None
