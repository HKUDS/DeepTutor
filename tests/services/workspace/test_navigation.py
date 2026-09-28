"""Cross-workspace navigation must not weaken scoped content access."""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.services.session import get_sqlite_session_store
from deeptutor.services.workspace.context import current_workspace_id, workspace_context
from deeptutor.services.workspace.navigation import session_index
from tests.services.workspace.test_data_scope import account as account
from tests.services.workspace.test_http_scope import scoped_client as scoped_client


@pytest.mark.asyncio
async def test_equal_timestamps_use_the_same_order_before_and_after_pagination(account):
    import sqlite3

    from deeptutor.services.path_service import get_path_service

    target = account.create_workspace("Tied timestamps")["workspace_id"]
    expected = []
    for scope in ("", target):
        with workspace_context(scope):
            store = get_sqlite_session_store()
            for sid in ("z-last", "a-first", "m-middle"):
                row = await store.create_session(title="Tied lesson", session_id=sid)
                expected.append((scope, row["id"]))
            with sqlite3.connect(get_path_service().get_chat_history_db()) as conn:
                conn.execute("UPDATE sessions SET updated_at=100")
    for query in (None, "Tied"):
        rows = []
        for offset in range(6):
            rows.extend((await session_index(1, offset, query))["sessions"])
        assert [(row["content_workspace_id"], row["session_id"]) for row in rows] == sorted(
            expected
        )


@pytest.mark.asyncio
async def test_index_merges_pages_and_keeps_origin_without_changing_scope(account):
    a = account.create_workspace("A")["workspace_id"]
    ids = []
    for scope in ("", a):
        with workspace_context(scope):
            store = get_sqlite_session_store()
            for n in range(3):
                row = await store.create_session(title=f"{scope or 'default'} lesson {n}")
                await store.add_message(row["id"], "user", "vectors lesson")
                ids.append(row["id"])
    with workspace_context(a):
        pages = [(await session_index(2, offset))["sessions"] for offset in (0, 2, 4)]
        rows = [row for page in pages for row in page]
        assert {row["session_id"] for row in rows} == set(ids)
        assert len(rows) == 6
        assert [row["updated_at"] for row in rows] == sorted(
            [row["updated_at"] for row in rows], reverse=True
        )
        assert {row["content_workspace_id"] for row in rows} == {"", a}
        assert current_workspace_id() == a
        searched = await session_index(2, 1, "vectors")
        assert searched["total"] == 6
        assert len(searched["sessions"]) == 2


def test_http_navigation_is_account_wide_but_detail_and_mutations_are_scoped(
    account, scoped_client
):
    a = account.create_workspace("A")["workspace_id"]
    with workspace_context(""):
        default = asyncio.run(get_sqlite_session_store().create_session(title="Default lesson"))
    with workspace_context(a):
        custom = asyncio.run(get_sqlite_session_store().create_session(title="Custom lesson"))
    client = scoped_client
    index = client.get(f"/api/sessions?all_workspaces=true&dt_workspace={a}")
    assert index.status_code == 200, index.text
    assert {row["session_id"] for row in index.json()["sessions"]} == {default["id"], custom["id"]}
    scoped = client.get(f"/api/sessions?dt_workspace={a}").json()["sessions"]
    assert [row["session_id"] for row in scoped] == [custom["id"]]
    assert client.get(f"/api/sessions/{default['id']}?dt_workspace={a}").status_code == 404
    assert (
        client.patch(
            f"/api/sessions/{default['id']}?dt_workspace={a}", json={"title": "Wrong"}
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/sessions/{default['id']}?dt_workspace=").json()["title"]
        == "Default lesson"
    )


@pytest.mark.asyncio
async def test_an_offline_workspace_does_not_hide_other_history(account):
    offline = account.create_workspace("Offline")
    from pathlib import Path

    Path(offline["path"]).rename(Path(offline["path"]).with_name("offline-moved"))
    with workspace_context(""):
        row = await get_sqlite_session_store().create_session(title="Still here")
    index = await session_index(50, 0)
    assert [item["session_id"] for item in index["sessions"]] == [row["id"]]
    assert offline["workspace_id"] in index["unavailable_workspaces"]


def test_move_rejects_combined_changes_before_mutating_either_store(account, scoped_client):
    target = account.create_workspace("Target")["workspace_id"]
    with workspace_context(""):
        row = asyncio.run(get_sqlite_session_store().create_session(title="Keep intact"))
    response = scoped_client.patch(
        f"/api/sessions/{row['id']}/organization?dt_workspace=",
        json={"workspace_id": target, "pinned": True},
    )
    assert response.status_code == 400, response.text
    assert "separately" in response.json()["detail"]
    source = scoped_client.get(f"/api/sessions/{row['id']}?dt_workspace=")
    assert source.status_code == 200
    assert not source.json()["preferences"].get("pinned")
    assert scoped_client.get(f"/api/sessions/{row['id']}?dt_workspace={target}").status_code == 404


def test_learning_index_includes_each_workspace_and_keeps_feature_lists_scoped(
    account, scoped_client
):
    from deeptutor.api.routers.dashboard import router
    from deeptutor.book.models import Book
    from deeptutor.book.storage import get_book_storage

    scoped_client.app.include_router(router, prefix="/api/dashboard")
    a = account.create_workspace("A")["workspace_id"]
    for scope, book_id in (("", "bk_default"), (a, "bk_custom")):
        with workspace_context(scope):
            get_book_storage().save_book(Book(id=book_id, title=book_id))
    result = scoped_client.get("/api/dashboard/learning-index").json()
    assert result["failed"] == []
    assert {(row["id"], row["content_workspace_id"]) for row in result["sources"]["books"]} == {
        ("bk_default", ""),
        ("bk_custom", a),
    }
    scoped = scoped_client.get("/api/book/books", params={"dt_workspace": a}).json()
    assert [book["id"] for book in scoped["books"]] == ["bk_custom"]


def test_learning_library_keeps_equal_ids_distinct_and_mutations_bound(account, scoped_client):
    from deeptutor.api.routers.dashboard import router
    from deeptutor.book.models import Book
    from deeptutor.book.storage import get_book_storage

    scoped_client.app.include_router(router, prefix="/api/dashboard")
    custom = account.create_workspace("Custom")["workspace_id"]
    for origin, title in (("", "Original book"), (custom, "Custom book")):
        with workspace_context(origin):
            get_book_storage().save_book(Book(id="same-id", title=title))
    result = scoped_client.get(
        "/api/dashboard/learning-library/books", params={"dt_workspace": custom}
    )
    assert result.status_code == 200
    rows = result.json()["items"]
    assert {(row["title"], row["content_workspace_id"]) for row in rows} == {
        ("Original book", ""),
        ("Custom book", custom),
    }
    assert (
        scoped_client.get("/api/book/books/same-id", params={"dt_workspace": ""}).json()["book"][
            "title"
        ]
        == "Original book"
    )
    assert (
        scoped_client.get("/api/book/books/same-id", params={"dt_workspace": custom}).json()[
            "book"
        ]["title"]
        == "Custom book"
    )
    assert (
        scoped_client.delete("/api/book/books/same-id", params={"dt_workspace": custom}).status_code
        == 200
    )
    assert (
        scoped_client.get("/api/book/books/same-id", params={"dt_workspace": ""}).status_code == 200
    )


def test_learning_library_mastery_and_reading_are_visible_from_other_workspaces(
    account, scoped_client
):
    from deeptutor.api.routers.dashboard import router

    scoped_client.app.include_router(router, prefix="/api/dashboard")
    target = account.create_workspace("Destination")["workspace_id"]
    topic = scoped_client.post(
        "/api/mastery-paths/topics?dt_workspace=",
        json={"name": "Original topic", "goal": "Learn vectors"},
    )
    assert topic.status_code == 200
    collection = scoped_client.post(
        "/api/reading/workspaces?dt_workspace=", json={"title": "Original collection"}
    )
    assert collection.status_code == 201
    for kind in ("mastery", "reading"):
        result = scoped_client.get(
            f"/api/dashboard/learning-library/{kind}", params={"dt_workspace": target}
        )
        assert result.status_code == 200
        assert result.json()["unavailable_workspaces"] == []
        assert len(result.json()["items"]) == 1
        assert result.json()["items"][0]["content_workspace_id"] == ""


@pytest.mark.asyncio
async def test_learning_library_does_not_hide_records_when_one_folder_is_offline(account):
    from pathlib import Path

    from deeptutor.api.routers.dashboard import get_learning_library
    from deeptutor.book.models import Book
    from deeptutor.book.storage import get_book_storage

    missing = account.create_workspace("Missing")
    Path(missing["path"]).rename(Path(missing["path"]).with_name("moved"))
    with workspace_context(""):
        get_book_storage().save_book(Book(id="still-here", title="Still here"))
    result = await get_learning_library("books")
    assert [row["id"] for row in result["items"]] == ["still-here"]
    assert result["unavailable_workspaces"] == [missing["workspace_id"]]
