"""Input formats supported by the current MinerU CLI and hosted API."""

from __future__ import annotations

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


__all__ = [
    "MINERU_IMAGE_FORMATS",
    "MINERU_OFFICE_FORMATS",
    "MINERU_PDF_FORMATS",
    "MINERU_SUPPORTED_FORMATS",
]
