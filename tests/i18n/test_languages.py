"""Tests for Spanish language support and backend catalog parity."""

import string

from deeptutor.services.i18n import _MESSAGES
from deeptutor.services.prompt.language import language_directive
from deeptutor.services.settings.interface_settings import _normalize_language


def test_spanish_aliases_resolve_to_spanish() -> None:
    for value in ("es", "ES", "es-ES", "es_ES", "Spanish", "español"):
        assert _normalize_language(value) == "es"


def test_existing_regional_ui_aliases_are_preserved() -> None:
    for value, expected in (("de_AT", "de"), ("fr-CA", "fr"), ("zh-TW", "zh")):
        assert _normalize_language(value) == expected


def test_unknown_ui_language_falls_back_to_english() -> None:
    assert _normalize_language("not-a-locale") == "en"


def test_spanish_model_directive_is_explicitly_from_spain() -> None:
    directive = language_directive("es")
    assert "español de España" in directive
    assert "strictly" in directive


def _format_fields(value: str) -> set[str]:
    return {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(value)
        if field_name is not None
    }


def test_backend_catalogs_have_matching_keys_and_placeholders() -> None:
    english = _MESSAGES["en"]
    for language, messages in _MESSAGES.items():
        assert messages.keys() == english.keys(), f"key mismatch for {language}"
        for key, source in english.items():
            assert _format_fields(messages[key]) == _format_fields(source), (
                f"placeholder mismatch for {language}:{key}"
            )
