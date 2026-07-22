"""One-click background jobs for optional parser engines.

The Document Parsing settings page runs two kinds of background job without the
user dropping to a shell:

* **install** — ``pip install`` an engine's optional PyPI package.
* **models**  — download an engine's model weights (e.g. Docling's layout/table
  models via ``docling-tools models download``).

Both mirror the MinerU model-download job (``mineru/models.py``): a single
background subprocess with a cursor-based line log the UI starts, polls, and
cancels. Commands come from fixed allow-lists (pip specs / downloader argv),
never user input, so the subprocess argv can't be injected. Package installs use
the bare package specs (the same strings as the ``[parse-*]`` extras) so pip
never re-resolves DeepTutor itself; after a successful install we invalidate the
import caches so the engine reports available in the same process (no restart).
"""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
import shutil
import subprocess  # nosec B404 - argv from fixed allow-lists, never user input
import sys
import threading
import time
from typing import Any, Callable, Optional

from ._versions import package_version

logger = logging.getLogger(__name__)

# Engine id -> pip requirement specifiers. Mirrors the optional extras in
# pyproject.toml. Engines absent here (text_only built-in, mineru external
# CLI/API) have no one-click install.
ENGINE_PIP_SPECS: dict[str, list[str]] = {
    # Pin <1.0: the 1.x line pulls onnxruntime + downloads a layout model and
    # drops image extraction — keep the lightweight, image-capable pre-1.0 line.
    "pymupdf4llm": ["pymupdf4llm>=0.0.17,<1.0"],
    "markitdown": ["markitdown[pdf,docx,pptx,xlsx]>=0.0.1a2"],
    "docling": ["docling>=2.0.0"],
}

# Engine id -> console-script argv that downloads its model weights. The script
# is resolved next to the server's python first (same env), then on PATH.
ENGINE_MODEL_DOWNLOADERS: dict[str, list[str]] = {
    "docling": ["docling-tools", "models", "download"],
}

# Buffered log lines kept in memory; older lines are dropped (the cursor
# protocol keeps clients consistent across trims).
_MAX_LINES = 2000
_LINE_MIN_INTERVAL = 0.2


def installable_engines() -> frozenset[str]:
    """Engine ids that support one-click pip install."""
    return frozenset(ENGINE_PIP_SPECS)


def model_downloadable_engines() -> frozenset[str]:
    """Engine ids that support one-click model-weight download."""
    return frozenset(ENGINE_MODEL_DOWNLOADERS)


def resolve_model_downloader(engine: str) -> Optional[list[str]]:
    """Resolve the model-download argv for ``engine``.

    Locates the console script next to the server's python first (same env so it
    matches the installed engine), then falls back to PATH. Returns ``None`` if
    the engine has no downloader or the script isn't found.
    """
    parts = ENGINE_MODEL_DOWNLOADERS.get(engine)
    if not parts:
        return None
    name = parts[0]
    sibling = Path(sys.executable).parent / name
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return [str(sibling), *parts[1:]]
    found = shutil.which(name)
    if found:
        return [found, *parts[1:]]
    return None


def _invalidate_import_caches() -> None:
    """Make a freshly installed package importable in this process and bust the
    cached "" version so readiness flips without a server restart."""
    try:
        importlib.invalidate_caches()
        package_version.cache_clear()
    except Exception:  # noqa: BLE001 - best effort
        logger.exception("Post-install cache invalidation failed")


class BackgroundJobManager:
    """At most one background subprocess (install or model download), with a
    cursor-based line log.

    States: ``idle`` → ``running`` → ``done`` / ``failed`` / ``cancelled``.
    ``status(cursor)`` returns lines after ``cursor`` plus ``next_cursor`` so the
    UI can poll incrementally; ``kind`` (``install`` | ``models``) and ``engine``
    tell the UI which job/card the log belongs to.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = "idle"
        self._kind = ""
        self._engine = ""
        self._lines: list[str] = []
        self._base = 0
        self._message = ""
        self._process: subprocess.Popen | None = None
        self._cancel_requested = False

    def start_install(self, *, engine: str, specs: list[str]) -> dict[str, Any]:
        cmd = [sys.executable, "-m", "pip", "install", "--no-input", *specs]
        return self._launch(
            kind="install",
            engine=engine,
            cmd=cmd,
            env={"PIP_DISABLE_PIP_VERSION_CHECK": "1"},
            on_success=_invalidate_import_caches,
        )

    def start_model_download(self, *, engine: str, cmd: list[str]) -> dict[str, Any]:
        return self._launch(kind="models", engine=engine, cmd=cmd)

    def status(self, cursor: int = 0) -> dict[str, Any]:
        with self._lock:
            start = max(int(cursor) - self._base, 0)
            return {
                "state": self._state,
                "kind": self._kind,
                "engine": self._engine,
                "lines": list(self._lines[start:]),
                "next_cursor": self._base + len(self._lines),
                "message": self._message,
            }

    def cancel(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
            running = self._state == "running"
            if running:
                self._cancel_requested = True
        if not (running and process):
            return {"ok": False, "message": "No job is running."}
        if process.poll() is None:
            try:
                process.terminate()
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "message": f"Failed to cancel: {exc}"}
        return {"ok": True, "message": ""}

    # ------------------------------------------------------------------

    def _launch(
        self,
        *,
        kind: str,
        engine: str,
        cmd: list[str],
        env: Optional[dict[str, str]] = None,
        on_success: Optional[Callable[[], None]] = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._state == "running":
                return {
                    "ok": False,
                    "message": f"A {self._kind or 'job'} is already running ({self._engine}).",
                }
            try:
                process = subprocess.Popen(  # nosec B603 - argv from fixed allow-lists
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    shell=False,
                    env={**os.environ, **(env or {})},
                )
            except Exception as exc:  # noqa: BLE001
                self._state = "failed"
                self._kind = kind
                self._engine = engine
                self._message = f"Failed to launch: {exc}"
                return {"ok": False, "message": self._message}
            self._state = "running"
            self._kind = kind
            self._engine = engine
            self._lines = []
            self._base = 0
            self._message = ""
            self._process = process
            self._cancel_requested = False
            thread = threading.Thread(
                target=self._pump, args=(process, kind, engine, on_success), daemon=True
            )
            thread.start()
            logger.info("Parser %s job started (%s): %s", kind, engine, " ".join(cmd))
            return {"ok": True, "message": ""}

    def _pump(
        self,
        process: subprocess.Popen,
        kind: str,
        engine: str,
        on_success: Optional[Callable[[], None]],
    ) -> None:
        last_emit = 0.0
        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                now = time.monotonic()
                if now - last_emit < _LINE_MIN_INTERVAL:
                    continue
                last_emit = now
                self._append(line[:300])
        except Exception:
            logger.exception("Background job output pump failed")
        returncode = process.wait()
        with self._lock:
            if self._cancel_requested:
                self._state = "cancelled"
                self._message = "Cancelled."
            elif returncode == 0:
                self._state = "done"
                self._message = "Finished."
            else:
                self._state = "failed"
                self._message = f"Exited with code {returncode}."
            self._process = None
        if returncode == 0 and not self._cancel_requested and on_success is not None:
            on_success()
        logger.info("Parser %s job finished (%s): %s", kind, engine, self._state)

    def _append(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
            overflow = len(self._lines) - _MAX_LINES
            if overflow > 0:
                del self._lines[:overflow]
                self._base += overflow


_manager = BackgroundJobManager()


def get_background_job_manager() -> BackgroundJobManager:
    return _manager


__all__ = [
    "ENGINE_MODEL_DOWNLOADERS",
    "ENGINE_PIP_SPECS",
    "BackgroundJobManager",
    "get_background_job_manager",
    "installable_engines",
    "model_downloadable_engines",
    "resolve_model_downloader",
]
