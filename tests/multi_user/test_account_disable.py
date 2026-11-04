"""Disabling an account: login stops working, and re-enabling restores it.

The flag existed in the user record and was honoured by the device-credential
path, but nothing could set it and password login never looked at it. These
tests pin the full loop, including the two boundaries an admin must not cross:
disabling themselves, and a non-admin disabling anybody.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_client(mu_isolated_root, monkeypatch):
    """The real auth router over an isolated store, with stub bearer tokens.

    ``services.auth.AUTH_ENABLED`` is forced on as well: ``authenticate()``
    reads that module's flag, not the router's.
    """
    import deeptutor.api.routers.auth as auth_router
    from deeptutor.multi_user.identity import save_user
    import deeptutor.services.auth as auth_service
    from deeptutor.services.auth import TokenPayload, hash_password

    alice = save_user("alice", hash_password("alice-password"), role="admin")
    bob = save_user("bob", hash_password("bob-password"), role="user")
    carol = save_user("carol", hash_password("carol-password"), role="user")

    tokens = {
        "admin-token": TokenPayload(username="alice", role="admin", user_id=alice["id"]),
        "carol-token": TokenPayload(username="carol", role="user", user_id=carol["id"]),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    return TestClient(app), {"alice": alice, "bob": bob, "carol": carol}


def test_admin_disables_an_account(admin_client):
    from deeptutor.multi_user.identity import get_user

    client, _users = admin_client
    response = client.put(
        "/api/auth/users/bob/disabled", headers=_auth("admin-token"), json={"disabled": True}
    )

    assert response.status_code == 200
    assert response.json()["disabled"] is True
    assert get_user("bob")["disabled"] is True


def test_a_disabled_account_cannot_sign_in(admin_client):
    from deeptutor.services.auth import authenticate

    client, _users = admin_client
    assert authenticate("bob", "bob-password") is not None

    client.put(
        "/api/auth/users/bob/disabled", headers=_auth("admin-token"), json={"disabled": True}
    )

    assert authenticate("bob", "bob-password") is None


def test_re_enabling_restores_access(admin_client):
    from deeptutor.multi_user.identity import get_user
    from deeptutor.services.auth import authenticate

    client, _users = admin_client
    client.put(
        "/api/auth/users/bob/disabled", headers=_auth("admin-token"), json={"disabled": True}
    )
    client.put(
        "/api/auth/users/bob/disabled", headers=_auth("admin-token"), json={"disabled": False}
    )

    assert get_user("bob")["disabled"] is False
    assert authenticate("bob", "bob-password") is not None


def test_only_an_admin_may_disable(admin_client):
    from deeptutor.multi_user.identity import get_user

    client, _users = admin_client
    response = client.put(
        "/api/auth/users/bob/disabled", headers=_auth("carol-token"), json={"disabled": True}
    )

    assert response.status_code == 403
    assert get_user("bob")["disabled"] is False


def test_an_admin_cannot_disable_themselves(admin_client):
    from deeptutor.multi_user.identity import get_user

    client, _users = admin_client
    response = client.put(
        "/api/auth/users/alice/disabled", headers=_auth("admin-token"), json={"disabled": True}
    )

    assert response.status_code == 400
    assert get_user("alice")["disabled"] is False


def test_disabling_an_unknown_account_is_a_404(admin_client):
    client, _users = admin_client
    response = client.put(
        "/api/auth/users/nobody/disabled", headers=_auth("admin-token"), json={"disabled": True}
    )

    assert response.status_code == 404
