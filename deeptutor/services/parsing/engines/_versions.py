"""Cheap, cached package-version lookup for parser signatures.

Using the installed distribution version (not a CLI ``--version`` subprocess)
keeps signature computation cheap while still invalidating the parse cache when
an engine is upgraded.
"""

from __future__ import annotations

from functools import lru_cache
import importlib.metadata


@lru_cache(maxsize=None)
def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except Exception:
        return ""


__all__ = ["package_version"]
