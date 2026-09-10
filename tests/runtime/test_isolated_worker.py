"""Cross-platform lifecycle tests for short-lived heavy workers."""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import sys

import pytest

from deeptutor.runtime.isolated_worker import (
    IsolatedWorkerError,
    IsolatedWorkerTimeout,
    run_in_isolated_process,
    run_in_isolated_process_sync,
)
from deeptutor.utils.document_extractor import (
    EmptyDocumentError,
    extract_text_from_path_isolated,
)


def test_sync_worker_returns_a_pickled_result() -> None:
    assert run_in_isolated_process_sync("operator:add", 20, 22, timeout=5) == 42


@pytest.mark.asyncio
async def test_async_worker_preserves_remote_error_details() -> None:
    with pytest.raises(IsolatedWorkerError) as raised:
        await run_in_isolated_process("builtins:int", "not-an-int", timeout=5)
    assert raised.value.remote_module == "builtins"
    assert raised.value.remote_type == "ValueError"
    assert "not-an-int" in str(raised.value)


@pytest.mark.asyncio
async def test_worker_timeout_terminates_the_child() -> None:
    with pytest.raises(IsolatedWorkerTimeout):
        await run_in_isolated_process("time:sleep", 10, timeout=0.05)


@pytest.mark.asyncio
async def test_worker_cancellation_terminates_the_child() -> None:
    task = asyncio.create_task(run_in_isolated_process("time:sleep", 10, timeout=20))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_document_wrapper_restores_public_error_type(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    with pytest.raises(EmptyDocumentError) as raised:
        await extract_text_from_path_isolated(empty, timeout=5)
    assert raised.value.filename == "empty.txt"


def test_child_allocation_does_not_raise_parent_rss_plateau() -> None:
    pytest.importorskip("psutil")
    probe = """
import gc
import psutil
from deeptutor.runtime.isolated_worker import run_in_isolated_process_sync

process = psutil.Process()
before = process.memory_info().rss
for _ in range(3):
    result = run_in_isolated_process_sync(
        "deeptutor.runtime.worker_tasks:test_allocate_bytes",
        64 * 1024 * 1024,
        timeout=10,
    )
    assert result == 64 * 1024 * 1024
gc.collect()
print(process.memory_info().rss - before)
"""
    completed = subprocess.run(  # noqa: S603 - fixed interpreter, no shell
        [sys.executable, "-c", probe],
        check=True,
        capture_output=True,
        text=True,
        timeout=45,
    )
    retained_bytes = int(completed.stdout.strip())
    # Measure in a dedicated process so allocations from earlier pytest tests
    # cannot be mistaken for memory retained by the isolated worker protocol.
    assert retained_bytes < 20 * 1024 * 1024


def test_text_only_parser_writes_result_from_worker(tmp_path: Path) -> None:
    from deeptutor.services.parsing.engines.text_only.engine import TextOnlyParser

    source = tmp_path / "source.txt"
    source.write_text("isolated parser output", encoding="utf-8")
    workdir = tmp_path / "work"
    workdir.mkdir()
    TextOnlyParser().parse(source, workdir, config={})
    assert (workdir / "source.md").read_text(encoding="utf-8") == "isolated parser output"
