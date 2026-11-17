"""Phone-OTP endpoints (Phase 2, `ADR-002`).

Kept in its own module rather than appended to ``auth.py``, which is already
2,000 lines: the phone flow is a self-contained story and reading it should not
mean scrolling past the codex callback and device credentials.

Mounted under the same ``/api/auth`` prefix, so the public paths are
``/api/auth/otp/request``, ``/api/auth/otp/verify`` and ``/api/auth/otp/resend``
(the last is an alias of ``request`` kept separate so a client can express
intent, and so rate-limit messages differ).

The existing password endpoints are untouched. A phone user and a password user
coexist: D-005 says the *first* sign-up is by phone, not that passwords stop
working.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from deeptutor.multi_user import otp as otp_service
from deeptutor.multi_user.phone import InvalidPhoneNumber, mask_phone, normalize_phone
from deeptutor.multi_user.sms import SmsDeliveryError, get_sms_provider

from .auth import (
    _COOKIE_MAX_AGE,
    AUTH_ENABLED,
    _cookie_attrs,
    _no_store,
    _require_private_frontend,
    add_user,
    create_token,
    get_user_info,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/otp", tags=["auth-otp"])


class OtpRequest(BaseModel):
    """Payload for ``POST /api/auth/otp/request``."""

    phone: str = Field(min_length=1, max_length=32)


class OtpVerifyRequest(BaseModel):
    """Payload for ``POST /api/auth/otp/verify``."""

    phone: str = Field(min_length=1, max_length=32)
    code: str = Field(min_length=4, max_length=8)
    #: Set by the client when this verification is a first-time sign-up, so the
    #: server knows whether an unknown number is an error or a new account.
    purpose: str = Field(default="signup", pattern="^(signup|reset)$")


def _normalise_or_400(raw: str) -> str:
    """Turn a user-typed number into E.164, or answer 400.

    The error deliberately does not echo the input: a rejected number may be a
    mistyped one, and reflecting it back is how logs end up holding whatever a
    caller sent.
    """
    try:
        return normalize_phone(raw)
    except InvalidPhoneNumber:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That does not look like a valid phone number.",
        ) from None


def _send(phone: str, message: str) -> None:
    """Deliver through the configured provider, mapping failures to 502."""
    provider = get_sms_provider()
    try:
        provider.send(phone, message)
    except SmsDeliveryError as exc:
        # The user must not be told "code sent" when it was not.
        logger.warning("SMS delivery failed for %s: %s", mask_phone(phone), exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="We could not send the code. Please try again.",
        ) from None


def _require_otp_available() -> None:
    if not AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication is disabled on this instance.",
        )


@router.post("/request")
async def request_code(body: OtpRequest, request: Request, response: Response) -> dict:
    """Send a code to ``phone``.

    Answers the same way whether or not the number already has an account.
    That is not politeness — a response that differs is a phone-number
    enumeration oracle, and the number space is small enough to walk.
    """
    _require_otp_available()
    _require_private_frontend(request)
    _no_store(response)

    phone = _normalise_or_400(body.phone)

    try:
        issued = otp_service.issue_code(phone, send=_send)
    except otp_service.OtpRateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from None

    logger.info("OTP issued for %s", mask_phone(phone))
    return {
        "ok": True,
        "expires_in": issued.expires_in,
        "resend_in": issued.resend_in,
    }


@router.post("/resend")
async def resend_code(body: OtpRequest, request: Request, response: Response) -> dict:
    """Alias of ``/request``.

    Exists so a client can distinguish intent in its logs; the rate limiter is
    shared, because counting them separately would double the send budget.
    """
    return await request_code(body, request, response)


@router.post("/verify")
async def verify_code(body: OtpVerifyRequest, request: Request, response: Response) -> dict:
    """Verify a code, creating the account on first sign-up.

    First verification with ``purpose=signup`` creates the account and promotes
    it to admin when the store was empty. The session cookie is set on success,
    so the caller is signed in exactly as ``/login`` would leave them.
    """
    _require_otp_available()
    _require_private_frontend(request)
    _no_store(response)

    phone = _normalise_or_400(body.phone)

    try:
        otp_service.verify_code(phone, body.code)
    except otp_service.OtpInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from None

    existing = get_user_info(phone)
    if existing is None:
        if body.purpose == "reset":
            # A reset for a number with no account is indistinguishable from a
            # wrong code to the caller; the log is where it is recorded.
            logger.info("Password reset requested for unknown number %s", mask_phone(phone))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="The code is incorrect or has expired.",
            )
        # First sign-up. `add_user` promotes the first account to admin itself,
        # so no explicit role is passed here.
        add_user(phone, _generate_placeholder_password(), role="user")
        logger.info("Account created by OTP for %s", mask_phone(phone))

    record = get_user_info(phone) or {}
    if record.get("disabled"):
        # Deliberately the same status as a bad code: a disabled account should
        # not learn that its number is known but blocked.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The code is incorrect or has expired.",
        )

    role = str(record.get("role") or "user")
    token = create_token(phone, role, str(record.get("id") or ""))
    response.set_cookie(value=token, max_age=_COOKIE_MAX_AGE, **_cookie_attrs())

    return {
        "ok": True,
        "user_id": record.get("id"),
        "username": phone,
        "role": role,
        "is_admin": role == "admin",
        "created": existing is None,
    }


def _generate_placeholder_password() -> str:
    """A random password nobody knows for an OTP-created account.

    The account signs in by OTP, so the password is unused. It must still be
    strong and unknown: a fixed value would be a back door, and an empty one
    would break the store's invariant that every record has a hash.
    """
    import secrets

    return secrets.token_urlsafe(32)
