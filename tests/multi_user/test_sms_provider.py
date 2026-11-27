"""SMS provider contract and the mock that ships in Phase 2 (ADR-002 D2-5)."""

from __future__ import annotations

import logging

import pytest

from deeptutor.multi_user import sms
from deeptutor.multi_user.sms import (
    LoggingSmsProvider,
    MockSmsProvider,
    SmsDeliveryError,
    SmsProvider,
    get_sms_provider,
    sms_provider_is_real,
)


def test_mock_satisfies_the_protocol() -> None:
    assert isinstance(MockSmsProvider(), SmsProvider)


def test_mock_records_deliveries() -> None:
    provider = MockSmsProvider()
    provider.send("+989121234567", "hello")
    assert provider.outbox == [("+989121234567", "hello")]


def test_mock_last_for_returns_most_recent() -> None:
    provider = MockSmsProvider()
    provider.send("+989121234567", "first")
    provider.send("+989121234567", "second")
    provider.send("+989129999999", "other")
    assert provider.last_for("+989121234567") == "second"


def test_mock_last_for_unknown_number_is_none() -> None:
    assert MockSmsProvider().last_for("+989120000000") is None


def test_mock_clear_empties_the_outbox() -> None:
    provider = MockSmsProvider()
    provider.send("+989121234567", "hello")
    provider.clear()
    assert provider.outbox == []


def test_default_provider_is_the_mock(monkeypatch) -> None:
    monkeypatch.delenv("DEEPTUTOR_SMS_PROVIDER", raising=False)
    assert isinstance(get_sms_provider(), MockSmsProvider)


def test_unknown_provider_raises_rather_than_falling_back(monkeypatch) -> None:
    """A typo in a deployment variable must stop sign-up loudly."""
    monkeypatch.setenv("DEEPTUTOR_SMS_PROVIDER", "kavenegar")
    with pytest.raises(SmsDeliveryError):
        get_sms_provider()


def test_logging_provider_writes_no_message_body(caplog) -> None:
    """The body carries the OTP, so it must never reach a log file."""
    logger = logging.getLogger("test-sms")
    provider = LoggingSmsProvider(logger)

    with caplog.at_level(logging.WARNING, logger="test-sms"):
        provider.send("+989121234567", "کد ورود شما به درسیار: 123456")

    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "123456" not in joined
    assert "کد ورود" not in joined
    # It still has to be useful for support: a masked recipient and the length.
    assert "+98912***4567" in joined
    assert "chars=" in joined


def test_no_real_provider_is_configured_in_this_phase() -> None:
    """Phase 2 ships the seam, not a gateway. This is the assertion that says so."""
    assert sms_provider_is_real() is False
