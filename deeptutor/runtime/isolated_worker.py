"""Run memory-heavy, importable functions in short-lived subprocesses.

Unlike ``multiprocessing.spawn``, the fixed ``python -m`` entry point works
from Uvicorn, the CLI, notebooks, ``python -c``, and frozen test runners
without requiring callers to guard their own main module. Arguments and
results travel through private temporary pickle files; callable paths are
fixed by DeepTutor code and are never accepted from an API request.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
import pickle
import subprocess  # nosec B404 - fixed interpreter/module argv, no shell
import sys
import tempfile
import threading
from typing import Any

DEFAULT_ISOLATED_TIMEOUT_SECONDS = 120.0
_WORKER_MODULE = "deeptutor.runtime.worker_process"


def _worker_limit() -> int:
    try:
        return max(1, int(os.environ.get("DEEPTUTOR_ISOLATED_WORKERS", "2") or "2"))
    except ValueError:
        return 2


MAX_CONCURRENT_ISOLATED_WORKERS = _worker_limit()
_WORKER_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_ISOLATED_WORKERS)


class IsolatedWorkerError(RuntimeError):
    """A callable failed inside an isolated worker process."""

    def __init__(
        self,
        message: str,
        *,
        remote_module: str = "",
        remote_type: str = "",
        remote_traceback: str = "",
        remote_attrs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.remote_module = remote_module
        self.remote_type = remote_type
        self.remote_traceback = remote_traceback
        self.remote_attrs = remote_attrs or {}


class IsolatedWorkerTimeout(TimeoutError):
    """An isolated call exceeded its wall-clock deadline."""


class IsolatedWorkerCrashed(IsolatedWorkerError):
    """The child exited without returning a protocol envelope."""


def _write_request(
    path: Path,
    callable_path: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    path.write_bytes(
        pickle.dumps(
            {"callable_path": callable_path, "args": args, "kwargs": kwargs},
            protocol=pickle.HIGHEST_PROTOCOL,
        )
    )


def _read_envelope(path: Path, callable_path: str, stderr: bytes = b"") -> Any:
    if not path.is_file():
        detail = stderr.decode("utf-8", errors="replace").strip()[-2000:]
        suffix = f": {detail}" if detail else ""
        raise IsolatedWorkerCrashed(
            f"Isolated call {callable_path!r} exited without a result{suffix}"
        )
    try:
        envelope = pickle.loads(path.read_bytes())  # noqa: S301 - private trusted child file
    except Exception as exc:
        raise IsolatedWorkerCrashed(
            f"Isolated call {callable_path!r} returned an invalid result"
        ) from exc
    return _unwrap(envelope, callable_path)


def _unwrap(envelope: object, callable_path: str) -> Any:
    if not isinstance(envelope, dict):
        raise IsolatedWorkerCrashed(f"Isolated call {callable_path!r} returned an invalid envelope")
    if envelope.get("ok") is True:
        return envelope.get("result")
    raise IsolatedWorkerError(
        str(envelope.get("message") or f"Isolated call {callable_path!r} failed"),
        remote_module=str(envelope.get("module") or ""),
        remote_type=str(envelope.get("type") or ""),
        remote_traceback=str(envelope.get("traceback") or ""),
        remote_attrs=(
            dict(envelope.get("attrs")) if isinstance(envelope.get("attrs"), dict) else {}
        ),
    )


def _command(request_path: Path, result_path: Path) -> list[str]:
    return [sys.executable, "-m", _WORKER_MODULE, str(request_path), str(result_path)]


def run_in_isolated_process_sync(
    callable_path: str,
    *args: Any,
    timeout: float = DEFAULT_ISOLATED_TIMEOUT_SECONDS,
    kwargs: dict[str, Any] | None = None,
) -> Any:
    """Run an importable synchronous callable and block until it exits."""

    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    with _WORKER_SLOTS:
        with tempfile.TemporaryDirectory(prefix="deeptutor-worker-") as temp_dir:
            request_path = Path(temp_dir) / "request.pickle"
            result_path = Path(temp_dir) / "result.pickle"
            _write_request(request_path, callable_path, tuple(args), dict(kwargs or {}))
            process = subprocess.Popen(  # noqa: S603 - fixed argv and shell=False
                _command(request_path, result_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            try:
                _stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()
                raise IsolatedWorkerTimeout(
                    f"Isolated call {callable_path!r} exceeded {timeout:g} seconds"
                ) from exc
            return _read_envelope(result_path, callable_path, stderr)


async def _stop_async_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=1.0)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()


async def run_in_isolated_process(
    callable_path: str,
    *args: Any,
    timeout: float = DEFAULT_ISOLATED_TIMEOUT_SECONDS,
    kwargs: dict[str, Any] | None = None,
) -> Any:
    """Run a synchronous callable without blocking the caller's event loop.

    Cancelling the coroutine terminates and joins the child before cancellation
    is re-raised, so a disconnected request cannot leave an orphan parser.
    """

    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    acquired = False
    try:
        while not acquired:
            acquired = _WORKER_SLOTS.acquire(blocking=False)
            if not acquired:
                await asyncio.sleep(0.02)
        with tempfile.TemporaryDirectory(prefix="deeptutor-worker-") as temp_dir:
            request_path = Path(temp_dir) / "request.pickle"
            result_path = Path(temp_dir) / "result.pickle"
            _write_request(request_path, callable_path, tuple(args), dict(kwargs or {}))
            process = await asyncio.create_subprocess_exec(
                *_command(request_path, result_path),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError as exc:
                await _stop_async_process(process)
                raise IsolatedWorkerTimeout(
                    f"Isolated call {callable_path!r} exceeded {timeout:g} seconds"
                ) from exc
            except asyncio.CancelledError:
                await asyncio.shield(_stop_async_process(process))
                raise
            return _read_envelope(result_path, callable_path, stderr)
    finally:
        if acquired:
            _WORKER_SLOTS.release()


__all__ = [
    "DEFAULT_ISOLATED_TIMEOUT_SECONDS",
    "IsolatedWorkerCrashed",
    "IsolatedWorkerError",
    "IsolatedWorkerTimeout",
    "MAX_CONCURRENT_ISOLATED_WORKERS",
    "run_in_isolated_process",
    "run_in_isolated_process_sync",
]
