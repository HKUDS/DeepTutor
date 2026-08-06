"""
Interface (UI) settings reader.

This is the canonical backend source for user-selected UI language/theme stored in:
  data/user/settings/interface.json
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from deeptutor.services.path_service import get_path_service

DEFAULT_UI_SETTINGS: dict[str, Any] = {
    # "snow" is the pure-white neutral theme, shown as "Default" in the UI.
    "theme": "snow",
    "language": "en",
    "response_language": "en",
}


def _interface_settings_file():
    # Resolved on every call so a per-user PathService (set after auth)
    # routes reads to the caller's own ``settings/interface.json`` instead
    # of the admin scope frozen at import time.
    return get_path_service().get_settings_file("interface")


def _normalize_language(language: Any, default: str = "en") -> str:
    """
    Normalize language codes:
    - en/english -> en
    - zh/chinese/cn -> zh
    """
    if language is None or language == "":
        language = default

    if isinstance(language, str):
        s = language.lower().strip()
        if s in {"en", "english"}:
            return "en"
        if s in {"zh", "chinese", "cn"}:
            return "zh"

    # Fall back to default
    if isinstance(default, str):
        return _normalize_language(default, "en")
    return "en"


def resolve_languages(saved: Mapping[str, Any]) -> dict[str, str]:
    """Normalize the two language fields out of a raw ``interface.json`` dict.

    ``response_language`` was split out of ``language`` after the two had been
    a single setting, so a file written before the split carries only
    ``language`` and must inherit it. That inheritance *is* the migration, and
    it lives here because this module owns the file's shape — both readers of
    ``interface.json`` (this module and the settings router, which layers its
    own superset of defaults on top) go through this one function so they can
    never disagree about what a legacy file means.

    ``_normalize_language`` already falls back to its ``default`` for a value
    that is missing, blank or unrecognized, so absence, ``null`` and junk all
    land on the interface language without a separate key-presence check.
    """
    language = _normalize_language(saved.get("language"), DEFAULT_UI_SETTINGS["language"])
    return {
        "language": language,
        "response_language": _normalize_language(saved.get("response_language"), language),
    }


def get_ui_settings() -> dict[str, Any]:
    """
    Read UI settings from interface.json with defaults.

    Returns:
        dict containing at least: {"theme": "...", "language": "...",
        "response_language": "..."}
    """
    settings_file = _interface_settings_file()
    if settings_file.exists():
        try:
            with open(settings_file, encoding="utf-8") as f:
                saved = json.load(f) or {}
            return {**DEFAULT_UI_SETTINGS, **saved, **resolve_languages(saved)}
        except Exception:
            # On any parse error, fall back to defaults (safe)
            return DEFAULT_UI_SETTINGS.copy()

    return DEFAULT_UI_SETTINGS.copy()


def get_ui_language(default: str = "en") -> str:
    """
    Get current UI language.

    Priority:
    1) interface.json
    2) provided default
    3) 'en'
    """
    settings = get_ui_settings()
    return _normalize_language(settings.get("language"), default)


def get_response_language(default: str = "en") -> str:
    """Get the preferred reader-facing model output language."""
    settings = get_ui_settings()
    return _normalize_language(settings.get("response_language"), default)
