"""Owner self-service sharing: a book's uploader decides who may read or edit.

The admin-catalogue permission model is reused untouched — a peer grant is a
plain ``book_permission.books`` entry on the *recipient's* record, and the
resolver finds the owning workspace by scanning ``data/users/*/``.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import book as book_router
from deeptutor.book.models import Block, BlockStatus, BlockType, Book, Page, PageStatus
from deeptutor.book.storage import BookStorage
from deeptutor.multi_user.book_permission import normalize_book_permission
from deeptutor.multi_user.models import CurrentUser
from deeptutor.multi_user.paths import user_context
from deeptutor.services.auth import TokenPayload


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def owner_env(tmp_path, monkeypatch):
    from deeptutor.book import engine as engine_module
    from deeptutor.book import storage as storage_module
    from deeptutor.multi_user import audit, grants, identity, paths
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services import auth as auth_service

    admin_root = (tmp_path / "data").resolve()
    system_root = admin_root / "system"
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", tmp_path / "multi-user")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "missing-users.json")
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", tmp_path / "missing-secret")
    monkeypatch.setattr(grants, "GRANTS_DIR", system_root / "grants")
    monkeypatch.setattr(audit, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_service, "AUTH_USERNAME", "")
    monkeypatch.setattr(auth_service, "AUTH_PASSWORD_HASH", "")
    storage_module._storages.clear()
    engine_module._engines.clear()

    accounts: dict[str, dict[str, Any]] = {}
    for name, role in (
        ("root", "admin"),
        ("alice", "user"),  # teacher: uploads and owns bk_mine
        ("bob", "user"),
        ("editor", "user"),
        ("student", "user"),
    ):
        accounts[name] = save_user(name, "hash", role=role)  # type: ignore[arg-type]

    tokens = {
        name: TokenPayload(username=name, role=record["role"], user_id=record["id"])
        for name, record in accounts.items()
    }
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))

    def as_user(name: str) -> CurrentUser:
        record = accounts[name]
        return CurrentUser(
            id=record["id"],
            username=name,
            role=record["role"],
            scope=paths.scope_for_user(record["id"], is_admin=record["role"] == "admin"),
        )

    # Alice uploads a book into her own workspace.
    with user_context(as_user("alice")):
        own = BookStorage(path_service=paths.get_current_path_service())
        own.save_book(Book(id="bk_mine", title="Mine", page_count=1))
        own.save_page(
            Page(
                id="pg_1",
                book_id="bk_mine",
                title="Page",
                status=PageStatus.READY,
                blocks=[
                    Block(
                        id="blk_1",
                        type=BlockType.TEXT,
                        status=BlockStatus.READY,
                        payload={"body": "Original"},
                    )
                ],
            )
        )

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    app.include_router(
        book_router.router,
        prefix="/api",
        dependencies=[Depends(auth_router.require_auth)],
    )
    return TestClient(app), accounts


def _grant(book_permission: Any) -> dict[str, str]:
    return normalize_book_permission(book_permission).books_dict()


def test_owner_share_read_is_visible_and_readable(owner_env) -> None:
    client, accounts = owner_env
    granted = client.post(
        "/api/books/bk_mine/share",
        headers=_headers("alice"),
        json={"user_id": "bob", "level": "read"},
    )
    assert granted.status_code == 200
    assert granted.json()["level"] == "read"
    assert "bk_mine" in _grant(_bob_permission())

    detail = client.get("/api/books/bk_mine", headers=_headers("bob"))
    assert detail.status_code == 200
    assert detail.json()["book"]["can_edit"] is False
    assert detail.json()["book"]["can_delete"] is False

    listing = client.get("/api/books", headers=_headers("bob")).json()
    mine = [book for book in listing["books"] if book["id"] == "bk_mine"]
    assert len(mine) == 1
    assert mine[0]["source"] == "shared"
    assert mine[0]["permission"] == "read"
    assert mine[0]["can_edit"] is False

    # A read grant cannot edit.
    denied = client.post(
        "/api/books/update-block",
        headers=_headers("bob"),
        json={
            "book_id": "bk_mine",
            "page_id": "pg_1",
            "block_id": "blk_1",
            "body": "Nope",
            "expected_revision": 1,
        },
    )
    assert denied.status_code == 404


def _bob_permission() -> Any:
    from deeptutor.multi_user.identity import get_user

    record = get_user("bob")
    assert record is not None
    return record.get("book_permission")


def test_owner_share_edit_allows_editing(owner_env) -> None:
    client, _ = owner_env
    granted = client.post(
        "/api/books/bk_mine/share",
        headers=_headers("alice"),
        json={"user_id": "editor", "level": "edit"},
    )
    assert granted.status_code == 200

    success = client.post(
        "/api/books/update-block",
        headers=_headers("editor"),
        json={
            "book_id": "bk_mine",
            "page_id": "pg_1",
            "block_id": "blk_1",
            "body": "Edited by grantee",
            "expected_revision": 1,
        },
    )
    assert success.status_code == 200
    assert success.json()["book_revision"] == 2


def test_non_owner_cannot_share(owner_env) -> None:
    client, _ = owner_env
    assert (
        client.post(
            "/api/books/bk_mine/share",
            headers=_headers("alice"),
            json={"user_id": "bob", "level": "read"},
        ).status_code
        == 200
    )
    # A grantee (read) cannot re-share.
    assert (
        client.post(
            "/api/books/bk_mine/share",
            headers=_headers("bob"),
            json={"user_id": "student", "level": "read"},
        ).status_code
        == 404
    )
    # An unrelated account cannot either — same 404 as an unknown book.
    assert (
        client.post(
            "/api/books/bk_mine/share",
            headers=_headers("student"),
            json={"user_id": "bob", "level": "read"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/books/bk_mine/share",
            headers=_headers("student"),
        ).status_code
        == 404
    )


def test_share_rejects_self_admin_and_unknown_targets(owner_env) -> None:
    client, _ = owner_env
    self_share = client.post(
        "/api/books/bk_mine/share",
        headers=_headers("alice"),
        json={"user_id": "alice", "level": "read"},
    )
    assert self_share.status_code == 400

    admin_share = client.post(
        "/api/books/bk_mine/share",
        headers=_headers("alice"),
        json={"user_id": "root", "level": "read"},
    )
    assert admin_share.status_code == 400

    unknown = client.post(
        "/api/books/bk_mine/share",
        headers=_headers("alice"),
        json={"user_id": "ghost", "level": "read"},
    )
    assert unknown.status_code == 404

    bad_level = client.post(
        "/api/books/bk_mine/share",
        headers=_headers("alice"),
        json={"user_id": "bob", "level": "delete"},
    )
    assert bad_level.status_code == 422


def test_revoke_removes_access(owner_env) -> None:
    client, _ = owner_env
    assert (
        client.post(
            "/api/books/bk_mine/share",
            headers=_headers("alice"),
            json={"user_id": "bob", "level": "edit"},
        ).status_code
        == 200
    )
    shares = client.get("/api/books/bk_mine/share", headers=_headers("alice")).json()
    assert {"user_id": accounts_bob_id(shares), "username": "bob", "level": "edit"} in [
        {key: item[key] for key in ("user_id", "username", "level")} for item in shares["shares"]
    ]

    revoked = client.delete("/api/books/bk_mine/share/bob", headers=_headers("alice"))
    assert revoked.status_code == 200

    assert client.get("/api/books/bk_mine", headers=_headers("bob")).status_code == 404
    listing = client.get("/api/books", headers=_headers("bob")).json()
    assert all(book["id"] != "bk_mine" for book in listing["books"])
    # Revoking an account that was never granted is idempotent.
    assert (
        client.delete("/api/books/bk_mine/share/student", headers=_headers("alice")).status_code
        == 200
    )


def accounts_bob_id(shares: dict[str, Any]) -> str:
    return next(item["user_id"] for item in shares["candidates"] if item["username"] == "bob")


def test_owner_delete_cleans_peer_grants(owner_env) -> None:
    client, _ = owner_env
    assert (
        client.post(
            "/api/books/bk_mine/share",
            headers=_headers("alice"),
            json={"user_id": "bob", "level": "read"},
        ).status_code
        == 200
    )
    assert client.delete("/api/books/bk_mine", headers=_headers("alice")).status_code == 200
    assert "bk_mine" not in _grant(_bob_permission())


def test_admin_catalogue_shares_coexist_with_peer_grants(owner_env) -> None:
    """Existing admin-shared books keep working alongside owner grants."""

    from deeptutor.multi_user.book_permission import BookPermission
    from deeptutor.multi_user.identity import set_book_permission
    from deeptutor.multi_user.paths import get_admin_path_service

    client, _ = owner_env
    admin_storage = BookStorage(path_service=get_admin_path_service())
    admin_storage.save_book(Book(id="bk_catalogue", title="Catalogue", page_count=1))
    set_book_permission("bob", BookPermission(books=(("bk_catalogue", "read"),)))

    assert client.get("/api/books/bk_catalogue", headers=_headers("bob")).status_code == 200

    assert (
        client.post(
            "/api/books/bk_mine/share",
            headers=_headers("alice"),
            json={"user_id": "bob", "level": "read"},
        ).status_code
        == 200
    )
    listing = client.get("/api/books", headers=_headers("bob")).json()
    shared_ids = {book["id"]: book["permission"] for book in listing["books"]}
    assert shared_ids.get("bk_catalogue") == "read"
    assert shared_ids.get("bk_mine") == "read"
