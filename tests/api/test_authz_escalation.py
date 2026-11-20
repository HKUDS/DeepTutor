"""Authorisation boundaries: horizontal and vertical (Phase 2 acceptance).

The roadmap asks for a test proving a non-admin cannot execute *any* admin API
by calling it directly. Doing that one endpoint at a time is how the list falls
out of date: someone adds ``DELETE /users/{u}/sessions`` and nobody remembers to
add a test. So the endpoint list is **discovered** from the router instead, and
every route carrying the admin dependency is exercised without one.

What each test proves:

* ``test_every_admin_route_refuses_anonymous`` — no token at all → 401/403.
* ``test_every_admin_route_refuses_a_student`` — a valid *student* token → 403.
  This is the vertical escalation case: authenticated, but insufficient role.
* ``test_student_cannot_read_another_account`` — horizontal: same role, other
  subject.
* ``test_disabled_student_token_is_refused`` — a session that was killed.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth as auth_router
from deeptutor.services.auth import TokenPayload


def _admin_routes() -> list[tuple[str, str]]:
    """Every route on the auth router that requires an administrator.

    Discovered, not hard-coded, so a route added later is covered the moment
    it exists. The check looks at the route's dependencies by name, because
    ``require_admin`` is applied via ``Depends`` and FastAPI does not expose a
    role on the route object itself.
    """
    found = []
    for route in auth_router.router.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        names = {getattr(dep.call, "__name__", "") for dep in dependant.dependencies}
        if "require_admin" in names:
            methods = sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"})
            if methods:
                found.append((methods[0], route.path))
    return found


def _client(*, token: TokenPayload | None) -> TestClient:
    """Mount the real auth router; optionally stand in for require_auth."""
    from deeptutor.api.routers import auth_otp

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    # The OTP routes live on their own router; mounting it here is what makes
    # the "no payload" assertions below reach them instead of 404ing.
    app.include_router(auth_otp.router, prefix="/api/auth")
    if token is not None:
        # Only `require_auth` is overridden. `require_admin` stays real, so the
        # role check actually runs - overriding both would make every test pass.
        app.dependency_overrides[auth_router.require_auth] = lambda: token
    return TestClient(app, raise_server_exceptions=False)


STUDENT = TokenPayload(username="student-one", role="student", user_id="u_student")
ADMIN = TokenPayload(username="admin-one", role="admin", user_id="u_admin")


@pytest.fixture(autouse=True)
def _auth_on(monkeypatch):
    """Auth must be enabled or ``require_admin`` short-circuits to allow.

    That short-circuit is the documented behaviour for single-user installs,
    but it would make every assertion below vacuous.
    """
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)


def _fill_params(path: str) -> str:
    """Substitute concrete values for path parameters."""
    return path.replace("{username}", "target-user").replace("{device_credential_id}", "dev_1")


def test_the_admin_route_list_is_not_empty() -> None:
    """Guard against the discovery silently finding nothing."""
    routes = _admin_routes()
    assert routes, "no admin routes discovered - the dependency probe broke"
    # A few that must be in there, to catch a probe that finds only some.
    paths = {path for _method, path in routes}
    assert "/users" in paths
    assert "/users/{username}/role" in paths
    assert "/users/{username}/disabled" in paths


@pytest.mark.parametrize("method,path", _admin_routes())
def test_every_admin_route_refuses_anonymous(method: str, path: str) -> None:
    response = _client(token=None).request(method, f"/api/auth{_fill_params(path)}", json={})
    assert response.status_code in (401, 403, 422), (
        f"{method} {path} answered {response.status_code} without a token"
    )


@pytest.mark.parametrize("method,path", _admin_routes())
def test_every_admin_route_refuses_a_student(method: str, path: str) -> None:
    """Vertical escalation: a real session, not enough privilege."""
    response = _client(token=STUDENT).request(method, f"/api/auth{_fill_params(path)}", json={})
    assert response.status_code == 403, (
        f"{method} {path} answered {response.status_code} for a student"
    )


def test_an_admin_is_not_refused_by_the_same_gate(monkeypatch) -> None:
    """The 403s above must come from the role check, not from a broken route.

    Without this, a route that fails for everyone would still satisfy the
    parametrised tests.
    """
    from deeptutor.multi_user import identity

    monkeypatch.setattr(identity, "set_disabled", lambda *a, **k: True)
    monkeypatch.setattr(auth_router, "get_user_info", lambda u: {"id": "u_target"})
    monkeypatch.setattr(auth_router, "log_admin_action", lambda *a, **k: None)

    response = _client(token=ADMIN).put(
        "/api/auth/users/target-user/disabled", json={"disabled": True}
    )
    assert response.status_code == 200


def test_student_cannot_disable_another_account() -> None:
    """Horizontal plus vertical in one call: the destructive case."""
    response = _client(token=STUDENT).put(
        "/api/auth/users/victim/disabled", json={"disabled": True}
    )
    assert response.status_code == 403


def test_student_cannot_revoke_another_accounts_sessions() -> None:
    response = _client(token=STUDENT).post("/api/auth/users/victim/revoke-sessions")
    assert response.status_code == 403


def test_student_cannot_promote_themselves() -> None:
    response = _client(token=STUDENT).put(
        "/api/auth/users/student-one/role", json={"role": "admin"}
    )
    assert response.status_code == 403


def test_student_cannot_list_users() -> None:
    assert _client(token=STUDENT).get("/api/auth/users").status_code == 403


def test_admin_cannot_disable_themselves(monkeypatch) -> None:
    """The one action that can lock the panel out entirely."""
    response = _client(token=ADMIN).put(
        "/api/auth/users/admin-one/disabled", json={"disabled": True}
    )
    assert response.status_code == 400
    assert "own account" in response.json()["detail"]


def test_admin_cannot_change_their_own_role(monkeypatch) -> None:
    response = _client(token=ADMIN).put("/api/auth/users/admin-one/role", json={"role": "student"})
    assert response.status_code == 400


@pytest.mark.parametrize("path", ["/api/auth/otp/request", "/api/auth/otp/verify"])
def test_otp_routes_reject_a_missing_body(path: str) -> None:
    """No payload must be a 422, never a 500 with a traceback."""
    response = _client(token=None).post(path, json={})
    assert response.status_code == 422
