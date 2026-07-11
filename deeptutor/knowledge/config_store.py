"""Atomic, lock-guarded store for the shared ``kb_config.json`` file.

Both ``KnowledgeBaseManager`` and ``KnowledgeBaseConfigService`` mutate the
same JSON file. Historically each did its own read-modify-write with no lock
spanning the cycle (and truncated the file before locking it), so concurrent
writers lost updates and readers could observe an empty file. This module is
the single write path that fixes both:

* Every mutation runs inside :meth:`KBConfigStore.transaction`: an exclusive
  lock on a stable sidecar file is held across read → mutate → write, so no
  writer can base its write on a stale snapshot.
* Writes go through a unique same-directory temp file + ``fsync`` +
  ``os.replace``, so any reader — locked or not — only ever sees the previous
  or the new file, never a truncated or partial one.
* A file that exists but does not parse — including a zero-byte file left
  behind by an interrupted legacy truncate-then-write — raises
  :class:`KBConfigCorruptionError` instead of silently becoming an empty
  default that a later write would persist over the damaged (but possibly
  recoverable) original. Only a missing file bootstraps the default payload.

The lock lives in a sidecar (``.kb_config.json.lock``) rather than on the data
file because ``os.replace`` swaps the data file's inode on every commit — a
lock taken on the old inode would not exclude writers that open the new one.
The sidecar is created once and never deleted, so its identity is stable.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_LOCK_TIMEOUT = 10.0
_LOCK_POLL_INTERVAL = 0.01


class KBConfigCorruptionError(RuntimeError):
    """The KB config file exists but cannot be parsed.

    Raised instead of falling back to a default payload: a fallback would let
    the next mutation overwrite the damaged file with a near-empty config,
    destroying whatever the original still holds.
    """


def write_json_atomic(path: Path, payload: dict) -> None:
    """Write JSON via a same-directory temp file and ``os.replace`` so
    readers only ever see the previous or the new file, never a partial
    write, and a crash mid-write cannot leave ``path`` truncated.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=2, ensure_ascii=False)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _try_lock_exclusive(fd: int) -> bool:
    """One non-blocking exclusive-lock attempt; ``False`` when held elsewhere."""
    if sys.platform == "win32":
        import msvcrt

        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            # msvcrt has no blocking primitive that waits indefinitely;
            # contention surfaces as OSError and the caller retries.
            return False
    else:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


class KBConfigStore:
    """Serialized read-modify-write access to one JSON config file.

    Instances are cheap and stateless besides their paths; any number of
    instances (across threads or processes) pointing at the same file
    coordinate through the same sidecar lock.
    """

    def __init__(
        self,
        config_path: Path | str,
        *,
        default_factory: Callable[[], dict] | None = None,
        lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
    ):
        self.config_path = Path(config_path)
        self.lock_path = self.config_path.with_name(f".{self.config_path.name}.lock")
        self._default_factory = default_factory or (lambda: {"knowledge_bases": {}})
        self._lock_timeout = lock_timeout

    @contextmanager
    def _locked(self):
        """Hold the sidecar's exclusive lock; bounded wait on contention.

        Both platforms poll a non-blocking attempt against a deadline: msvcrt
        offers nothing that blocks indefinitely, and a shared bounded loop
        also turns a would-be deadlock into a ``TimeoutError``.
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            deadline = time.monotonic() + self._lock_timeout
            while not _try_lock_exclusive(fd):
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Timed out after {self._lock_timeout}s waiting for "
                        f"exclusive lock on {self.lock_path}"
                    )
                time.sleep(_LOCK_POLL_INTERVAL)
            try:
                yield
            finally:
                _unlock(fd)
        finally:
            os.close(fd)

    def _read_current(self) -> dict:
        try:
            raw = self.config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self._default_factory()
        if not raw.strip():
            # A zero-byte file is the signature of the legacy truncate-then-
            # crash write path: the pre-truncate content is already gone, and
            # silently rebuilding a default here would hide that damage.
            raise KBConfigCorruptionError(
                f"{self.config_path} exists but is empty — likely an interrupted "
                f"write truncated it. Refusing to rebuild it silently; remove the "
                f"file to start fresh or restore it from a backup."
            )
        try:
            config = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise KBConfigCorruptionError(
                f"{self.config_path} is not valid JSON ({exc}). Refusing to fall back "
                f"to an empty config; repair or remove the file manually."
            ) from exc
        if not isinstance(config, dict):
            raise KBConfigCorruptionError(
                f"{self.config_path} does not contain a JSON object (got {type(config).__name__})."
            )
        return config

    def read(self) -> dict:
        """Lock-free snapshot of the current config.

        Safe without the lock because every writer commits via atomic
        replace: this returns the previous or the new config in full, never
        a torn intermediate state.
        """
        return self._read_current()

    def transaction(self, mutate: Callable[[dict], Any]) -> tuple[dict, Any]:
        """Run one locked read-modify-write cycle.

        ``mutate`` receives the latest on-disk state and edits it in place;
        its return value is passed through. If it raises, nothing is written
        and the exception propagates. Returns ``(committed_state, result)``.

        ``mutate`` must not invoke another transaction on the same file (the
        lock is not reentrant) and should not perform slow I/O — prepare
        expensive inputs before entering the transaction.
        """
        with self._locked():
            config = self._read_current()
            result = mutate(config)
            write_json_atomic(self.config_path, config)
        return config, result
