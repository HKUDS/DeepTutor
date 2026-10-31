"""Turkish UI locale integration tests."""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from deeptutor.core.response_languages import validate_reply_language_override
from deeptutor.services.config.launch_settings import (
    _normalize_language as _launch_language,
)
from deeptutor.services.config.settings_spec import (
    _LANGUAGE_CHOICES,
    _RESPONSE_LANGUAGE_CHOICES,
)
from deeptutor.services.prompt.language import language_directive, language_label
from deeptutor.services.settings.interface_settings import _normalize_language

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


def _catalog(locale: str, name: str = "app") -> dict[str, str]:
    return json.loads((WEB / f"locales/{locale}/{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "raw",
    ["tr", "TR", " tr ", "turkish", "türkçe", "turkce", "tr-TR", "tr_TR"],
)
def test_normalizer_accepts_turkish_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "tr"


def test_launch_settings_accept_turkish() -> None:
    assert _launch_language("tr-TR") == "tr"
    assert _launch_language("turkish") == "tr"
    assert _launch_language("türkçe") == "tr"


def test_settings_offers_turkish() -> None:
    assert "tr" in {code for code, _label, _desc in _LANGUAGE_CHOICES}
    assert "tr" in {code for code, _label, _desc in _RESPONSE_LANGUAGE_CHOICES}


def test_turkish_is_a_valid_reply_language() -> None:
    assert validate_reply_language_override("tr") == "tr"


def test_language_directive_names_turkish() -> None:
    assert language_label("tr") == "Türkçe"
    assert "Türkçe" in language_directive("tr")


def test_cli_banner_has_complete_turkish_labels() -> None:
    pytest.importorskip("rich")
    from deeptutor.runtime.banner import LABELS, labels_for

    assert set(LABELS["tr"]) == set(LABELS["en"])
    assert labels_for("tr-TR") is LABELS["tr"]
    placeholder = re.compile(r"\{[a-z_]+\}")
    for key, english in LABELS["en"].items():
        assert set(placeholder.findall(english)) == set(placeholder.findall(LABELS["tr"][key]))


def test_quiz_judge_speaks_turkish() -> None:
    from deeptutor.api.routers.quiz_judge import SUPPORTED_JUDGE_LANGUAGES

    assert "tr" in SUPPORTED_JUDGE_LANGUAGES


def test_web_locale_covers_every_english_key() -> None:
    en = _catalog("en")
    tr = _catalog("tr")

    assert set(en) <= set(tr)
    # Turkish has only "one"/"other" plural forms, so no extra suffixes are allowed.
    assert set(tr) - set(en) == set()


def test_web_locale_keeps_interpolation_placeholders() -> None:
    en = _catalog("en")
    tr = _catalog("tr")

    pattern = re.compile(r"\{\{[^}]+\}\}")

    mismatches = [
        key
        for key in set(en) & set(tr)
        if set(pattern.findall(en[key])) != set(pattern.findall(tr[key]))
    ]

    assert mismatches == []


def test_turkish_common_bundle_matches_app_bundle_keys() -> None:
    common = _catalog("tr", "common")
    assert set(common) == set(_catalog("en", "common"))
    assert set(common) <= set(_catalog("tr"))


def test_every_locale_can_name_turkish() -> None:
    for locale in ("en", "zh", "fr", "de", "uk", "pl", "tr"):
        assert "language.turkish" in _catalog(locale)


def test_frontend_registers_turkish() -> None:
    languages = (WEB / "i18n/languages.ts").read_text(encoding="utf-8")
    assert '{ code: "tr", labelKey: "language.turkish" }' in languages

    init = (WEB / "i18n/init.ts").read_text(encoding="utf-8")
    assert "@/locales/tr/app.json" in init
