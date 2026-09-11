"""LiteParse version floor and official multi-format input list."""

from __future__ import annotations

from .._versions import package_version, version_at_least

MIN_LITEPARSE_VERSION = "2.14.2"

# Source: run-llama/liteparse README, "Multi-Format Input Support" at 2.14.2.
# Office/iWork/OpenDocument inputs require LibreOffice; images are native.
LITEPARSE_2_14_2_FORMATS = frozenset(
    {
        ".bmp",
        ".csv",
        ".doc",
        ".docm",
        ".docx",
        ".gif",
        ".jpeg",
        ".jpg",
        ".key",
        ".numbers",
        ".odp",
        ".ods",
        ".odt",
        ".pages",
        ".pdf",
        ".png",
        ".ppt",
        ".pptm",
        ".pptx",
        ".rtf",
        ".svg",
        ".tiff",
        ".tsv",
        ".webp",
        ".xls",
        ".xlsm",
        ".xlsx",
    }
)


def installed_liteparse_version() -> str:
    return package_version("liteparse")


def liteparse_version_is_current(version: str | None = None) -> bool:
    current = installed_liteparse_version() if version is None else version
    return version_at_least(current, MIN_LITEPARSE_VERSION)


__all__ = [
    "LITEPARSE_2_14_2_FORMATS",
    "MIN_LITEPARSE_VERSION",
    "installed_liteparse_version",
    "liteparse_version_is_current",
]
