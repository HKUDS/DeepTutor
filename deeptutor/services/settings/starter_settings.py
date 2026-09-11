"""Starter-suggestion settings.

One knob, stored per user in ``data/user/settings/starters.json``: how many
recent activities the model is shown when it proposes what to explore next.

Per user rather than deployment-wide because it tunes a reading of *this*
learner's own memory, and because it costs nothing on the server — it changes
the size of one prompt, not the resources anyone else can claim.
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

DEFAULT_STARTER_SETTINGS: dict[str, Any] = {
    "version": 1,
    "trace_count": DEFAULT_TRACE_COUNT,
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
    }


def save_starter_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Persist *settings* (clamped) and return what was written."""
    resolved = {
        "version": 1,
        "trace_count": _clamp(settings.get("trace_count", DEFAULT_TRACE_COUNT)),
    }
    atomic_write_json(_settings_file(), resolved)
    return resolved


__all__ = [
    "DEFAULT_STARTER_SETTINGS",
    "DEFAULT_TRACE_COUNT",
    "TRACE_COUNT_RANGE",
    "get_starter_settings",
    "save_starter_settings",
]
