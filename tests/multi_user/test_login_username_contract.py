"""Contract: auth accepts a plain username, not just an email address.

The admin "Add user" dialog and the login/register forms let an operator use a
bare username (no ``@``). These tests lock the backend half of that contract so
a future change (e.g. swapping the field for ``pydantic.EmailStr``) can't
silently make username login impossible again — which is exactly the bug the
frontend ``type="text"`` fix was paired with.
"""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from deeptutor.api.routers.auth import LoginRequest, RegisterRequest

# ---------------------------------------------------------------------------
# RegisterRequest.username — the real validator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "username",
    [
        "admin@admin.com",  # standard email (PocketBase mode)
        "user.name@sub.example.co",  # email with dotted local/sub-domain
        "admin",  # bare username (SQLite/JSON mode) — the regression guard
        "john_doe",
        "user.name",
        "a-b-c",
        "abc",  # minimum length (3)
        "x" * 64,  # maximum length (64)
    ],
)
def test_register_accepts_email_or_plain_username(username: str) -> None:
    assert RegisterRequest(username=username, password="password1234").username == username


@pytest.mark.parametrize(
    "username",
    [
        "",  # empty
        "   ",  # whitespace only
        "ab",  # too short for a plain username and not an email
        "x" * 65,  # too long
        "has space",  # spaces allowed in neither form
        "@nodomain",  # has '@' but is not a valid email
        "bad@",  # malformed email, '@' disqualifies it as a plain username
        "no-at-but-bad!",  # '!' is outside the plain-username charset
    ],
)
def test_register_rejects_invalid_username(username: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(username=username, password="password1234")


def test_register_username_is_trimmed() -> None:
    assert RegisterRequest(username="  admin  ", password="password1234").username == "admin"


@pytest.mark.parametrize("password", ["", "short", "1234567"])  # all < 8 chars
def test_register_rejects_short_password(password: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(username="admin", password=password)


def test_register_accepts_eight_char_password() -> None:
    assert RegisterRequest(username="admin", password="12345678").password == "12345678"


# ---------------------------------------------------------------------------
# LoginRequest — must NOT impose email-only validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("username", ["admin", "admin@admin.com", "john_doe"])
def test_login_accepts_plain_username(username: str) -> None:
    """Login must accept whatever identity a user registered with — including a
    bare username. It also must not re-validate the password length, or existing
    accounts with legacy short passwords could no longer sign in."""
    req = LoginRequest(username=username, password="x")
    assert req.username == username
    assert req.password == "x"


# ---------------------------------------------------------------------------
# End-to-end: a user created with a plain username can authenticate
# ---------------------------------------------------------------------------


def test_authenticate_round_trip_with_plain_username(
    monkeypatch: pytest.MonkeyPatch, seed_user
) -> None:
    pytest.importorskip("bcrypt")  # password hashing dep; present in CI/Docker
    from deeptutor.services import auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    seed_user("plainuser", password="password1234")

    payload = auth_service.authenticate("plainuser", "password1234")
    assert payload is not None
    assert payload.username == "plainuser"

    assert auth_service.authenticate("plainuser", "wrong-password") is None
    assert auth_service.authenticate("ghost", "password1234") is None
