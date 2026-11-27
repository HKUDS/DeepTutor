"""Session revocation and account disabling (ADR-002 D2-4).

Two properties are under test:

* a token minted before a bump stops working, because ``decode_token`` compares
  the ``tv`` claim with the record;
* a disabled account loses both future sign-ins and existing tokens, because
  ``disabled`` was a field nothing read before this phase.

Backward compatibility gets its own test: a token with no ``tv`` claim at all
must still validate against a record with no ``token_version``. Otherwise
deploying this would sign out every user in the product.
"""

from __future__ import annotations

import pytest

from deeptutor.multi_user import identity
from deeptutor.services import auth

pytestmark = pytest.mark.usefixtures("mu_isolated_root")

USER = "phase2-user"
PASSWORD = "phase2-pass-123"


@pytest.fixture
def user(monkeypatch) -> str:
    """A real account in the isolated store, with auth enabled.

    ``AUTH_SECRET`` is read at import time, so an isolated run inherits
    whatever the environment had - usually nothing. Pinning it here is what
    makes token minting and decoding actually round-trip.
    """
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_SECRET", "test-secret-for-phase2-revocation")
    auth.add_user(USER, PASSWORD, role="user")
    return USER


def token_for(username: str, version: int | None = None) -> str:
    """Mint a token, optionally pinning its generation.

    Pinning matters: ``create_token`` reads the current version, so a test that
    wants "a token from before the bump" has to say so explicitly.
    """
    if version is None:
        return auth.create_token(username, role="user")
    from datetime import datetime, timedelta, timezone

    from jose import jwt

    payload = {
        "sub": username,
        "role": "user",
        "uid": "",
        "dcid": "",
        "dcs": "",
        "tv": version,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, auth.AUTH_SECRET, algorithm=auth._ALGORITHM)


# --------------------------------------------------------------- compatibility


def test_fresh_token_verifies(user) -> None:
    payload = auth.decode_token(token_for(user))
    assert payload is not None
    assert payload.username == user
    assert payload.token_version == 0


def test_legacy_token_without_tv_still_works(user) -> None:
    """A token minted before this claim existed must not be rejected.

    Every session in the product at deploy time looks like this, so failing
    here would be a mass sign-out.
    """
    from datetime import datetime, timedelta, timezone

    from jose import jwt

    payload = {
        "sub": user,
        "role": "user",
        "uid": "",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, auth.AUTH_SECRET, algorithm=auth._ALGORITHM)

    decoded = auth.decode_token(token)
    assert decoded is not None
    assert decoded.token_version == 0


def test_record_without_token_version_reads_as_zero(user) -> None:
    assert identity.token_version_of(user) == 0


# ------------------------------------------------------------------ revocation


def test_bump_invalidates_an_existing_token(user) -> None:
    token = token_for(user)
    assert auth.decode_token(token) is not None

    assert auth.revoke_user_sessions(user) is True

    assert auth.decode_token(token) is None


def test_token_minted_after_the_bump_works(user) -> None:
    auth.revoke_user_sessions(user)
    fresh = auth.create_token(user, role="user")
    assert auth.decode_token(fresh) is not None


def test_each_bump_invalidates_the_previous_generation(user) -> None:
    first = token_for(user)
    auth.revoke_user_sessions(user)
    second = auth.create_token(user, role="user")
    auth.revoke_user_sessions(user)

    assert auth.decode_token(first) is None
    assert auth.decode_token(second) is None


def test_revoking_an_unknown_user_reports_failure() -> None:
    """An admin action on a missing account must not read as success."""
    assert auth.revoke_user_sessions("nobody-here") is False


def test_revocation_does_not_touch_other_users(user) -> None:
    # `user` is requested for its side effect: it pins AUTH_SECRET, without
    # which both tokens below decode to None and the test passes vacuously.
    auth.add_user("other-user", PASSWORD, role="user")

    victim = token_for(USER)
    bystander = token_for("other-user")

    auth.revoke_user_sessions(USER)

    assert auth.decode_token(victim) is None
    assert auth.decode_token(bystander) is not None


# -------------------------------------------------------------------- disabled


def test_disabled_account_cannot_authenticate(user) -> None:
    assert identity.set_disabled(user, True) is True
    assert auth.authenticate(user, PASSWORD) is None


def test_restored_account_can_authenticate_again(user) -> None:
    identity.set_disabled(user, True)
    identity.set_disabled(user, False)
    assert auth.authenticate(user, PASSWORD) is not None


def test_disabling_kills_existing_tokens(user) -> None:
    token = token_for(user)
    assert auth.decode_token(token) is not None

    identity.set_disabled(user, True)

    assert auth.decode_token(token) is None


def test_disabled_login_is_refused_even_with_the_right_password(user) -> None:
    """The refusal must not depend on whether the guess was correct."""
    identity.set_disabled(user, True)
    assert auth.authenticate(user, PASSWORD) is None
    assert auth.authenticate(user, "wrong-password") is None


def test_is_disabled_reports_the_stored_flag(user) -> None:
    assert identity.is_disabled(user) is False
    identity.set_disabled(user, True)
    assert identity.is_disabled(user) is True


def test_disabling_an_unknown_user_reports_failure() -> None:
    assert identity.set_disabled("nobody-here", True) is False
