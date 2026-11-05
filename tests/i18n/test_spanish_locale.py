"""Spanish interface locale integration tests."""

from __future__ import annotations

from collections import Counter
import json
import pathlib
import re

import pytest

from deeptutor.services.config.launch_settings import _normalize_language as _launch_language
from deeptutor.services.config.settings_spec import _LANGUAGE_CHOICES
from deeptutor.services.settings.interface_settings import _normalize_language

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


def _catalog(locale: str) -> dict[str, str]:
    return json.loads((WEB / f"locales/{locale}/app.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "raw",
    ["es", "ES", " es ", "es-ES", "es_ES", "spanish", "español", "espanol"],
)
def test_normalizer_accepts_spanish_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "es"
    assert _launch_language(raw) == "es"


def test_settings_offers_spanish() -> None:
    assert ("es", "Español") in {(code, label) for code, label, _ in _LANGUAGE_CHOICES}


def test_web_locale_covers_every_english_key() -> None:
    en, es = _catalog("en"), _catalog("es")
    assert set(en) <= set(es)
    assert all(key.endswith("_many") for key in set(es) - set(en))


def test_web_locale_keeps_interpolation_placeholders() -> None:
    en, es = _catalog("en"), _catalog("es")
    pattern = re.compile(r"\{\{[^}]+\}\}")
    mismatches = [
        key for key in en if Counter(pattern.findall(en[key])) != Counter(pattern.findall(es[key]))
    ]
    assert mismatches == []


def test_every_locale_can_name_spanish() -> None:
    for path in (WEB / "locales").glob("*/app.json"):
        assert _catalog(path.parent.name)["language.spanish"]


def test_frontend_registers_spanish() -> None:
    languages = (WEB / "i18n/languages.ts").read_text(encoding="utf-8")
    assert '{ code: "es", labelKey: "language.spanish" }' in languages
    assert 'code === "spanish"' in languages

    init = (WEB / "i18n/init.ts").read_text(encoding="utf-8")
    assert '@/locales/es/app.json' in init
