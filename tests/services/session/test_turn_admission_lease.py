"""Rejected admissions must leave the session free for another request."""

from __future__ import annotations

import pytest

from deeptutor.runtime.coordination.memory import MemoryCoordinator
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["selection", "preferences", "begin"])
async def test_rejected_admission_releases_coordinator_lease(tmp_path, monkeypatch, failure):
    """Validate rejection using a real store and the production coordinator."""
    store = SQLiteSessionStore(tmp_path / "admission.db")
    coordinator = MemoryCoordinator()
    runtime = TurnRuntimeManager(store, coordinator=coordinator, owner_id="worker")
    session = await store.create_session()
    payload = {
        "type": "start_turn",
        "session_id": session["id"],
        "capability": "chat",
        "content": "hello",
        "tools": [],
        "knowledge_bases": [],
        "attachments": [],
        "language": "en",
        "config": {},
    }
    if failure == "selection":
        payload["config"] = {"selection_tutor_context": {"selected_text": " "}}
        expected = "requires selected text"
    else:

        async def reject(*args, **kwargs):
            raise RuntimeError("admission storage failure")

        method = "update_session_preferences" if failure == "preferences" else "begin_turn"
        monkeypatch.setattr(store, method, reject)
        expected = "admission storage failure"
    try:
        for _ in range(2):
            with pytest.raises(RuntimeError, match=expected):
                await runtime.start_turn(payload)
            assert await store.get_active_turn(session["id"]) is None
            lease = await coordinator.acquire_turn(
                "probe", f"{runtime._coordination_scope}:{session['id']}", "probe-worker"
            )
            assert lease is not None
            assert await coordinator.release_turn(lease)
    finally:
        await runtime.close()
        await coordinator.close()
