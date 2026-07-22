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
    _instance: "KnowledgeTaskStreamManager | None" = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._lock = threading.Lock()
        self._buffers: dict[str, deque[dict[str, Any]]] = {}
        self._subscribers: dict[str, list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]]] = {}

    @classmethod
    def get_instance(cls) -> "KnowledgeTaskStreamManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def ensure_task(self, task_id: str):
        with self._lock:
            self._buffers.setdefault(task_id, deque(maxlen=500))
            self._subscribers.setdefault(task_id, [])

    def emit(self, task_id: str, event: str, payload: dict[str, Any]):
        event_payload = {"event": event, "payload": payload}
        with self._lock:
            self._buffers.setdefault(task_id, deque(maxlen=500)).append(event_payload)
            subscribers = list(self._subscribers.get(task_id, []))

        for queue, loop in subscribers:
            try:
                loop.call_soon_threadsafe(self._queue_event, queue, event_payload)
            except RuntimeError:
                continue

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
            self._buffers.setdefault(task_id, deque(maxlen=500))
            self._subscribers.setdefault(task_id, []).append((queue, loop))
            backlog = list(self._buffers[task_id])
        return queue, backlog, loop

    def unsubscribe(
        self, task_id: str, queue: asyncio.Queue[dict[str, Any]], loop: asyncio.AbstractEventLoop
    ):
        with self._lock:
            subscribers = self._subscribers.get(task_id, [])
            self._subscribers[task_id] = [
                (subscriber_queue, subscriber_loop)
                for subscriber_queue, subscriber_loop in subscribers
                if subscriber_queue is not queue or subscriber_loop is not loop
            ]

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
