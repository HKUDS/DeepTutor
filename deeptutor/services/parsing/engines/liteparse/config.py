"""liteparse engine config (read-side adapter over the v2 settings slice)."""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config.runtime_settings import (
    DOCUMENT_PARSING_ENGINE_LITEPARSE,
    load_document_parsing_settings,
)


@dataclass(frozen=True)
class LiteParseConfig:
    # Output format: "markdown" | "json" | "text"
    output_format: str = "markdown"
    # How to handle images in markdown: "placeholder" | "off" | "embed"
    image_mode: str = "placeholder"
    # Whether to render [text](url) links in markdown output
    extract_links: bool = True
    # Whether to extract embedded images (requires image_output_dir)
    extract_images: bool = False
    # Directory to write extracted images to
    image_output_dir: str = ""
    # Max pages to parse (0 = unlimited)
    max_pages: int = 0


def resolve_liteparse_config() -> LiteParseConfig:
    slice_ = (
        load_document_parsing_settings()
        .get("engines", {})
        .get(DOCUMENT_PARSING_ENGINE_LITEPARSE, {})
    )
    return LiteParseConfig(
        output_format=str(slice_.get("output_format") or "markdown"),
        image_mode=str(slice_.get("image_mode") or "placeholder"),
        extract_links=bool(slice_.get("extract_links", True)),
        extract_images=bool(slice_.get("extract_images", False)),
        image_output_dir=str(slice_.get("image_output_dir") or ""),
        max_pages=int(slice_.get("max_pages") or 0),
    )


__all__ = ["LiteParseConfig", "resolve_liteparse_config"]
