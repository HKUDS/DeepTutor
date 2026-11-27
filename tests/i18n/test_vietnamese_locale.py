"""Vietnamese UI locale integration tests."""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from deeptutor.core.response_languages import (
    validate_reply_language_override,
)
from deeptutor.services.config.launch_settings import (
    _normalize_language as _launch_language,
)
from deeptutor.services.prompt.language import language_directive, language_label
from deeptutor.services.settings.interface_settings import (
    _normalize_language,
    _normalize_response_language,
    resolve_languages,
)

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"

_PLURAL_SUFFIXES = ("_zero", "_one", "_two", "_few", "_many", "_other")


def _catalog(locale: str) -> dict[str, str]:
    return json.loads((WEB / f"locales/{locale}/app.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "raw",
    ["vi", "VI", " vi ", "vietnamese", "Vietnamese", "tiếng việt", "tieng viet", "vi-VN", "vi_VN"],
)
def test_ui_normalizer_accepts_vietnamese_spellings(raw: str) -> None:
    assert _normalize_language(raw) == "vi"


@pytest.mark.parametrize("raw", ["vi", "vi-VN", "Vietnamese", "tiếng việt", "tieng viet"])
def test_response_normalizer_accepts_vietnamese_spellings(raw: str) -> None:
    assert _normalize_response_language(raw) == "vi"


def test_launch_settings_accept_vietnamese() -> None:
    assert _launch_language("vi-VN") == "vi"
    assert _launch_language("vietnamese") == "vi"
    assert _launch_language("tiếng việt") == "vi"


def test_vietnamese_is_a_valid_reply_language() -> None:
    assert validate_reply_language_override("vi") == "vi"
    with pytest.raises(ValueError):
        validate_reply_language_override("vi-VN")


def test_language_directive_names_vietnamese_and_stays_in_it() -> None:
    assert language_label("vi") == "Tiếng Việt"
    assert language_label("vi-VN") == "Tiếng Việt"
    assert "Tiếng Việt" in language_directive("vi")
    assert "Tiếng Việt" in language_directive("vi", allow_user_override=True)


def test_ui_language_is_kept_separate_from_an_explicit_response_language() -> None:
    assert resolve_languages({"language": "vi", "response_language": "en"}) == {
        "language": "vi",
        "response_language": "en",
    }
    assert resolve_languages({"language": "en", "response_language": "vi"}) == {
        "language": "en",
        "response_language": "vi",
    }
    # A file written before the UI/response split inherits its one language.
    assert resolve_languages({"language": "vi"}) == {
        "language": "vi",
        "response_language": "vi",
    }


def test_web_locale_covers_every_english_key() -> None:
    """Vietnamese has one plural category, so ``_one`` variants may be absent.

    Every other English key must be translated, and every plural group must
    keep its ``_other`` form.
    """
    en = _catalog("en")
    vi = _catalog("vi")

    missing = set(en) - set(vi)
    assert all(key.endswith("_one") for key in missing)
    assert all(f"{key[: -len('_one')]}_other" in vi for key in missing)

    extras = set(vi) - set(en)
    assert all(key.endswith(_PLURAL_SUFFIXES) for key in extras)


def test_web_locale_keeps_interpolation_placeholders() -> None:
    en = _catalog("en")
    vi = _catalog("vi")

    pattern = re.compile(r"\{\{[^}]+\}\}")

    mismatches = [
        key
        for key in set(en) & set(vi)
        if set(pattern.findall(en[key])) != set(pattern.findall(vi[key]))
    ]

    assert mismatches == []
