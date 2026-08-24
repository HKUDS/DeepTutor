"""The Overview page is built without an LLM, so its copy is ours to get right.

Every other block's wording comes from the model in the book's language. This
one page is rendered deterministically, so its strings used to be
`"中文" if language == "zh" else "English"` conditionals in engine.py — which is
why the language picker could offer eleven languages while the book's own front
page spoke two.

These tests pin the table's shape and keep the remaining gap countable rather
than implicit.
"""

from __future__ import annotations

import pytest

from deeptutor.book.overview_copy import (
    _COPY,
    REQUIRED_KEYS,
    missing_languages,
    overview_copy,
)

# What the creator's picker offers (BookCreator.BOOK_LANGUAGES).
PICKER_LANGUAGES = [
    "en",
    "zh",
    "zh-tw",
    "ja",
    "ko",
    "es",
    "fr",
    "de",
    "ru",
    "pt",
    "it",
]


@pytest.mark.parametrize("language", sorted(_COPY))
def test_every_entry_defines_every_key(language: str) -> None:
    """A partial translation would render a stray English string mid-page."""
    missing = REQUIRED_KEYS - set(_COPY[language])
    assert not missing, f"{language} is missing {missing}"


@pytest.mark.parametrize("language", sorted(_COPY))
def test_the_intro_body_interpolates(language: str) -> None:
    body = _COPY[language]["intro_body"].format(concepts=7, chapters=3)
    assert "7" in body and "3" in body
    assert "{" not in body


@pytest.mark.parametrize("language", sorted(_COPY))
def test_objectives_are_a_non_empty_list_of_strings(language: str) -> None:
    objectives = _COPY[language]["objectives"]
    assert isinstance(objectives, list) and objectives
    assert all(isinstance(o, str) and o.strip() for o in objectives)


def test_a_regional_tag_resolves_to_its_base_language() -> None:
    assert overview_copy("zh-tw") is _COPY["zh"]
    assert overview_copy("zh-CN") is _COPY["zh"]


def test_an_unknown_language_falls_back_to_english_rather_than_breaking() -> None:
    for unknown in ("ja", "kl", "", None, "   "):
        assert overview_copy(unknown) is _COPY["en"]


def test_the_translation_gap_is_reported_honestly() -> None:
    """Not a failure — a ledger. Adding a language is one entry in _COPY."""
    gap = missing_languages(PICKER_LANGUAGES)
    covered = len(PICKER_LANGUAGES) - len(gap)
    assert covered >= 3, "en, zh and zh-tw (via fallback) must be covered"
    # If this trips, someone translated more languages — update the number,
    # and be glad.
    assert set(gap) <= {"ja", "ko", "es", "fr", "de", "ru", "pt", "it"}


def test_english_is_always_present_because_it_is_the_fallback() -> None:
    assert "en" in _COPY
    assert REQUIRED_KEYS <= set(_COPY["en"])
