from __future__ import annotations

import pytest

from deeptutor.services.session import get_sqlite_session_store
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.data_migration import migrate_data
from tests.services.workspace.test_data_scope import account as account


@pytest.mark.asyncio
async def test_move_renumbers_turn_events_instead_of_colliding(account):
    """``turn_events.id`` is a surrogate; unrelated destination ids must not block."""
    target = account.create_workspace("Destination")["workspace_id"]
    with workspace_context():
        store = get_sqlite_session_store()
        session = await store.create_session("With events")
        turn = await store.create_turn(session["id"])
        await store.update_turn_status(turn["id"], "completed")
        await store.append_turn_events(
            turn["id"],
            [
                {"type": "content", "content": "first"},
                {"type": "content", "content": "second"},
            ],
        )
    with workspace_context(target):
        target_store = get_sqlite_session_store()
        other = await target_store.create_session("Existing")
        other_turn = await target_store.create_turn(other["id"])
        await target_store.update_turn_status(other_turn["id"], "completed")
        await target_store.append_turn_events(
            other_turn["id"], [{"type": "content", "content": "existing"}]
        )

    migrate_data("", target, ["chat"])

    with workspace_context(target):
        events = await get_sqlite_session_store().get_turn_events(turn["id"])
        assert [event["content"] for event in events] == ["first", "second"]
