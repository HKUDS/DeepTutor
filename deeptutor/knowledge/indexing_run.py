"""Durable per-KB indexing state and ownership at reliable boundaries (#1612).

Parsing caches remain the reusable work store. This journal records what was
accepted, parsed, failed, published, or unknown after interruption; it is not a
queue or a second parsing cache.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any
from uuid import uuid4

try:
    import psutil
except ImportError:  # CLI-only installs need no process-monitor dependency.
    psutil = None

from deeptutor.services.file_io import atomic_write_json

_CURRENT: ContextVar[IndexingRun | None] = ContextVar("indexing_run", default=None)
_TERMINAL = {"completed", "partial", "failed", "cancelled", "interrupted"}


class IndexingBusyError(RuntimeError):
    pass


class IndexingCancelled(RuntimeError):
    pass


def current_run() -> IndexingRun | None:
    return _CURRENT.get()


def _redact(detail: str) -> str:
    text = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[redacted]", str(detail))
    text = re.sub(
        r"(?i)((?:api[_-]?key|token|secret|password|signature|authorization)\s*[=:]\s*)[^\s&]+",
        r"\1[redacted]",
        text,
    )
    text = re.sub(
        r'(?i)(["\']?(?:api[_-]?key|token|secret|password|signature|authorization)["\']?\s*[:=]\s*)["\'][^"\']*["\']',
        r'\1"[redacted]"',
        text,
    )
    text = re.sub(r"(https?://)[^/\s@]+:[^/\s@]+@", r"\1[redacted]@", text)
    return text[-1600:]


def failure_code(exc: BaseException) -> str:
    text = str(exc).casefold()
    if isinstance(exc, (TimeoutError,)) or "timeout" in text or "timed out" in text:
        return "timeout"
    if isinstance(exc, MemoryError) or "out of memory" in text or "resource exhausted" in text:
        return "resource_exhaustion"
    if (
        isinstance(exc, (FileNotFoundError, ModuleNotFoundError))
        or "not installed" in text
        or "cli_missing" in text
    ):
        return "dependency_missing"
    if "unsupported" in text or "doesn't support" in text:
        return "unsupported_input"
    if "download" in text:
        return "model_download_failed"
    if "embedding" in text or "vector" in text:
        return "embedding_failed"
    if "no content" in text or "no output" in text or "invalid" in text:
        return "invalid_output"
    return "runtime_failure"


def load_run(kb_dir: Path) -> dict[str, Any] | None:
    path = Path(kb_dir) / ".indexing-run.json"
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise OSError("Indexing journal is unreadable; original file preserved.") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema") != 1
        or not isinstance(value.get("documents"), dict)
    ):
        raise OSError("Indexing journal is invalid; original file preserved.")
    try:
        cancelled = json.loads((Path(kb_dir) / ".indexing-cancel.json").read_text())
    except FileNotFoundError:
        cancelled = {}
    except (OSError, ValueError) as exc:
        raise OSError(
            "Indexing cancellation state is unreadable; original file preserved."
        ) from exc
    value["cancel_requested"] = bool(
        isinstance(cancelled, dict) and cancelled.get("task_id") == value.get("task_id")
    )
    return value


def _lease_is_held(kb_dir: Path) -> bool:
    try:
        with (Path(kb_dir) / ".indexing.lock").open("r+b") as lease:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(lease.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lease.fileno(), fcntl.LOCK_UN)
        return False
    except FileNotFoundError:
        return False
    except OSError:
        return True


def visible_run(kb_dir: Path) -> dict[str, Any] | None:
    """Pure projection: a crashed owner's in-flight work becomes unknown."""
    value = load_run(kb_dir)
    if value is None or value.get("state") in _TERMINAL:
        return value
    try:
        alive = (
            psutil.Process(int(value["pid"])).create_time() == value["process_started_at"]
            if psutil is not None
            else _lease_is_held(kb_dir)
        )
    except Exception:
        alive = False
    if alive:
        return value
    documents = {
        key: {
            **doc,
            "status": "unknown"
            if doc.get("status") in {"pending", "parsing", "embedding"}
            else doc.get("status"),
        }
        for key, doc in value["documents"].items()
    }
    return {
        **value,
        "state": "interrupted",
        "documents": documents,
        "recovery": "Retry reuses validated parser outputs and completed slices. The interrupted uncheckpointed stage restarts.",
    }


class IndexingRun:
    def __init__(
        self,
        kb_dir: Path,
        sources: list[str],
        *,
        task_id: str = "",
        action: str = "rebuild",
        provider: str = "",
        reporter=None,
    ):
        self.kb_dir = Path(kb_dir)
        self.path = self.kb_dir / ".indexing-run.json"
        self.task_id = task_id or f"index_{uuid4().hex}"
        self.action = action
        self.provider = provider
        self.sources = sources
        self.reporter = reporter
        self._mutex = threading.RLock()
        self.active = False
        self.data: dict[str, Any] = {}
        self._lock = None
        self._token = None
        self._source_paths: dict[str, Path] = {}

    def __enter__(self):
        return self._start()

    async def __aenter__(self):
        future = asyncio.create_task(asyncio.to_thread(self._start, False))
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            await future
            self.finish("cancelled")
            self.active = False
            self._release()
            raise
        self._token = _CURRENT.set(self)
        return self

    async def __aexit__(self, kind, exc, traceback):
        self.__exit__(kind, exc, traceback)

    def _start(self, bind_context=True):
        self.kb_dir.mkdir(parents=True, exist_ok=True)
        self._lock = (self.kb_dir / ".indexing.lock").open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                self._lock.seek(0)
                if not self._lock.read(1):
                    self._lock.write(b"\0")
                    self._lock.flush()
                self._lock.seek(0)
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lock.close()
            raise IndexingBusyError(
                "An indexing worker still owns this knowledge base. Wait for it to settle before retrying."
            ) from exc
        try:
            previous = visible_run(self.kb_dir)
            now = time.time()
            self.data = {
                "schema": 1,
                "task_id": self.task_id,
                "action": self.action,
                "provider": self.provider,
                "pid": os.getpid(),
                "process_started_at": psutil.Process().create_time()
                if psutil is not None
                else None,
                "state": "running",
                "phase": "preflight",
                "started_at": now,
                "last_activity_at": now,
                "last_progress_at": now,
                "documents": {},
                "previous_task_id": previous.get("task_id") if previous else None,
                "recovery": "Validated parser caches and completed slices are reused. Uncheckpointed stages restart.",
                "cancel_requested": False,
                "usable_version": None,
            }
            from deeptutor.services.rag.file_routing import FileTypeRouter

            candidates = list(dict.fromkeys(self.sources))
            raw = self.kb_dir / "raw"
            if self.action != "upload" and raw.is_dir():
                candidates.extend(
                    str(path)
                    for path in raw.rglob("*")
                    if path.is_file() and not path.is_symlink() and str(path) not in candidates
                )
            classification = FileTypeRouter.classify_files(candidates)
            unsupported = set(classification.unsupported)
            for name in candidates:
                source = Path(name)
                key = self.source_key(source)
                self._source_paths[key] = source
                try:
                    digest = self._hash(source)
                    reason = "unsupported_input" if name in unsupported else ""
                    status = "excluded" if reason else "pending"
                except OSError as exc:
                    digest, reason, status = "", _redact(str(exc)), "failed"
                self.data["documents"][key] = {
                    "status": status,
                    "reason": reason,
                    "source_hash": digest,
                    "parse_reused": False,
                }
            self.active = True
            if bind_context:
                self._token = _CURRENT.set(self)
            self._save()
            return self
        except BaseException:
            self.active = False
            if self._token is not None:
                _CURRENT.reset(self._token)
            self._release()
            raise

    def __exit__(self, kind, exc, traceback):
        try:
            if exc is not None:
                self.finish(
                    "partial"
                    if self.data.get("usable_version")
                    else "cancelled"
                    if isinstance(exc, IndexingCancelled)
                    or (load_run(self.kb_dir) or {}).get("cancel_requested")
                    else "failed",
                    version=self.data.get("usable_version"),
                    error=exc,
                )
            elif self.data.get("state") not in _TERMINAL:
                self.finish("failed", error=RuntimeError("Index readiness was not verified."))
        finally:
            self.active = False
            if self._token is not None:
                _CURRENT.reset(self._token)
            self._release()

    def _release(self):
        if self._lock is not None and not self._lock.closed:
            if sys.platform == "win32":
                import msvcrt

                self._lock.seek(0)
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._lock.fileno(), fcntl.LOCK_UN)
            self._lock.close()

    def source_key(self, source: Path) -> str:
        try:
            return source.resolve().relative_to((self.kb_dir / "raw").resolve()).as_posix()
        except ValueError:
            return (
                f"external-{sha256(str(source.resolve()).encode()).hexdigest()[:12]}/{source.name}"
            )

    @staticmethod
    def _hash(source: Path) -> str:
        digest = sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def check(self):
        if not self.active:
            raise IndexingCancelled("This indexing worker no longer owns the run.")
        stored = load_run(self.kb_dir)
        if stored and stored.get("task_id") != self.task_id:
            raise IndexingCancelled("A newer run owns the indexing journal.")
        if stored and stored.get("cancel_requested"):
            self.data["cancel_requested"] = True
            raise IndexingCancelled(
                "Cancellation reached a safe boundary; validated completed parsing remains reusable."
            )

    def phase(
        self,
        phase: str,
        *,
        source: Path | None = None,
        current: int | None = None,
        total: int | None = None,
        activity: str = "",
    ):
        with self._mutex:
            self.check()
            now = time.time()
            changed = self.data.get("phase") != phase or (
                current is not None and current != self.data.get("phase_current")
            )
            self.data.update(
                {
                    "phase": phase,
                    "last_activity_at": now,
                    "current_document": self.source_key(source)
                    if source
                    else self.data.get("current_document"),
                    "phase_current": current,
                    "phase_total": total,
                    "activity": _redact(activity),
                }
            )
            if changed:
                self.data["last_progress_at"] = now
            self._save()

    def document(self, source: Path, status: str, **details):
        with self._mutex:
            if not self.active:
                return
            stored = load_run(self.kb_dir)
            if stored and stored.get("task_id") != self.task_id:
                return
            key = self.source_key(source)
            doc = self.data["documents"].setdefault(key, {})
            doc.update({"status": status, "updated_at": time.time(), **details})
            self.data["last_progress_at"] = time.time()
            self._save()

    def verify_sources(self):
        self.check()
        for key, doc in self.data["documents"].items():
            if doc.get("status") in {"parsed", "embedding", "completed"}:
                if self._hash(self._source_paths[key]) != doc.get("source_hash"):
                    raise RuntimeError(
                        f"Source changed during indexing: {key}. Retry with the current source."
                    )

    def finish(self, state: str, *, version: str | None = None, error: BaseException | None = None):
        with self._mutex:
            if not self.active:
                return
            stored = load_run(self.kb_dir)
            if stored and stored.get("task_id") != self.task_id:
                return
            for doc in self.data["documents"].values():
                if doc.get("status") in {"pending", "parsing", "embedding", "parsed"}:
                    doc["status"] = "unknown"
            self.data.update(
                {
                    "state": state,
                    "finished_at": time.time(),
                    "usable_version": version,
                    "error_code": failure_code(error) if error else None,
                    "error": _redact(str(error)) if error else None,
                }
            )
            self._save()

    def _save(self):
        atomic_write_json(self.path, self.data)
        if self.reporter is not None:
            try:
                self.reporter(dict(self.data))
            except Exception:
                # Notification delivery cannot invalidate the durable checkpoint.
                pass


def request_cancel(kb_dir: Path, task_id: str) -> bool:
    value = load_run(kb_dir)
    if value is None or value.get("task_id") != task_id or value.get("state") in _TERMINAL:
        return False
    atomic_write_json(
        Path(kb_dir) / ".indexing-cancel.json", {"task_id": task_id, "requested_at": time.time()}
    )
    return True
