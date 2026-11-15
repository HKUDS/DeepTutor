"""Cross-process exclusion for durable session migrations."""

from collections.abc import Iterator
from contextlib import contextmanager
import errno
from pathlib import Path

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - exercised only on Windows
    fcntl = None  # type: ignore[assignment]
try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - exercised only off Windows
    msvcrt = None  # type: ignore[assignment]


@contextmanager
def exclusive_lock(lock_path: Path) -> Iterator[None]:
    with lock_path.open("a+b") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            # Without a lock, workers starting together race the WAL switch
            # ("database is locked") and CREATE TRIGGER ("already exists").
            lock_file.seek(0, 2)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            # LK_LOCK gives up with EDEADLK after about ten seconds, and a
            # one-time upgrade of a large database can take longer than that.
            # Keep waiting, as flock does on POSIX.
            while True:
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]  # Windows-only API
                    break
                except OSError as exc:
                    if exc.errno != errno.EDEADLK:
                        raise
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]  # Windows-only API
