"""Small, dependency-free helpers for durable service files."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# fsync failures weaken the durability promise but do not corrupt the write:
# the replacement below still publishes complete content. Warn about them,
# rate-limited, so a failing disk fills the log once per interval instead of
# once per write.
_FSYNC_WARNING_INTERVAL_SECONDS = 60.0
_last_fsync_warning_at: float | None = None
_fsync_warning_lock = threading.Lock()


def _sync_to_disk(handle: Any, path: Path) -> None:
    """fsync *handle*, surfacing a failure as a rate-limited warning."""
    global _last_fsync_warning_at
    try:
        os.fsync(handle.fileno())
    except OSError as exc:
        now = time.monotonic()
        with _fsync_warning_lock:
            should_warn = (
                _last_fsync_warning_at is None
                or now - _last_fsync_warning_at >= _FSYNC_WARNING_INTERVAL_SECONDS
            )
            if should_warn:
                _last_fsync_warning_at = now
        if should_warn:
            logger.warning(
                "fsync failed while writing %s; the write succeeded but is not"
                " guaranteed durable on disk (%r)",
                path,
                exc,
            )


def _atomic_replace(src: Path, dst: Path, *, max_retries: int = 5) -> None:
    """Replace *dst* with *src*, retrying on transient ``PermissionError``.

    On Windows the destination file is occasionally locked by another process
    (antivirus, indexer, or a concurrent reader), which makes ``Path.replace``
    raise ``PermissionError``. A short exponential backoff recovers in most
    cases without losing the already-written content.
    """
    delay = 0.2
    last_err: PermissionError | None = None
    for attempt in range(max_retries):
        try:
            src.replace(dst)
            return
        except PermissionError as exc:  # pragma: no cover - platform specific
            last_err = exc
            if attempt == max_retries - 1:
                break
            time.sleep(delay)
            delay = min(delay * 2, 1.6)
    assert last_err is not None
    raise last_err


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write *payload* as UTF-8 JSON without exposing a partial target file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            _sync_to_disk(handle, path)
        _atomic_replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 text with a same-directory atomic replacement."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            _sync_to_disk(handle, path)
        _atomic_replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


__all__ = ["atomic_write_json", "atomic_write_text"]
