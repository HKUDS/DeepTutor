"""Regression tests for #481.

When ``require_auth`` was declared as a sync ``def``, FastAPI dispatched it
through ``anyio.to_thread.run_sync``, which executes the function in a worker
thread under a *copy* of the request context. Any ``ContextVar.set`` inside
that thread is discarded when the thread returns, so the endpoint reads the
unset default. The user-scoped path service then silently falls back to the
admin workspace and non-admin users hit 404 on every session request.

These tests pin two invariants:

1. ``require_auth`` and ``require_admin`` are declared ``async``.
2. With ``AUTH_ENABLED=true`` and a valid token, the user ContextVar set
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
    that path service must point at ``multi-user/<uid>/``, not the
    admin fallback."""
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.multi_user import paths as mu_paths
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.path_service import get_path_service

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(mu_paths, "MULTI_USER_ROOT", tmp_path / "multi-user")
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
    assert "multi-user/u_alice" in chat_db, (
        f"Per-user request should resolve to multi-user/<uid>/ workspace, got: {chat_db}"
    )
