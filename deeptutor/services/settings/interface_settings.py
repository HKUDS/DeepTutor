"""
Interface (UI) settings reader.

This is the canonical backend source for user-selected UI language/theme stored in:
  data/user/settings/interface.json
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from deeptutor.services.path_service import get_path_service

DEFAULT_UI_SETTINGS: dict[str, Any] = {
    # "snow" is the pure-white neutral theme, shown as "Default" in the UI.
    "theme": "snow",
    "language": "en",
    "response_language": "en",
}


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def _settings_lock(path: Path) -> threading.Lock:
    """One lock per settings file, so a write only serialises its own file.

    Keyed by resolved path rather than a single global lock because in a
    multi-user deployment each account has its own ``interface.json``; making
    them contend would serialise unrelated users' preference writes.
    """
    key = str(path.resolve() if path.is_absolute() else path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


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


def atomic_update(
    settings_file: Path, mutate: Callable[[dict[str, Any]], Mapping[str, Any]]
) -> dict[str, Any]:
    """Read, mutate and replace a settings file as one indivisible step.

    Takes the path rather than resolving it, so every writer of a given file
    shares one lock even though they resolve the path themselves — the settings
    router and the setup capability both write ``interface.json`` and a lock
    only one of them takes is not a lock. Measured with each module writing
    directly: six router writes racing six capability writes lost every one of
    the router's.

    ``mutate`` receives the raw stored mapping — never the defaults-merged view,
    since writing that back would freeze today's defaults as the user's explicit
    choices — and returns what should be on disk. The write is a temp-file
    rename, so a crash or a full disk leaves the previous file rather than a
    truncated one; a half-written ``interface.json`` is what would drop a user
    back to English and the default theme.
    """
    with _settings_lock(settings_file):
        stored: dict[str, Any] = {}
        if settings_file.exists():
            try:
                with open(settings_file, encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    stored = loaded
            except Exception:
                # A corrupt file is replaced rather than inherited: reads already
                # fall back to defaults, so preserving the broken bytes would only
                # keep the user stuck with settings that do not apply.
                stored = {}
        payload = dict(mutate(stored))
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{settings_file.name}.", suffix=".tmp", dir=settings_file.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, settings_file)
        finally:
            temp_path.unlink(missing_ok=True)
        return payload


def update_ui_settings(patch: Mapping[str, Any]) -> dict[str, Any]:
    """Merge ``patch`` into the stored settings, leaving every other field intact.

    Merged into the *raw* stored mapping rather than into
    :func:`get_ui_settings`, whose return value is defaults-merged. Writing that
    merged view back would materialise every current default as an explicit
    stored value, so a user who once changed their theme would silently stop
    following later changes to any other default — the file would already
    contain a frozen copy of the defaults as they were that day.

    Returns the mapping now on disk.
    """
    updates = dict(patch)

    def _mutate(stored: dict[str, Any]) -> dict[str, Any]:
        stored.update(updates)
        return stored

    return atomic_update(_interface_settings_file(), _mutate)


def replace_ui_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Replace the stored settings wholesale (reset, and full-document saves)."""
    payload = dict(settings)
    return atomic_update(_interface_settings_file(), lambda _stored: payload)


def set_ui_setting(key: str, value: Any) -> dict[str, Any]:
    """Persist one field, leaving every other field intact."""
    return update_ui_settings({key: value})


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
