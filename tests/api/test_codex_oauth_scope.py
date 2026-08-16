"""Who may drive the Codex OAuth lifecycle (issue #781).

These five endpoints act on the *caller's own* credentials — the store, the
model catalog, and the callback route are all resolved from owner scope — so
the administrator gate that used to sit on them was what left ordinary users
unable to use Codex at all: an owner-bound profile is never grantable, and
they could not sign in for themselves either.

What replaces it is narrower, not absent: a partner is refused. A partner is
a synthetic user whose owner is a real account, so admitting one would mean
acting on that person's login — including signing them out.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.partners.scope import PARTNER_USER_PREFIX

CODEX_ROUTES = [
    ("post", "/api/v1/settings/providers/openai-codex/oauth/start"),
    ("get", "/api/v1/settings/providers/openai-codex/oauth/status"),
    ("post", "/api/v1/settings/providers/openai-codex/oauth/cancel"),
    ("post", "/api/v1/settings/providers/openai-codex/oauth/logout"),
    ("post", "/api/v1/settings/providers/openai-codex/models/refresh"),
]


class _Service:
    """Stand-in for the per-owner ``CodexOAuthService``."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def start_login(self) -> dict[str, Any]:
        self.calls.append("start")
        return {"operation_id": "op-1"}

    def public_status(self) -> dict[str, Any]:
        self.calls.append("status")
        return {"connection": "disconnected"}

    async def cancel_login(self) -> dict[str, Any]:
        self.calls.append("cancel")
        return {"connection": "disconnected"}

    async def logout(self) -> dict[str, Any]:
        self.calls.append("logout")
        return {"connection": "disconnected"}

    async def refresh_models(self) -> dict[str, Any]:
        self.calls.append("refresh")
        return {"connection": "connected"}

    async def set_reasoning_effort(
        self,
        model: str,
        reasoning_effort: str | None,
    ) -> dict[str, Any]:
        self.calls.append(f"reasoning:{model}:{reasoning_effort}")
        return {"connection": "connected"}


def _user(uid: str, *, role: str, root) -> CurrentUser:
    return CurrentUser(
        id=uid,
        username=uid,
        role=role,
        scope=UserScope(kind="user", user_id=uid, root=root),
    )


@pytest.fixture
def client(tmp_path, monkeypatch) -> tuple[TestClient, _Service, dict[str, CurrentUser]]:
    service = _Service()
    monkeypatch.setattr(settings_router, "get_codex_oauth_service", lambda: service)
    current: dict[str, CurrentUser] = {
        "user": _user("u_alice", role="user", root=tmp_path / "alice")
    }
    monkeypatch.setattr(settings_router, "get_current_user", lambda: current["user"])

    app = FastAPI()
    app.include_router(settings_router.router, prefix="/api/v1/settings")
    return TestClient(app), service, current


@pytest.mark.parametrize(("method", "path"), CODEX_ROUTES)
def test_an_ordinary_user_drives_their_own_codex_lifecycle(client, method, path) -> None:
    test_client, service, _current = client

    response = getattr(test_client, method)(path)

    assert response.status_code == 200
    assert service.calls, "the request must reach the owner-scoped service"


def test_an_ordinary_user_sets_their_own_codex_reasoning_effort(client) -> None:
    test_client, service, _current = client

    response = test_client.post(
        "/api/v1/settings/providers/openai-codex/models/reasoning-effort",
        json={"model": "gpt-5.6-sol", "reasoning_effort": "high"},
    )

    assert response.status_code == 200
    assert service.calls == ["reasoning:gpt-5.6-sol:high"]


@pytest.mark.parametrize(("method", "path"), CODEX_ROUTES)
def test_a_partner_is_refused(client, tmp_path, method, path) -> None:
    """A partner inherits its owner's login at call time; letting it in here
    would let it sign that person out."""
    test_client, service, current = client
    current["user"] = _user(f"{PARTNER_USER_PREFIX}ada", role="user", root=tmp_path / "partner-ada")

    response = getattr(test_client, method)(path)

    assert response.status_code == 403
    assert service.calls == []


def test_a_partner_cannot_change_their_owners_reasoning_effort(client, tmp_path) -> None:
    test_client, service, current = client
    current["user"] = _user(f"{PARTNER_USER_PREFIX}ada", role="user", root=tmp_path / "partner-ada")

    response = test_client.post(
        "/api/v1/settings/providers/openai-codex/models/reasoning-effort",
        json={"model": "gpt-5.6-sol", "reasoning_effort": "high"},
    )

    assert response.status_code == 403
    assert service.calls == []
