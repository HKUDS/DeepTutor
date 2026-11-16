"""Italian is wired through every seam a UI and reply language has to pass.

Mirrors the German, Ukrainian, and Turkish locale tests, ensuring Italian
is fully integrated across the system.
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
    "raw", ["it", "IT", " it ", "it-IT", "it_IT", "italian", "italiano", "Italiano", "ITALIANO"]
)
def test_normalizer_accepts_italian_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "it"


def test_launch_settings_accept_italian() -> None:
    assert _launch_language("it-IT") == "it"


@pytest.mark.parametrize("raw", ["it", "italian", "italiano"])
def test_reply_language_accepts_italian(raw: str) -> None:
    assert _normalize_response_language(raw) == "it"


def test_italian_is_a_supported_reply_language() -> None:
    assert "it" in SUPPORTED_RESPONSE_LANGUAGES


def test_settings_offer_italian_for_interface_and_replies() -> None:
    assert ("it", "Italiano") in {(code, label) for code, label, _ in _LANGUAGE_CHOICES}
    assert ("it", "Italiano") in {(code, label) for code, label, _ in _RESPONSE_LANGUAGE_CHOICES}


def test_language_directive_names_italian() -> None:
    assert language_label("it") == "Italiano"
    assert "Italiano" in language_directive("it")


def test_judge_speaks_italian() -> None:
    assert SUPPORTED_JUDGE_LANGUAGES == frozenset(_JUDGE_SYSTEM_PROMPTS)
    assert "it" in SUPPORTED_JUDGE_LANGUAGES
    assert "italiano" in _JUDGE_SYSTEM_PROMPTS["it"].lower()


@pytest.mark.parametrize(
    "intent",
    ["Scrivi un libro sull'ottica in italiano", "Write a book on optics in Italian"],
)
def test_book_honours_an_explicit_italian_request(intent: str) -> None:
    assert _explicit_language(intent) == "it"


def test_book_ignores_a_mere_mention_of_italian() -> None:
    assert _explicit_language("A book about Italian history") is None


def test_book_overview_and_export_copy_are_translated() -> None:
    assert REQUIRED_KEYS <= set(OVERVIEW_COPY["it"])
    assert set(EXPORT_LABELS["it"]) == set(EXPORT_LABELS["en"])


def test_voice_offers_italian() -> None:
    assert "it" in {row["id"] for row in ISO_LANGUAGES}


def test_web_locale_covers_every_english_key() -> None:
    assert set(_catalog("en")) <= set(_catalog("it"))


def test_web_locale_keeps_interpolation_placeholders() -> None:
    en, it = _catalog("en"), _catalog("it")
    pattern = re.compile(r"\{\{[^}]+\}\}")
    mismatches = [
        key for key in en if Counter(pattern.findall(en[key])) != Counter(pattern.findall(it[key]))
    ]
    assert mismatches == []


def test_every_locale_can_name_italian() -> None:
    for path in (WEB / "locales").glob("*/app.json"):
        assert _catalog(path.parent.name)["language.italian"] == "Italiano"


def test_frontend_registers_italian() -> None:
    languages = (WEB / "i18n/languages.ts").read_text(encoding="utf-8")
    assert '{ code: "it", labelKey: "language.italian" }' in languages
    init = (WEB / "i18n/init.ts").read_text(encoding="utf-8")
    assert "@/locales/it/app.json" in init
    assert 'fallbackLng: "en"' in init
    datetime = (WEB / "lib/datetime.ts").read_text(encoding="utf-8")
    assert '"it-IT"' in datetime
