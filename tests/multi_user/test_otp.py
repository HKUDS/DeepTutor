"""OTP issue/verify behaviour (ADR-002 D2-3).

Each test names the property from the ADR table it defends. Where a test needs
the clock to move, it passes ``now=`` rather than sleeping: a two-minute expiry
must not cost two minutes of suite time, and a time-dependent test that sleeps
is a flaky test.
"""

from __future__ import annotations

import pytest

from deeptutor.multi_user import otp
from deeptutor.multi_user.otp import (
    OTP_MAX_ATTEMPTS,
    OTP_MAX_SENDS_PER_WINDOW,
    OTP_RESEND_COOLDOWN_SECONDS,
    OTP_TTL_SECONDS,
    OtpInvalid,
    OtpRateLimited,
)

PHONE = "+989121234567"

# The store is a file under ``paths.SYSTEM_ROOT``; without this the records
# leak between tests and the rate limiter starts refusing the second test's
# first send.
pytestmark = pytest.mark.usefixtures("mu_isolated_root")


@pytest.fixture
def sent() -> list[tuple[str, str]]:
    """Records deliveries instead of hitting a provider."""
    return []


@pytest.fixture
def sender(sent):
    def _send(phone: str, message: str) -> None:
        sent.append((phone, message))

    return _send


def code_from(message: str) -> str:
    """The issued code is the trailing token of the Persian template."""
    return message.rsplit(":", 1)[-1].strip()


def issue(sender, now: float = 1000.0):
    return otp.issue_code(PHONE, send=sender, now=now)


# ---------------------------------------------------------------- happy path


def test_issue_then_verify_succeeds(sender, sent) -> None:
    issue(sender)
    otp.verify_code(PHONE, code_from(sent[0][1]), now=1001.0)


def test_issued_record_stores_no_plaintext_code(sender, sent) -> None:
    """No plaintext code at rest — the headline requirement of Phase 2."""
    issue(sender)
    code = code_from(sent[0][1])

    raw = otp._store_path().read_text(encoding="utf-8")
    assert code not in raw
    # The digest is present, so this is a real record and not an empty file.
    assert "digest" in raw
    assert PHONE in raw


def test_stored_digest_differs_for_the_same_code_across_numbers(sender, sent) -> None:
    """Per-record salt, so identical digits do not collide in storage."""
    otp.issue_code(PHONE, send=sender, now=1000.0)
    otp.issue_code("+989129999999", send=sender, now=1000.0)

    store = otp._read_store()
    assert store[PHONE]["salt"] != store["+989129999999"]["salt"]


# ------------------------------------------------------------------- expiry


def test_expired_code_is_rejected(sender, sent) -> None:
    issue(sender, now=1000.0)
    with pytest.raises(OtpInvalid):
        otp.verify_code(PHONE, code_from(sent[0][1]), now=1000.0 + OTP_TTL_SECONDS + 1)


def test_expiry_boundary_is_exclusive(sender, sent) -> None:
    """Exactly at ``expires_at`` counts as expired — no off-by-one window."""
    issue(sender, now=1000.0)
    code = code_from(sent[0][1])
    with pytest.raises(OtpInvalid):
        otp.verify_code(PHONE, code, now=1000.0 + OTP_TTL_SECONDS)


def test_expired_record_is_removed(sender, sent) -> None:
    issue(sender, now=1000.0)
    with pytest.raises(OtpInvalid):
        otp.verify_code(PHONE, "000000", now=1000.0 + OTP_TTL_SECONDS + 1)
    assert PHONE not in otp._read_store()


# -------------------------------------------------------------- single use


def test_a_used_code_cannot_be_replayed(sender, sent) -> None:
    issue(sender)
    code = code_from(sent[0][1])
    otp.verify_code(PHONE, code, now=1001.0)
    with pytest.raises(OtpInvalid):
        otp.verify_code(PHONE, code, now=1002.0)


def test_verifying_without_issuing_is_rejected() -> None:
    with pytest.raises(OtpInvalid):
        otp.verify_code(PHONE, "123456", now=1000.0)


def test_unknown_number_and_wrong_code_give_the_same_message() -> None:
    """No enumeration: both paths must be indistinguishable to a caller."""
    with pytest.raises(OtpInvalid) as no_record:
        otp.verify_code("+989120000000", "123456", now=1000.0)

    def sender(phone, message):
        pass

    otp.issue_code(PHONE, send=sender, now=1000.0)
    with pytest.raises(OtpInvalid) as wrong_code:
        otp.verify_code(PHONE, "000000", now=1000.0)

    assert str(no_record.value) == str(wrong_code.value)


# ------------------------------------------------------------------ attempts


def test_wrong_code_is_rejected(sender, sent) -> None:
    issue(sender)
    with pytest.raises(OtpInvalid):
        otp.verify_code(PHONE, "000000", now=1001.0)


def test_attempts_are_counted(sender, sent) -> None:
    issue(sender)
    for _ in range(OTP_MAX_ATTEMPTS - 1):
        with pytest.raises(OtpInvalid):
            otp.verify_code(PHONE, "000000", now=1001.0)
    assert otp._read_store()[PHONE]["attempts"] == OTP_MAX_ATTEMPTS - 1


def test_code_is_burned_after_too_many_attempts(sender, sent) -> None:
    """The correct code stops working once the attempt budget is spent."""
    issue(sender)
    real = code_from(sent[0][1])
    for _ in range(OTP_MAX_ATTEMPTS):
        with pytest.raises(OtpInvalid):
            otp.verify_code(PHONE, "000000", now=1001.0)

    assert PHONE not in otp._read_store()
    with pytest.raises(OtpInvalid):
        otp.verify_code(PHONE, real, now=1002.0)


# ------------------------------------------------------------------- resend


def test_resend_inside_cooldown_is_refused(sender, sent) -> None:
    issue(sender, now=1000.0)
    with pytest.raises(OtpRateLimited) as exc:
        issue(sender, now=1000.0 + OTP_RESEND_COOLDOWN_SECONDS - 1)
    assert exc.value.retry_after >= 1


def test_resend_after_cooldown_is_allowed(sender, sent) -> None:
    issue(sender, now=1000.0)
    issue(sender, now=1000.0 + OTP_RESEND_COOLDOWN_SECONDS + 1)
    assert len(sent) == 2


def test_send_window_caps_total_messages(sender, sent) -> None:
    now = 1000.0
    for _ in range(OTP_MAX_SENDS_PER_WINDOW):
        issue(sender, now=now)
        now += OTP_RESEND_COOLDOWN_SECONDS + 1

    with pytest.raises(OtpRateLimited):
        issue(sender, now=now)


def test_window_rolls_over_and_allows_sending_again(sender, sent) -> None:
    now = 1000.0
    for _ in range(OTP_MAX_SENDS_PER_WINDOW):
        issue(sender, now=now)
        now += OTP_RESEND_COOLDOWN_SECONDS + 1

    with pytest.raises(OtpRateLimited):
        issue(sender, now=now)

    # Past the 15-minute window, sending is permitted again.
    with pytest.raises(OtpRateLimited):
        issue(sender, now=now)
    later = 1000.0 + otp.OTP_SEND_WINDOW_SECONDS + 1
    issue(sender, now=later)


def test_rate_limit_does_not_consume_the_previous_code(sender, sent) -> None:
    """A refused resend must leave the outstanding code valid."""
    issue(sender, now=1000.0)
    first = code_from(sent[0][1])
    with pytest.raises(OtpRateLimited):
        issue(sender, now=1001.0)

    otp.verify_code(PHONE, first, now=1002.0)


# ---------------------------------------------------------------- housekeeping


def test_purge_expired_removes_only_dead_records(sender, sent) -> None:
    otp.issue_code(PHONE, send=sender, now=1000.0)
    otp.issue_code("+989129999999", send=sender, now=1000.0 + OTP_TTL_SECONDS)

    removed = otp.purge_expired(now=1000.0 + OTP_TTL_SECONDS + 1)
    assert removed == 1
    assert PHONE not in otp._read_store()
    assert "+989129999999" in otp._read_store()


def test_generated_codes_are_six_digits() -> None:
    for _ in range(50):
        code = otp.generate_code()
        assert len(code) == 6
        assert code.isdigit()
