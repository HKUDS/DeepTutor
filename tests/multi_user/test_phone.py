"""Phone normalisation (ADR-002 D2-2).

The point of these tests is that one human typing one number seven ways
resolves to one account. Every accepted shape is therefore asserted against the
same expected output, and every rejected shape is asserted to raise rather than
silently produce something plausible.
"""

from __future__ import annotations

import pytest

from deeptutor.multi_user.phone import (
    InvalidPhoneNumber,
    is_valid_phone,
    mask_phone,
    normalize_phone,
)

CANONICAL = "+989123456789"

ACCEPTED_FORMS = [
    "+989123456789",
    "+98 912 345 6789",
    "+98-912-345-6789",
    "00989123456789",
    "09123456789",
    "0912 345 6789",
    "0912-345-6789",
    "(0912) 345 6789",
    "9123456789",
    "۰۹۱۲۳۴۵۶۷۸۹",  # Persian digits, no separators
    "۰۹۱۲ ۳۴۵ ۶۷۸۹",  # Persian digits with spaces
    "٠٩١٢٣٤٥٦٧٨٩",  # Arabic-Indic digits
    "  +98 912 345 6789  ",  # padded
    "09123456789\u200c",  # trailing ZWNJ, which a Persian keyboard can add
]


@pytest.mark.parametrize("raw", ACCEPTED_FORMS)
def test_accepted_forms_normalise_to_one_canonical_value(raw: str) -> None:
    assert normalize_phone(raw) == CANONICAL


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "abc",
        "not-a-number",
        "0912",  # too short
        "+0",  # no country code content
        "09123456789012345",  # too long
        "+98912345678901234",  # exceeds E.164's 15 digits
        "++989123456789",
        "-----",
    ],
)
def test_rejected_input_raises(raw: str) -> None:
    with pytest.raises(InvalidPhoneNumber):
        normalize_phone(raw)


def test_non_string_raises() -> None:
    with pytest.raises(InvalidPhoneNumber):
        normalize_phone(12345)  # type: ignore[arg-type]


def test_is_valid_phone_mirrors_normalize() -> None:
    assert is_valid_phone("09123456789")
    assert not is_valid_phone("0912")


def test_default_country_can_be_overridden() -> None:
    # A bare national number is ambiguous; the default is what resolves it.
    assert normalize_phone("9123456789", default_country="98") == "+989123456789"


def test_normalisation_is_idempotent() -> None:
    once = normalize_phone("09123456789")
    assert normalize_phone(once) == once


def test_mask_hides_the_identifying_middle() -> None:
    masked = mask_phone(CANONICAL)
    assert masked == "+98912***6789"
    # The tail is what a support operator confirms against; the middle is not
    # present at all.
    assert "3456" not in masked


def test_mask_of_short_input_does_not_leak_it() -> None:
    assert mask_phone("123") == "***"
