"""Hungarian is wired through every seam a UI and reply language has to pass.

Mirrors the Turkish locale test so a dropped seam fails here instead of
silently serving English to a Hungarian reader.
"""

from __future__ import annotations

from collections import Counter
import json
import pathlib
import re

import pytest

from deeptutor.api.routers.quiz_judge import (
    _JUDGE_SYSTEM_PROMPTS,
    SUPPORTED_JUDGE_LANGUAGES,
)
from deeptutor.book.export import _LABELS as EXPORT_LABELS
from deeptutor.book.language import _explicit_language
from deeptutor.book.overview_copy import _COPY as OVERVIEW_COPY
from deeptutor.book.overview_copy import REQUIRED_KEYS
from deeptutor.core.response_languages import SUPPORTED_RESPONSE_LANGUAGES
from deeptutor.services.config.launch_settings import (
    _normalize_language as _launch_language,
)
from deeptutor.services.config.settings_spec import (
    _LANGUAGE_CHOICES,
    _RESPONSE_LANGUAGE_CHOICES,
)
from deeptutor.services.prompt.language import language_directive, language_label
from deeptutor.services.settings.interface_settings import (
    _normalize_language,
    _normalize_response_language,
)
from deeptutor.services.voice.options import ISO_LANGUAGES

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


def _catalog(locale: str) -> dict[str, str]:
    return json.loads((WEB / f"locales/{locale}/app.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "raw", ["hu", "HU", " hu ", "hu-HU", "hu_HU", "hungarian", "Hungarian", "magyar", "Magyar"]
)
def test_normalizer_accepts_hungarian_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "hu"


def test_launch_settings_accept_hungarian() -> None:
    assert _launch_language("hu-HU") == "hu"
    assert _launch_language("magyar") == "hu"


@pytest.mark.parametrize("raw", ["hu", "hu-HU", "hungarian", "magyar"])
def test_reply_language_accepts_hungarian(raw: str) -> None:
    assert _normalize_response_language(raw) == "hu"


def test_hungarian_is_a_supported_reply_language() -> None:
    assert "hu" in SUPPORTED_RESPONSE_LANGUAGES


def test_settings_offer_hungarian_for_interface_and_replies() -> None:
    assert ("hu", "Magyar") in {(code, label) for code, label, _ in _LANGUAGE_CHOICES}
    assert ("hu", "Magyar") in {(code, label) for code, label, _ in _RESPONSE_LANGUAGE_CHOICES}


def test_language_directive_names_hungarian() -> None:
    assert language_label("hu") == "Magyar"
    assert "Magyar" in language_directive("hu")


def test_judge_speaks_hungarian() -> None:
    assert SUPPORTED_JUDGE_LANGUAGES == frozenset(_JUDGE_SYSTEM_PROMPTS)
    assert "hu" in SUPPORTED_JUDGE_LANGUAGES
    assert "Magyarul" in _JUDGE_SYSTEM_PROMPTS["hu"]


@pytest.mark.parametrize(
    "intent",
    ["Írj könyvet az optikáról magyarul", "Write a book on optics in Hungarian"],
)
def test_book_honours_an_explicit_hungarian_request(intent: str) -> None:
    assert _explicit_language(intent) == "hu"


def test_book_ignores_a_mere_mention_of_hungarian() -> None:
    assert _explicit_language("A book about Hungarian history") is None


def test_book_overview_and_export_copy_are_translated() -> None:
    assert REQUIRED_KEYS <= set(OVERVIEW_COPY["hu"])
    assert set(EXPORT_LABELS["hu"]) == set(EXPORT_LABELS["en"])


def test_voice_offers_hungarian() -> None:
    assert "hu" in {row["id"] for row in ISO_LANGUAGES}


def test_web_locale_covers_every_english_key() -> None:
    en, hu = _catalog("en"), _catalog("hu")

    # Hungarian has no plural forms beyond the English ones, so the key sets match.
    assert set(en) == set(hu)


def test_web_locale_keeps_interpolation_placeholders() -> None:
    en, hu = _catalog("en"), _catalog("hu")
    pattern = re.compile(r"\{\{[^}]+\}\}")
    mismatches = [
        key for key in en if Counter(pattern.findall(en[key])) != Counter(pattern.findall(hu[key]))
    ]
    assert mismatches == []


def test_every_locale_can_name_hungarian() -> None:
    for path in (WEB / "locales").glob("*/app.json"):
        assert _catalog(path.parent.name)["language.hungarian"] == "Magyar"


def test_frontend_registers_hungarian() -> None:
    languages = (WEB / "i18n/languages.ts").read_text(encoding="utf-8")
    assert '{ code: "hu", labelKey: "language.hungarian" }' in languages
    init = (WEB / "i18n/init.ts").read_text(encoding="utf-8")
    assert "@/locales/hu/app.json" in init
    assert 'fallbackLng: "en"' in init
    datetime = (WEB / "lib/datetime.ts").read_text(encoding="utf-8")
    assert '"hu-HU"' in datetime


@pytest.mark.parametrize("raw", ["hu", "hu-HU", "hu_HU", "hungarian", "Magyar"])
def test_backend_messages_select_hungarian(raw: str) -> None:
    from deeptutor.services.i18n import _parse_language, t

    assert _parse_language(raw) == "hu"
    assert (
        t("api.partner_already_exists", language=raw, name="Ada")
        == "'Ada' nevű partner már létezik"
    )


def test_backend_hungarian_messages_cover_english_and_preserve_format_fields() -> None:
    from deeptutor.services.i18n import _MESSAGES

    assert set(_MESSAGES["hu"]) == set(_MESSAGES["en"])
    pattern = re.compile(r"\{[^{}]*\}")
    for key, text in _MESSAGES["en"].items():
        assert Counter(pattern.findall(text)) == Counter(pattern.findall(_MESSAGES["hu"][key])), key
