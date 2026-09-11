from __future__ import annotations

import asyncio
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
async def test_remote_worker_subscribes_and_cancels_owner_turn(monkeypatch, tmp_path) -> None:
    hold = asyncio.Event()

    class Engine:
        async def execute(self, _context):
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                content="owner output",
            )
            await hold.wait()

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
    received: list[dict] = []

    async def collect() -> None:
        async for event in app_b.subscribe_turn(turn["id"]):
            received.append(event)

    subscriber = asyncio.create_task(collect())
    for _ in range(100):
        if any(event["type"] == "content" for event in received):
            break
        await asyncio.sleep(0.01)
    assert await app_b.cancel_turn(turn["id"], command_id="cancel-from-b") is True
    await asyncio.wait_for(subscriber, timeout=3)

    assert [event["seq"] for event in received] == sorted({event["seq"] for event in received})
    assert [event["type"] for event in received][-2:] == ["error", "done"]
    persisted = await store_b.get_turn(turn["id"])
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    await runtime_a.close()
    await runtime_b.close()


@pytest.mark.asyncio
async def test_remote_worker_reply_reaches_owner_waiter(monkeypatch, tmp_path) -> None:
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
    assert await app_b.submit_user_reply(turn["id"], "yes", command_id="reply-from-b") is True
    events = [event async for event in app_b.subscribe_turn(turn["id"])]

    assert any(event.get("content") == "reply:yes" for event in events)
    # DONE is not the last frame of a completed turn: the runtime publishes
    # post-turn metadata (the LLM-written session title) after it, and a
    # subscriber has to receive that too — dropping it is what left finished
    # conversations sitting on "New conversation". Assert the shape instead of
    # asserting DONE is last: everything after DONE must be post-turn metadata.
    done_index = next(i for i, event in enumerate(events) if event["type"] == "done")
    assert all(event["type"] == "session_meta" for event in events[done_index + 1 :])
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    await runtime_a.close()
    await runtime_b.close()
