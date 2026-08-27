from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers.auth import require_admin
from deeptutor.book.models import Book
from deeptutor.book.storage import BookStorage


@pytest.fixture
def permission_client(tmp_path, monkeypatch):
    from deeptutor.book import engine as engine_module
    from deeptutor.book import storage as storage_module
    from deeptutor.multi_user import audit, grants, identity, paths, router
    from deeptutor.multi_user.paths import get_admin_path_service

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
    storage_module._storages.clear()
    engine_module._engines.clear()

    identity.save_user("root", "hash", role="admin")
    alice = identity.save_user("alice", "hash", role="user")
    BookStorage(path_service=get_admin_path_service()).save_book(
        Book(id="bk_shared", title="Shared")
    )

    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1/multi-user")
    app.dependency_overrides[require_admin] = lambda: object()
    return TestClient(app), alice


def test_admin_can_list_books_and_set_permission(permission_client) -> None:
    client, alice = permission_client
    catalog = client.get("/api/v1/multi-user/admin/books")
    assert catalog.status_code == 200
    assert catalog.json()["books"][0]["book_id"] == "bk_shared"

    response = client.put(
        f"/api/v1/multi-user/users/{alice['id']}/book-permission",
        json={
            "create": False,
            "default": "none",
            "books": {"bk_shared": "edit"},
        },
    )
    assert response.status_code == 200
    assert response.json()["permission"] == {
        "create": False,
        "default": "none",
        "books": {"bk_shared": "edit"},
    }


def test_permission_api_rejects_unknown_book_and_delete_level(permission_client) -> None:
    client, alice = permission_client
    unknown = client.put(
        f"/api/v1/multi-user/users/{alice['id']}/book-permission",
        json={"books": {"bk_missing": "read"}},
    )
    assert unknown.status_code == 400

    delete = client.put(
        f"/api/v1/multi-user/users/{alice['id']}/book-permission",
        json={"books": {"bk_shared": "delete"}},
    )
    assert delete.status_code == 422


def test_permission_api_rejects_default_edit(permission_client) -> None:
    client, alice = permission_client
    response = client.put(
        f"/api/v1/multi-user/users/{alice['id']}/book-permission",
        json={"default": "edit"},
    )
    assert response.status_code == 422
