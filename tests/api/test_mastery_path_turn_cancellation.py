from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import mastery_path as router


@pytest.mark.asyncio
async def test_path_mutation_waits_for_waiting_turn_and_releases_lease(monkeypatch):
    learning_store = SimpleNamespace(
        get_path_lease=lambda _book_id: SimpleNamespace(
            session_id="session", turn_id="waiting-turn"
        ),
        release_path_lease=Mock(),
    )
    turns = SimpleNamespace(cancel_turn_and_wait=AsyncMock(return_value=True))
    monkeypatch.setattr(router, "LearningStore", lambda: learning_store)
    monkeypatch.setattr(router, "_turn_application_service", lambda: turns)

    await router._cancel_active_learning_turn("path")

    turns.cancel_turn_and_wait.assert_awaited_once_with("waiting-turn")
    learning_store.release_path_lease.assert_called_once_with("path", turn_id="waiting-turn")


@pytest.mark.asyncio
async def test_path_mutation_keeps_lease_when_cancellation_times_out(monkeypatch):
    learning_store = SimpleNamespace(
        get_path_lease=lambda _book_id: SimpleNamespace(
            session_id="session", turn_id="waiting-turn"
        ),
        release_path_lease=Mock(),
    )
    turns = SimpleNamespace(cancel_turn_and_wait=AsyncMock(return_value=False))
    monkeypatch.setattr(router, "LearningStore", lambda: learning_store)
    monkeypatch.setattr(router, "_turn_application_service", lambda: turns)

    with pytest.raises(HTTPException) as exc:
        await router._cancel_active_learning_turn("path")

    assert exc.value.status_code == 409
    learning_store.release_path_lease.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_mastery_session_lookup_uses_application_cancellation(monkeypatch):
    learning_store = SimpleNamespace(
        get_path_lease=lambda _book_id: None,
        list_session_ids=lambda _book_id: ["session"],
    )

    async def list_active_turns(session_id):
        if session_id == "session":
            return [{"id": "turn", "capability": "mastery_path"}]
        return []

    session_store = SimpleNamespace(list_active_turns=list_active_turns)
    turns = SimpleNamespace(cancel_turn_and_wait=AsyncMock(return_value=True))
    monkeypatch.setattr(router, "LearningStore", lambda: learning_store)
    monkeypatch.setattr("deeptutor.services.session.get_session_store", lambda: session_store)
    monkeypatch.setattr(router, "_turn_application_service", lambda: turns)

    await router._cancel_active_learning_turn("path")

    turns.cancel_turn_and_wait.assert_awaited_once_with("turn")
