"""Portuguese UI locale integration tests."""

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
from deeptutor.runtime.banner import LABELS, labels_for
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
        "pt",
        "PT",
        " pt ",
        "portuguese",
        "português",
        "pt-BR",
        "pt_PT",
    ],
)
def test_normalizer_accepts_portuguese_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "pt"


def test_launch_settings_accept_portuguese() -> None:
    assert _launch_language("pt-BR") == "pt"
    assert _launch_language("portuguese") == "pt"
    assert _launch_language("português") == "pt"


def test_settings_offers_portuguese() -> None:
    assert "pt" in {code for code, _label, _desc in _LANGUAGE_CHOICES}


def test_cli_banner_is_fully_translated() -> None:
    assert set(LABELS["pt"]) == set(LABELS["en"])
    assert labels_for("pt") is LABELS["pt"]


def test_language_directive_names_portuguese() -> None:
    assert language_label("pt") == "Português"
    assert "Português" in language_directive("pt")


def test_judge_speaks_portuguese() -> None:
    assert SUPPORTED_JUDGE_LANGUAGES == frozenset(_JUDGE_SYSTEM_PROMPTS)
    assert "pt" in SUPPORTED_JUDGE_LANGUAGES
    assert "em português" in _JUDGE_SYSTEM_PROMPTS["pt"]


def test_web_locale_covers_every_english_key() -> None:
    en = _catalog("en")
    pt = _catalog("pt")

    assert set(en) <= set(pt)
    assert all(key.endswith("_many") for key in set(pt) - set(en))
    for key in en:
        if key.endswith("_other"):
            assert key[:-6] + "_many" in pt


def test_web_locale_keeps_interpolation_placeholders() -> None:
    en = _catalog("en")
    pt = _catalog("pt")

    pattern = re.compile(r"\{\{[^}]+\}\}")

    mismatches = [
        key
        for key in set(en) & set(pt)
        if Counter(pattern.findall(en[key])) != Counter(pattern.findall(pt[key]))
    ]

    assert mismatches == []


def test_every_locale_can_name_portuguese() -> None:
    for locale in ("en", "zh", "fr", "de", "uk", "pl", "pt", "vi", "ja"):
        assert "language.portuguese" in _catalog(locale)


def test_frontend_registers_portuguese() -> None:
    languages = (WEB / "i18n/languages.ts").read_text(encoding="utf-8")
    assert '{ code: "pt", labelKey: "language.portuguese" }' in languages

    init = (WEB / "i18n/init.ts").read_text(encoding="utf-8")
    assert "@/locales/pt/app.json" in init


# Proper names, technical identifiers, language endonyms, and Portuguese words
# that happen to match English are reviewed exceptions, not untranslated copy.
# Store the English value too: changing a whitelisted label into new prose must
# not silently exempt that prose from translation.
def _untranslated_keys(en: dict[str, str], pt: dict[str, str]) -> list[str]:
    approved = json.loads(
        (WEB.parent / "tests/fixtures/portuguese_unchanged_ui.json").read_text(encoding="utf-8")
    )
    return [key for key, value in en.items() if pt.get(key) == value and approved.get(key) != value]


def test_web_locale_has_no_unreviewed_english_copy() -> None:
    assert _untranslated_keys(_catalog("en"), _catalog("pt")) == []


def test_english_fallback_cannot_replace_a_completed_translation() -> None:
    en = _catalog("en")
    copied = dict(_catalog("pt"), **{"Save": en["Save"]})
    assert "Save" in _untranslated_keys(en, copied)
    assert len(_untranslated_keys(en, en)) > 6000


def test_backend_catalogs_keep_every_formatted_argument() -> None:
    from string import Formatter

    from deeptutor.book.export import _LABELS
    from deeptutor.services.i18n import _MESSAGES

    formatter = Formatter()
    for catalogs in (LABELS, _LABELS, _MESSAGES):
        assert set(catalogs["pt"]) == set(catalogs["en"])
        for key, value in catalogs["en"].items():
            expected = Counter(
                (name, spec, conversion)
                for _, name, spec, conversion in formatter.parse(value)
                if name is not None
            )
            actual = Counter(
                (name, spec, conversion)
                for _, name, spec, conversion in formatter.parse(catalogs["pt"][key])
                if name is not None
            )
            assert actual == expected, key
