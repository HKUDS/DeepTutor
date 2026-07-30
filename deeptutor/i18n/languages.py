"""Canonical language registry shared by backend i18n surfaces."""

from __future__ import annotations

from typing import Any

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "zh", "es")

_ALIASES = {
    "en": "en",
    "english": "en",
    "zh": "zh",
    "zh-cn": "zh",
    "cn": "zh",
    "chinese": "zh",
    "es": "es",
    "es-es": "es",
    "spanish": "es",
    "español": "es",
}


def normalize_supported_language(
    language: Any,
    default: str = DEFAULT_LANGUAGE,
) -> str:
    """Return a supported base language, falling back to *default*."""
    if isinstance(language, str):
        normalized = _ALIASES.get(language.strip().lower())
        if normalized:
            return normalized

    if language != default:
        return normalize_supported_language(default, DEFAULT_LANGUAGE)
    return DEFAULT_LANGUAGE


__all__ = [
    "DEFAULT_LANGUAGE",
    "SUPPORTED_LANGUAGES",
    "normalize_supported_language",
]
