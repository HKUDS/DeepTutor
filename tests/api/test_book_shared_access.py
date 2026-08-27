from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth as auth_router
from deeptutor.api.routers import book as book_router
from deeptutor.book.models import Block, BlockStatus, BlockType, Book, Page, PageStatus
from deeptutor.book.storage import BookStorage
from deeptutor.multi_user.book_permission import BookPermission
from deeptutor.services.auth import TokenPayload


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def shared_env(tmp_path, monkeypatch):
    from deeptutor.book import engine as engine_module
    from deeptutor.book import storage as storage_module
    from deeptutor.multi_user import audit, grants, identity, paths
    from deeptutor.multi_user.identity import save_user, set_book_permission
    from deeptutor.multi_user.paths import get_admin_path_service
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

    root = save_user("root", "hash", role="admin")
    alice = save_user("alice", "hash", role="user")
    bob = save_user("bob", "hash", role="user")
    editor = save_user("editor", "hash", role="user")
    set_book_permission("alice", BookPermission(books=(("bk_shared", "read"),)))
    set_book_permission("bob", BookPermission(books=(("bk_shared", "read"),)))
    set_book_permission("editor", BookPermission(books=(("bk_shared", "edit"),)))

    tokens = {
        "root": TokenPayload(username="root", role="admin", user_id=root["id"]),
        "alice": TokenPayload(username="alice", role="user", user_id=alice["id"]),
        "bob": TokenPayload(username="bob", role="user", user_id=bob["id"]),
        "editor": TokenPayload(username="editor", role="user", user_id=editor["id"]),
    }
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))

    shared = BookStorage(path_service=get_admin_path_service())
    shared.save_book(Book(id="bk_shared", title="Shared", page_count=1))
    shared.save_page(
        Page(
            id="pg_1",
            book_id="bk_shared",
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
    app.include_router(auth_router.router, prefix="/api/v1/auth")
    app.include_router(
        book_router.router,
        prefix="/api/v1/book",
        dependencies=[Depends(auth_router.require_auth)],
    )
    return TestClient(app), shared


def test_shared_learning_state_is_isolated_per_reader(shared_env) -> None:
    client, canonical = shared_env
    visit = client.post(
        "/api/v1/book/books/progress/visit",
        headers=_headers("alice"),
        json={"book_id": "bk_shared", "page_id": "pg_1"},
    )
    assert visit.status_code == 200
    capture = client.post(
        "/api/v1/book/books/bk_shared/learning-captures",
        headers=_headers("alice"),
        json={"page_id": "pg_1", "source_text": "Alice note"},
    )
    assert capture.status_code == 200
    chat = client.post(
        "/api/v1/book/books/page-chat-session",
        headers=_headers("alice"),
        json={"book_id": "bk_shared", "page_id": "pg_1", "session_id": "alice-chat"},
    )
    assert chat.status_code == 200

    alice = client.get("/api/v1/book/books/bk_shared", headers=_headers("alice")).json()
    bob = client.get("/api/v1/book/books/bk_shared", headers=_headers("bob")).json()
    assert alice["progress"]["current_page_id"] == "pg_1"
    assert alice["book"]["metadata"]["page_chat_sessions"] == {"pg_1": "alice-chat"}
    assert bob["progress"]["current_page_id"] == ""
    assert bob["book"]["metadata"]["page_chat_sessions"] == {}
    assert client.get(
        "/api/v1/book/books/bk_shared/learning-captures",
        headers=_headers("bob"),
    ).json() == {"captures": []}

    # Nothing reader-specific landed in the admin canonical directory.
    assert canonical.load_progress("bk_shared") is None
    assert canonical.load_learning_captures("bk_shared") == []
    assert canonical.load_book("bk_shared").metadata.get("page_chat_sessions") is None


def test_shared_read_user_cannot_edit_or_delete(shared_env) -> None:
    client, canonical = shared_env
    update = client.post(
        "/api/v1/book/books/update-block",
        headers=_headers("alice"),
        json={
            "book_id": "bk_shared",
            "page_id": "pg_1",
            "block_id": "blk_1",
            "body": "Nope",
            "expected_revision": 1,
        },
    )
    assert update.status_code == 404
    assert (
        client.delete(
            "/api/v1/book/books/bk_shared",
            headers=_headers("alice"),
        ).status_code
        == 404
    )
    assert canonical.load_book("bk_shared") is not None


def test_shared_read_health_check_does_not_mutate_canonical_book(shared_env) -> None:
    client, canonical = shared_env
    book = canonical.load_book("bk_shared")
    assert book is not None
    book.stale_page_ids = ["pg_1"]
    canonical.save_book(book)
    updated_at = canonical.load_book("bk_shared").updated_at

    response = client.get(
        "/api/v1/book/books/bk_shared/health",
        headers=_headers("alice"),
    )

    assert response.status_code == 200
    assert response.json()["kb_drift"]["cached"] is True
    assert response.json()["kb_drift"]["stale_page_ids"] == ["pg_1"]
    assert canonical.load_book("bk_shared").updated_at == updated_at


def test_shared_editor_requires_current_revision(shared_env) -> None:
    client, canonical = shared_env
    missing = client.post(
        "/api/v1/book/books/update-block",
        headers=_headers("editor"),
        json={
            "book_id": "bk_shared",
            "page_id": "pg_1",
            "block_id": "blk_1",
            "body": "First",
        },
    )
    assert missing.status_code == 409
    assert missing.json()["detail"]["code"] == "book_revision_required"

    success = client.post(
        "/api/v1/book/books/update-block",
        headers=_headers("editor"),
        json={
            "book_id": "bk_shared",
            "page_id": "pg_1",
            "block_id": "blk_1",
            "body": "Edited",
            "expected_revision": 1,
        },
    )
    assert success.status_code == 200
    assert success.json()["book_revision"] == 2
    assert canonical.load_page("bk_shared", "pg_1").blocks[0].payload["body"] == "Edited"

    stale = client.post(
        "/api/v1/book/books/update-block",
        headers=_headers("editor"),
        json={
            "book_id": "bk_shared",
            "page_id": "pg_1",
            "block_id": "blk_1",
            "body": "Stale",
            "expected_revision": 1,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "book_revision_conflict"
    assert stale.json()["detail"]["current_revision"] == 2


def test_shared_capabilities_are_returned_in_list_and_detail(shared_env) -> None:
    client, _ = shared_env
    listing = client.get("/api/v1/book/books", headers=_headers("alice")).json()
    assert listing["can_create"] is True
    assert listing["books"][0]["source"] == "shared"
    assert listing["books"][0]["permission"] == "read"
    assert listing["books"][0]["can_edit"] is False
    assert listing["books"][0]["can_delete"] is False

    detail = client.get("/api/v1/book/books/bk_shared", headers=_headers("editor")).json()
    assert detail["book"]["revision"] == 1
    assert detail["book"]["can_edit"] is True
    assert detail["book"]["can_delete"] is False


def test_admin_delete_cleans_explicit_book_permissions(shared_env) -> None:
    from deeptutor.multi_user.book_permission import normalize_book_permission
    from deeptutor.multi_user.identity import get_user

    client, canonical = shared_env
    response = client.delete(
        "/api/v1/book/books/bk_shared",
        headers=_headers("root"),
    )

    assert response.status_code == 200
    assert canonical.load_book("bk_shared") is None
    alice = get_user("alice")
    editor = get_user("editor")
    assert alice is not None and editor is not None
    assert "bk_shared" not in normalize_book_permission(alice.get("book_permission")).books_dict()
    assert "bk_shared" not in normalize_book_permission(editor.get("book_permission")).books_dict()
