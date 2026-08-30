"""Helpers for writing files that hold secrets."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

SECRET_FILE_MODE = 0o600
SECRET_DIR_MODE = 0o700


def write_secret_text(path: Path, text: str) -> None:
    """Write *text* to *path*, readable only by the owner.

    The mode is applied at creation rather than by a later ``chmod``, which
    would leave the contents world-readable in between.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.parent.chmod(SECRET_DIR_MODE)

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
