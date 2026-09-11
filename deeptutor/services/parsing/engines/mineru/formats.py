"""Input formats supported by the current MinerU CLI and hosted API."""

from __future__ import annotations

import re

from .._versions import version_at_least

MIN_MINERU_VERSION = "3.4.5"

# Keep this list aligned with ``mineru/cli/common.py`` in the official MinerU
# project. DeepTutor uses dotted, lower-case suffixes throughout its parser
# protocol.
MINERU_PDF_FORMATS = frozenset({".pdf"})
MINERU_IMAGE_FORMATS = frozenset(
    {
        ".bmp",
        ".gif",
        ".jp2",
        ".jpeg",
        ".jpg",
        ".png",
        ".tiff",
        ".webp",
    }
)
MINERU_OFFICE_FORMATS = frozenset({".docx", ".pptx", ".xlsx"})
MINERU_SUPPORTED_FORMATS = frozenset(
    MINERU_PDF_FORMATS | MINERU_IMAGE_FORMATS | MINERU_OFFICE_FORMATS
)


def mineru_version_is_current(version_text: str) -> bool:
    """Whether a MinerU CLI ``--version`` result meets the supported floor."""
    match = re.search(r"\d+(?:\.\d+)+", str(version_text or ""))
    return bool(match) and version_at_least(match.group(0), MIN_MINERU_VERSION)


__all__ = [
    "MIN_MINERU_VERSION",
    "MINERU_IMAGE_FORMATS",
    "MINERU_OFFICE_FORMATS",
    "MINERU_PDF_FORMATS",
    "MINERU_SUPPORTED_FORMATS",
    "mineru_version_is_current",
]
