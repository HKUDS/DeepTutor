"""Persian is wired through every seam a UI and reply language has to pass.

Mirrors the Turkish locale test, and also pins the seams earlier locales left
out (book language cues, book overview and export copy, the voice language
list), so dropping Persian from any of them fails here instead of silently
serving English.
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
    "raw", ["fa", "FA", " fa ", "fa-IR", "fa_IR", "farsi", "persian", "Farsi", "فارسی"]
)
def test_normalizer_accepts_persian_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "fa"


def test_launch_settings_accept_persian() -> None:
    assert _launch_language("fa-IR") == "fa"


@pytest.mark.parametrize("raw", ["fa", "farsi", "persian", "فارسی"])
def test_reply_language_accepts_persian(raw: str) -> None:
    assert _normalize_response_language(raw) == "fa"


def test_persian_is_a_supported_reply_language() -> None:
    assert "fa" in SUPPORTED_RESPONSE_LANGUAGES


def test_settings_offer_persian_for_interface_and_replies() -> None:
    assert ("fa", "فارسی") in {(code, label) for code, label, _ in _LANGUAGE_CHOICES}
    assert ("fa", "فارسی") in {(code, label) for code, label, _ in _RESPONSE_LANGUAGE_CHOICES}


def test_language_directive_names_persian() -> None:
    assert language_label("fa") == "فارسی"
    assert "فارسی" in language_directive("fa")


def test_cli_banner_is_fully_translated() -> None:
    assert set(LABELS["fa"]) == set(LABELS["en"])
    assert labels_for("fa") is LABELS["fa"]
    assert _pick_language("fa-IR") == "fa"
    assert _pick_language("fa_IR") == "fa"


def test_cli_banner_keeps_format_placeholders() -> None:
    pattern = re.compile(r"\{[^{}]*\}")
    mismatches = [
        key
        for key, text in LABELS["en"].items()
        if Counter(pattern.findall(text)) != Counter(pattern.findall(LABELS["fa"][key]))
    ]
    assert mismatches == []


def test_judge_speaks_persian() -> None:
    assert SUPPORTED_JUDGE_LANGUAGES == frozenset(_JUDGE_SYSTEM_PROMPTS)
    assert "fa" in SUPPORTED_JUDGE_LANGUAGES
    assert "فارسی" in _JUDGE_SYSTEM_PROMPTS["fa"]


@pytest.mark.parametrize(
    "intent",
    ["یک کتاب دربارهٔ نورشناسی به فارسی بنویس", "Write a book on optics in Persian"],
)
def test_book_honours_an_explicit_persian_request(intent: str) -> None:
    assert _explicit_language(intent) == "fa"


def test_book_ignores_a_mere_mention_of_persian() -> None:
    assert _explicit_language("A book about Persian history") is None


def test_book_overview_and_export_copy_are_translated() -> None:
    assert REQUIRED_KEYS <= set(OVERVIEW_COPY["fa"])
    assert set(EXPORT_LABELS["fa"]) == set(EXPORT_LABELS["en"])


def test_voice_offers_persian() -> None:
    assert "fa" in {row["id"] for row in ISO_LANGUAGES}


def test_web_locale_covers_every_english_key() -> None:
    assert set(_catalog("en")) <= set(_catalog("fa"))


def test_web_locale_keeps_interpolation_placeholders() -> None:
    en, fa = _catalog("en"), _catalog("fa")
    pattern = re.compile(r"\{\{[^}]+\}\}")
    mismatches = [
        key for key in en if Counter(pattern.findall(en[key])) != Counter(pattern.findall(fa[key]))
    ]
    assert mismatches == []


def test_every_locale_can_name_persian() -> None:
    for path in (WEB / "locales").glob("*/app.json"):
        assert _catalog(path.parent.name)["language.persian"] == "فارسی"


def test_frontend_registers_persian() -> None:
    languages = (WEB / "i18n/languages.ts").read_text(encoding="utf-8")
    assert '{ code: "fa", labelKey: "language.persian" }' in languages
    init = (WEB / "i18n/init.ts").read_text(encoding="utf-8")
    assert "@/locales/fa/app.json" in init
    assert 'fallbackLng: "en"' in init
    datetime = (WEB / "lib/datetime.ts").read_text(encoding="utf-8")
    assert '"fa-IR"' in datetime


@pytest.mark.parametrize("raw", ["fa", "fa-IR", "fa_IR", "farsi", "persian", "Farsi", "فارسی"])
def test_backend_messages_select_persian(raw: str) -> None:
    from deeptutor.services.i18n import _parse_language, t

    assert _parse_language(raw) == "fa"
    assert (
        t("api.partner_already_exists", language=raw, name="Ada")
        == "هم‌مطالعه‌ای با نام 'Ada' از قبل وجود دارد"
    )


def test_backend_persian_messages_cover_english_and_preserve_format_fields() -> None:
    from deeptutor.services.i18n import _MESSAGES

    assert set(_MESSAGES["fa"]) == set(_MESSAGES["en"])
    pattern = re.compile(r"\{[^{}]*\}")
    for key, text in _MESSAGES["en"].items():
        assert Counter(pattern.findall(text)) == Counter(pattern.findall(_MESSAGES["fa"][key])), key
