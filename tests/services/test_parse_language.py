"""Language codes must survive parsing.

``parse_language`` used to be a binary zh/en classifier whose final statement
was ``return "zh"``, so a Japanese book came back with Chinese quizzes — the
prose path normalized the code correctly while quiz, Deep Research and Mastery
Path all ran through this one (issue #712).
"""

from __future__ import annotations

import pytest

from deeptutor.services.config import parse_language
from deeptutor.services.prompt import get_prompt_manager


def prompt_file_chain(code: str) -> list[str]:
    """The order ``PromptManager`` tries language-specific prompt files in."""
    return get_prompt_manager()._fallback_chain(code)


@pytest.mark.parametrize("code", ["ja", "ko", "fr", "de", "es", "ru", "ar", "pt", "it"])
def test_a_requested_language_is_not_rewritten_to_chinese(code: str) -> None:
    assert parse_language(code) == code


@pytest.mark.parametrize("value", ["en", "EN", "English", "english"])
def test_english_aliases_resolve_to_en(value: str) -> None:
    assert parse_language(value) == "en"


@pytest.mark.parametrize("value", ["zh", "ZH", "cn", "Chinese", "chinese"])
def test_chinese_aliases_resolve_to_zh(value: str) -> None:
    assert parse_language(value) == "zh"


def test_regional_codes_keep_their_region() -> None:
    assert parse_language("zh-tw") == "zh-tw"
    assert parse_language("pt-BR") == "pt-br"


@pytest.mark.parametrize("value", [None, "", "   ", 0, 5, ["ja"]])
def test_an_unconfigured_language_still_defaults_to_chinese(value: object) -> None:
    """Deployments that never set a language keep the behaviour they shipped with."""
    assert parse_language(value) == "zh"


def test_prompt_files_fall_back_to_english_not_chinese() -> None:
    """Only zh/en ship prompt YAML; a language without files must not land on zh,
    or the model is handed Chinese scaffolding for a Japanese answer."""
    assert prompt_file_chain("ja") == ["ja", "en"]
    assert prompt_file_chain("ko") == ["ko", "en"]


def test_prompt_files_reuse_the_base_locale_for_a_regional_code() -> None:
    assert prompt_file_chain("zh-tw") == ["zh-tw", "zh", "cn", "en"]


def test_prompt_file_fallbacks_are_unchanged_for_the_two_shipped_locales() -> None:
    assert prompt_file_chain("zh") == ["zh", "cn", "en"]
    assert prompt_file_chain("en") == ["en", "zh", "cn"]
