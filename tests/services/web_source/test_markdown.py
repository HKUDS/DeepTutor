"""Tests for web snapshot cleanup, URL normalization, and local assets."""

from __future__ import annotations

import pytest

from deeptutor.services.web_source.html_extractor import extract_article_markdown
from deeptutor.services.web_source.markdown import strip_leading_snapshot_provenance
from deeptutor.services.web_source.snapshot_assets import (
    SnapshotAsset,
    localize_snapshot_images,
)


def test_strips_only_leading_source_comments() -> None:
    markdown = (
        "\n<!-- source: https://docs.example.com/page -->\n"
        "<!-- source: https://docs.example.com/canonical -->\n# Documentation\n"
    )
    assert strip_leading_snapshot_provenance(markdown) == "# Documentation\n"

    body_comment = (
        "# Documentation\n\n<!-- source: https://docs.example.com/body -->\n\n"
        "```html\n<!-- source: https://docs.example.com/code -->\n```\n"
    )
    assert strip_leading_snapshot_provenance(body_comment) == body_comment


def test_html_extractor_resolves_relative_links_and_images() -> None:
    _, markdown = extract_article_markdown(
        "<html><body><article><a href='../next'>Next</a>"
        "<img src='../images/diagram.png' alt='Diagram'></article></body></html>",
        base_url="https://docs.example.com/guide/start/",
    )

    assert "[Next](https://docs.example.com/guide/next)" in markdown
    assert "![Diagram](https://docs.example.com/guide/images/diagram.png)" in markdown


@pytest.mark.asyncio
async def test_localizes_safe_images_and_never_leaves_failed_hotlinks() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"safe"

    async def fetcher(url: str):
        if url.endswith("ok.png"):
            return SnapshotAsset(png, "image/png", "png")
        return None

    markdown, assets = await localize_snapshot_images(
        "![Diagram](https://cdn.example.com/ok.png)\n![Tracker](https://cdn.example.com/bad.svg)",
        "0123456789abcdef",
        fetcher=fetcher,
    )

    assert "https://cdn.example.com" not in markdown
    assert "/api/reading/materials/0123456789abcdef/assets/" in markdown
    assert "Image unavailable: Tracker" in markdown
    assert list(assets.values()) == [png]
