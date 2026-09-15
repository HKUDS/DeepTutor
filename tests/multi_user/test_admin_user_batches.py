"""Regression tests for admin batch user provisioning and deletion."""

from __future__ import annotations

import pytest


@pytest.fixture
def batch_client(mu_isolated_root, seed_user, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import deeptutor.api.routers.auth as auth_router
    from deeptutor.services.auth import TokenPayload

    admin = seed_user("root", role="admin")
    tokens = {
        "admin-token": TokenPayload(username="root", role="admin", user_id=admin["id"]),
        "user-token": TokenPayload(username="alice", role="user", user_id="u_alice"),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    return TestClient(app), {
        "admin": {"Authorization": "Bearer admin-token"},
        "user": {"Authorization": "Bearer user-token"},
    }


def test_import_reports_rows_and_creates_only_ordinary_users(batch_client):
    client, headers = batch_client
    csv_data = (
        "username,password,preset\n"
        "alice,alice-password-123,learner\n"
        "bob,bob-password-123,standard\n"
        "carol,carol-password-123,custom\n"
        "alice,duplicate-password-123,standard\n"
        "carol,short,standard\n"
    )

    response = client.post(
        "/api/auth/users/import",
        files={"file": ("users.csv", csv_data.encode("utf-8"), "text/csv")},
        headers=headers["admin"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created_count"] == 3
    assert body["failed_count"] == 2
    assert [result["ok"] for result in body["results"]] == [True, True, True, False, False], body
    assert "Username already taken" in body["results"][3]["error"]
    assert "Password must be at least 8 characters" in body["results"][4]["error"]
    assert all(result["user"]["role"] == "user" for result in body["results"][:3])
    assert all(result["user"]["is_admin"] is False for result in body["results"][:3])

    users = {
        item["username"]: item
        for item in client.get("/api/auth/users", headers=headers["admin"]).json()
    }
    assert set(users) == {"root", "alice", "bob", "carol"}
    assert users["alice"]["preset"] == "learner"
    assert users["carol"]["preset"] == "custom"
    assert all(item["role"] == "user" for name, item in users.items() if name != "root")


def test_import_rejects_role_column_and_creates_nothing(batch_client):
    client, headers = batch_client
    csv_data = "username,password,preset,role\nalice,alice-password-123,standard,admin\n"

    response = client.post(
        "/api/auth/users/import",
        files={"file": ("users.csv", csv_data.encode("utf-8"), "text/csv")},
        headers=headers["admin"],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "CSV header must be exactly: username,password,preset"
    usernames = {
        item["username"] for item in client.get("/api/auth/users", headers=headers["admin"]).json()
    }
    assert usernames == {"root"}


def test_import_rolls_back_learner_when_grant_initialization_fails(batch_client, monkeypatch):
    client, headers = batch_client
    from deeptutor.multi_user import grants

    def fail_save_grant(*args, **kwargs):
        raise RuntimeError("grant initialization unavailable")

    monkeypatch.setattr(grants, "save_grant", fail_save_grant)

    response = client.post(
        "/api/auth/users/import",
        files={
            "file": (
                "users.csv",
                b"username,password,preset\nalice,alice-password-123,learner\n",
                "text/csv",
            )
        },
        headers=headers["admin"],
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["ok"] is False
    assert result["error"] == "The learner preset could not be initialized."
    usernames = {
        item["username"] for item in client.get("/api/auth/users", headers=headers["admin"]).json()
    }
    assert usernames == {"root"}


def test_import_requires_admin(batch_client):
    client, headers = batch_client

    response = client.post(
        "/api/auth/users/import",
        files={
            "file": (
                "users.csv",
                b"username,password,preset\nalice,alice-password-123,standard\n",
                "text/csv",
            )
        },
        headers=headers["user"],
    )

    assert response.status_code == 403


def test_batch_delete_requires_admin(batch_client):
    client, headers = batch_client

    response = client.post(
        "/api/auth/users/batch-delete",
        json={"usernames": ["alice"]},
        headers=headers["user"],
    )

    assert response.status_code == 403


def test_batch_delete_reports_partial_results_and_protects_current_admin(batch_client, seed_user):
    client, headers = batch_client
    seed_user("alice")
    seed_user("bob")

    response = client.post(
        "/api/auth/users/batch-delete",
        json={"usernames": ["alice", "root", "missing", "bob"]},
        headers=headers["admin"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "ok": False,
        "deleted_count": 2,
        "failed_count": 2,
        "results": [
            {"username": "alice", "ok": True, "error": None},
            {"username": "root", "ok": False, "error": "You cannot delete your own account"},
            {"username": "missing", "ok": False, "error": "User not found"},
            {"username": "bob", "ok": True, "error": None},
        ],
    }
    usernames = {
        item["username"] for item in client.get("/api/auth/users", headers=headers["admin"]).json()
    }
    assert usernames == {"root"}
