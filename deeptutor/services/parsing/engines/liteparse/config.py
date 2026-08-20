"""liteparse engine config (read-side adapter over the v2 settings slice)."""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config.runtime_settings import (
    DOCUMENT_PARSING_ENGINE_LITEPARSE,
    LITEPARSE_IMAGE_MODES,
    load_document_parsing_settings,
)


@dataclass(frozen=True)
class LiteParseConfig:
    """User-facing knobs for the liteparse engine.

    ``output_format`` and the image output directory are deliberately absent:
    the parse contract is "one Markdown file plus an ``images/`` dir in the
    workdir" (see the engine docstring), so neither is the user's to choose.
    """

    # How images appear in the Markdown: "off" | "placeholder" | "embed".
    image_mode: str = "placeholder"
    # Render hyperlink annotations as [text](url) instead of bare anchor text.
    extract_links: bool = True
    # Write embedded images into the parse's ``images/`` dir.
    extract_images: bool = False
    # Stop after this many pages (0 = whole document).
    max_pages: int = 0


def _image_mode(value: object) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in LITEPARSE_IMAGE_MODES else "placeholder"


def _max_pages(value: object) -> int:
    # The settings slice is JSON, so anything outside these three types could
    # only ever have raised TypeError inside int() and been caught below.
    # Narrowing here says the same thing to a reader and to the type checker.
    if not isinstance(value, (str, int, float)):
        return 0
    try:
        pages = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return pages if pages > 0 else 0


def resolve_liteparse_config() -> LiteParseConfig:
    slice_ = (
        load_document_parsing_settings()
        .get("engines", {})
        .get(DOCUMENT_PARSING_ENGINE_LITEPARSE, {})
    )
    return LiteParseConfig(
        image_mode=_image_mode(slice_.get("image_mode")),
        extract_links=bool(slice_.get("extract_links", True)),
        extract_images=bool(slice_.get("extract_images", False)),
        max_pages=_max_pages(slice_.get("max_pages")),
    )


__all__ = ["LiteParseConfig", "resolve_liteparse_config"]
