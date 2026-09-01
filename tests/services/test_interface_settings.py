"""Reply language is independent of the two UI locales."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.settings.interface_settings import (
    get_response_language,
    get_ui_language,
    get_ui_settings,
    normalize_response_language,
    normalize_ui_language,
    resolve_languages,
    try_parse_response_language,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("en", "en"),
        ("english", "en"),
        ("zh", "zh"),
        ("Chinese", "zh"),
        ("ja", "ja"),
        ("JA", "ja"),
        ("pl", "pl"),
        ("zh-tw", "zh-tw"),
        ("pt-BR", "pt-br"),
        ("ar", "ar"),
    ],
)
def test_response_language_codes_are_kept(value: str, expected: str) -> None:
    assert try_parse_response_language(value) == expected
    assert normalize_response_language(value) == expected


@pytest.mark.parametrize("value", ["", None, "klingon", "en_US", "toolongcode-xx", "sk-arbitrary-key"])
def test_unusable_response_language_falls_back(value: object) -> None:
    assert try_parse_response_language(value) is None
    assert normalize_response_language(value, "ja") == "ja"
    assert normalize_response_language(value, "not-a-code") == "en"


def test_ui_language_still_collapses_to_en_or_zh() -> None:
    assert normalize_ui_language("ja") == "en"
    assert normalize_ui_language("pl", "zh") == "zh"
    assert normalize_ui_language("zh") == "zh"


def test_legacy_file_inherits_interface_language_for_replies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings_file = tmp_path / "interface.json"
    settings_file.write_text('{"theme": "snow", "language": "zh"}', encoding="utf-8")
    monkeypatch.setattr(
        "deeptutor.services.settings.interface_settings._interface_settings_file",
        lambda: settings_file,
    )

    assert resolve_languages(json.loads(settings_file.read_text(encoding="utf-8"))) == {
        "language": "zh",
        "response_language": "zh",
    }
    assert get_ui_language() == "zh"
    assert get_response_language() == "zh"


def test_stored_japanese_replies_survive_english_ui(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings_file = tmp_path / "interface.json"
    settings_file.write_text(
        '{"theme": "snow", "language": "en", "response_language": "ja"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "deeptutor.services.settings.interface_settings._interface_settings_file",
        lambda: settings_file,
    )

    settings = get_ui_settings()
    assert settings["language"] == "en"
    assert settings["response_language"] == "ja"
    assert get_response_language() == "ja"
