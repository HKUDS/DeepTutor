from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from deeptutor.app.service import TurnApplicationService
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


class _ContextBuilder:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def build(self, **_kwargs):
        return SimpleNamespace(
            conversation_history=[],
            conversation_summary="",
            context_text="",
            token_count=0,
            budget=0,
        )


def _application(store, runtime, coordinator) -> TurnApplicationService:
    return TurnApplicationService(
        SimpleNamespace(get=lambda: store),
        SimpleNamespace(get=lambda _store: runtime),
        coordinator,
    )


def _payload() -> dict:
    return {
        "content": "hello",
        "capability": "chat",
        "tools": [],
        "knowledge_bases": [],
        "attachments": [],
        "language": "en",
        "config": {},
    }


@pytest.mark.asyncio
async def test_reply_accepted_after_local_queue_dropped_is_never_delivered(
    monkeypatch, tmp_path, caplog
) -> None:
    """A reply that outlives its turn's local waiter is ACKed but never delivered."""
    waiting = asyncio.Event()

    class Engine:
        async def execute(self, context):
            yield StreamEvent(
                type=StreamEventType.WAIT_FOR_INPUT,
                source="chat",
                content="Continue?",
            )
            waiting.set()
            reply = await context.runtime.wait_for_user_reply()
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                content=f"reply:{reply['text']}",
            )

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", _ContextBuilder
    )
    coordinator = MemoryCoordinator(lease_ttl_seconds=5)
    path = tmp_path / "shared.sqlite3"
    store_a = SQLiteSessionStore(path)
    store_b = SQLiteSessionStore(path)
    runtime_a = TurnRuntimeManager(
        store_a, coordinator=coordinator, owner_id="worker-a", turn_engine=Engine()
    )
    runtime_b = TurnRuntimeManager(
        store_b, coordinator=coordinator, owner_id="worker-b", turn_engine=Engine()
    )
    app_a = _application(store_a, runtime_a, coordinator)
    app_b = _application(store_b, runtime_b, coordinator)

    _session, turn = await app_a.start_turn(_payload())
    await asyncio.wait_for(waiting.wait(), timeout=2)
    for _ in range(100):
        active = await app_b.check_active_turn(turn["session_id"])
        if active and active["status"] == "waiting_input":
            break
        await asyncio.sleep(0.01)
    assert active is not None
    assert active["status"] == "waiting_input"

    # Simulate the state executor.py's own comment anticipates: the local
    # waiter is gone (e.g. a dead/superseded turn), while the coordinator's
    # lease (what TurnApplicationService actually gates on) is untouched.
    dropped_queue = runtime_a._reply_queues.pop(turn["id"])
    assert dropped_queue is not None

    with caplog.at_level(logging.WARNING):
        accepted = await app_b.submit_user_reply(turn["id"], "yes", command_id="late-reply-from-b")
        assert accepted is True  # the false-positive ACK

        # Give worker A's coordination loop a few polls to consume the command.
        for _ in range(20):
            await asyncio.sleep(0.05)

    persisted = await store_b.get_turn(turn["id"])
    assert persisted is not None
    assert persisted["status"] == "waiting_input"  # stuck forever, exactly as reported

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("late-reply-from-b" in r.getMessage() for r in warnings), (
        "a reply that was accepted but never delivered must be logged so an "
        "operator can tell the three failure modes #1297 asks to distinguish"
    )

    await runtime_a.close()
    await runtime_b.close()
