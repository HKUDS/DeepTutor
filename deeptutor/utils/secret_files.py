"""Helpers for writing files that hold secrets."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

SECRET_FILE_MODE = 0o600
SECRET_DIR_MODE = 0o700


def ensure_private_directory(path: Path) -> Path:
    """Create *path* and keep it accessible only to its owner when possible."""
    path.mkdir(parents=True, exist_ok=True, mode=SECRET_DIR_MODE)
    with contextlib.suppress(OSError):
        path.chmod(SECRET_DIR_MODE)
    return path


def ensure_private_file(path: Path) -> Path:
    """Tighten an existing file to owner-only access when the OS supports it."""
    with contextlib.suppress(OSError):
        path.chmod(SECRET_FILE_MODE)
    return path


def write_secret_text(path: Path, text: str) -> None:
    """Write *text* to *path*, readable only by the owner.

    The mode is applied at creation rather than by a later ``chmod``, which
    would leave the contents world-readable in between.
    """
    ensure_private_directory(path.parent)

    # O_CREAT does not apply the mode to an existing file, so a leftover from an
    # interrupted run must be replaced rather than truncated.
    with contextlib.suppress(FileNotFoundError):
        path.unlink()

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SECRET_FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
    except BaseException:
        with contextlib.suppress(OSError):
            path.unlink()
        raise
