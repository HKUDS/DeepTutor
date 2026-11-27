"""Starter-suggestion settings.

Two knobs, stored per user in ``data/user/settings/starters.json``:

- ``trace_count`` — how many recent activities the model is shown when it
  proposes what to explore next.
- ``ask_hint_enabled`` — whether the chat composer offers a predicted next
  line (:mod:`deeptutor.services.chat_hints`) once a conversation is under
  way. On by default; a learner answering a quiz in chat turns it off,
  because the most likely next line there is the answer itself.

Per user rather than deployment-wide because both tune what *this* learner
sees, and because neither costs anything on the server — they change the size
of one prompt or skip one call, not the resources anyone else can claim.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

# Twenty is enough to cover a week of ordinary use without burying the model in
# a list it has to skim. The floor is where a suggestion stops being grounded
# in anything; the ceiling is where the trace list starts crowding out L3,
# which is the more useful half of the material.
DEFAULT_TRACE_COUNT = 20
TRACE_COUNT_RANGE = (3, 100)
DEFAULT_ASK_HINT_ENABLED = True

DEFAULT_STARTER_SETTINGS: dict[str, Any] = {
    "version": 1,
    "trace_count": DEFAULT_TRACE_COUNT,
    "ask_hint_enabled": DEFAULT_ASK_HINT_ENABLED,
}


def _settings_file():
    # Resolved on every call so a per-user PathService (installed after auth)
    # routes reads to the caller's own file rather than the admin scope frozen
    # at import time.
    return get_path_service().get_settings_file("starters")


def _clamp(value: Any) -> int:
    low, high = TRACE_COUNT_RANGE
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_TRACE_COUNT


def _flag(value: Any, default: bool) -> bool:
    # Only a real boolean counts: "false" or 0 in a hand-edited file is not a
    # clear enough "off" to act on, so it reads as the default instead.
    return value if isinstance(value, bool) else default


def get_starter_settings() -> dict[str, Any]:
    """Current settings, with defaults filled in. Never raises."""
    try:
        path = _settings_file()
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        logger.debug("starter settings unreadable; using defaults", exc_info=True)
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "version": 1,
        "trace_count": _clamp(raw.get("trace_count", DEFAULT_TRACE_COUNT)),
        "ask_hint_enabled": _flag(raw.get("ask_hint_enabled"), DEFAULT_ASK_HINT_ENABLED),
    }


def save_starter_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Persist *settings* (clamped) and return what was written.

    A missing ``ask_hint_enabled`` keeps the stored value rather than resetting
    it: a client or a saved settings draft from before the switch existed only
    sends ``trace_count``, and that must not quietly turn the hint back on.
    """
    resolved = {
        "version": 1,
        "trace_count": _clamp(settings.get("trace_count", DEFAULT_TRACE_COUNT)),
        "ask_hint_enabled": _flag(
            settings.get("ask_hint_enabled"),
            get_starter_settings()["ask_hint_enabled"],
        ),
    }
    atomic_write_json(_settings_file(), resolved)
    return resolved


def ask_hint_enabled() -> bool:
    """Whether the chat composer should offer a predicted next line. Never raises."""
    try:
        return bool(get_starter_settings()["ask_hint_enabled"])
    except Exception:
        logger.debug("starter settings unreadable; ask hint left on", exc_info=True)
        return DEFAULT_ASK_HINT_ENABLED


__all__ = [
    "DEFAULT_ASK_HINT_ENABLED",
    "DEFAULT_STARTER_SETTINGS",
    "DEFAULT_TRACE_COUNT",
    "TRACE_COUNT_RANGE",
    "ask_hint_enabled",
    "get_starter_settings",
    "save_starter_settings",
]
