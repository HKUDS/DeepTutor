"""Polish UI locale integration tests."""

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
        "pl",
        "PL",
        " pl ",
        "polish",
        "polski",
        "pl-PL",
        "pl_PL",
    ],
)
def test_normalizer_accepts_polish_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "pl"


def test_launch_settings_accept_polish() -> None:
    assert _launch_language("pl-PL") == "pl"
    assert _launch_language("polish") == "pl"
    assert _launch_language("polski") == "pl"


def test_settings_offers_polish() -> None:
    assert "pl" in {code for code, _label, _desc in _LANGUAGE_CHOICES}


def test_language_directive_names_polish() -> None:
    assert language_label("pl") == "Polski"
    assert "Polski" in language_directive("pl")


def test_web_locale_covers_every_english_key() -> None:
    en = _catalog("en")
    pl = _catalog("pl")

    assert set(en) <= set(pl)

    extras = set(pl) - set(en)
    assert all(key.endswith(("_few", "_many")) for key in extras)


def test_web_locale_keeps_interpolation_placeholders() -> None:
    en = _catalog("en")
    pl = _catalog("pl")

    pattern = re.compile(r"\{\{[^}]+\}\}")

    mismatches = [
        key
        for key in set(en) & set(pl)
        if set(pattern.findall(en[key])) != set(pattern.findall(pl[key]))
    ]

    assert mismatches == []


def test_every_locale_can_name_polish() -> None:
    for locale in ("en", "zh", "fr", "de", "uk", "pl"):
        assert "language.polish" in _catalog(locale)


def test_frontend_registers_polish() -> None:
    languages = (WEB / "i18n/languages.ts").read_text(encoding="utf-8")
    assert '{ code: "pl", labelKey: "language.polish" }' in languages

    init = (WEB / "i18n/init.ts").read_text(encoding="utf-8")
    assert "@/locales/pl/app.json" in init
