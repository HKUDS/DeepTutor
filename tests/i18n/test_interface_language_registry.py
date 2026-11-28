"""Every web interface locale must also exist on the backend.

The web picker (``APP_LANGUAGES`` in ``web/i18n/languages.ts``) and the
backend ``UiLanguage`` contract are maintained separately. When a locale is
added to the picker only, ``PUT /api/settings/ui`` rejects it with 422 and the
saved language snaps back to English on the next load, so the picker offers a
language the app cannot keep. These tests pin the two lists together.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import get_args

import pytest

from deeptutor.services.config.launch_settings import _normalize_language as _launch_language
from deeptutor.services.config.settings_spec import _LANGUAGE_CHOICES
from deeptutor.services.settings.interface_settings import UiLanguage, _normalize_language

LANGUAGES_TS = Path(__file__).resolve().parents[2] / "web" / "i18n" / "languages.ts"


def _web_interface_languages() -> list[str]:
    source = LANGUAGES_TS.read_text(encoding="utf-8")
    block = re.search(r"APP_LANGUAGES\s*=\s*\[(.*?)\]\s*as const", source, re.S)
    assert block, "APP_LANGUAGES not found in web/i18n/languages.ts"
    codes = re.findall(r'code:\s*"([^"]+)"', block.group(1))
    assert codes, "APP_LANGUAGES has no codes"
    return codes


WEB_LANGUAGES = _web_interface_languages()


@pytest.mark.parametrize("code", WEB_LANGUAGES)
def test_web_interface_language_is_a_backend_ui_language(code: str) -> None:
    assert code in get_args(UiLanguage)


@pytest.mark.parametrize("code", WEB_LANGUAGES)
def test_web_interface_language_survives_backend_normalization(code: str) -> None:
    assert _normalize_language(code) == code
    assert _launch_language(code) == code


@pytest.mark.parametrize("code", WEB_LANGUAGES)
def test_web_interface_language_is_offered_in_settings_spec(code: str) -> None:
    assert code in {choice_code for choice_code, _label, _description in _LANGUAGE_CHOICES}


@pytest.mark.parametrize(
    "raw", ["ko", "KO", " ko ", "ko-KR", "ko_KR", "korean", "Korean", "한국어"]
)
def test_korean_aliases_normalize_to_ko(raw: str) -> None:
    assert _normalize_language(raw) == "ko"
    assert _launch_language(raw) == "ko"
