"""One-click MinerU model download.

Wraps the ``mineru-models-download`` CLI (MinerU 2.x) in a background job the
settings UI can start, poll, and cancel. The same source/endpoint settings
also feed the parse subprocess via :func:`model_env_overrides`, so a lazy
first-parse download honors the configured mirror even when the user never
pressed the explicit Download button.

Download sources map onto MinerU's own mechanisms:

* ``MINERU_MODEL_SOURCE`` — ``huggingface`` (default) or ``modelscope``.
* ``HF_ENDPOINT`` — standard huggingface_hub mirror override (e.g.
  ``https://hf-mirror.com``); only meaningful for the huggingface source.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

DOWNLOADER_NAME = "mineru-models-download"
MODEL_TYPES = ("pipeline", "vlm", "all")
DOWNLOAD_SOURCES = ("huggingface", "modelscope")

# Buffered log lines kept in memory; older lines are dropped (the cursor
# protocol keeps clients consistent across trims).
_MAX_LINES = 2000
_LINE_MIN_INTERVAL = 0.3


def resolve_models_downloader(local_cli_path: str = "") -> dict[str, Any]:
    """Locate the ``mineru-models-download`` executable.

    When ``local_cli_path`` is configured, the downloader must live next to it
    (same env ``bin/``) — no silent fallback to PATH, mirroring the parse-side
    rule that a configured path means "use exactly this install". Returns
    ``{found, path}``; ``path`` carries the expected location even on a miss
    so error messages can point at it.
    """
    configured = (local_cli_path or "").strip()
    if configured:
        sibling = Path(configured).expanduser().parent / DOWNLOADER_NAME
        found = sibling.is_file() and os.access(sibling, os.X_OK)
        return {"found": found, "path": str(sibling)}
    path = shutil.which(DOWNLOADER_NAME)
    if path:
        return {"found": True, "path": path}
    return {"found": False, "path": ""}


def model_env_overrides(source: str, endpoint: str = "") -> dict[str, str]:
    """Env vars that steer where MinerU fetches model weights from.

    Returned dict contains only the override keys (callers merge over
    ``os.environ``). ``endpoint`` is the custom download address; it maps to
    ``HF_ENDPOINT`` and is ignored for the modelscope source.
    """
    src = source if source in DOWNLOAD_SOURCES else "huggingface"
    overrides = {"MINERU_MODEL_SOURCE": src}
    cleaned = (endpoint or "").strip().rstrip("/")
    if cleaned and src == "huggingface":
        overrides["HF_ENDPOINT"] = cleaned
    return overrides


class ModelDownloadManager:
    """At most one model-download subprocess, with a cursor-based line log.

    States: ``idle`` → ``running`` → ``done`` / ``failed`` / ``cancelled``.
    ``status(cursor)`` returns lines after ``cursor`` plus ``next_cursor`` so
    the UI can poll incrementally; trimming old lines shifts an internal base
    offset instead of breaking cursors.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = "idle"
        self._lines: list[str] = []
        self._base = 0
        self._message = ""
        self._process: subprocess.Popen | None = None
        self._cancel_requested = False

    def start(
        self,
        *,
        downloader: str,
        model_type: str,
        source: str,
        endpoint: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            if self._state == "running":
                return {"ok": False, "message": "A model download is already running."}
            mt = model_type if model_type in MODEL_TYPES else "pipeline"
            src = source if source in DOWNLOAD_SOURCES else "huggingface"
            cmd = [downloader, "-s", src, "-m", mt]
            env = {**os.environ, **model_env_overrides(src, endpoint)}
            try:
                process = subprocess.Popen(  # nosec B603 — argv from validated resolver
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    shell=False,
                    env=env,
                )
            except Exception as exc:
                self._state = "failed"
                self._message = f"Failed to launch downloader: {exc}"
                return {"ok": False, "message": self._message}
            self._state = "running"
            self._lines = []
            self._base = 0
            self._message = ""
            self._process = process
            self._cancel_requested = False
            thread = threading.Thread(target=self._pump, args=(process,), daemon=True)
            thread.start()
            logger.info("MinerU model download started: %s", " ".join(cmd))
            return {"ok": True, "message": ""}

    def status(self, cursor: int = 0) -> dict[str, Any]:
        with self._lock:
            start = max(int(cursor) - self._base, 0)
            return {
                "state": self._state,
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
            return {"ok": False, "message": "No model download is running."}
        if process.poll() is None:
            try:
                process.terminate()
            except Exception as exc:
                return {"ok": False, "message": f"Failed to cancel: {exc}"}
        return {"ok": True, "message": ""}

    # ------------------------------------------------------------------

    def _pump(self, process: subprocess.Popen) -> None:
        last_emit = 0.0
        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                # tqdm-style \r progress arrives as many lines per second
                # (universal newlines); the throttle keeps memory and polling
                # payloads bounded without losing the narrative.
                now = time.monotonic()
                if now - last_emit < _LINE_MIN_INTERVAL:
                    continue
                last_emit = now
                self._append(line[:300])
        except Exception:
            logger.exception("Model download output pump failed")
        returncode = process.wait()
        with self._lock:
            if self._cancel_requested:
                self._state = "cancelled"
                self._message = "Download cancelled."
            elif returncode == 0:
                self._state = "done"
                self._message = "Download finished."
            else:
                self._state = "failed"
                self._message = f"Downloader exited with code {returncode}."
            self._process = None
        logger.info("MinerU model download finished: %s", self._state)

    def _append(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
            overflow = len(self._lines) - _MAX_LINES
            if overflow > 0:
                del self._lines[:overflow]
                self._base += overflow


_manager = ModelDownloadManager()


def get_model_download_manager() -> ModelDownloadManager:
    return _manager


__all__ = [
    "DOWNLOAD_SOURCES",
    "MODEL_TYPES",
    "ModelDownloadManager",
    "get_model_download_manager",
    "model_env_overrides",
    "resolve_models_downloader",
]
