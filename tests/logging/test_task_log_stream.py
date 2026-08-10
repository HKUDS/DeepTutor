import json
import logging

import pytest

from deeptutor.api.utils.task_log_stream import (
    KnowledgeTaskStreamManager,
    capture_task_logs,
    get_task_stream_manager,
)


@pytest.mark.asyncio
async def test_knowledge_task_stream_emits_process_log_sse_event():
    manager = KnowledgeTaskStreamManager()
    manager.ensure_task("task-1")
    manager.emit_log("task-1", "Indexing started")

    stream = manager.stream("task-1")
    try:
        chunk = await anext(stream)
    finally:
        await stream.aclose()

    lines = chunk.splitlines()
    header, data_line = lines[:2]
    assert header == "event: process_log"
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload["type"] == "process_log"
    assert payload["message"] == "Indexing started"
    assert payload["context"]["task_id"] == "task-1"


def test_capture_task_logs_forwards_lightrag_non_propagating_logger():
    original_instance = KnowledgeTaskStreamManager._instance
    lightrag_logger = logging.getLogger("lightrag")
    original_handlers = list(lightrag_logger.handlers)
    original_propagate = lightrag_logger.propagate
    original_level = lightrag_logger.level
    try:
        KnowledgeTaskStreamManager._instance = KnowledgeTaskStreamManager()
        lightrag_logger.handlers = []
        lightrag_logger.propagate = False
        lightrag_logger.setLevel(logging.INFO)

        with capture_task_logs("task-native"):
            lightrag_logger.info("Chunk 1 of 1 extracted 14 Ent + 13 Rel")

        manager = get_task_stream_manager()
        events = list(manager._buffers["task-native"])
    finally:
        KnowledgeTaskStreamManager._instance = original_instance
        lightrag_logger.handlers = original_handlers
        lightrag_logger.propagate = original_propagate
        lightrag_logger.setLevel(original_level)

    assert any(
        event["event"] == "process_log"
        and event["payload"]["logger"] == "lightrag"
        and event["payload"]["message"] == "Chunk 1 of 1 extracted 14 Ent + 13 Rel"
        and event["payload"]["context"]["task_id"] == "task-native"
        for event in events
    )


def test_capture_task_logs_forwards_graphrag_propagating_logger_once():
    original_instance = KnowledgeTaskStreamManager._instance
    graphrag_logger = logging.getLogger("graphrag.api.query")
    original_handlers = list(graphrag_logger.handlers)
    original_propagate = graphrag_logger.propagate
    original_level = graphrag_logger.level
    try:
        KnowledgeTaskStreamManager._instance = KnowledgeTaskStreamManager()
        graphrag_logger.handlers = []
        graphrag_logger.propagate = True
        graphrag_logger.setLevel(logging.INFO)

        with capture_task_logs("task-graphrag"):
            graphrag_logger.info("GraphRAG local search selected 3 text units")

        manager = get_task_stream_manager()
        events = list(manager._buffers["task-graphrag"])
    finally:
        KnowledgeTaskStreamManager._instance = original_instance
        graphrag_logger.handlers = original_handlers
        graphrag_logger.propagate = original_propagate
        graphrag_logger.setLevel(original_level)

    matches = [
        event
        for event in events
        if event["event"] == "process_log"
        and event["payload"]["logger"] == "graphrag.api.query"
        and event["payload"]["message"] == "GraphRAG local search selected 3 text units"
        and event["payload"]["context"]["task_id"] == "task-graphrag"
    ]
    assert len(matches) == 1


def test_completed_task_buffers_are_bounded_and_restore_terminal_event():
    manager = KnowledgeTaskStreamManager()
    manager._MAX_RETAINED_TASKS = 3

    for index in range(8):
        task_id = f"task-{index}"
        manager.ensure_task(task_id)
        manager.emit_log(task_id, "x" * 100)
        manager.emit_complete(task_id)

    assert manager.retained_task_count() == 3
    assert len(manager._terminal_tombstones) == 5

    manager.ensure_task("task-0")
    restored = list(manager._buffers["task-0"])
    assert restored[-1]["event"] == "complete"


def test_task_buffer_has_approximate_byte_ceiling():
    manager = KnowledgeTaskStreamManager()
    manager._MAX_BYTES_PER_TASK = 2_000
    manager.ensure_task("large-task")

    for _ in range(20):
        manager.emit_log("large-task", "x" * 500)

    assert manager._buffer_bytes["large-task"] <= manager._MAX_BYTES_PER_TASK
    assert len(manager._buffers["large-task"]) < 20
