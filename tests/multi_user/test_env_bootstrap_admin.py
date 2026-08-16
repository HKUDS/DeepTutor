"""Regression tests for the env/``auth.json`` bootstrap admin (issue #849).

Two deployment shapes have to behave differently, and the identity store used
to conflate them:

* **Env-bootstrapped** — ``auth.json`` carries ``username`` +
  ``password_hash`` and ``users.json`` is empty. An admin already exists, so
  accounts created from ``/admin/users`` must stay ``role="user"`` and the
  bootstrap admin must keep working after the store gains its first record.
* **Genuinely empty** — no bootstrap credentials at all. The first account to
  register is promoted to admin, which is the documented bootstrap path.
"""

from __future__ import annotations

import pytest

# A real bcrypt hash of "bootstrap-pass-1234", generated in-test so no secret
# literal is committed.
_BOOTSTRAP_PASSWORD = "bootstrap-pass-1234"  # nosec B105 - test fixture credential


@pytest.fixture
def bootstrap_hash() -> str:
    from deeptutor.services.auth import hash_password

    return hash_password(_BOOTSTRAP_PASSWORD)


@pytest.fixture
def env_admin(mu_isolated_root, monkeypatch, bootstrap_hash):
    """Simulate an ``auth.json``-bootstrapped admin with an empty user store."""
    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_USERNAME", "operator")
    monkeypatch.setattr(auth_service, "AUTH_PASSWORD_HASH", bootstrap_hash)
    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    return "operator"


# ---------------------------------------------------------------------------
# Bug A — the first account created by an admin must not be promoted
# ---------------------------------------------------------------------------


def test_first_created_account_is_not_promoted_when_env_admin_exists(env_admin):
    """``POST /auth/users`` documents role=``user``; honour that."""
    from deeptutor.multi_user.identity import save_user

    record = save_user("student1", "$2b$12$placeholder", role="user")

    assert record["role"] == "user"


def test_admin_can_still_create_an_explicit_admin_when_env_admin_exists(env_admin):
    """The gate must not clamp an explicitly requested admin role."""
    from deeptutor.multi_user.identity import save_user

    record = save_user("deputy", "$2b$12$placeholder", role="admin")

    assert record["role"] == "admin"


# ---------------------------------------------------------------------------
# Bug B — the env bootstrap admin must survive the store gaining records
# ---------------------------------------------------------------------------


def test_env_admin_still_resolves_after_first_account_is_created(env_admin, bootstrap_hash):
    from deeptutor.multi_user.identity import load_users, save_user

    save_user("student1", "$2b$12$placeholder", role="user")

    users = load_users(env_admin, bootstrap_hash)

    assert set(users) == {env_admin, "student1"}
    assert users[env_admin]["role"] == "admin"
    assert users[env_admin]["hash"] == bootstrap_hash


def test_env_admin_can_log_in_after_first_account_is_created(env_admin):
    """End-to-end shape of the reported lockout: login returned 401."""
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import authenticate

    save_user("student1", "$2b$12$placeholder", role="user")

    payload = authenticate(env_admin, _BOOTSTRAP_PASSWORD)

    assert payload is not None
    assert payload.role == "admin"


def test_env_admin_is_never_written_into_the_user_store(env_admin):
    """The bootstrap admin is an in-memory overlay, not a persisted record.

    Persisting it would pin the hash at the time of the first write, so a
    later rotation of ``auth.json`` would silently keep accepting the old
    password.
    """
    import json

    from deeptutor.multi_user.identity import USERS_FILE, save_user

    save_user("student1", "$2b$12$placeholder", role="user")

    on_disk = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    assert set(on_disk) == {"student1"}


def test_stored_record_wins_over_env_bootstrap_admin(env_admin):
    """Re-creating the bootstrap username adopts the account into the store."""
    from deeptutor.multi_user.identity import load_users, save_user

    save_user(env_admin, "$2b$12$adopted", role="admin")

    users = load_users(env_admin, "$2b$12$fromenv")

    assert users[env_admin]["hash"] == "$2b$12$adopted"
    assert users[env_admin]["role"] == "admin"


def test_adopting_the_bootstrap_username_keeps_admin_role(env_admin):
    """The adoption write must not be demoted to ``user`` by the new gate."""
    from deeptutor.multi_user.identity import save_user

    record = save_user(env_admin, "$2b$12$adopted", role="user")

    assert record["role"] == "admin"


def test_env_admin_appears_exactly_once_in_the_admin_user_list(env_admin, bootstrap_hash):
    from deeptutor.multi_user.identity import list_user_info, save_user

    save_user("student1", "$2b$12$placeholder", role="user")

    listed = list_user_info(env_admin, bootstrap_hash)
    usernames = [item["username"] for item in listed]

    assert usernames.count(env_admin) == 1
    assert set(usernames) == {env_admin, "student1"}


def test_is_first_user_is_false_when_only_the_env_admin_exists(env_admin):
    from deeptutor.services.auth import is_first_user

    assert is_first_user() is False


# ---------------------------------------------------------------------------
# No-env-admin path — the documented bootstrap behaviour is preserved
# ---------------------------------------------------------------------------


def test_first_account_is_promoted_when_no_env_admin_exists(mu_isolated_root):
    from deeptutor.multi_user.identity import save_user

    record = save_user("alice", "$2b$12$placeholder", role="user")

    assert record["role"] == "admin"


def test_second_account_is_not_promoted_when_no_env_admin_exists(mu_isolated_root):
    from deeptutor.multi_user.identity import save_user

    save_user("alice", "$2b$12$placeholder", role="user")
    record = save_user("bob", "$2b$12$placeholder", role="user")

    assert record["role"] == "user"


def test_partial_env_credentials_do_not_count_as_an_admin(mu_isolated_root, monkeypatch):
    """A username with no hash cannot log in, so it must not block promotion.

    This is the shipped default (``auth.json`` seeds ``username="admin"`` with
    an empty hash), so treating it as an existing admin would leave a fresh
    deployment with no way to create one.
    """
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_USERNAME", "admin")
    monkeypatch.setattr(auth_service, "AUTH_PASSWORD_HASH", "")

    record = save_user("alice", "$2b$12$placeholder", role="user")

    assert record["role"] == "admin"


def test_is_first_user_is_true_for_a_genuinely_empty_deployment(mu_isolated_root):
    from deeptutor.services.auth import is_first_user

    assert is_first_user() is True


# ---------------------------------------------------------------------------
# End-to-end over the real router — the exact sequence reported in #849
# ---------------------------------------------------------------------------


@pytest.fixture
def bootstrap_client(env_admin, monkeypatch):
    """TestClient over the auth router, authenticated as the bootstrap admin."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import deeptutor.api.routers.auth as auth_router
    from deeptutor.services.auth import TokenPayload

    tokens = {
        "operator-token": TokenPayload(username=env_admin, role="admin", user_id="env-admin"),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1/auth")
    return TestClient(app), {"Authorization": "Bearer operator-token"}


def test_admin_create_user_returns_role_user(bootstrap_client):
    client, headers = bootstrap_client

    response = client.post(
        "/api/v1/auth/users",
        json={"username": "student1", "password": "student-pass-1234"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "user"
    assert body["is_admin"] is False


def test_bootstrap_admin_remains_listed_after_creating_an_account(bootstrap_client, env_admin):
    client, headers = bootstrap_client

    client.post(
        "/api/v1/auth/users",
        json={"username": "student1", "password": "student-pass-1234"},
        headers=headers,
    )
    listed = client.get("/api/v1/auth/users", headers=headers).json()

    by_name = {item["username"]: item for item in listed}
    assert by_name[env_admin]["role"] == "admin"
    assert by_name["student1"]["role"] == "user"


def test_bootstrap_admin_username_cannot_be_taken_by_a_new_account(bootstrap_client, env_admin):
    """The bootstrap username is now reserved, so it cannot be clobbered.

    Creating a store record under that name would shadow the overlay and
    demote the operator, so the endpoint must reject it as already taken.
    """
    client, headers = bootstrap_client

    response = client.post(
        "/api/v1/auth/users",
        json={"username": env_admin, "password": "attacker-pass-1234"},
        headers=headers,
    )

    assert response.status_code == 409
