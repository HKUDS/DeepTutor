"""A permanently closed runtime must reject subsequent admissions."""

from __future__ import annotations

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


@pytest.mark.asyncio
@pytest.mark.parametrize("drain_timeout", [0.0, 0.1])
async def test_closed_runtime_rejects_turn_without_creating_session(tmp_path, drain_timeout):
    """Shutdown stays final even when no managed application update is active."""
    store = SQLiteSessionStore(tmp_path / "close.db")
    runtime = TurnRuntimeManager(store)
    await runtime.close(drain_timeout_seconds=drain_timeout)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="closed"):
            await runtime.start_turn(
                {
                    "type": "start_turn",
                    "capability": "chat",
                    "content": "hello",
                    "tools": [],
                    "knowledge_bases": [],
                    "attachments": [],
                    "language": "en",
                    "config": {},
                }
            )
        assert await store.list_sessions() == []
        assert await store.list_nonterminal_turns() == []
    await runtime.close()
