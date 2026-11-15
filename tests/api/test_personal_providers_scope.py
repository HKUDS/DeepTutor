"""Who may manage personal "bring your own key" provider credentials (#1927).

Slice-1 wires three owner-scoped endpoints (list / save / delete) onto the
settings router. Like the Codex lifecycle, they act on the *caller's own*
credentials, so an ordinary user reaches them without administrator rights
and a partner is refused: a partner resolves to the account that owns it, so
admitting one would let it overwrite that person's provider key.

The service is stood in here to keep routing, gating, payload flow and error
translation deterministic. The real store's policy gate, redaction, SSRF
refusal and per-owner isolation are covered in
``tests/multi_user/test_personal_providers.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.partners.scope import PARTNER_USER_PREFIX
from deeptutor.services.personal_providers import PersonalProviderError

_SAVE_BODY = {"api_key": "sk-personal-secret", "base_url": "https://1.1.1.1/v1"}

PERSONAL_ROUTES = [
    ("get", "/api/settings/providers/personal", None),
    ("put", "/api/settings/providers/personal/openai", _SAVE_BODY),
    ("delete", "/api/settings/providers/personal/openai", None),
]


class _Service:
    """Stand-in for the per-owner ``PersonalProviderService``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.error: PersonalProviderError | None = None

    def _maybe_raise(self) -> None:
        if self.error is not None:
            raise self.error

    def list_public(self) -> list[dict[str, Any]]:
        self.calls.append(("list", None))
        self._maybe_raise()
        return [
            {
                "id": "openai",
                "label": "My key",
                "binding": "openai_compat",
                "base_url": "https://1.1.1.1/v1",
                "has_key": True,
            }
        ]

    async def save(
        self,
        provider_id: str,
        *,
        api_key: str,
        base_url: str,
        binding: str = "openai_compat",
        label: str = "",
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "save",
                {
                    "provider_id": provider_id,
                    "api_key": api_key,
                    "base_url": base_url,
                    "binding": binding,
                    "label": label,
                },
            )
        )
        self._maybe_raise()
        return {
            "id": provider_id,
            "label": label or provider_id,
            "binding": binding,
            "base_url": base_url,
            "has_key": True,
        }

    def delete(self, provider_id: str) -> dict[str, Any]:
        self.calls.append(("delete", provider_id))
        self._maybe_raise()
        return {"id": provider_id, "removed": True}


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
    monkeypatch.setattr(settings_router, "get_personal_provider_service", lambda: service)
    current: dict[str, CurrentUser] = {
        "user": _user("u_alice", role="user", root=tmp_path / "alice")
    }
    monkeypatch.setattr(settings_router, "get_current_user", lambda: current["user"])

    app = FastAPI()
    app.include_router(settings_router.router, prefix="/api/settings")
    return TestClient(app), service, current


@pytest.mark.parametrize(("method", "path", "body"), PERSONAL_ROUTES)
def test_an_ordinary_user_manages_their_own_providers(client, method, path, body) -> None:
    test_client, service, _current = client

    kwargs = {"json": body} if body is not None else {}
    response = getattr(test_client, method)(path, **kwargs)

    assert response.status_code == 200
    assert service.calls, "the request must reach the owner-scoped service"


@pytest.mark.parametrize(("method", "path", "body"), PERSONAL_ROUTES)
def test_a_partner_is_refused(client, tmp_path, method, path, body) -> None:
    """A partner resolves to its owner's secret store; letting it in here would
    let it overwrite that person's provider key."""
    test_client, service, current = client
    current["user"] = _user(f"{PARTNER_USER_PREFIX}ada", role="user", root=tmp_path / "partner-ada")

    kwargs = {"json": body} if body is not None else {}
    response = getattr(test_client, method)(path, **kwargs)

    assert response.status_code == 403
    assert service.calls == []


def test_save_forwards_the_whole_payload(client) -> None:
    test_client, service, _current = client

    response = test_client.put(
        "/api/settings/providers/personal/openai",
        json={**_SAVE_BODY, "binding": "openai_compat", "label": "My key"},
    )

    assert response.status_code == 200
    assert service.calls == [
        (
            "save",
            {
                "provider_id": "openai",
                "api_key": "sk-personal-secret",
                "base_url": "https://1.1.1.1/v1",
                "binding": "openai_compat",
                "label": "My key",
            },
        )
    ]


def test_save_response_never_contains_the_key(client) -> None:
    test_client, _service, _current = client

    response = test_client.put("/api/settings/providers/personal/openai", json=_SAVE_BODY)

    assert response.status_code == 200
    assert "api_key" not in response.json()
    assert "sk-personal-secret" not in response.text


def test_list_wraps_rows_under_providers(client) -> None:
    test_client, _service, _current = client

    response = test_client.get("/api/settings/providers/personal")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"providers"}
    assert payload["providers"][0]["id"] == "openai"
    assert "api_key" not in payload["providers"][0]


def test_delete_reports_removal(client) -> None:
    test_client, service, _current = client

    response = test_client.delete("/api/settings/providers/personal/openai")

    assert response.status_code == 200
    assert response.json() == {"id": "openai", "removed": True}
    assert service.calls == [("delete", "openai")]


def test_policy_off_maps_to_403(client) -> None:
    test_client, service, _current = client
    service.error = PersonalProviderError(
        "personal_providers_disabled",
        "Personal providers are not enabled on this deployment.",
        403,
    )

    response = test_client.get("/api/settings/providers/personal")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "personal_providers_disabled"


@pytest.mark.parametrize(
    ("code", "http_status"),
    [
        ("invalid_provider_id", 400),
        ("unsupported_binding", 400),
        ("missing_api_key", 400),
        ("base_url_not_allowed", 400),
        ("unsafe_storage_path", 500),
    ],
)
def test_service_error_maps_to_http_status_and_code(client, code, http_status) -> None:
    test_client, service, _current = client
    service.error = PersonalProviderError(code, "A safe message.", http_status)

    response = test_client.put("/api/settings/providers/personal/openai", json=_SAVE_BODY)

    assert response.status_code == http_status
    detail = response.json()["detail"]
    assert detail == {"code": code, "message": "A safe message."}
