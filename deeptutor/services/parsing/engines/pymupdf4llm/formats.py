"""PyMuPDF4LLM version floor and PyMuPDF-backed input formats."""

from __future__ import annotations

from .._versions import package_version, version_at_least

MIN_PYMUPDF4LLM_VERSION = "1.28.2"

# PyMuPDF4LLM supports the formats opened by the bundled PyMuPDF runtime.
# Office/HWP formats require the separately licensed PyMuPDF Pro product and
# therefore are not advertised by DeepTutor's open-source extra.
PYMUPDF4LLM_1_28_2_FORMATS = frozenset(
    {
        ".bmp",
        ".cbz",
        ".epub",
        ".fb2",
        ".gif",
        ".jpeg",
        ".jpg",
        ".jp2",
        ".jpx",
        ".jxr",
        ".markdown",
        ".md",
        ".mobi",
        ".oxps",
        ".pam",
        ".pbm",
        ".pdf",
        ".pgm",
        ".png",
        ".pnm",
        ".ppm",
        ".psd",
        ".svg",
        ".text",
        ".tif",
        ".tiff",
        ".txt",
        ".xps",
    }
)


def installed_pymupdf4llm_version() -> str:
    return package_version("pymupdf4llm")


def pymupdf4llm_version_is_current(version: str | None = None) -> bool:
    current = installed_pymupdf4llm_version() if version is None else version
    return version_at_least(current, MIN_PYMUPDF4LLM_VERSION)


__all__ = [
    "MIN_PYMUPDF4LLM_VERSION",
    "PYMUPDF4LLM_1_28_2_FORMATS",
    "installed_pymupdf4llm_version",
    "pymupdf4llm_version_is_current",
]
