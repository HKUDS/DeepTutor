"""Real-store tests for workspace boundaries and asynchronous scope capture."""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.multi_user.paths import get_account_path_service, user_context
from deeptutor.services.path_service import get_path_service
from deeptutor.services.workspace import ContentWorkspaceService, WorkspaceError
from deeptutor.services.workspace.context import workspace_context


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
    user = CurrentUser("scope-test", "test", "admin", UserScope("admin", "scope-test", tmp_path))
    with user_context(user):
        get_account_path_service().ensure_all_directories()
        yield ContentWorkspaceService()


def test_feature_paths_and_cache_identity_are_isolated_but_settings_and_memory_are_global(account):
    from deeptutor.book.storage import get_book_storage
    from deeptutor.learning.storage import LearningStore
    from deeptutor.reading.store import ReadingStore
    from deeptutor.video_learning.service import get_timed_media_store

    base = get_account_path_service()
    a, b = account.create_workspace("A"), account.create_workspace("B")
    seen = []
    for wid in ("", a["workspace_id"], b["workspace_id"]):
        with workspace_context(wid):
            paths = get_path_service()
            assert paths.get_settings_dir() == base.get_settings_dir()
            assert paths.get_memory_dir() == base.get_memory_dir()
            assert account._catalog_file() == base.get_runtime_state_dir() / "workspaces.sqlite3"
            seen.append(
                (
                    paths.get_chat_history_db(),
                    get_book_storage(),
                    LearningStore().event_scope,
                    ReadingStore().root,
                )
            )
            get_timed_media_store().save(
                {"material_id": "0123456789abcdef", "type": "timed_media", "title": wid}
            )
    assert len({row[0] for row in seen}) == 3
    assert len({id(row[1]) for row in seen}) == 3
    assert len({row[2] for row in seen}) == 3
    assert len({row[3] for row in seen}) == 3
    assert seen[0][0] == base.get_chat_history_db()
    for wid in ("", a["workspace_id"], b["workspace_id"]):
        with workspace_context(wid):
            assert get_timed_media_store().get("0123456789abcdef")["title"] == wid


@pytest.mark.asyncio
async def test_sessions_and_turns_are_not_accessible_from_other_workspaces(account):
    from deeptutor.services.session import get_sqlite_session_store

    a = account.create_workspace("A")["workspace_id"]
    with workspace_context(a):
        store = get_sqlite_session_store()
        session = await store.create_session()
        turn = await store.create_turn(session["id"])
        await store.add_message(session["id"], "user", "private")
        assert session["preferences"]["workspace_id"] == a
    with workspace_context():
        other = get_sqlite_session_store()
        assert await other.get_session(session["id"]) is None
        assert await other.get_turn(turn["id"]) is None
        assert await other.get_messages(session["id"]) == []


@pytest.mark.asyncio
async def test_background_task_and_thread_keep_original_workspace(account):
    a, b = account.create_workspace("A"), account.create_workspace("B")
    ready = asyncio.Event()

    async def work():
        await ready.wait()
        path = await asyncio.to_thread(lambda: get_path_service().get_book_dir())
        path.mkdir(parents=True, exist_ok=True)
        (path / "finished.txt").write_text("A")
        return path

    with workspace_context(a["workspace_id"]):
        task = asyncio.create_task(work())
    with workspace_context(b["workspace_id"]):
        ready.set()
        original = await task
        assert original != get_path_service().get_book_dir()
        assert not (get_path_service().get_book_dir() / "finished.txt").exists()


def test_invalid_scope_never_falls_back_to_default(account, tmp_path):
    with pytest.raises(WorkspaceError):
        with workspace_context("ws_missing"):
            pass
    with pytest.raises(WorkspaceError):
        with workspace_context(account.system_binding().workspace_id):
            pass
    row = account.create_workspace("A")
    with workspace_context(row["workspace_id"]):
        other = CurrentUser(
            "other", "other", "admin", UserScope("admin", "other", tmp_path / "other")
        )
        with user_context(other):
            assert get_path_service().workspace_root == other.scope.root
        assert get_path_service().scope.workspace_id == row["workspace_id"]
