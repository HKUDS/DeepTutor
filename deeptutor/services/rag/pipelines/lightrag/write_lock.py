"""One nonblocking writer per knowledge base, shared across worker processes."""

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path

from .indexing_policy import IndexingPolicyError


@contextmanager
def write_ownership(kb_dir: Path) -> Iterator[None]:
    """Hold exclusive nonblocking write ownership for a knowledge base.

    Yields:
        None while the cross-process indexing lock is held.

    Raises:
        IndexingPolicyError: The target uses a symlink or another writer owns it."""
    kb_dir = Path(kb_dir)
    if kb_dir.is_symlink():
        raise IndexingPolicyError("A writable knowledge-base directory cannot be a symbolic link.")
    lock_dir = kb_dir.parent / ".lightrag-locks"
    if lock_dir.is_symlink():
        raise IndexingPolicyError("The indexing lock directory cannot be a symbolic link.")
    lock_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(kb_dir.resolve()).encode("utf-8")).hexdigest()
    lock_path = lock_dir / f"{key}.lock"
    if lock_path.is_symlink():
        raise IndexingPolicyError("The indexing lock cannot be a symbolic link.")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "r+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise IndexingPolicyError(
                "Another indexing operation is active for this knowledge base; resubmit after it finishes."
            ) from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
