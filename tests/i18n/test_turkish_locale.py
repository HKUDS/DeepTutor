"""Turkish is wired through every seam a UI and reply language has to pass.

Mirrors the German and Ukrainian locale tests, and also pins the seams earlier
locales left out (book language cues, book overview and export copy, the voice
language list), so dropping Turkish from any of them fails here instead of
silently serving English.
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
from deeptutor.runtime.banner import LABELS, _pick_language, labels_for
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
    "raw", ["tr", "TR", " tr ", "tr-TR", "tr_TR", "turkish", "türkçe", "Türkçe", "TÜRKÇE"]
)
def test_normalizer_accepts_turkish_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "tr"


def test_launch_settings_accept_turkish() -> None:
    assert _launch_language("tr-TR") == "tr"


@pytest.mark.parametrize("raw", ["tr", "turkish", "türkçe"])
def test_reply_language_accepts_turkish(raw: str) -> None:
    assert _normalize_response_language(raw) == "tr"


def test_turkish_is_a_supported_reply_language() -> None:
    assert "tr" in SUPPORTED_RESPONSE_LANGUAGES


def test_settings_offer_turkish_for_interface_and_replies() -> None:
    assert ("tr", "Türkçe") in {(code, label) for code, label, _ in _LANGUAGE_CHOICES}
    assert ("tr", "Türkçe") in {(code, label) for code, label, _ in _RESPONSE_LANGUAGE_CHOICES}


def test_language_directive_names_turkish() -> None:
    assert language_label("tr") == "Türkçe"
    assert "Türkçe" in language_directive("tr")


def test_cli_banner_is_fully_translated() -> None:
    assert set(LABELS["tr"]) == set(LABELS["en"])
    assert labels_for("tr") is LABELS["tr"]
    assert _pick_language("tr-TR") == "tr"
    assert _pick_language("tr_TR") == "tr"


def test_cli_banner_keeps_format_placeholders() -> None:
    pattern = re.compile(r"\{[^{}]*\}")
    mismatches = [
        key
        for key, text in LABELS["en"].items()
        if Counter(pattern.findall(text)) != Counter(pattern.findall(LABELS["tr"][key]))
    ]
    assert mismatches == []


def test_judge_speaks_turkish() -> None:
    assert SUPPORTED_JUDGE_LANGUAGES == frozenset(_JUDGE_SYSTEM_PROMPTS)
    assert "tr" in SUPPORTED_JUDGE_LANGUAGES
    assert "Türkçe" in _JUDGE_SYSTEM_PROMPTS["tr"]


@pytest.mark.parametrize(
    "intent",
    ["Bu konuyu Türkçe olarak anlatan bir kitap yaz", "Write a book on optics in Turkish"],
)
def test_book_honours_an_explicit_turkish_request(intent: str) -> None:
    assert _explicit_language(intent) == "tr"


def test_book_ignores_a_mere_mention_of_turkish() -> None:
    assert _explicit_language("A book about Turkish history") is None


def test_book_overview_and_export_copy_are_translated() -> None:
    assert REQUIRED_KEYS <= set(OVERVIEW_COPY["tr"])
    assert set(EXPORT_LABELS["tr"]) == set(EXPORT_LABELS["en"])


def test_voice_offers_turkish() -> None:
    assert "tr" in {row["id"] for row in ISO_LANGUAGES}


def test_web_locale_covers_every_english_key() -> None:
    assert set(_catalog("en")) <= set(_catalog("tr"))


def test_web_locale_keeps_interpolation_placeholders() -> None:
    en, tr = _catalog("en"), _catalog("tr")
    pattern = re.compile(r"\{\{[^}]+\}\}")
    mismatches = [
        key for key in en if Counter(pattern.findall(en[key])) != Counter(pattern.findall(tr[key]))
    ]
    assert mismatches == []


def test_every_locale_can_name_turkish() -> None:
    for path in (WEB / "locales").glob("*/app.json"):
        assert _catalog(path.parent.name)["language.turkish"] == "Türkçe"


def test_frontend_registers_turkish() -> None:
    languages = (WEB / "i18n/languages.ts").read_text(encoding="utf-8")
    assert '{ code: "tr", labelKey: "language.turkish" }' in languages
    init = (WEB / "i18n/init.ts").read_text(encoding="utf-8")
    assert "@/locales/tr/app.json" in init
    assert 'fallbackLng: "en"' in init
    datetime = (WEB / "lib/datetime.ts").read_text(encoding="utf-8")
    assert '"tr-TR"' in datetime


@pytest.mark.parametrize("raw", ["tr", "tr-TR", "tr_TR", "turkish", "Türkçe"])
def test_backend_messages_select_turkish(raw: str) -> None:
    from deeptutor.services.i18n import _parse_language, t

    assert _parse_language(raw) == "tr"
    assert (
        t("api.partner_already_exists", language=raw, name="Ada") == "'Ada' adlı partner zaten var"
    )


def test_backend_turkish_messages_cover_english_and_preserve_format_fields() -> None:
    from deeptutor.services.i18n import _MESSAGES

    assert set(_MESSAGES["tr"]) == set(_MESSAGES["en"])
    pattern = re.compile(r"\{[^{}]*\}")
    for key, text in _MESSAGES["en"].items():
        assert Counter(pattern.findall(text)) == Counter(pattern.findall(_MESSAGES["tr"][key])), key
