"""
Interface (UI) settings reader.

This is the canonical backend source for user-selected UI language/theme stored in:
  data/user/settings/interface.json
"""

from __future__ import annotations

import json
from typing import Any

from deeptutor.services.path_service import get_path_service

DEFAULT_UI_SETTINGS: dict[str, Any] = {
    "theme": "light",
    "language": "en",
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


def get_ui_settings() -> dict[str, Any]:
    """
    Read UI settings from interface.json with defaults.

    Returns:
        dict containing at least: {"theme": "...", "language": "..."}
    """
    settings_file = _interface_settings_file()
    if settings_file.exists():
        try:
            with open(settings_file, encoding="utf-8") as f:
                saved = json.load(f) or {}
            merged = {**DEFAULT_UI_SETTINGS, **saved}
            merged["language"] = _normalize_language(
                merged.get("language"), DEFAULT_UI_SETTINGS["language"]
            )
            return merged
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
