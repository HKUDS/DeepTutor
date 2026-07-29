from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

from deeptutor.api.routers import auth as auth_router
from deeptutor.services import email_verification


def _request(ip: str = "127.0.0.1"):
    return SimpleNamespace(client=SimpleNamespace(host=ip))


@pytest.fixture
def auth_registration_env(tmp_path, monkeypatch):
    from deeptutor.multi_user import identity
    from deeptutor.services import auth as auth_service

    system_root = tmp_path / "data" / "system"
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "POCKETBASE_ENABLED", False)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "test-auth-secret")
    monkeypatch.setattr(
        auth_router,
        "load_auth_settings",
        lambda: {
            "self_registration_enabled": True,
            "email_verification_required": True,
        },
    )
    monkeypatch.setattr(email_verification, "email_delivery_configured", lambda: True)
    sent_challenges = []
    monkeypatch.setattr(
        email_verification,
        "send_verification_email",
        lambda challenge: sent_challenges.append(challenge),
    )
    monkeypatch.setattr(
        email_verification,
        "load_auth_settings",
        lambda: {
            "verification_code_ttl_minutes": 10,
            "verification_resend_cooldown_seconds": 60,
            "verification_max_attempts": 5,
            "verification_max_per_email_hour": 5,
            "verification_max_per_ip_hour": 30,
        },
    )
    return system_root, sent_challenges


@pytest.mark.asyncio
async def test_registration_requires_code_and_then_auto_logs_in(auth_registration_env) -> None:
    system_root, sent_challenges = auth_registration_env
    body = auth_router.EmailRegistrationRequest(
        email="User@Example.com", password="password1234"
    )
    result = await auth_router.request_registration_code(body, _request())
    assert result["ok"] is True

    with pytest.raises(HTTPException) as invalid:
        await auth_router.register(
            auth_router.VerifyRegistrationRequest(email="user@example.com", code="000000"),
            Response(),
        )
    assert invalid.value.status_code == 400

    db = system_root / "auth" / "email_verification.sqlite3"
    import sqlite3

    with sqlite3.connect(db) as connection:
        row = connection.execute(
            "SELECT code_digest, issued_at FROM pending_registrations WHERE email = ?",
            ("user@example.com",),
        ).fetchone()
    assert row is not None

    challenge = sent_challenges[0]
    response = Response()
    registered = await auth_router.register(
        auth_router.VerifyRegistrationRequest(
            email="user@example.com", code=challenge.code
        ),
        response,
    )
    assert registered["ok"] is True
    assert registered["role"] == "admin"
    assert "dt_token" in response.headers.get("set-cookie", "")

    with pytest.raises(HTTPException) as replay:
        await auth_router.register(
            auth_router.VerifyRegistrationRequest(
                email="user@example.com", code=challenge.code
            ),
            Response(),
        )
    assert replay.value.status_code == 400


@pytest.mark.asyncio
async def test_registration_request_does_not_send_for_existing_account(auth_registration_env) -> None:
    _, sent_challenges = auth_registration_env
    from deeptutor.services.auth import add_user

    add_user("existing@example.com", "password1234")
    sent = []

    # The route calls asyncio.to_thread with the function object, so replacing
    # it is enough to prove the existing-address branch stays side-effect free.
    import deeptutor.services.email_verification as verification_module

    original = verification_module.send_verification_email
    verification_module.send_verification_email = lambda challenge: sent.append(True)
    try:
        result = await auth_router.request_registration_code(
            auth_router.EmailRegistrationRequest(
                email="EXISTING@example.com", password="password1234"
            ),
            _request(),
        )
    finally:
        verification_module.send_verification_email = original

    assert result["ok"] is True
    assert sent == []
    assert sent_challenges == []
