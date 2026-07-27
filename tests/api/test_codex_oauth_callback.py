from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth as auth_router
from deeptutor.services.codex_auth.contracts import CodexAuthError


class FakeCodexOAuthService:
    def __init__(self, error: CodexAuthError | None = None) -> None:
        self.error = error
        self.received: list[tuple[str | None, str | None, str | None]] = []

    async def receive_callback(
        self,
        code: str | None,
        state: str | None,
        error: str | None,
    ) -> None:
        self.received.append((code, state, error))
        if self.error is not None:
            raise self.error


def _client(
    monkeypatch: pytest.MonkeyPatch,
    service: FakeCodexOAuthService,
) -> TestClient:
    monkeypatch.setattr(auth_router, "get_codex_oauth_service", lambda: service)
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1/auth")
    return TestClient(app)


def test_codex_callback_endpoint_delivers_without_echoing_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeCodexOAuthService()
    client = _client(monkeypatch, service)

    response = client.get(
        "/api/v1/auth/openai-codex/callback",
        params={
            "code": "private-code",
            "state": "private-state",
            "error": "private-error",
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("text/html")
    assert "Authentication received. You can return to DeepTutor." in response.text
    assert service.received == [
        ("private-code", "private-state", "private-error"),
    ]
    for secret in ("private-code", "private-state", "private-error"):
        assert secret not in response.text


@pytest.mark.parametrize(
    ("service_error", "expected_status"),
    [
        (
            CodexAuthError(
                "state_mismatch",
                "Codex sign-in returned an invalid state.",
                400,
            ),
            400,
        ),
        (
            CodexAuthError(
                "login_not_active",
                "Codex sign-in is not waiting for a callback.",
                409,
            ),
            409,
        ),
    ],
)
def test_codex_callback_endpoint_returns_safe_html_errors(
    monkeypatch: pytest.MonkeyPatch,
    service_error: CodexAuthError,
    expected_status: int,
) -> None:
    service = FakeCodexOAuthService(service_error)
    client = _client(monkeypatch, service)

    response = client.get(
        "/api/v1/auth/openai-codex/callback",
        params={
            "code": "private-code",
            "state": "private-state",
            "error": "access-token",
        },
    )

    assert response.status_code == expected_status
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("text/html")
    assert "Authentication could not be received." in response.text
    for secret in ("private-code", "private-state", "access-token"):
        assert secret not in response.text
