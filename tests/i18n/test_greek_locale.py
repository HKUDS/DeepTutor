"""Greek is wired through every seam a UI and reply language has to pass.

Mirrors the Turkish locale test, so dropping Greek from any seam (normalizers,
settings choices, prompts, CLI banner, quiz judge, book cues and copy, voice,
web catalog, backend messages) fails here instead of silently serving English.
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
from deeptutor.book.language import _explicit_language, _script_language
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
    "raw", ["el", "EL", " el ", "el-GR", "el_GR", "el-CY", "greek", "ελληνικά", "Ελληνικά"]
)
def test_normalizer_accepts_greek_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "el"


def test_launch_settings_accept_greek() -> None:
    assert _launch_language("el-GR") == "el"


@pytest.mark.parametrize("raw", ["el", "el-GR", "greek", "ελληνικά"])
def test_reply_language_accepts_greek(raw: str) -> None:
    assert _normalize_response_language(raw) == "el"


def test_greek_is_a_supported_reply_language() -> None:
    assert "el" in SUPPORTED_RESPONSE_LANGUAGES


def test_settings_offer_greek_for_interface_and_replies() -> None:
    assert ("el", "Ελληνικά") in {(code, label) for code, label, _ in _LANGUAGE_CHOICES}
    assert ("el", "Ελληνικά") in {(code, label) for code, label, _ in _RESPONSE_LANGUAGE_CHOICES}


def test_language_directive_names_greek() -> None:
    assert language_label("el") == "Ελληνικά"
    assert "Ελληνικά" in language_directive("el")


def test_cli_banner_is_fully_translated() -> None:
    assert set(LABELS["el"]) == set(LABELS["en"])
    assert labels_for("el") is LABELS["el"]
    assert _pick_language("el-GR") == "el"
    assert _pick_language("el_GR") == "el"


def test_cli_banner_keeps_format_placeholders() -> None:
    pattern = re.compile(r"\{[^{}]*\}")
    mismatches = [
        key
        for key, text in LABELS["en"].items()
        if Counter(pattern.findall(text)) != Counter(pattern.findall(LABELS["el"][key]))
    ]
    assert mismatches == []


def test_judge_speaks_greek() -> None:
    assert SUPPORTED_JUDGE_LANGUAGES == frozenset(_JUDGE_SYSTEM_PROMPTS)
    assert "el" in SUPPORTED_JUDGE_LANGUAGES
    assert "στα ελληνικά" in _JUDGE_SYSTEM_PROMPTS["el"]


@pytest.mark.parametrize(
    "intent",
    [
        "Γράψε ένα βιβλίο για την οπτική στα ελληνικά",
        "ΓΡΑΨΕ ΤΟ ΣΤΑ ΕΛΛΗΝΙΚΑ",
        "Write a book on optics in Greek",
    ],
)
def test_book_honours_an_explicit_greek_request(intent: str) -> None:
    assert _explicit_language(intent) == "el"


def test_book_ignores_a_mere_mention_of_greek() -> None:
    assert _explicit_language("A book about Greek history") is None


def test_book_infers_greek_from_greek_script() -> None:
    assert _script_language("Φτιάξε ένα βιβλίο για τις συναρτήσεις στη JavaScript") == "el"


def test_book_keeps_stray_greek_symbols_in_english_requests() -> None:
    assert _script_language("Write a book about π and λ-calculus") is None


def test_book_overview_and_export_copy_are_translated() -> None:
    assert REQUIRED_KEYS <= set(OVERVIEW_COPY["el"])
    assert set(EXPORT_LABELS["el"]) == set(EXPORT_LABELS["en"])


def test_voice_offers_greek() -> None:
    assert "el" in {row["id"] for row in ISO_LANGUAGES}


def test_web_locale_covers_every_english_key() -> None:
    assert set(_catalog("en")) <= set(_catalog("el"))


def test_web_locale_keeps_interpolation_placeholders() -> None:
    en, el = _catalog("en"), _catalog("el")
    pattern = re.compile(r"\{\{[^}]+\}\}")
    mismatches = [
        key for key in en if Counter(pattern.findall(en[key])) != Counter(pattern.findall(el[key]))
    ]
    assert mismatches == []


def test_every_locale_can_name_greek() -> None:
    for path in (WEB / "locales").glob("*/app.json"):
        assert _catalog(path.parent.name)["language.greek"] == "Ελληνικά"


def test_frontend_registers_greek() -> None:
    languages = (WEB / "i18n/languages.ts").read_text(encoding="utf-8")
    assert '{ code: "el", labelKey: "language.greek" }' in languages
    init = (WEB / "i18n/init.ts").read_text(encoding="utf-8")
    assert "@/locales/el/app.json" in init
    assert 'fallbackLng: "en"' in init
    datetime = (WEB / "lib/datetime.ts").read_text(encoding="utf-8")
    assert '"el-GR"' in datetime


@pytest.mark.parametrize("raw", ["el", "el-GR", "el_GR", "greek", "Ελληνικά"])
def test_backend_messages_select_greek(raw: str) -> None:
    from deeptutor.services.i18n import _parse_language, t

    assert _parse_language(raw) == "el"
    assert t("api.partner_already_exists", language=raw, name="Ada") == (
        "Ο Partner 'Ada' υπάρχει ήδη"
    )


def test_backend_greek_messages_cover_english_and_preserve_format_fields() -> None:
    from deeptutor.services.i18n import _MESSAGES

    assert set(_MESSAGES["el"]) == set(_MESSAGES["en"])
    pattern = re.compile(r"\{[^{}]*\}")
    for key, text in _MESSAGES["en"].items():
        assert Counter(pattern.findall(text)) == Counter(pattern.findall(_MESSAGES["el"][key])), key
