"""SMS delivery for OTP codes.

Only the interface and an in-memory mock ship in this phase. ``ADR-002``
records why: a real gateway needs a vendor decision and credentials the owner
has not supplied, and a fake gateway that pretends to send is worse than an
honest one that refuses.

The shape is deliberately tiny — ``send(phone, message)`` and nothing else. A
vendor SDK's retry policy, templating and delivery receipts are all things we
would otherwise inherit and have to fight; one function keeps the seam thin
enough to swap in a real provider later without touching the OTP logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import threading
from typing import Protocol, runtime_checkable

from .phone import mask_phone


class SmsDeliveryError(RuntimeError):
    """The provider refused to accept the message."""


@runtime_checkable
class SmsProvider(Protocol):
    """What the OTP service needs from a delivery channel."""

    def send(self, phone: str, message: str) -> None:
        """Deliver ``message`` to ``phone`` (already E.164).

        Must raise :class:`SmsDeliveryError` on failure. Silently swallowing a
        failure here would leave a user staring at "code sent" forever.
        """
        ...


@dataclass
class MockSmsProvider:
    """Keeps messages in memory so tests can read them back.

    Never touches the network. ``outbox`` is a plain list so a test can assert
    on what *would* have been delivered without any monkeypatching.
    """

    outbox: list[tuple[str, str]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def send(self, phone: str, message: str) -> None:
        with self._lock:
            self.outbox.append((phone, message))

    def last_for(self, phone: str) -> str | None:
        """Most recent message sent to ``phone``, or ``None``."""
        with self._lock:
            for recipient, message in reversed(self.outbox):
                if recipient == phone:
                    return message
        return None

    def clear(self) -> None:
        with self._lock:
            self.outbox.clear()


class LoggingSmsProvider:
    """Development-only: writes the fact of a message, never its contents.

    The message body carries the OTP, so logging it would put a live code in a
    file that outlives the code's two-minute lifetime. Only the recipient and
    the code's length are written.
    """

    def __init__(self, logger) -> None:
        self._logger = logger

    def send(self, phone: str, message: str) -> None:
        self._logger.warning(
            "SMS not actually sent (dev provider): to=%s chars=%d",
            mask_phone(phone),
            len(message),
        )


#: Process-wide mock, so a running dev server and a test helper see the same
#: outbox. Real providers would be constructed per call; this one has state.
_MOCK = MockSmsProvider()


def get_sms_provider() -> SmsProvider:
    """Resolve the provider named by ``DEEPTUTOR_SMS_PROVIDER``.

    ``mock`` (default) and ``log`` are the only implemented values. Anything
    else raises rather than falling back: a typo in a deployment variable
    should stop sign-up loudly, not silently route to the mock.
    """
    kind = (os.environ.get("DEEPTUTOR_SMS_PROVIDER") or "mock").strip().lower()
    if kind == "mock":
        return _MOCK
    if kind == "log":
        import logging

        return LoggingSmsProvider(logging.getLogger(__name__))
    raise SmsDeliveryError(
        f"Unknown SMS provider {kind!r}. Set DEEPTUTOR_SMS_PROVIDER to 'mock' or 'log'."
    )


def sms_provider_is_real() -> bool:
    """True when a provider that can actually reach a handset is configured.

    The OTP endpoints refuse to issue a code when this is False *and* the
    process is running in production — see ``ADR-002`` D2-5.
    """
    return False
