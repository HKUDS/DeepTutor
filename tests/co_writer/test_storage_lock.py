"""The Co-Writer write lock's Windows (msvcrt) branch."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from deeptutor.co_writer.storage import CoWriterStorage
from deeptutor.services.path_service import PathService


def test_windows_write_lock_file_keeps_its_single_byte(tmp_path, monkeypatch) -> None:
    # Every save, note-thread change and proposal takes this lock; the
    # Windows branch used to append a byte to the lock file each time.
    calls: list[int] = []

    def locking(_fileno: int, mode: int, length: int) -> None:
        assert length == 1
        calls.append(mode)

    monkeypatch.setitem(sys.modules, "fcntl", None)  # `import fcntl` fails, as on Windows
    monkeypatch.setitem(
        sys.modules, "msvcrt", SimpleNamespace(LK_LOCK=1, LK_UNLCK=0, locking=locking)
    )
    storage = CoWriterStorage(path_service=PathService(workspace_root=tmp_path))

    for _ in range(5):
        with storage.locked():
            pass

    assert (storage.docs_root() / ".write.lock").stat().st_size == 1
    assert calls == [1, 0] * 5
