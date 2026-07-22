"""Regression tests for #481 and the auth-dep refactor.

When ``require_auth`` was declared as a sync ``def``, FastAPI dispatched it
through ``anyio.to_thread.run_sync``, which executes the function in a worker
thread under a *copy* of the request context. Any ``ContextVar.set`` inside
that thread is discarded when the thread returns, so the endpoint reads the
unset default. The user-scoped path service then silently falls back to the
admin workspace and non-admin users hit 404 on every session request.

These tests pin three invariants:

1. ``require_auth`` and ``require_admin`` are declared ``async``.
2. ``_install_current_user`` is the single point of truth for the
   payload-to-CurrentUser mapping used by both HTTP and WebSocket entry
   points (``None`` → local admin, payload → ``user_from_token_payload``).
3. With ``AUTH_ENABLED=true`` and a valid token, the user ContextVar set
   inside ``require_auth`` is visible from inside the endpoint, so
   ``get_path_service()`` resolves to the per-user workspace.
"""

from __future__ import annotations

import inspect

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def test_require_auth_is_async_def() -> None:
    from deeptutor.api.routers.auth import require_admin, require_auth

    assert inspect.iscoroutinefunction(require_auth), (
        "require_auth must be async — a sync dep is run in a threadpool whose "
        "ContextVar mutations don't propagate back to the endpoint. See #481."
    )
    assert inspect.iscoroutinefunction(require_admin), (
        "require_admin must be async for the same reason."
    )


def test_install_current_user_maps_none_to_local_admin() -> None:
    """``_install_current_user(None)`` is the AUTH_ENABLED=false branch
    for both HTTP and WS deps. It must install the local admin user so
    that ``get_current_path_service()`` resolves to the admin workspace
    rather than silently falling back through the None path."""
    from deeptutor.api.routers.auth import _install_current_user
    from deeptutor.multi_user.context import get_current_user_or_none, reset_current_user
    from deeptutor.multi_user.models import LOCAL_ADMIN_ID, LOCAL_ADMIN_USERNAME

    token = _install_current_user(None)
    try:
        user = get_current_user_or_none()
        assert user is not None
        assert user.id == LOCAL_ADMIN_ID
        assert user.username == LOCAL_ADMIN_USERNAME
        assert user.role == "admin"
        assert user.scope.kind == "admin"
    finally:
        reset_current_user(token)


def test_install_current_user_maps_payload_to_scoped_user() -> None:
    """``_install_current_user(payload)`` must produce a user-scoped
    CurrentUser whose workspace root lives under USERS_ROOT — the
    same shape that ``ws_require_auth`` and HTTP deps need to install."""
    from deeptutor.api.routers.auth import _install_current_user
    from deeptutor.multi_user.context import get_current_user_or_none, reset_current_user
    from deeptutor.services.auth import TokenPayload

    token = _install_current_user(TokenPayload(username="alice", role="user", user_id="u_alice"))
    try:
        user = get_current_user_or_none()
        assert user is not None
        assert user.id == "u_alice"
        assert user.username == "alice"
        assert user.role == "user"
        assert user.scope.kind == "user"
    finally:
        reset_current_user(token)


def test_local_admin_token_payload_matches_local_admin_user() -> None:
    """The synthetic admin TokenPayload returned by ``require_admin`` when
    AUTH_ENABLED=false must use the same identity constants as
    ``local_admin_user()`` — drift between the two reintroduces the kind
    of dual-source-of-truth bug that #481 lived in."""
    from deeptutor.api.routers.auth import _local_admin_token_payload
    from deeptutor.multi_user.models import LOCAL_ADMIN_ID, LOCAL_ADMIN_USERNAME
    from deeptutor.multi_user.paths import local_admin_user

    tp = _local_admin_token_payload()
    user = local_admin_user()
    assert tp.username == LOCAL_ADMIN_USERNAME == user.username
    assert tp.user_id == LOCAL_ADMIN_ID == user.id
    assert tp.role == "admin" == user.role


def test_require_auth_propagates_user_contextvar_to_endpoint(monkeypatch) -> None:
    """End-to-end: a valid token through require_auth makes the user
    ContextVar visible to the endpoint."""
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user.context import get_current_user_or_none
    from deeptutor.services.auth import TokenPayload

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda _t: TokenPayload(username="alice", role="user", user_id="u_alice"),
    )

    app = FastAPI()

    @app.get("/whoami")
    async def whoami(_=Depends(auth_router.require_auth)) -> dict:
        user = get_current_user_or_none()
        if user is None:
            return {"seen": None}
        return {"seen": user.username, "role": user.role, "scope_kind": user.scope.kind}

    with TestClient(app) as client:
        resp = client.get("/whoami", headers={"Authorization": "Bearer test-token"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["seen"] == "alice", (
        "Endpoint should observe the user ContextVar set inside require_auth. "
        "If this returns None the dependency is being run in a threadpool and "
        "the ContextVar mutation is discarded — see #481."
    )
    assert body["role"] == "user"
    assert body["scope_kind"] == "user"


def test_require_auth_propagates_admin_contextvar_to_endpoint(monkeypatch) -> None:
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user.context import get_current_user_or_none
    from deeptutor.services.auth import TokenPayload

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda _t: TokenPayload(username="root", role="admin", user_id="u_root"),
    )

    app = FastAPI()

    @app.get("/whoami")
    async def whoami(_=Depends(auth_router.require_auth)) -> dict:
        user = get_current_user_or_none()
        return {"role": None if user is None else user.role}

    with TestClient(app) as client:
        resp = client.get("/whoami", headers={"Authorization": "Bearer test-token"})

    assert resp.status_code == 200
    assert resp.json() == {"role": "admin"}


def test_path_service_resolves_per_user_workspace_through_dependency(monkeypatch, tmp_path) -> None:
    """The full chain that the reporter exercised in #481: a non-admin
    request lands on an endpoint that calls ``get_path_service()`` and
    that path service must point at ``data/users/<uid>/``, not the
    admin fallback."""
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user import paths as mu_paths
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.path_service import get_path_service

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(mu_paths, "USERS_ROOT", tmp_path / "data" / "users")
    monkeypatch.setattr(mu_paths, "_path_services", {})
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda _t: TokenPayload(username="alice", role="user", user_id="u_alice"),
    )

    app = FastAPI()

    @app.get("/db-path")
    async def db_path(_=Depends(auth_router.require_auth)) -> dict:
        service = get_path_service()
        return {"chat_db": str(service.get_chat_history_db())}

    with TestClient(app) as client:
        resp = client.get("/db-path", headers={"Authorization": "Bearer test-token"})

    assert resp.status_code == 200
    chat_db = resp.json()["chat_db"]
    expected_root = str((tmp_path / "data" / "users" / "u_alice").resolve())
    assert chat_db.startswith(expected_root), (
        "Per-user request should resolve under the user's USERS_ROOT scope. "
        f"Expected prefix {expected_root!r}, got: {chat_db!r}. If this fails, the "
        "ContextVar mutation in require_auth is not reaching the endpoint — "
        "see #481."
    )
