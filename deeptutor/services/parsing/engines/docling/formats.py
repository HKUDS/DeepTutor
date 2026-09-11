"""Docling version and input-format compatibility helpers.

The fallback mirrors Docling 2.123.1, the minimum version DeepTutor installs.
The list stays static on purpose. Importing even Docling's format-model module
loads Transformers and PyTorch in current Docling releases. On macOS the
PyTorch and FAISS wheels bundle different OpenMP runtimes, and putting both in
the backend process can terminate it with ``OMP Error #15``. Format discovery
is used by lightweight API and routing paths, so it must never import the local
Docling runtime. Update this table together with the supported-version floor.
"""

from __future__ import annotations

import re

from .._versions import package_version

MIN_DOCLING_VERSION = "2.123.1"

# Source: docling.datamodel.base_models.FormatToExtensions in Docling 2.123.1.
# Extensions are normalized to lower case and include the leading dot.  This
# deliberately includes compound suffixes such as .dclg.xml and .tar.gz.
DOCLING_2_123_1_FORMATS = frozenset(
    {
        ".aac",
        ".adoc",
        ".asc",
        ".asciidoc",
        ".avi",
        ".bmp",
        ".boxnote",
        ".csv",
        ".dclg",
        ".dclg.xml",
        ".dclx",
        ".doc",
        ".docm",
        ".docx",
        ".dot",
        ".dotm",
        ".dotx",
        ".ebc",
        ".ebcdic",
        ".eml",
        ".epub",
        ".flac",
        ".htm",
        ".html",
        ".jpeg",
        ".jpg",
        ".json",
        ".latex",
        ".m4a",
        ".md",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".msg",
        ".nxml",
        ".odp",
        ".ods",
        ".odt",
        ".ogg",
        ".otp",
        ".ots",
        ".ott",
        ".pages",
        ".pdf",
        ".png",
        ".pot",
        ".potm",
        ".potx",
        ".pps",
        ".ppsm",
        ".ppsx",
        ".ppt",
        ".pptm",
        ".pptx",
        ".qmd",
        ".rmd",
        ".tar.gz",
        ".tex",
        ".text",
        ".tif",
        ".tiff",
        ".txt",
        ".vtt",
        ".wav",
        ".webm",
        ".webp",
        ".xbrl",
        ".xhtml",
        ".xls",
        ".xlsm",
        ".xlsx",
        ".xlt",
        ".xml",
    }
)


def docling_supported_formats() -> frozenset[str]:
    """Return the formats supported by DeepTutor's Docling compatibility floor.

    Do not import ``docling`` here. This helper is called by upload-policy and
    file-routing paths that must stay independent of Docling's ML runtime.
    """
    return DOCLING_2_123_1_FORMATS


def installed_docling_version() -> str:
    return package_version("docling")


def docling_version_is_current(version: str | None = None) -> bool:
    """Whether ``version`` satisfies DeepTutor's Docling compatibility floor."""

    def release(value: str) -> tuple[int, ...]:
        match = re.match(r"\d+(?:\.\d+)*", str(value or "").strip())
        return tuple(int(part) for part in match.group(0).split(".")) if match else ()

    current = release(version if version is not None else installed_docling_version())
    minimum = release(MIN_DOCLING_VERSION)
    width = max(len(current), len(minimum))
    return bool(current) and current + (0,) * (width - len(current)) >= minimum + (0,) * (
        width - len(minimum)
    )


__all__ = [
    "DOCLING_2_123_1_FORMATS",
    "MIN_DOCLING_VERSION",
    "docling_supported_formats",
    "docling_version_is_current",
    "installed_docling_version",
]
