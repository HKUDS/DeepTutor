"""Cross-process leases separating LlamaIndex use from snapshot cleanup."""

from contextlib import contextmanager
from functools import wraps
import hashlib
import inspect
import os
from pathlib import Path


class VersionInUseError(ValueError):
    pass


@contextmanager
def version_lease(kb_dir: Path, *, cleanup: bool = False):
    if kb_dir.is_symlink():
        raise VersionInUseError("Knowledge-base storage must not be a symbolic link")
    locks = kb_dir.parent / ".index-version-locks"
    if locks.is_symlink():
        raise VersionInUseError("Index lock directory must not be a symbolic link")
    locks.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(str(kb_dir.resolve()).encode()).hexdigest()
    path = locks / f"{key}.lock"
    if path.is_symlink():
        raise VersionInUseError("Index lock must not be a symbolic link")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "r+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK if cleanup else msvcrt.LK_NBRLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, (fcntl.LOCK_EX if cleanup else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except OSError as exc:
            raise VersionInUseError(
                "This knowledge base is in use. Try cleanup when it is idle."
            ) from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)


def uses_index_versions(function):
    """Keep a lease throughout async indexing/retrieval, including executor awaits."""
    signature = inspect.signature(function)

    @wraps(function)
    async def wrapped(self, *args, **kwargs):
        from deeptutor.services.rag.kb_paths import resolve_kb_dir

        bound = signature.bind(self, *args, **kwargs)
        kb_dir = resolve_kb_dir(self.kb_base_dir, bound.arguments["kb_name"])
        with version_lease(kb_dir):
            return await function(self, *args, **kwargs)

    return wrapped
