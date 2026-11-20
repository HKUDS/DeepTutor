"""Persian is wired through every seam a UI and reply language has to pass.

Mirrors ``test_hungarian_locale.py`` so a dropped seam fails here instead of
silently serving English to a Persian reader. Persian additionally carries the
app's first right-to-left locale, so the direction metadata is asserted here
too (``DECISIONS.md`` D-02).
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
from deeptutor.book.language import _explicit_language
from deeptutor.core.response_languages import SUPPORTED_RESPONSE_LANGUAGES
from deeptutor.services.config.launch_settings import (
    _normalize_language as _launch_language,
)
from deeptutor.services.config.settings_spec import (
    _LANGUAGE_CHOICES,
    _RESPONSE_LANGUAGE_CHOICES,
)
from deeptutor.services.i18n import _MESSAGES, _parse_language, t
from deeptutor.services.prompt.language import language_directive, language_label
from deeptutor.services.settings.interface_settings import (
    _normalize_language,
    _normalize_response_language,
)
from deeptutor.services.voice.options import ISO_LANGUAGES

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


def _catalog(locale: str, name: str = "app.json") -> dict[str, str]:
    return json.loads((WEB / f"locales/{locale}/{name}").read_text(encoding="utf-8"))


# ── the locale key itself ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    ["fa", "FA", " fa ", "fa-IR", "fa_IR", "persian", "Persian", "farsi", "فارسی"],
)
def test_normalizer_accepts_persian_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "fa"


def test_launch_settings_accept_persian() -> None:
    assert _launch_language("fa-IR") == "fa"
    assert _launch_language("farsi") == "fa"
    assert _launch_language("فارسی") == "fa"


@pytest.mark.parametrize("raw", ["fa", "fa-IR", "persian", "farsi"])
def test_reply_language_accepts_persian(raw: str) -> None:
    assert _normalize_response_language(raw) == "fa"


def test_persian_is_a_supported_reply_language() -> None:
    assert "fa" in SUPPORTED_RESPONSE_LANGUAGES


def test_settings_offer_persian_for_interface_and_replies() -> None:
    assert ("fa", "فارسی") in {(code, label) for code, label, _ in _LANGUAGE_CHOICES}
    assert ("fa", "فارسی") in {(code, label) for code, label, _ in _RESPONSE_LANGUAGE_CHOICES}


# ── prompt, judge, book and voice seams ──────────────────────────────────────


def test_language_directive_names_persian() -> None:
    assert language_label("fa") == "فارسی"
    assert "فارسی" in language_directive("fa")


def test_judge_speaks_persian() -> None:
    assert SUPPORTED_JUDGE_LANGUAGES == frozenset(_JUDGE_SYSTEM_PROMPTS)
    assert "fa" in SUPPORTED_JUDGE_LANGUAGES
    assert "فارسی" in _JUDGE_SYSTEM_PROMPTS["fa"]


@pytest.mark.parametrize(
    "intent",
    [
        "یک کتاب در مورد اپتیک به فارسی بنویس",
        "Write a book on optics in Persian",
        "Write a book on optics in Farsi",
    ],
)
def test_book_honours_an_explicit_persian_request(intent: str) -> None:
    assert _explicit_language(intent) == "fa"


def test_voice_offers_persian() -> None:
    assert "fa" in {row["id"] for row in ISO_LANGUAGES}


# ── backend message catalog ──────────────────────────────────────────────────


@pytest.mark.parametrize("raw", ["fa", "fa-IR", "fa_IR", "persian", "Farsi"])
def test_backend_messages_select_persian(raw: str) -> None:
    assert _parse_language(raw) == "fa"
    assert t("api.partner_already_exists", language=raw, name="آدا") == (
        "همکار «آدا» از قبل وجود دارد"
    )


def test_backend_persian_messages_cover_english_and_preserve_format_fields() -> None:
    assert set(_MESSAGES["fa"]) == set(_MESSAGES["en"])
    pattern = re.compile(r"\{[^{}]*\}")
    for key, text in _MESSAGES["en"].items():
        assert Counter(pattern.findall(text)) == Counter(pattern.findall(_MESSAGES["fa"][key])), key


# ── web catalogs ─────────────────────────────────────────────────────────────


def test_web_locale_registers_persian() -> None:
    languages = (WEB / "i18n/languages.ts").read_text(encoding="utf-8")
    assert '{ code: "fa", labelKey: "language.persian" }' in languages
    init = (WEB / "i18n/init.ts").read_text(encoding="utf-8")
    assert "@/locales/fa/app.json" in init
    assert 'fallbackLng: "en"' in init


def test_web_persian_catalog_only_uses_keys_that_exist_in_english() -> None:
    en, fa = _catalog("en"), _catalog("fa")
    # A partial bundle is legal: i18next falls back per key. What is NOT legal
    # is inventing a key English does not have — that string would render
    # nowhere and silently drift.
    assert set(fa) <= set(en)


def test_web_persian_catalog_keeps_interpolation_placeholders() -> None:
    en, fa = _catalog("en"), _catalog("fa")
    pattern = re.compile(r"\{\{[^}]+\}\}")
    mismatches = [
        key for key in fa if Counter(pattern.findall(en[key])) != Counter(pattern.findall(fa[key]))
    ]
    assert mismatches == []


def test_web_persian_common_catalog_is_key_complete() -> None:
    assert set(_catalog("en", "common.json")) == set(_catalog("fa", "common.json"))


def test_every_locale_can_name_persian() -> None:
    for path in (WEB / "locales").glob("*/app.json"):
        catalog = _catalog(path.parent.name)
        assert catalog["language.persian"] == "فارسی", path.parent.name


def test_persian_core_screens_are_actually_translated() -> None:
    """The core screens reachable in Phase 1 must not fall back to English.

    A key that survived translation as English text would render untranslated
    in the very screens Gate 1 smoke-tests, which ROADMAP 1.2 rules out.
    """
    en, fa = _catalog("en"), _catalog("fa")
    core = [
        "Sign in",
        "Sign in to your account",
        "Password",
        "Create account",
        "Create your account",
        "Login failed",
        "Registration failed",
        "Email or username",
        "Dashboard",
        "Question Bank",
        "Chat History",
        "Settings",
        "Profile",
        "Language",
        "Reply language",
        "Sign out",
        "navigation.home",
        "navigation.chat",
        "navigation.learning",
        "navigation.resources",
        "navigation.personalization",
    ]
    missing = [key for key in core if key not in fa]
    assert missing == []
    untranslated = [key for key in core if fa[key] == en[key]]
    assert untranslated == []


# ── direction metadata (D-02) ────────────────────────────────────────────────


def test_direction_is_declared_per_locale_not_guessed() -> None:
    languages = (WEB / "i18n/languages.ts").read_text(encoding="utf-8")
    assert "RTL_LANGUAGES" in languages
    assert 'new Set<AppLanguage>(["fa"])' in languages
    assert "regionalLocale" in languages
    assert 'fa: "fa-IR"' in languages


def test_document_locale_uses_the_iranian_region() -> None:
    datetime_module = (WEB / "lib/datetime.ts").read_text(encoding="utf-8")
    assert 'if (lang === "fa") return "fa-IR";' in datetime_module
