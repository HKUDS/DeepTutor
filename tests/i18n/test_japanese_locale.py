"""Japanese UI locale integration tests."""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from deeptutor.services.config.launch_settings import (
    _normalize_language as _launch_language,
)
from deeptutor.services.config.settings_spec import _LANGUAGE_CHOICES
from deeptutor.services.prompt.language import language_directive, language_label
from deeptutor.services.settings.interface_settings import _normalize_language

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


def _catalog(locale: str) -> dict[str, str]:
    return json.loads((WEB / f"locales/{locale}/app.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "raw",
    [
        "ja",
        "JA",
        " ja ",
        "jp",
        "japanese",
        "Japanese",
        "ja-JP",
        "ja_JP",
    ],
)
def test_normalizer_accepts_japanese_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "ja"


def test_launch_settings_accept_japanese() -> None:
    assert _launch_language("ja-JP") == "ja"
    assert _launch_language("japanese") == "ja"


def test_settings_offers_japanese() -> None:
    assert "ja" in {code for code, _label, _desc in _LANGUAGE_CHOICES}


def test_language_directive_names_japanese() -> None:
    assert language_label("ja") == "日本語"
    assert "日本語" in language_directive("ja")


def test_web_locale_covers_every_english_key() -> None:
    en = _catalog("en")
    ja = _catalog("ja")

    # Japanese has no plural forms beyond the English ones, so the key sets match.
    assert set(en) == set(ja)


def test_web_locale_keeps_interpolation_placeholders() -> None:
    en = _catalog("en")
    ja = _catalog("ja")

    pattern = re.compile(r"\{\{[^}]+\}\}")

    mismatches = [
        key
        for key in set(en) & set(ja)
        if set(pattern.findall(en[key])) != set(pattern.findall(ja[key]))
    ]

    assert mismatches == []


def test_every_locale_can_name_japanese() -> None:
    for locale in ("en", "zh", "fr", "de", "uk", "pl", "ja"):
        assert "language.japanese" in _catalog(locale)


def test_frontend_registers_japanese() -> None:
    languages = (WEB / "i18n/languages.ts").read_text(encoding="utf-8")
    assert '{ code: "ja", labelKey: "language.japanese" }' in languages

    init = (WEB / "i18n/init.ts").read_text(encoding="utf-8")
    assert "@/locales/ja/app.json" in init
