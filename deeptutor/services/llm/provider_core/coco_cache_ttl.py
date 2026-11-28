"""CoCo fork: switchable Anthropic prompt-cache lifetime.

Anthropic keeps a prompt cache for 5 minutes unless the breakpoint asks for
``"ttl": "1h"``. A child solving a problem often replies after more than five
minutes, so every turn rewrote the whole cache. The 1-hour cache costs 2x
base input to write (5-minute: 1.25x) but reads stay at 0.1x.

Setting: ``data/user/settings/coco.json`` -> ``{"anthropic_cache_ttl": "1h"}``.
The process env ``COCO_ANTHROPIC_CACHE_TTL`` overrides the file. Missing or
invalid values fall back to the upstream default (no ``ttl`` field = 5m), so
upstream behaviour is unchanged unless the setting is turned on.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SETTINGS_FILE = "coco.json"
SETTING_KEY = "anthropic_cache_ttl"
ENV_VAR = "COCO_ANTHROPIC_CACHE_TTL"
DEFAULT_TTL = "5m"
VALID_TTLS = frozenset({"5m", "1h"})

# (path, mtime) -> ttl, so the file is re-read only when it changes.
_cache: dict[tuple[str, float], str] = {}


def _settings_dir() -> Path | None:
    try:
        from deeptutor.services.config.runtime_settings import _global_settings_dir

        return _global_settings_dir()
    except Exception:  # noqa: BLE001 - settings are optional; never break a request
        logger.debug("CoCo cache TTL: settings dir unavailable", exc_info=True)
        return None


def _normalize(value: Any, source: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text not in VALID_TTLS:
        logger.warning("CoCo cache TTL: ignoring %s=%r (use 5m or 1h)", source, value)
        return None
    return text


def _ttl_from_file(settings_dir: Path) -> str | None:
    path = settings_dir / SETTINGS_FILE
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime)
    if key in _cache:
        return _cache[key]
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        logger.warning("CoCo cache TTL: cannot read %s; using default", path)
        return None
    ttl = _normalize(data.get(SETTING_KEY) if isinstance(data, dict) else None, str(path))
    _cache.clear()
    _cache[key] = ttl or DEFAULT_TTL
    return ttl


def anthropic_cache_ttl(settings_dir: Path | None = None) -> str:
    """Effective TTL: env override, then coco.json, then the 5m default."""
    env_ttl = _normalize(os.environ.get(ENV_VAR), ENV_VAR)
    if env_ttl:
        return env_ttl
    directory = settings_dir if settings_dir is not None else _settings_dir()
    file_ttl = _ttl_from_file(directory) if directory is not None else None
    return file_ttl or DEFAULT_TTL


def anthropic_cache_marker(settings_dir: Path | None = None) -> dict[str, str]:
    """``cache_control`` value for Anthropic breakpoints."""
    if anthropic_cache_ttl(settings_dir) == "1h":
        return {"type": "ephemeral", "ttl": "1h"}
    return {"type": "ephemeral"}
