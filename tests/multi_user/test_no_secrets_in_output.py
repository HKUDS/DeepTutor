"""No raw OTP or password may reach storage, logs or a response (Phase 2).

The roadmap states this as an acceptance condition: «هیچ OTP/password خام در
DB/log/trace». Each test here targets one sink, because "we do not log secrets"
is easy to believe and easy to break with one careless ``logger.info``.

The sinks covered:

* the on-disk OTP store
* the log records produced while issuing and verifying
* the HTTP response bodies of the OTP endpoints
* the user store (password hashes only, never plaintext)
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth_otp
from deeptutor.multi_user import identity, otp

pytestmark = pytest.mark.usefixtures("mu_isolated_root")

PHONE = "+989121234567"


@pytest.fixture
def otp_client(monkeypatch) -> TestClient:
    """A client for the OTP router with auth on and a private peer."""
    monkeypatch.setattr(auth_otp, "AUTH_ENABLED", True)
    monkeypatch.setenv("DEEPTUTOR_SMS_PROVIDER", "mock")

    app = FastAPI()
    app.include_router(auth_otp.router, prefix="/api/auth")
    return TestClient(app)


def _captured_code(client: TestClient) -> str:
    """The code the mock provider was handed."""
    from deeptutor.multi_user.sms import get_sms_provider

    provider = get_sms_provider()
    message = provider.last_for(PHONE)  # type: ignore[attr-defined]
    assert message, "no message was delivered"
    return message.rsplit(":", 1)[-1].strip()


# ---------------------------------------------------------------- the store


def test_store_holds_a_digest_not_the_code(otp_client, caplog) -> None:
    with caplog.at_level(logging.DEBUG):
        otp_client.post("/api/auth/otp/request", json={"phone": PHONE})
    code = _captured_code(otp_client)

    raw = otp._store_path().read_text(encoding="utf-8")
    assert code not in raw
    payload = json.loads(raw)[PHONE]
    assert set(payload) >= {"salt", "digest", "expires_at", "attempts"}
    assert "code" not in payload


# ----------------------------------------------------------------- the logs


def test_issuing_logs_no_code(otp_client, caplog) -> None:
    with caplog.at_level(logging.DEBUG):
        otp_client.post("/api/auth/otp/request", json={"phone": PHONE})
    code = _captured_code(otp_client)

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert code not in text
    # The number is logged, so a support engineer can trace a delivery...
    assert "***" in text or "not actually sent" in text
    # ...but not in full.
    assert PHONE not in text


def test_verifying_logs_no_code(otp_client, caplog) -> None:
    otp_client.post("/api/auth/otp/request", json={"phone": PHONE})
    code = _captured_code(otp_client)

    with caplog.at_level(logging.DEBUG):
        otp_client.post(
            "/api/auth/otp/verify", json={"phone": PHONE, "code": code, "purpose": "signup"}
        )

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert code not in text


def test_dev_provider_logs_length_not_body(caplog) -> None:
    from deeptutor.multi_user.sms import LoggingSmsProvider

    provider = LoggingSmsProvider(logging.getLogger("phase2-secrets"))
    with caplog.at_level(logging.WARNING, logger="phase2-secrets"):
        provider.send(PHONE, "کد ورود شما به درسیار: 424242")

    text = " ".join(r.getMessage() for r in caplog.records)
    assert "424242" not in text


# ------------------------------------------------------------- the responses


def test_request_response_does_not_echo_the_code(otp_client) -> None:
    response = otp_client.post("/api/auth/otp/request", json={"phone": PHONE})
    assert response.status_code == 200
    code = _captured_code(otp_client)
    assert code not in response.text
    # Nor does it echo the number back in full.
    assert PHONE not in response.text


def test_verify_response_carries_a_session_not_a_secret(otp_client) -> None:
    otp_client.post("/api/auth/otp/request", json={"phone": PHONE})
    code = _captured_code(otp_client)

    response = otp_client.post(
        "/api/auth/otp/verify", json={"phone": PHONE, "code": code, "purpose": "signup"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # No password field at all, in any casing.
    for key in body:
        assert "password" not in key.lower()
        assert "hash" not in key.lower()


# ------------------------------------------------------------- the user store


def test_signup_stores_a_hash_not_a_password(otp_client) -> None:
    otp_client.post("/api/auth/otp/request", json={"phone": PHONE})
    code = _captured_code(otp_client)
    otp_client.post(
        "/api/auth/otp/verify", json={"phone": PHONE, "code": code, "purpose": "signup"}
    )

    record = identity.get_user(PHONE)
    assert record is not None
    stored = str(record.get("hash") or "")
    # bcrypt hashes start with $2 and are 60 characters; anything else means
    # someone stored something that is not a hash.
    assert stored.startswith("$2"), f"unexpected hash format: {stored[:12]!r}"
    assert len(stored) == 60


def test_user_list_never_returns_hashes() -> None:
    identity.save_user("someone", "hash-value-here", role="user")
    for row in identity.list_user_info():
        assert "hash" not in row
