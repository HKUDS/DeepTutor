from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import sessions as router
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@pytest.mark.asyncio
async def test_delete_removes_conversation_descendants_and_messages(tmp_path, monkeypatch):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    for sid, parent in (("root", ""), ("child", "root"), ("grandchild", "child"), ("other", "")):
        await store.create_session(session_id=sid, title=sid)
        await store.add_message(sid, "user", "private conversation")
        await store.update_session_preferences(sid, {"parent_session_id": parent, "archived": True})
    monkeypatch.setattr(router, "get_session_store", lambda: store)
    attachments = SimpleNamespace(delete_session=AsyncMock())
    learning = SimpleNamespace(detach_session=Mock())
    monkeypatch.setattr(router, "get_attachment_store", lambda: attachments)
    monkeypatch.setattr(router, "LearningStore", lambda: learning)
    reading = SimpleNamespace(forget_session=Mock())
    monkeypatch.setattr(router, "ReadingCatalogStore", lambda: reading)
    runtime = SimpleNamespace(cancel_turn=AsyncMock())
    monkeypatch.setattr("deeptutor.services.session.get_turn_runtime_manager", lambda: runtime)
    monkeypatch.setattr(
        store, "list_active_turns", AsyncMock(side_effect=lambda sid: [{"id": f"turn-{sid}"}])
    )

    result = await router.delete_session("root")

    assert result == {"deleted": True, "session_id": "root"}
    for sid in ("root", "child", "grandchild"):
        assert await store.get_session(sid) is None
        assert await store.get_messages(sid) == []
        assert await store.restore_session(sid) is False
        attachments.delete_session.assert_any_await(sid)
        learning.detach_session.assert_any_call(sid)
        reading.forget_session.assert_any_call(sid)
        runtime.cancel_turn.assert_any_await(f"turn-{sid}")
    assert await store.get_session("other") is not None
    assert len(await store.get_messages("other")) == 1
    assert await store.list_deleted_sessions() == []


@pytest.mark.asyncio
async def test_missing_or_unowned_session_has_no_deletion_side_effects(monkeypatch):
    store = SimpleNamespace(get_session=AsyncMock(return_value=None), delete_session=AsyncMock())
    monkeypatch.setattr(router, "get_session_store", lambda: store)
    with pytest.raises(HTTPException) as exc:
        await router.delete_session("missing")
    assert exc.value.status_code == 404
    store.delete_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_deleted_chats_migrate_to_archive_without_data_loss(tmp_path):
    path = tmp_path / "sessions.db"
    store = SQLiteSessionStore(path)
    await store.create_session(session_id="legacy", title="Keep me")
    await store.update_session_preferences("legacy", {"pinned": True})
    await store.add_message("legacy", "user", "Keep this message")
    before = await store.get_session("legacy")
    await store.soft_delete_session("legacy")

    store = SQLiteSessionStore(path)
    restored = await store.get_session("legacy")
    assert restored["preferences"]["archived"] is True
    assert restored["preferences"]["pinned"] is True
    assert restored["updated_at"] == before["updated_at"]
    assert (await store.get_messages("legacy"))[0]["content"] == "Keep this message"
    assert await store.list_deleted_sessions() == []
    assert await store.migrate_workspace_preferences() == 0
