"""The phone sign-up flow end to end, over HTTP (Phase 2, D-005).

Covers the path a real user takes: request a code, receive it, verify it, end
up signed in with a session cookie. Everything goes through the router, so the
FastAPI layer, the OTP store and the identity store all have to agree.

The rate-limit and expiry rules are unit-tested in ``tests/multi_user/test_otp``
against an injected clock. Here they are only exercised where the HTTP layer
adds something: status codes, the ``Retry-After`` header, and the shape of the
responses.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth_otp
from deeptutor.multi_user import identity, otp
from deeptutor.multi_user.sms import MockSmsProvider

PHONE = "+989121234567"
PHONE_2 = "+989129876543"


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Redirect the whole multi-user tree, not just the OTP file.

    ``mu_isolated_root`` lives in ``tests/multi_user/conftest.py`` and is not
    visible from this directory, so the two paths this suite touches are
    redirected here directly.
    """
    from deeptutor.multi_user import paths

    system_root = tmp_path / "system"
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "USERS_ROOT", tmp_path / "users")
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", tmp_path)

    from deeptutor.multi_user import identity

    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", system_root / "auth" / "auth_secret")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "none-a")
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", tmp_path / "none-b")
    return system_root


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(auth_otp, "AUTH_ENABLED", True)
    monkeypatch.setenv("DEEPTUTOR_SMS_PROVIDER", "mock")

    # A fresh outbox per test, installed as the configured provider.
    provider = MockSmsProvider()
    monkeypatch.setattr(auth_otp, "get_sms_provider", lambda: provider)

    app = FastAPI()
    app.include_router(auth_otp.router, prefix="/api/auth")
    client = TestClient(app)
    client.provider = provider  # type: ignore[attr-defined]
    return client


def code_for(client: TestClient, phone: str = PHONE) -> str:
    provider = client.provider  # type: ignore[attr-defined]
    message = provider.last_for(phone)
    assert message, f"no message delivered to {phone}"
    return message.rsplit(":", 1)[-1].strip()


def signup(client: TestClient, phone: str = PHONE) -> dict:
    client.post("/api/auth/otp/request", json={"phone": phone})
    response = client.post(
        "/api/auth/otp/verify",
        json={"phone": phone, "code": code_for(client, phone), "purpose": "signup"},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ request


def test_request_returns_the_timing_contract(client) -> None:
    response = client.post("/api/auth/otp/request", json={"phone": PHONE})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["expires_in"] > 0
    assert body["resend_in"] > 0


def test_request_accepts_a_persian_digit_number(client) -> None:
    response = client.post("/api/auth/otp/request", json={"phone": "۰۹۱۲۱۲۳۴۵۶۷"})
    assert response.status_code == 200


def test_request_rejects_a_malformed_number(client) -> None:
    response = client.post("/api/auth/otp/request", json={"phone": "not-a-phone"})
    assert response.status_code == 400


def test_request_does_not_reveal_whether_the_account_exists(client) -> None:
    """Same status and same shape for a known and an unknown number."""
    signup(client, PHONE)  # PHONE now exists

    known = client.post("/api/auth/otp/request", json={"phone": PHONE})
    unknown = client.post("/api/auth/otp/request", json={"phone": PHONE_2})

    assert known.status_code == unknown.status_code == 200
    assert set(known.json()) == set(unknown.json())


def test_second_request_inside_the_cooldown_is_429_with_retry_after(client) -> None:
    client.post("/api/auth/otp/request", json={"phone": PHONE})
    response = client.post("/api/auth/otp/request", json={"phone": PHONE})

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1


def test_resend_alias_shares_the_rate_limiter(client) -> None:
    client.post("/api/auth/otp/request", json={"phone": PHONE})
    response = client.post("/api/auth/otp/resend", json={"phone": PHONE})
    assert response.status_code == 429


# ------------------------------------------------------------------- verify


def test_verify_creates_the_account_and_signs_in(client) -> None:
    body = signup(client)

    assert body["ok"] is True
    assert body["created"] is True
    assert body["username"] == PHONE
    # First account in an empty store is the administrator.
    assert body["role"] == "admin"
    assert body["is_admin"] is True

    # The session cookie is set, exactly as /login would set it.
    assert "dt_token" in client.cookies


def test_the_created_account_can_sign_in_with_a_password_reset(client) -> None:
    signup(client)
    record = identity.get_user(PHONE)
    assert record is not None
    # A real hash, so the account is not a password-less special case.
    assert str(record["hash"]).startswith("$2")


def test_second_signup_is_not_an_admin(client) -> None:
    signup(client, PHONE)
    body = signup(client, PHONE_2)
    assert body["role"] != "admin"
    assert body["is_admin"] is False


def test_verify_with_a_wrong_code_is_401(client) -> None:
    client.post("/api/auth/otp/request", json={"phone": PHONE})
    response = client.post(
        "/api/auth/otp/verify",
        json={"phone": PHONE, "code": "000000", "purpose": "signup"},
    )
    assert response.status_code == 401
    # No account was created by a failed verification.
    assert identity.get_user(PHONE) is None


def test_verify_of_a_used_code_is_401(client) -> None:
    signup(client)
    code = code_for(client)

    replay = client.post(
        "/api/auth/otp/verify",
        json={"phone": PHONE, "code": code, "purpose": "signup"},
    )
    assert replay.status_code == 401


def test_verify_twice_does_not_create_two_accounts(client) -> None:
    signup(client)
    first = identity.load_users()

    # A second request + verify signs in, it does not duplicate.
    client.post("/api/auth/otp/request", json={"phone": PHONE})
    client.post(
        "/api/auth/otp/verify",
        json={"phone": PHONE, "code": code_for(client), "purpose": "signup"},
    )

    assert identity.load_users() == first


def test_reset_purpose_for_an_unknown_number_is_refused(client) -> None:
    client.post("/api/auth/otp/request", json={"phone": PHONE})
    response = client.post(
        "/api/auth/otp/verify",
        json={"phone": PHONE, "code": code_for(client), "purpose": "reset"},
    )
    assert response.status_code == 401
    assert identity.get_user(PHONE) is None


def test_reset_purpose_for_a_known_number_signs_in(client) -> None:
    signup(client)
    identity.set_disabled(PHONE, False)

    client.post("/api/auth/otp/request", json={"phone": PHONE})
    response = client.post(
        "/api/auth/otp/verify",
        json={"phone": PHONE, "code": code_for(client), "purpose": "reset"},
    )
    assert response.status_code == 200
    assert response.json()["created"] is False


def test_a_disabled_account_cannot_sign_in_by_otp(client) -> None:
    signup(client)
    identity.set_disabled(PHONE, True)

    client.post("/api/auth/otp/request", json={"phone": PHONE})
    response = client.post(
        "/api/auth/otp/verify",
        json={"phone": PHONE, "code": code_for(client), "purpose": "signup"},
    )
    assert response.status_code == 401


def test_verifying_when_auth_is_off_is_refused(client, monkeypatch) -> None:
    monkeypatch.setattr(auth_otp, "AUTH_ENABLED", False)
    response = client.post("/api/auth/otp/request", json={"phone": PHONE})
    assert response.status_code == 400


# --------------------------------------------------------------- housekeeping


def test_expired_code_is_rejected_over_http(client, monkeypatch) -> None:
    client.post("/api/auth/otp/request", json={"phone": PHONE})
    code = code_for(client)

    # Move the clock past the TTL rather than sleeping two minutes.
    real_time = otp.time.time
    monkeypatch.setattr(otp.time, "time", lambda: real_time() + otp.OTP_TTL_SECONDS + 1)

    response = client.post(
        "/api/auth/otp/verify",
        json={"phone": PHONE, "code": code, "purpose": "signup"},
    )
    assert response.status_code == 401
