"""Navigation reads legacy stores in place; IDs, content and ownership survive."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deeptutor.api.routers import dashboard, partners
from deeptutor.book.models import Book
from deeptutor.book.storage import get_book_storage
from deeptutor.services.path_service import get_path_service
from deeptutor.services.session import get_sqlite_session_store
from deeptutor.services.workspace.context import current_workspace_id, workspace_context
from tests.services.workspace.test_data_scope import account as account
from tests.services.workspace.test_learning_sources_review import seed_question


@pytest.mark.asyncio
async def test_learning_index_preserves_equal_ids_and_existing_bytes(account):
    other = account.create_workspace("Other")["workspace_id"]
    originals = {}
    questions = {}
    for origin in ("", other):
        with workspace_context(origin):
            book = Book(id="bk_legacy", title=f"Book {origin}", metadata={"legacy_extra": "keep"})
            store = get_book_storage()
            store.save_book(book)
            manifest = get_path_service().get_book_manifest_file(book.id)
            originals[manifest] = manifest.read_bytes()
            questions[origin] = await seed_question(origin, f"Question {origin}")
    with workspace_context(other):
        result = await dashboard.get_learning_index()
        assert current_workspace_id() == other
    assert result["failed"] == []
    # Only the request's workspace is read, even when another holds equal ids.
    assert [(row["id"], row["content_workspace_id"]) for row in result["sources"]["books"]] == [
        ("bk_legacy", other)
    ]
    assert [row["content_workspace_id"] for row in result["sources"]["practice"]] == [other]
    for origin in ("", other):
        with workspace_context(origin):
            current = await get_sqlite_session_store().find_notebook_entry("lesson", "q1")
            assert current == questions[origin]
            assert get_book_storage().load_book("bk_legacy").metadata == {"legacy_extra": "keep"}
    assert all(path.read_bytes() == data for path, data in originals.items())


@pytest.mark.asyncio
async def test_learning_index_never_reads_disallowed_sources(account, monkeypatch):
    from deeptutor.api.routers import book, mastery_path, reading
    from deeptutor.multi_user import learning_access

    monkeypatch.setattr(
        learning_access, "current_learning_policy", lambda: {"allowed_surfaces": ["reading"]}
    )
    denied = AsyncMock(side_effect=AssertionError("denied source read"))
    monkeypatch.setattr(book, "list_books", denied)
    monkeypatch.setattr(mastery_path, "list_topics", denied)
    monkeypatch.setattr(type(get_sqlite_session_store()), "list_notebook_navigation", denied)
    monkeypatch.setattr(reading, "list_workspaces", AsyncMock(return_value={"workspaces": []}))
    result = await dashboard.get_learning_index()
    denied.assert_not_called()
    assert (
        result["sources"]["books"]
        == result["sources"]["mastery"]
        == result["sources"]["practice"]
        == []
    )


@pytest.mark.asyncio
async def test_partner_index_uses_visible_actor_stores_and_keeps_archives(account, monkeypatch):
    from deeptutor.services import partner_groups

    rows = [
        {
            "session_key": "web-old",
            "title": "Old conversation",
            "updated_at": "2026-10-01T12:00:00Z",
        },
        {
            "session_key": "archive",
            "title": "Archived",
            "archived": True,
            "updated_at": "2026-10-02T12:00:00Z",
        },
    ]
    accessed = []

    def session_store(partner_id):
        accessed.append(partner_id)
        assert partner_id == "visible"
        return SimpleNamespace(list_sessions=lambda: rows)

    monkeypatch.setattr(
        partners,
        "visible_partners",
        lambda: [
            {
                "partner_id": "visible",
                "name": "Tutor",
                "soul": "never return",
                "channels": {"secret": "never return"},
            }
        ],
    )
    monkeypatch.setattr(
        partners, "get_partner_manager", lambda: SimpleNamespace(session_store=session_store)
    )
    monkeypatch.setattr(
        partner_groups,
        "get_partner_group_manager",
        lambda: SimpleNamespace(
            list_groups=lambda: [{"group_id": "group-a", "name": "Group"}],
            list_sessions=lambda gid: [
                {
                    "session_key": "default",
                    "title": "Old group",
                    "updated_at": "2026-10-02T12:00:00Z",
                }
            ],
        ),
    )
    result = await partners.partner_navigation()
    assert accessed == ["visible"]
    assert [row.session_key for row in result.sessions] == ["default", "web-old"]
    assert "soul" not in result.partners[0] and "channels" not in result.partners[0]
    assert rows[1]["archived"] is True and len(rows) == 2
