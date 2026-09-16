import asyncio
import logging
import threading
import warnings

from deeptutor.logging import (
    PROCESS_LOG_PRIVATE_ATTR,
    ProcessLogEvent,
    bind_log_context,
    capture_process_logs,
)


def test_capture_process_logs_emits_structured_event_for_matching_task():
    events: list[ProcessLogEvent] = []
    logger = logging.getLogger("deeptutor.tests.process")
    original_level = logger.level
    logger.setLevel(logging.INFO)

    try:
        with bind_log_context(task_id="task-1", capability="knowledge", stage="indexing"):
            with capture_process_logs(events.append, task_id="task-1"):
                logger.info("Embedding batches: %s/%s", 2, 8)
    finally:
        logger.setLevel(original_level)

    assert len(events) == 1
    event = events[0].to_dict()
    assert event["type"] == "process_log"
    assert event["level"] == "INFO"
    assert event["message"] == "Embedding batches: 2/8"
    assert event["logger"] == "deeptutor.tests.process"
    assert event["context"] == {
        "task_id": "task-1",
        "capability": "knowledge",
        "stage": "indexing",
    }


def test_capture_process_logs_filters_other_tasks():
    events: list[ProcessLogEvent] = []
    logger = logging.getLogger("deeptutor.tests.process")

    with capture_process_logs(events.append, task_id="task-1"):
        with bind_log_context(task_id="task-2"):
            logger.warning("wrong task")

    assert events == []


def test_capture_process_logs_excludes_server_only_diagnostics():
    events: list[ProcessLogEvent] = []
    logger = logging.getLogger("deeptutor.tests.process")

    with bind_log_context(task_id="task-1", capability="knowledge"):
        with capture_process_logs(events.append, task_id="task-1"):
            logger.error(
                "Stack trace contains sk-secret-must-not-leak",
                extra={PROCESS_LOG_PRIVATE_ATTR: True},
            )

    assert events == []


def test_async_emit_from_a_worker_thread_still_reaches_the_stream():
    """Retrieval logs from worker threads; its progress events must survive.

    KB indexing and retrieval run their heavy work off the event loop, so the
    records they log arrive on a thread with no loop of its own. The handler
    used to drop the coroutine an async sink returned in exactly that case —
    the event never reached the reader and Python reported only
    ``coroutine '...' was never awaited`` (#1435).
    """
    seen: list[str] = []

    async def scenario() -> None:
        async def emit(event: ProcessLogEvent) -> None:
            seen.append(event.message)

        logger = logging.getLogger("deeptutor.tests.process")
        original_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            with capture_process_logs(emit, min_level=logging.INFO):
                worker = threading.Thread(target=lambda: logger.info("retrieving chunk 3/8"))
                worker.start()
                worker.join()
                # Hand the loop a turn so the cross-thread call can run.
                await asyncio.sleep(0)
                await asyncio.sleep(0)
        finally:
            logger.setLevel(original_level)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        asyncio.run(scenario())

    assert seen == ["retrieving chunk 3/8"]
    assert [w for w in caught if "never awaited" in str(w.message)] == []
