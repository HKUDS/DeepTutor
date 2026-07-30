"""Shared normalization for per-user resource quotas.

The persisted shape is deliberately resource-oriented instead of treating every
provider as an LLM.  ``token_quota`` remains a compatibility alias for the
``quota.llm`` block so existing grants and API clients keep working.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

MAX_QUOTA_UNITS = 10_000_000_000

DEFAULT_QUOTA: dict[str, dict[str, int]] = {
    "llm": {
        "daily_tokens": 100_000,
        "monthly_tokens": 1_000_000,
    },
    "embedding": {
        "daily_tokens": 1_000_000,
        "monthly_tokens": 10_000_000,
    },
    "mineru": {
        "daily_pages": 50,
        "monthly_pages": 500,
        "max_pages_per_file": 50,
    },
}

# Backward-compatible names used by the existing LLM quota path.
MAX_QUOTA_TOKENS = MAX_QUOTA_UNITS
DEFAULT_TOKEN_QUOTA: dict[str, int] = dict(DEFAULT_QUOTA["llm"])


def normalize_quota_limit(value: Any, fallback: int) -> int:
    """Return a quota limit in the inclusive ``0..MAX_QUOTA_UNITS`` range.

    Zero deliberately means unlimited. Invalid values use the supplied fallback
    rather than silently turning malformed configuration into unlimited access.
    """
    try:
        if isinstance(value, bool):
            raise ValueError("boolean is not a quota limit")
        number = int(str(value).strip())
    except (TypeError, ValueError):
        number = fallback
    return max(0, min(number, MAX_QUOTA_UNITS))


def _normalised_fallback(resource: str, fallback: Mapping[str, Any] | None) -> dict[str, int]:
    defaults = DEFAULT_QUOTA[resource]
    source = fallback if isinstance(fallback, Mapping) else defaults
    return {
        key: normalize_quota_limit(source.get(key, default), default)
        for key, default in defaults.items()
    }


def normalize_resource_quota(
    resource: str,
    value: Any,
    *,
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    """Normalize one resource quota while dropping unknown fields."""
    if resource not in DEFAULT_QUOTA:
        raise ValueError(f"Unknown quota resource: {resource}")
    raw = value if isinstance(value, Mapping) else {}
    fallback_values = _normalised_fallback(resource, fallback)
    return {
        key: normalize_quota_limit(raw.get(key, fallback_values[key]), fallback_values[key])
        for key in DEFAULT_QUOTA[resource]
    }


def normalize_quotas(
    value: Any,
    *,
    fallback: Mapping[str, Any] | None = None,
    legacy_token_quota: Any = None,
) -> dict[str, dict[str, int]]:
    """Normalize all resource quotas and migrate the old LLM-only shape.

    ``legacy_token_quota`` is used only when the new ``llm`` block is absent,
    which makes the migration deterministic and lets an explicit new block win.
    """
    raw = value if isinstance(value, Mapping) else {}
    fallback_map = fallback if isinstance(fallback, Mapping) else DEFAULT_QUOTA
    llm_value = raw.get("llm")
    if not isinstance(llm_value, Mapping) and isinstance(legacy_token_quota, Mapping):
        llm_value = legacy_token_quota

    result: dict[str, dict[str, int]] = {}
    for resource in DEFAULT_QUOTA:
        resource_fallback = fallback_map.get(resource)
        source = llm_value if resource == "llm" else raw.get(resource)
        result[resource] = normalize_resource_quota(
            resource,
            source,
            fallback=resource_fallback if isinstance(resource_fallback, Mapping) else None,
        )
    return result


def default_quotas() -> dict[str, dict[str, int]]:
    """Return a detached copy suitable for a mutable settings payload."""
    return deepcopy(DEFAULT_QUOTA)


def normalize_token_quota(
    value: Any,
    *,
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    """Normalize the legacy LLM-only quota shape."""
    fallback_values = fallback if isinstance(fallback, Mapping) else DEFAULT_TOKEN_QUOTA
    return normalize_resource_quota("llm", value, fallback=fallback_values)


__all__ = [
    "DEFAULT_QUOTA",
    "DEFAULT_TOKEN_QUOTA",
    "MAX_QUOTA_TOKENS",
    "MAX_QUOTA_UNITS",
    "default_quotas",
    "normalize_quota_limit",
    "normalize_quotas",
    "normalize_resource_quota",
    "normalize_token_quota",
]
