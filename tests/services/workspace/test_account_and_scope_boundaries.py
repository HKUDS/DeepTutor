"""Account-level stores stay shared; workspace-bound work stays in its workspace."""

from __future__ import annotations

import asyncio
import json

import pytest

from deeptutor.multi_user.paths import get_current_path_service
from deeptutor.services.session import get_sqlite_session_store
from deeptutor.services.workspace.context import workspace_context
from tests.services.workspace.test_data_scope import account as account


@pytest.mark.asyncio
async def test_cron_reminder_runs_in_the_workspace_it_was_scheduled_from(account, monkeypatch):
    from deeptutor.core.stream import StreamEvent, StreamEventType
    from deeptutor.multi_user import paths
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.runtime import turn_engine
    from deeptutor.services.cron import executor
    from deeptutor.services.cron.service import CronJob, CronOwner, CronSchedule

    target = account.create_workspace("Reminders")["workspace_id"]
    with workspace_context(target):
        session = await get_sqlite_session_store().create_session(title="Plan")

    class Engine:
        async def execute(self, context):
            yield StreamEvent(
                type=StreamEventType.RESULT, source="chat", metadata={"response": "Time to study"}
            )

    monkeypatch.setattr(paths, "local_admin_user", get_current_user)
    monkeypatch.setattr(turn_engine, "get_turn_engine", lambda: Engine())
    monkeypatch.setattr(executor, "_maybe_send_desktop_notification", lambda *_: _noop())
    job = CronJob(
        id="job1",
        name="Study",
        message="Study vectors",
        schedule=CronSchedule(kind="every", every_seconds=3600),
        owner=CronOwner(kind="chat", session_id=session["id"], workspace_id=target),
    )
    assert await executor._execute_chat_job(job) == ("ok", None)
    with workspace_context(target):
        messages = await get_sqlite_session_store().get_messages(session["id"])
    assert [row["content"] for row in messages][-1] == "Time to study"
    # Older jobs carry no workspace and keep resolving in General.
    job.owner.workspace_id = ""
    assert await executor._execute_chat_job(job) == ("error", "session no longer exists")


async def _noop():
    return None


def test_partner_groups_are_shared_and_adopt_groups_once_stored_per_workspace(account):
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.services.partner_groups import store as group_store
    from deeptutor.services.partner_groups.models import PartnerGroupConfig

    target = account.create_workspace("Groups")["workspace_id"]
    owner = get_current_user().id
    with workspace_context(target):
        legacy_root = get_current_path_service().get_user_root() / "partner_groups"
    legacy = PartnerGroupConfig(group_id="study-circle", name="Study circle", owner_id=owner)
    (legacy_root / "study-circle").mkdir(parents=True)
    (legacy_root / "study-circle" / "config.json").write_text(
        json.dumps(legacy.to_dict()), encoding="utf-8"
    )
    group_store._ADOPTED.clear()
    for scope in ("", target):
        with workspace_context(scope):
            assert [group.group_id for group in group_store.PartnerGroupStore().list()] == [
                "study-circle"
            ]
    assert not (legacy_root / "study-circle").exists()


def test_knowledge_library_lists_only_the_viewing_workspace(account, monkeypatch):
    from deeptutor.multi_user import knowledge_access
    from deeptutor.services.workspace import knowledge

    catalog = [
        {"id": "account:kb:general", "name": "general", "workspace_id": ""},
        {"id": "workspace:ws_a:kb:physics", "name": "physics", "workspace_id": "ws_a"},
    ]
    monkeypatch.setattr(knowledge, "knowledge_catalog", lambda: catalog)
    request = knowledge.library_request.set(True)
    try:
        for viewer, expected in (
            ("", ["general"]),
            ("ws_a", ["physics"]),
            (None, ["general", "physics"]),
        ):
            token = knowledge.library_viewer.set(viewer)
            try:
                names = [row["name"] for row in knowledge_access.list_visible_knowledge_bases()]
            finally:
                knowledge.library_viewer.reset(token)
            assert names == expected
    finally:
        knowledge.library_request.reset(request)


def test_learning_journal_moves_with_workspace_data(account):
    from deeptutor.services.path_service import get_path_service
    from deeptutor.services.workspace.data_migration import FEATURES, _feature_path

    target = account.create_workspace("Journal")["workspace_id"]
    assert "learning_journal" in FEATURES
    seen = set()
    for scope in ("", target):
        with workspace_context(scope):
            paths = get_path_service()
            assert _feature_path(paths, "learning_journal") == paths.get_learning_journal_dir()
            seen.add(paths.get_learning_journal_dir())
    assert len(seen) == 2


def test_dashboard_rows_name_the_request_workspace(account):
    from deeptutor.api.routers import dashboard

    target = account.create_workspace("Named")["workspace_id"]

    async def read():
        return [{"id": 1}]

    with workspace_context(target):
        rows = asyncio.run(dashboard._workspace_rows(read))
    assert rows == [{"id": 1, "content_workspace_id": target, "content_workspace_name": "Named"}]


def test_personas_are_shared_and_adopt_personas_written_in_a_workspace(account):
    from deeptutor.services.persona import service as persona_service

    target = account.create_workspace("Personas")["workspace_id"]
    with workspace_context(target):
        legacy = get_current_path_service().get_workspace_dir() / "personas" / "coach"
    legacy.mkdir(parents=True)
    (legacy / "PERSONA.md").write_text(
        "---\nname: coach\ndescription: Brisk\n---\nBe brisk.\n", encoding="utf-8"
    )
    persona_service._instances.clear()
    for scope in ("", target):
        with workspace_context(scope):
            names = [item.name for item in persona_service.get_persona_service().list_personas()]
            assert "coach" in names
    assert not legacy.exists()


@pytest.mark.asyncio
async def test_page_chats_name_their_book_without_looking_recently_used(account, monkeypatch):
    from types import SimpleNamespace

    from deeptutor.book import chat_sessions

    store = get_sqlite_session_store()
    session = await store.create_session(title="Page chat")
    before = (await store.get_session(session["id"]))["updated_at"]
    book = SimpleNamespace(id="bk_1", metadata={"page_chat_sessions": {"pg_1": session["id"]}})
    monkeypatch.setattr(
        "deeptutor.multi_user.book_access.accessible_books",
        lambda: [(book, SimpleNamespace(is_shared=False))],
    )
    assert await chat_sessions.adopt_book_chat_sessions(store) == 1
    tagged = await store.get_session(session["id"])
    assert tagged["preferences"]["book_id"] == "bk_1"
    assert tagged["preferences"]["book_page_id"] == "pg_1"
    assert tagged["updated_at"] == before
    # Adoption is idempotent: nothing left to tag.
    assert await chat_sessions.adopt_book_chat_sessions(store) == 0
