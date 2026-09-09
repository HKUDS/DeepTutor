"""Ukrainian is a first-class UI/output language, not a half-wired one.

Language support in this codebase was historically a binary — ``zh`` was the
special case and ``en`` the silent fallback — repeated independently in the
settings normalizer, the settings spec, the CLI banner, the prompt language
directive and the quiz judge. Adding a language meant editing all of them, and
missing one produced no error: the user picked Ukrainian and got English back.

These tests pin every seam a new language has to pass through, so the next one
fails loudly in CI instead of quietly in the UI.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from deeptutor.api.routers.quiz_judge import (
    SUPPORTED_JUDGE_LANGUAGES,
    _JUDGE_SYSTEM_PROMPTS,
)
from deeptutor.runtime.banner import LABELS, labels_for
from deeptutor.services.config.settings_spec import _LANGUAGE_CHOICES
from deeptutor.services.prompt.language import language_directive, language_label
from deeptutor.services.settings.interface_settings import _normalize_language

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


@pytest.mark.parametrize("raw", ["uk", "UK", " uk ", "ukrainian", "ua"])
def test_normalizer_accepts_ukrainian_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "uk"


def test_an_unknown_language_still_falls_back() -> None:
    assert _normalize_language("klingon") == "en"


def test_settings_offers_ukrainian() -> None:
    assert "uk" in {code for code, _label, _desc in _LANGUAGE_CHOICES}


def test_cli_banner_is_fully_translated() -> None:
    """A partial label set would render a half-Ukrainian wizard."""
    assert set(LABELS["uk"]) == set(LABELS["en"])
    assert labels_for("uk") is LABELS["uk"]


def test_language_directive_names_ukrainian() -> None:
    assert language_label("uk") == "Українська"
    assert "Українська" in language_directive("uk")


def test_judge_speaks_every_language_it_advertises() -> None:
    """The whitelist is derived from the prompts, so the two cannot drift."""
    assert SUPPORTED_JUDGE_LANGUAGES == frozenset(_JUDGE_SYSTEM_PROMPTS)
    assert "uk" in SUPPORTED_JUDGE_LANGUAGES
    assert "українською" in _JUDGE_SYSTEM_PROMPTS["uk"]


def test_web_locale_covers_every_english_key() -> None:
    """A missing key renders as the raw key, not as English."""
    en = json.loads((WEB / "locales/en/app.json").read_text(encoding="utf-8"))
    uk = json.loads((WEB / "locales/uk/app.json").read_text(encoding="utf-8"))
    assert set(uk) == set(en)


def test_web_locale_keeps_interpolation_placeholders() -> None:
    import re

    en = json.loads((WEB / "locales/en/app.json").read_text(encoding="utf-8"))
    uk = json.loads((WEB / "locales/uk/app.json").read_text(encoding="utf-8"))
    pattern = re.compile(r"\{\{[^}]+\}\}")
    lost = [
        key
        for key, value in en.items()
        if isinstance(value, str)
        for ph in pattern.findall(value)
        if ph not in str(uk.get(key, ""))
    ]
    assert lost == []


def test_frontend_language_list_is_the_single_source() -> None:
    """Pickers must map over APP_LANGUAGES rather than inline a literal."""
    init = (WEB / "i18n/init.ts").read_text(encoding="utf-8")
    assert "APP_LANGUAGES" in init
    assert '{ code: "uk", labelKey: "language.ukrainian" }' in init
    overview = (WEB / "components/settings/SettingsOverview.tsx").read_text(encoding="utf-8")
    assert "APP_LANGUAGES.map" in overview
    assert '["en", "zh"]' not in overview
