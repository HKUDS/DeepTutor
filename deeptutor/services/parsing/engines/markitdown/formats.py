"""MarkItDown version and built-in input-format compatibility helpers."""

from __future__ import annotations

from functools import lru_cache
import importlib
import pkgutil

from .._versions import package_version, version_at_least

MIN_MARKITDOWN_VERSION = "0.1.7"

# Built-in local converters shipped by MarkItDown 0.1.7. Azure Content
# Understanding formats are intentionally excluded because DeepTutor's local
# adapter does not configure that billable cloud service.
MARKITDOWN_0_1_7_FORMATS = frozenset(
    {
        ".atom",
        ".csv",
        ".docx",
        ".epub",
        ".html",
        ".htm",
        ".ipynb",
        ".jpeg",
        ".jpg",
        ".json",
        ".jsonl",
        ".m4a",
        ".markdown",
        ".md",
        ".mp3",
        ".mp4",
        ".msg",
        ".pdf",
        ".png",
        ".pptx",
        ".rss",
        ".text",
        ".txt",
        ".wav",
        ".xls",
        ".xlsx",
        ".xml",
        ".zip",
    }
)


def _normalize_extensions(values: object) -> set[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return set()
    normalized: set[str] = set()
    for value in values:
        extension = str(value or "").strip().lower()
        if extension:
            normalized.add(extension if extension.startswith(".") else f".{extension}")
    return normalized


@lru_cache(maxsize=1)
def markitdown_supported_formats() -> frozenset[str]:
    """Return the current installed converter extensions plus the 0.1.7 floor.

    Converter modules expose extension constants. Inspecting them means a
    future compatible MarkItDown release can add a built-in type without
    waiting for a DeepTutor release.
    """
    discovered: set[str] = set()
    try:
        converters = importlib.import_module("markitdown.converters")
        paths = getattr(converters, "__path__", ())
        for module_info in pkgutil.iter_modules(paths, f"{converters.__name__}."):
            try:
                module = importlib.import_module(module_info.name)
            except Exception:
                continue
            for name in dir(module):
                if "EXTENSION" not in name.upper():
                    continue
                discovered.update(_normalize_extensions(getattr(module, name, None)))
    except Exception:
        pass
    return MARKITDOWN_0_1_7_FORMATS | frozenset(discovered)


def installed_markitdown_version() -> str:
    return package_version("markitdown")


def markitdown_version_is_current(version: str | None = None) -> bool:
    current = installed_markitdown_version() if version is None else version
    return version_at_least(current, MIN_MARKITDOWN_VERSION)


__all__ = [
    "MARKITDOWN_0_1_7_FORMATS",
    "MIN_MARKITDOWN_VERSION",
    "installed_markitdown_version",
    "markitdown_supported_formats",
    "markitdown_version_is_current",
]
