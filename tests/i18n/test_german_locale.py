"""German is wired through every seam a UI language has to pass.

Mirrors ``test_ukrainian_locale.py``: each assertion pins one of the places
that independently decide which languages exist, so dropping German from any
of them fails here instead of silently serving English.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from deeptutor.api.routers.quiz_judge import (
    _JUDGE_SYSTEM_PROMPTS,
    SUPPORTED_JUDGE_LANGUAGES,
)
from deeptutor.runtime.banner import LABELS, labels_for
from deeptutor.services.config.launch_settings import _normalize_language as _launch_language
from deeptutor.services.config.settings_spec import _LANGUAGE_CHOICES
from deeptutor.services.prompt.language import language_directive, language_label
from deeptutor.services.settings.interface_settings import _normalize_language

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


def _catalog(locale: str) -> dict[str, str]:
    return json.loads((WEB / f"locales/{locale}/app.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("raw", ["de", "DE", " de ", "german", "deutsch", "de-DE", "de_AT"])
def test_normalizer_accepts_german_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "de"


def test_launch_settings_accept_german() -> None:
    assert _launch_language("de-CH") == "de"


def test_settings_offers_german() -> None:
    assert "de" in {code for code, _label, _desc in _LANGUAGE_CHOICES}


def test_cli_banner_is_fully_translated() -> None:
    assert set(LABELS["de"]) == set(LABELS["en"])
    assert labels_for("de") is LABELS["de"]


def test_language_directive_names_german() -> None:
    assert language_label("de") == "Deutsch"
    assert "Deutsch" in language_directive("de")


def test_judge_speaks_german() -> None:
    assert SUPPORTED_JUDGE_LANGUAGES == frozenset(_JUDGE_SYSTEM_PROMPTS)
    assert "de" in SUPPORTED_JUDGE_LANGUAGES
    assert "auf Deutsch" in _JUDGE_SYSTEM_PROMPTS["de"]


def test_web_locale_covers_every_english_key() -> None:
    assert set(_catalog("en")) == set(_catalog("de"))


def test_web_locale_keeps_interpolation_placeholders() -> None:
    en, de = _catalog("en"), _catalog("de")
    pattern = re.compile(r"\{\{[^}]+\}\}")
    mismatches = [
        key for key in en if set(pattern.findall(en[key])) != set(pattern.findall(de[key]))
    ]
    assert mismatches == []


def test_every_locale_can_name_german() -> None:
    for locale in ("en", "zh", "fr", "uk", "de"):
        assert "language.german" in _catalog(locale)


def test_frontend_registers_german() -> None:
    languages = (WEB / "i18n/languages.ts").read_text(encoding="utf-8")
    assert '{ code: "de", labelKey: "language.german" }' in languages
    init = (WEB / "i18n/init.ts").read_text(encoding="utf-8")
    assert "@/locales/de/app.json" in init
