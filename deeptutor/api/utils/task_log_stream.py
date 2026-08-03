import asyncio
from collections import deque
from collections.abc import AsyncGenerator
import contextlib
import importlib
import json
import logging
import threading
import time
from typing import Any

from deeptutor.logging import (
    ProcessLogEvent,
    bind_log_context,
    capture_process_logs,
    current_log_context,
)


def _format_sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


class KnowledgeTaskStreamManager:
    _MAX_EVENTS_PER_TASK = 500
    _MAX_BYTES_PER_TASK = 2 * 1024 * 1024
    _MAX_RETAINED_TASKS = 32
    _MAX_TERMINAL_TOMBSTONES = 256
    _TERMINAL_TTL_SECONDS = 60 * 60
    _TOMBSTONE_TTL_SECONDS = 24 * 60 * 60

    _instance: "KnowledgeTaskStreamManager | None" = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._lock = threading.Lock()
        self._buffers: dict[str, deque[dict[str, Any]]] = {}
        self._buffer_bytes: dict[str, int] = {}
        self._subscribers: dict[str, list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]]] = {}
        self._terminal_at: dict[str, float] = {}
        self._terminal_tombstones: dict[str, tuple[float, dict[str, Any]]] = {}

    @classmethod
    def get_instance(cls) -> "KnowledgeTaskStreamManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def ensure_task(self, task_id: str):
        with self._lock:
            self._prune_locked(time.monotonic())
            if task_id not in self._buffers:
                restored = self._terminal_tombstones.pop(task_id, None)
                self._buffers[task_id] = deque(maxlen=self._MAX_EVENTS_PER_TASK)
                self._buffer_bytes[task_id] = 0
                if restored is not None:
                    terminal_at, event = restored
                    self._append_locked(task_id, event)
                    self._terminal_at[task_id] = terminal_at
            self._subscribers.setdefault(task_id, [])

    def emit(self, task_id: str, event: str, payload: dict[str, Any]):
        event_payload = {"event": event, "payload": payload}
        with self._lock:
            self._buffers.setdefault(task_id, deque(maxlen=self._MAX_EVENTS_PER_TASK))
            self._buffer_bytes.setdefault(task_id, 0)
            self._append_locked(task_id, event_payload)
            if event in {"complete", "failed"}:
                self._terminal_at[task_id] = time.monotonic()
            subscribers = list(self._subscribers.get(task_id, []))
            self._prune_locked(time.monotonic())

        for queue, loop in subscribers:
            try:
                loop.call_soon_threadsafe(self._queue_event, queue, event_payload)
            except RuntimeError:
                continue
        if event in {"complete", "failed"}:
            self._schedule_memory_reclaim()

    def emit_process_log(self, task_id: str, event: ProcessLogEvent):
        payload = event.to_dict()
        payload.setdefault("context", {})["task_id"] = task_id
        self.emit(task_id, "process_log", payload)

    def emit_log(self, task_id: str, line: str):
        event = ProcessLogEvent(
            level="INFO",
            message=line,
            logger="deeptutor.knowledge.task",
            timestamp=time.time(),
            context={"task_id": task_id, "capability": "knowledge", "sink": "ui"},
        )
        self.emit_process_log(task_id, event)

    def emit_complete(self, task_id: str, detail: str = "Task completed"):
        self.emit(task_id, "complete", {"detail": detail, "task_id": task_id})

    def emit_failed(self, task_id: str, detail: str, *, details: str | None = None):
        payload: dict[str, Any] = {"detail": detail, "task_id": task_id}
        if details:
            payload["details"] = details
        self.emit(task_id, "failed", payload)

    def subscribe(
        self, task_id: str
    ) -> tuple[asyncio.Queue[dict[str, Any]], list[dict[str, Any]], asyncio.AbstractEventLoop]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        loop = asyncio.get_running_loop()
        with self._lock:
            self._prune_locked(time.monotonic())
            if task_id not in self._buffers:
                restored = self._terminal_tombstones.pop(task_id, None)
                self._buffers[task_id] = deque(maxlen=self._MAX_EVENTS_PER_TASK)
                self._buffer_bytes[task_id] = 0
                if restored is not None:
                    terminal_at, event = restored
                    self._append_locked(task_id, event)
                    self._terminal_at[task_id] = terminal_at
            self._subscribers.setdefault(task_id, []).append((queue, loop))
            backlog = list(self._buffers[task_id])
        return queue, backlog, loop

    def unsubscribe(
        self, task_id: str, queue: asyncio.Queue[dict[str, Any]], loop: asyncio.AbstractEventLoop
    ):
        with self._lock:
            subscribers = self._subscribers.get(task_id, [])
            remaining = [
                (subscriber_queue, subscriber_loop)
                for subscriber_queue, subscriber_loop in subscribers
                if subscriber_queue is not queue or subscriber_loop is not loop
            ]
            if remaining:
                self._subscribers[task_id] = remaining
            else:
                self._subscribers.pop(task_id, None)
            self._prune_locked(time.monotonic())

    @staticmethod
    def _event_bytes(event: dict[str, Any]) -> int:
        try:
            return len(json.dumps(event, ensure_ascii=False, default=str).encode("utf-8"))
        except Exception:
            return 256

    def _append_locked(self, task_id: str, event: dict[str, Any]) -> None:
        buffer = self._buffers[task_id]
        size = self._event_bytes(event)
        while buffer and (
            len(buffer) >= self._MAX_EVENTS_PER_TASK
            or self._buffer_bytes.get(task_id, 0) + size > self._MAX_BYTES_PER_TASK
        ):
            removed = buffer.popleft()
            self._buffer_bytes[task_id] = max(
                0, self._buffer_bytes.get(task_id, 0) - self._event_bytes(removed)
            )
        # Keep a single oversized terminal/error event so a subscriber always
        # observes task completion. Its traceback is clipped to the hard byte
        # budget rather than retaining an arbitrary multi-megabyte payload.
        if size > self._MAX_BYTES_PER_TASK:
            compact = {
                "event": event.get("event", "process_log"),
                "payload": {
                    "detail": str((event.get("payload") or {}).get("detail") or "")[:8192],
                    "truncated": True,
                },
            }
            event = compact
            size = self._event_bytes(event)
        buffer.append(event)
        self._buffer_bytes[task_id] = self._buffer_bytes.get(task_id, 0) + size

    def _drop_task_locked(self, task_id: str) -> None:
        buffer = self._buffers.pop(task_id, None)
        terminal_at = self._terminal_at.pop(task_id, None)
        if buffer and terminal_at is not None:
            terminal = next(
                (item for item in reversed(buffer) if item.get("event") in {"complete", "failed"}),
                None,
            )
            if terminal is not None:
                self._terminal_tombstones[task_id] = (terminal_at, terminal)
        self._buffer_bytes.pop(task_id, None)
        if not self._subscribers.get(task_id):
            self._subscribers.pop(task_id, None)

    def _prune_locked(self, now: float) -> None:
        for task_id, terminal_at in list(self._terminal_at.items()):
            if now - terminal_at >= self._TERMINAL_TTL_SECONDS and not self._subscribers.get(
                task_id
            ):
                self._drop_task_locked(task_id)

        overflow = len(self._buffers) - self._MAX_RETAINED_TASKS
        if overflow > 0:
            candidates = sorted(
                (
                    (terminal_at, task_id)
                    for task_id, terminal_at in self._terminal_at.items()
                    if not self._subscribers.get(task_id)
                )
            )
            for _, task_id in candidates[:overflow]:
                self._drop_task_locked(task_id)

        expired_tombstones = [
            task_id
            for task_id, (terminal_at, _) in self._terminal_tombstones.items()
            if now - terminal_at >= self._TOMBSTONE_TTL_SECONDS
        ]
        for task_id in expired_tombstones:
            self._terminal_tombstones.pop(task_id, None)
        overflow = len(self._terminal_tombstones) - self._MAX_TERMINAL_TOMBSTONES
        if overflow > 0:
            oldest = sorted(
                self._terminal_tombstones,
                key=lambda task_id: self._terminal_tombstones[task_id][0],
            )
            for task_id in oldest[:overflow]:
                self._terminal_tombstones.pop(task_id, None)

    def retained_task_count(self) -> int:
        with self._lock:
            self._prune_locked(time.monotonic())
            return len(self._buffers)

    @staticmethod
    def _schedule_memory_reclaim() -> None:
        """Run after the producing coroutine unwinds and releases job locals."""
        from deeptutor.runtime.memory_reclaim import schedule_memory_reclaim

        schedule_memory_reclaim()

    async def stream(self, task_id: str) -> AsyncGenerator[str, None]:
        queue, backlog, loop = self.subscribe(task_id)
        try:
            for item in backlog:
                yield _format_sse(item["event"], item["payload"])

            if backlog and backlog[-1]["event"] in {"complete", "failed"}:
                return

            while True:
                item = await queue.get()
                yield _format_sse(item["event"], item["payload"])
                if item["event"] in {"complete", "failed"}:
                    break
        finally:
            self.unsubscribe(task_id, queue, loop)

    @staticmethod
    def _queue_event(queue: asyncio.Queue[dict[str, Any]], payload: dict[str, Any]):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass


class _TaskScopedLogHandler(logging.Handler):
    """Forward non-propagating library logs into one knowledge task stream."""

    def __init__(self, task_id: str, manager: KnowledgeTaskStreamManager) -> None:
        super().__init__(logging.INFO)
        self._task_id = task_id
        self._manager = manager

    def emit(self, record: logging.LogRecord) -> None:
        try:
            context = current_log_context()
            record_task_id = context.get("task_id")
            if record_task_id and record_task_id != self._task_id:
                return

            context.setdefault("task_id", self._task_id)
            context.setdefault("capability", "knowledge")
            context.setdefault("sink", "ui")
            self._manager.emit_process_log(
                self._task_id,
                ProcessLogEvent(
                    level=record.levelname,
                    message=record.getMessage(),
                    logger=record.name,
                    timestamp=record.created,
                    context=context,
                ),
            )
        except Exception:
            self.handleError(record)


@contextlib.contextmanager
def _capture_non_propagating_task_logs(task_id: str, manager: KnowledgeTaskStreamManager):
    """Capture library loggers that intentionally do not propagate to root."""
    logger_names = ("lightrag", "graphrag", "graphrag_llm")
    handlers: list[tuple[logging.Logger, _TaskScopedLogHandler]] = []
    for logger_name in logger_names:
        if logger_name == "lightrag":
            with contextlib.suppress(Exception):
                importlib.import_module("lightrag.utils")
        source_logger = logging.getLogger(logger_name)
        if source_logger.propagate:
            continue
        handler = _TaskScopedLogHandler(task_id, manager)
        source_logger.addHandler(handler)
        handlers.append((source_logger, handler))

    try:
        yield
    finally:
        for source_logger, handler in handlers:
            if handler in source_logger.handlers:
                source_logger.removeHandler(handler)
            handler.close()


@contextlib.contextmanager
def capture_task_logs(task_id: str):
    """Forward all logs bound to ``task_id`` into the task's SSE stream."""
    manager = KnowledgeTaskStreamManager.get_instance()
    manager.ensure_task(task_id)

    def emit(event: ProcessLogEvent) -> None:
        manager.emit_process_log(task_id, event)

    with bind_log_context(task_id=task_id, capability="knowledge", sink="ui"):
        with capture_process_logs(emit, task_id=task_id):
            with _capture_non_propagating_task_logs(task_id, manager):
                yield


def get_task_stream_manager() -> KnowledgeTaskStreamManager:
    return KnowledgeTaskStreamManager.get_instance()
