"""Tests for LocalDiskAttachmentStore's write path (issue #2245).

The staging file used to be a fixed "<target>.tmp", so two writers to the same
target truncated each other's staging bytes and the slower rename raised
FileNotFoundError once the faster one had consumed it.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from deeptutor.services.storage.attachment_store import LocalDiskAttachmentStore


def _write_concurrently(target: Path, payloads: list[bytes], force_loser: bool):
    """Run one _write_sync per payload on separate threads.

    ``force_loser`` pins the interleaving that exposes the defect: the first
    writer to reach the rename waits until the other writer has already
    renamed, so it definitely finds the staging file gone. Without it the two
    renames race inside the kernel and can both report success on some
    platforms.
    """
    real_replace = os.replace
    order = {"n": 0}
    lock = threading.Lock()
    second_renamed = threading.Event()

    def ordered_replace(source, destination):
        with lock:
            order["n"] += 1
            index = order["n"]
        if force_loser and index == 1:
            second_renamed.wait(timeout=5)
        real_replace(source, destination)
        if force_loser and index == 2:
            second_renamed.set()

    with patch("os.replace", side_effect=ordered_replace):
        with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
            futures = [
                pool.submit(LocalDiskAttachmentStore._write_sync, target, payload)
                for payload in payloads
            ]
            return [future.exception() for future in futures]


@pytest.mark.parametrize("force_loser", [False, True])
def test_concurrent_writes_do_not_share_a_staging_file(tmp_path: Path, force_loser: bool):
    target = tmp_path / "attachment_notes.txt"

    errors = _write_concurrently(target, [b"writer-0", b"writer-1"], force_loser)

    assert errors == [None, None]
    assert target.read_bytes() in (b"writer-0", b"writer-1")


def test_concurrent_writes_leave_no_staging_file(tmp_path: Path):
    target = tmp_path / "attachment_notes.txt"

    _write_concurrently(target, [b"writer-0", b"writer-1"], force_loser=True)

    leftovers = sorted(p.name for p in tmp_path.iterdir())
    assert leftovers == [target.name]


def test_sequential_writes_still_replace_the_file(tmp_path: Path):
    target = tmp_path / "attachment_notes.txt"

    for payload in (b"first", b"second", b"third"):
        LocalDiskAttachmentStore._write_sync(target, payload)
        assert target.read_bytes() == payload

    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_write_creates_missing_parent_directories(tmp_path: Path):
    target = tmp_path / "sessions" / "abc" / "attachment_notes.txt"

    LocalDiskAttachmentStore._write_sync(target, b"payload")

    assert target.read_bytes() == b"payload"
