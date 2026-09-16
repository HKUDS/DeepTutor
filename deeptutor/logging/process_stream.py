"""Process-log event capture for user-visible operational logs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import inspect
import logging
from typing import Any

from .context import LOG_CONTEXT_FIELDS
from .formatters import ContextFilter

PROCESS_LOG_PRIVATE_ATTR = "deeptutor_process_log_private"


@dataclass(frozen=True)
class ProcessLogEvent:
    type: str = "process_log"
    level: str = "INFO"
    message: str = ""
    logger: str = ""
    timestamp: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, record: logging.LogRecord) -> "ProcessLogEvent":
        context = dict(getattr(record, "log_context", {}) or {})
        for key in LOG_CONTEXT_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                context[key] = value
        return cls(
            level=record.levelname,
            message=record.getMessage(),
            logger=record.name,
            timestamp=record.created,
            context=context,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "level": self.level,
            "message": self.message,
            "logger": self.logger,
            "timestamp": self.timestamp,
            "context": self.context,
        }


class ProcessLogHandler(logging.Handler):
    """Emit structured process-log events from matching records."""

    def __init__(
        self,
        emit: Callable[[ProcessLogEvent], Any],
        *,
        task_id: str | None = None,
        turn_id: str | None = None,
        min_level: int = logging.INFO,
    ) -> None:
        super().__init__(level=min_level)
        self._emit = emit
        self._task_id = task_id
        self._turn_id = turn_id
        # The loop that owns this capture, remembered while we are still on
        # it. A record logged from a worker thread has no running loop of its
        # own, and that is where an async ``emit`` used to be dropped (#1435).
        try:
            self._loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self.addFilter(ContextFilter())

    def _schedule(self, coro: Any) -> None:
        """Run an async ``emit`` on the loop that owns this capture.

        Retrieval does its heavy work in worker threads, so its log records
        arrive off-loop. ``ensure_future`` needs a loop running in *this*
        thread; the owning loop is the one that can always take the call.
        """
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None:
            asyncio.ensure_future(coro, loop=running)
            return
        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._loop)
            return
        # Nothing is left to deliver to — the capture outlived its loop.
        # Close it explicitly so an undeliverable event does not also
        # surface as a "never awaited" warning with no context.
        coro.close()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if getattr(record, PROCESS_LOG_PRIVATE_ATTR, False):
                return
            event = ProcessLogEvent.from_record(record)
            if self._task_id and event.context.get("task_id") != self._task_id:
                return
            if self._turn_id and event.context.get("turn_id") != self._turn_id:
                return
            result = self._emit(event)
            if inspect.isawaitable(result):
                self._schedule(result)
        except Exception:
            self.handleError(record)


@contextmanager
def capture_process_logs(
    emit: Callable[[ProcessLogEvent], Any],
    *,
    task_id: str | None = None,
    turn_id: str | None = None,
    min_level: int = logging.INFO,
) -> Iterator[ProcessLogHandler]:
    """Capture matching stdlib log records and emit ``ProcessLogEvent`` objects."""
    handler = ProcessLogHandler(
        emit,
        task_id=task_id,
        turn_id=turn_id,
        min_level=min_level,
    )
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        handler.close()
