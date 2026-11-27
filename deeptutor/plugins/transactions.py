"""Nonblocking process ownership for plugin lifecycle/state transactions."""

from contextlib import contextmanager
from functools import wraps
import sys


def serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        registry = getattr(self, "registry", self)
        with transaction(registry):
            return method(self, *args, **kwargs)

    return call


@contextmanager
def transaction(registry):
    from deeptutor.plugins.registry import PluginStateError

    path = registry.state_path.with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lease:
        try:
            if sys.platform == "win32":
                import msvcrt

                lease.seek(0)
                if not lease.read(1):
                    lease.write(b"0")
                    lease.flush()
                lease.seek(0)
                msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise PluginStateError(
                "Another plugin lifecycle transaction is active; retry after it finishes."
            ) from exc
        try:
            yield
        finally:
            if sys.platform == "win32":
                lease.seek(0)
                msvcrt.locking(lease.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lease.fileno(), fcntl.LOCK_UN)
