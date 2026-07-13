"""Persistent, cancellable consolidator runs.

A "run" is one invocation of :func:`run_update` / :func:`run_audit` /
:func:`run_dedup`. The run is owned by an asyncio task; events flow
through a buffered ring so a disconnecting client can re-attach by
posting ``since=<cursor>`` to the events endpoint and replay everything
it missed.

Why an in-memory manager instead of a DB:
- Memory consolidator runs are minutes-long at most.
- Crash / restart wipes them — that's acceptable; the docs themselves
  are atomically written per step and the meta-id-diff still gives us
  "what's new since last refresh" correctness on restart.

Concurrency rules
-----------------
At most one **active** run per ``(layer, key)``. Starting a second run
while the first is active returns ``RunBusyError``. Once a run reaches
a terminal status (``done`` / ``cancelled`` / ``error``) it stays in
the registry indefinitely so the UI can re-attach to see the final
trace; older runs evict on FIFO when ``_MAX_HISTORY`` is exceeded.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Awaitable, Callable, Literal
import uuid

logger = logging.getLogger(__name__)

RunMode = Literal["update", "audit", "dedup"]
RunStatus = Literal["queued", "running", "cancelled", "done", "error"]

_MAX_EVENTS_PER_RUN = 2000
_MAX_HISTORY = 200


@dataclass
class RunEvent:
    seq: int  # 0-based, monotonic per run
    ts: str  # ISO-8601 UTC
    payload: dict[str, Any]


@dataclass
class UndoCheckpoint:
    id: str
    ts: str
    layer: str
    key: str
    path: str
    existed: bool
    previous_content: str
    action: str
    turn: int | None = None
    label: str | None = None


@dataclass
class Run:
    id: str
    layer: str
    key: str
    mode: RunMode
    params: dict[str, Any]
    language: str
    user_label: str
    status: RunStatus = "queued"
    started_at: str = ""
    ended_at: str | None = None
    error: str | None = None
    events: list[RunEvent] = field(default_factory=list)
    undo_stack: list[UndoCheckpoint] = field(default_factory=list)
    _waiters: list[asyncio.Event] = field(default_factory=list, repr=False)
    _task: asyncio.Task | None = field(default=None, repr=False)
    _cancel_flag: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "layer": self.layer,
            "key": self.key,
            "mode": self.mode,
            "params": self.params,
            "language": self.language,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "error": self.error,
            "event_count": len(self.events),
            "undo_count": len(self.undo_stack),
        }


class RunBusyError(RuntimeError):
    """Raised when a (layer, key) already has an active run."""


# ContextVar holds the current Run for handlers running inside the task.
# Mode code uses :func:`emit` indirectly via ``modes._runtime.emit``;
# we install our own on_event that pushes into the active run too.
_current_run: ContextVar[Run | None] = ContextVar("memory_run", default=None)


class RunManager:
    """Process-wide singleton — one manager owns every consolidator run.

    The instance is created on first call to :func:`get_run_manager`.
    """

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._order: list[str] = []  # FIFO for eviction
        self._active: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()

    # ── Lookup ─────────────────────────────────────────────────────────

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def active_for(self, layer: str, key: str) -> Run | None:
        run_id = self._active.get((layer, key))
        if run_id is None:
            return None
        run = self._runs.get(run_id)
        return run if run is not None and run.active else None

    def list_for(self, layer: str | None = None, key: str | None = None) -> list[Run]:
        out: list[Run] = []
        for rid in self._order:
            run = self._runs.get(rid)
            if run is None:
                continue
            if layer is not None and run.layer != layer:
                continue
            if key is not None and run.key != key:
                continue
            out.append(run)
        return out

    # ── Start ──────────────────────────────────────────────────────────

    async def start(
        self,
        *,
        layer: str,
        key: str,
        mode: RunMode,
        runner: Callable[[Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[None]],
        params: dict[str, Any] | None = None,
        language: str = "en",
        user_label: str = "anonymous",
    ) -> Run:
        """Register and kick off a new run.

        ``runner`` is an awaitable factory: takes a ``on_event`` callback
        and runs the consolidator mode. The manager wires the callback to
        the event buffer + waiter machinery.
        """
        async with self._lock:
            if self.active_for(layer, key) is not None:
                raise RunBusyError(f"a run is already in progress for {layer}/{key}")
            run = Run(
                id=uuid.uuid4().hex,
                layer=layer,
                key=key,
                mode=mode,
                params=dict(params or {}),
                language=language,
                user_label=user_label,
                status="queued",
                started_at=_now_iso(),
            )
            self._runs[run.id] = run
            self._order.append(run.id)
            self._active[(layer, key)] = run.id
            self._evict_if_needed()

        run._task = asyncio.create_task(self._drive(run, runner))
        return run

    async def cancel(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run is None or not run.active:
            return False
        run._cancel_flag.set()
        if run._task is not None and not run._task.done():
            run._task.cancel()
        return True

    async def undo_last(self, run_id: str) -> RunEvent | None:
        """Restore the document snapshot before the latest run write."""
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.active:
            raise RunBusyError("cancel the active run before undoing memory edits")
        if not run.undo_stack:
            return None

        checkpoint = run.undo_stack.pop()
        path = Path(checkpoint.path)
        if checkpoint.existed:
            await asyncio.to_thread(_atomic_write, path, checkpoint.previous_content)
        else:
            await asyncio.to_thread(_remove_if_exists, path)

        return await self._emit(
            run,
            {
                "stage": "undo_applied",
                "run_id": run.id,
                "undo_id": checkpoint.id,
                "undo_depth": len(run.undo_stack),
                "layer": checkpoint.layer,
                "key": checkpoint.key,
                "turn": checkpoint.turn,
                "label": checkpoint.label,
                "action": checkpoint.action,
            },
        )

    # ── Event subscription ─────────────────────────────────────────────

    async def wait_for_events(self, run: Run, *, since: int) -> list[RunEvent]:
        """Return events since cursor; block until new ones arrive or done."""
        if since < 0:
            since = 0
        # Fast path: events already buffered past cursor.
        if since < len(run.events):
            return run.events[since:]
        if not run.active:
            return []
        waiter = asyncio.Event()
        run._waiters.append(waiter)
        try:
            await waiter.wait()
        finally:
            try:
                run._waiters.remove(waiter)
            except ValueError:
                pass
        if since < len(run.events):
            return run.events[since:]
        return []

    # ── Drive ──────────────────────────────────────────────────────────

    async def _drive(
        self,
        run: Run,
        runner: Callable[[Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[None]],
    ) -> None:
        token = _current_run.set(run)
        run.status = "running"
        await self._emit(run, {"stage": "run_started", "run_id": run.id, "mode": run.mode})
        try:

            async def on_event(evt: dict[str, Any]) -> None:
                await self._emit(run, evt)

            await runner(on_event)
            if run.status == "running":
                run.status = "done"
        except asyncio.CancelledError:
            run.status = "cancelled"
            await self._emit(run, {"stage": "cancelled"})
        except Exception as exc:  # noqa: BLE001
            run.status = "error"
            run.error = str(exc)
            logger.warning(
                "consolidator run failed (id=%s layer=%s key=%s mode=%s): %s",
                run.id,
                run.layer,
                run.key,
                run.mode,
                exc,
                exc_info=True,
            )
            await self._emit(run, {"stage": "error", "message": str(exc)})
        finally:
            run.ended_at = _now_iso()
            await self._emit(run, {"stage": "run_ended", "status": run.status})
            self._active.pop((run.layer, run.key), None)
            # Wake any remaining waiters so they observe the terminal state.
            for w in list(run._waiters):
                w.set()
            _current_run.reset(token)

    async def _emit(self, run: Run, payload: dict[str, Any]) -> RunEvent:
        event = RunEvent(seq=len(run.events), ts=_now_iso(), payload=payload)
        run.events.append(event)
        if len(run.events) > _MAX_EVENTS_PER_RUN:
            # Drop the oldest non-meta event but renumber tail to keep
            # monotonic seq stable — clients use seq to resume.
            run.events.pop(0)
            for i, ev in enumerate(run.events):
                run.events[i] = RunEvent(seq=i, ts=ev.ts, payload=ev.payload)
        for w in list(run._waiters):
            w.set()
        return event

    def _evict_if_needed(self) -> None:
        while len(self._order) > _MAX_HISTORY:
            old = self._order.pop(0)
            run = self._runs.pop(old, None)
            if run is not None and run.active:
                # Active runs are protected from eviction.
                self._runs[old] = run
                self._order.insert(0, old)
                return


_manager: RunManager | None = None


def get_run_manager() -> RunManager:
    global _manager
    if _manager is None:
        _manager = RunManager()
    return _manager


def reset_run_manager_for_tests() -> None:
    global _manager
    _manager = None


def current_run() -> Run | None:
    """Return the run currently driving the active task, if any.

    Used by the LLM-IO event emitter so it can attach per-turn payloads
    to whichever run is calling out to the model.
    """
    return _current_run.get()


def push_undo_checkpoint(
    *,
    layer: str,
    key: str,
    path: Path,
    existed: bool,
    previous_content: str,
    action: str,
    turn: int | None = None,
    label: str | None = None,
) -> int:
    """Register a per-write rollback snapshot on the active run."""
    run = _current_run.get()
    if run is None:
        return 0
    run.undo_stack.append(
        UndoCheckpoint(
            id=uuid.uuid4().hex,
            ts=_now_iso(),
            layer=layer,
            key=key,
            path=str(path),
            existed=existed,
            previous_content=previous_content,
            action=action,
            turn=turn,
            label=label,
        )
    )
    return len(run.undo_stack)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_str, path)
    finally:
        if os.path.exists(tmp_str):
            try:
                os.remove(tmp_str)
            except OSError:
                pass


def _remove_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


__all__ = [
    "Run",
    "RunBusyError",
    "RunEvent",
    "RunManager",
    "RunMode",
    "RunStatus",
    "UndoCheckpoint",
    "current_run",
    "get_run_manager",
    "push_undo_checkpoint",
    "reset_run_manager_for_tests",
]
