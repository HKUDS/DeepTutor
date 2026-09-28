from __future__ import annotations

import pytest

from deeptutor.services.session.pocketbase_store import PocketBaseSessionStore
from deeptutor.services.session.scope import pocketbase_scope
from deeptutor.services.workspace.context import workspace_context
from tests.services.session.test_pocketbase_isolation import fake_pb as fake_pb
from tests.services.workspace.test_data_scope import account as account


@pytest.mark.asyncio
async def test_pocketbase_lists_and_direct_ids_are_partitioned(account, fake_pb):
    a = account.create_workspace("A")["workspace_id"]
    b = account.create_workspace("B")["workspace_id"]
    store = PocketBaseSessionStore()
    with workspace_context(a):
        session = await store.create_session("A private", session_id="scope_a")
        message = await store.add_message(session["id"], "user", "Private")
        turn = await store.create_turn(session["id"])
    for wid in (b, ""):
        with workspace_context(wid):
            assert await store.list_sessions() == []
            assert await store.get_session(session["id"]) is None
            assert await store.get_messages(session["id"]) == []
            assert await store.get_turn(turn["id"]) is None
            assert await store.get_turn_events(turn["id"]) == []
            assert await store.delete_message(message) is False
            assert await store.update_session_title(session["id"], "Leak") is False
    with workspace_context(a):
        assert len(await store.list_sessions()) == 1
        assert (await store.get_messages(session["id"]))[0]["content"] == "Private"


@pytest.mark.asyncio
async def test_provider_store_keeps_captured_workspace_after_switch(account, fake_pb):
    a = account.create_workspace("A")["workspace_id"]
    b = account.create_workspace("B")["workspace_id"]
    with workspace_context(a):
        fixed = PocketBaseSessionStore()
        fixed.store_scope = pocketbase_scope("http://test")
    with workspace_context(b):
        row = await fixed.create_session("Finish A")
        assert row["preferences"]["workspace_id"] == a
        assert await PocketBaseSessionStore().get_session(row["id"]) is None


@pytest.mark.asyncio
async def test_pocketbase_migration_rebinds_verified_rows(account, fake_pb, monkeypatch):
    from deeptutor.services.workspace.data_migration import migrate_data

    monkeypatch.setattr(
        "deeptutor.services.workspace.data_migration._backend", lambda: "pocketbase"
    )
    target = account.create_workspace("Target")["workspace_id"]
    store = PocketBaseSessionStore()
    with workspace_context():
        row = await store.create_session("Move PB")
        await store.add_message(row["id"], "user", "Keep content")
    assert migrate_data("", target, ["chat"])["status"] == "completed"
    with workspace_context():
        assert await store.get_session(row["id"]) is None
    with workspace_context(target):
        assert (await store.get_messages(row["id"]))[0]["content"] == "Keep content"


@pytest.mark.asyncio
async def test_pocketbase_migration_keeps_local_quiz_store(account, fake_pb, monkeypatch):
    from deeptutor.services.session import get_sqlite_session_store
    from deeptutor.services.workspace.data_migration import migrate_data

    monkeypatch.setattr(
        "deeptutor.services.workspace.data_migration._backend", lambda: "pocketbase"
    )
    target = account.create_workspace("Quiz target")["workspace_id"]
    with workspace_context():
        remote = await PocketBaseSessionStore().create_session(
            "PB session", session_id="same_session"
        )
        local = get_sqlite_session_store()
        await local.create_session("Quiz session", session_id=remote["id"])
        await local.upsert_notebook_entries(
            remote["id"], [{"question_id": "q", "question": "Keep this quiz"}]
        )
    assert migrate_data("", target, ["chat"])["status"] == "completed"
    with workspace_context(target):
        entries = await get_sqlite_session_store().list_notebook_entries()
        assert entries["items"][0]["question"] == "Keep this quiz"
        assert await PocketBaseSessionStore().get_session(remote["id"])
    with workspace_context():
        assert not (await local.list_notebook_entries())["items"]
