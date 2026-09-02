"""Lightweight aggregate of parser formats used by KB upload routing."""

from __future__ import annotations

from .docling.formats import docling_supported_formats
from .liteparse.formats import LITEPARSE_2_14_2_FORMATS
from .markitdown.formats import markitdown_supported_formats
from .mineru.formats import MINERU_SUPPORTED_FORMATS
from .pymupdf4llm.formats import PYMUPDF4LLM_1_28_2_FORMATS
from .tika.formats import TIKA_4_0_0_KNOWN_FORMATS


def known_parser_formats() -> frozenset[str]:
    """Known suffixes from every bundled parser adapter.

    This is an upload/discovery superset. The selected engine still makes the
    final decision inside :class:`ParseService`.
    """
    return frozenset(
        set(docling_supported_formats())
        | set(markitdown_supported_formats())
        | set(MINERU_SUPPORTED_FORMATS)
        | set(LITEPARSE_2_14_2_FORMATS)
        | set(PYMUPDF4LLM_1_28_2_FORMATS)
        | set(TIKA_4_0_0_KNOWN_FORMATS)
    )


__all__ = ["known_parser_formats"]
