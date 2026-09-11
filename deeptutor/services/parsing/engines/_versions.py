"""Cheap, cached package-version lookup for parser signatures.

Using the installed distribution version (not a CLI ``--version`` subprocess)
keeps signature computation cheap while still invalidating the parse cache when
an engine is upgraded.
"""

from __future__ import annotations

from functools import lru_cache
import importlib.metadata
import re


@lru_cache(maxsize=None)
def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except Exception:
        return ""


def version_at_least(version: str | None, minimum: str) -> bool:
    """Compare numeric release components without importing packaging tooling."""

    def release(value: str | None) -> tuple[int, ...]:
        match = re.match(r"\d+(?:\.\d+)*", str(value or "").strip())
        return tuple(int(part) for part in match.group(0).split(".")) if match else ()

    current = release(version)
    required = release(minimum)
    width = max(len(current), len(required))
    return bool(current and required) and current + (0,) * (width - len(current)) >= required + (
        0,
    ) * (width - len(required))


__all__ = ["package_version", "version_at_least"]
