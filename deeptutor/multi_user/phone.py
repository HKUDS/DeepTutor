"""Phone-number normalisation for phone-based identity.

Phase 2 of the Darsyar roadmap makes a phone number the sign-up identity
(D-005), so the same human typing the same number three ways has to resolve to
one account. Everything here is a pure function over a string: no I/O, no
config lookups, no provider calls, which is what makes the edge cases cheap to
test.

The canonical form is E.164 (``+989121234567``). That choice is deliberate:

* it is what SMS gateways expect, so no translation happens at send time;
* it sorts and compares correctly as a plain string, so the unique constraint
  on it behaves;
* the leading ``+`` makes it unmistakable in logs and support conversations,
  where ``0912...`` and ``912...`` otherwise look alike.

Only Iran is mapped from a national prefix. Adding a country means one entry in
``_NATIONAL_PREFIXES``; see ``ADR-002`` for why this is hand-written rather
than pulling in ``phonenumbers``.
"""

from __future__ import annotations

import re

#: Country calling code assumed when the caller supplies a national number.
DEFAULT_COUNTRY_CODE = "98"

#: National prefixes (the trunk "0" plus area/operator code) → country code.
#: Iran's mobile numbers are all ``09xxxxxxxxx``, so the trunk ``0`` is the only
#: thing to drop. Kept as a table rather than an ``if`` so a second country is a
#: data change, not a control-flow change.
_NATIONAL_PREFIXES: dict[str, str] = {
    "0": "98",
}

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")

#: Persian (U+06F0-06F9) and Arabic-Indic (U+0660-0669) digits, which is what a
#: Persian keyboard produces and what users paste from web forms.
_DIGIT_TRANSLATION = str.maketrans(
    {
        **{chr(0x06F0 + i): str(i) for i in range(10)},
        **{chr(0x0660 + i): str(i) for i in range(10)},
    }
)

#: Characters people type as visual grouping. Removed before anything else so
#: ``+98 912-345 6789`` and ``+989123456789`` are the same string.
_GROUPING = re.compile(r"[\s\-().\u200c\u00a0]+")


class InvalidPhoneNumber(ValueError):
    """Raised when a string cannot be read as a phone number at all."""


def normalize_phone(raw: str, *, default_country: str = DEFAULT_COUNTRY_CODE) -> str:
    """Return ``raw`` in E.164 form, or raise :class:`InvalidPhoneNumber`.

    >>> normalize_phone("۰۹۱۲ ۳۴۵ ۶۷۸۹")
    '+989123456789'
    >>> normalize_phone("+98 912 345 6789")
    '+989123456789'
    >>> normalize_phone("09123456789")
    '+989123456789'
    """
    if not isinstance(raw, str):
        raise InvalidPhoneNumber("phone number must be a string")

    text = raw.translate(_DIGIT_TRANSLATION)
    text = _GROUPING.sub("", text)

    if not text:
        raise InvalidPhoneNumber("phone number is empty")

    # ``00`` is the ITU international prefix; some carriers and most people
    # type it instead of ``+``.
    if text.startswith("00"):
        text = "+" + text[2:]

    if text.startswith("+"):
        candidate = text
    elif text.startswith("0"):
        # National form. The trunk prefix is not part of the country code, so
        # it is swapped out rather than kept.
        country = _NATIONAL_PREFIXES.get(text[0], default_country)
        candidate = f"+{country}{text[1:]}"
    else:
        # Bare national number, e.g. ``9123456789``.
        candidate = f"+{default_country}{text}"

    if not _E164.fullmatch(candidate):
        raise InvalidPhoneNumber(f"not a valid phone number: {raw!r}")

    return candidate


def is_valid_phone(raw: str, *, default_country: str = DEFAULT_COUNTRY_CODE) -> bool:
    """Non-raising companion to :func:`normalize_phone`."""
    try:
        normalize_phone(raw, default_country=default_country)
    except InvalidPhoneNumber:
        return False
    return True


def mask_phone(phone: str) -> str:
    """Return a form safe for logs and support screens.

    ``+989121234567`` → ``+98912***4567``. The middle digits are what identify
    the individual, and a support operator only needs the tail to confirm which
    line they are looking at.
    """
    if len(phone) < 8:
        return "***"
    return f"{phone[:6]}***{phone[-4:]}"
