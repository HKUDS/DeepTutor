"""Unified source adapters for Immersive Reading.

Adapters stop the reader store from knowing whether text came from an upload,
a web snapshot, or a knowledge-base document.  Every adapter produces the same
locator-addressed payload and provenance fields; the store owns persistence,
revisioning, and annotation migration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
import time
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

import httpx

from deeptutor.reading.extract import Extraction, extract_material, split_into_sections
from deeptutor.reading.models import (
    BilingualGroup,
    ContentFormat,
    OutlineEntry,
    RenderMode,
    SourceType,
    UnitKind,
    UnitReference,
)


@dataclass(frozen=True, slots=True)
class ReadingSourcePayload:
    source_type: SourceType
    source_ref: str
    filename: str
    title: str
    units: tuple[str, ...]
    unit: UnitKind = "section"
    outline: tuple[OutlineEntry, ...] = field(default_factory=tuple)
    unit_refs: tuple[UnitReference, ...] = field(default_factory=tuple)
    source_url: str = ""
    kb_name: str = ""
    kb_path: str = ""
    mime: str = "text/markdown"
    extractor: str = "reading-source"
    raw_bytes: bytes = b""
    has_raw_view: bool = False
    render_mode: RenderMode = "text"
    captured_at: float = field(default_factory=time.time)
    tutorial_available: bool = False
    navigation_kind: str = ""
    content_format: ContentFormat = "markdown"
    bilingual_groups: tuple[BilingualGroup, ...] = field(default_factory=tuple)
    bilingual_languages: tuple[str, ...] = field(default_factory=tuple)
    bilingual_pairing_ids: tuple[str, ...] = field(default_factory=tuple)
    snapshot_assets: tuple["SnapshotAsset", ...] = field(default_factory=tuple)

    @property
    def content_hash(self) -> str:
        digest = hashlib.sha256()
        digest.update(
            (
                f"unit={self.unit}\0mime={self.mime}\0extractor={self.extractor}\0"
                f"render_mode={self.render_mode}\0has_raw_view={int(self.has_raw_view)}\0"
                f"source_url={self.source_url}\0"
                f"tutorial_available={int(self.tutorial_available)}\0"
                f"navigation_kind={self.navigation_kind}\0"
                f"content_format={self.content_format}\0"
            ).encode("utf-8")
        )
        for unit in self.units:
            digest.update(unit.encode("utf-8"))
            digest.update(b"\0")
        for row in self.outline:
            digest.update(
                (
                    f"{row.locator}\0{row.level}\0{row.title}\0{row.source_url}\0"
                    f"{int(row.synthesised)}\0"
                ).encode("utf-8")
            )
        for row in self.unit_refs:
            digest.update(f"{row.locator}\0{row.source_href}\0{row.title}\0".encode("utf-8"))
        for row in self.bilingual_groups:
            digest.update(json_bilingual_group(row).encode("utf-8"))
        for row in self.snapshot_assets:
            digest.update(row.asset_id.encode("ascii"))
        if self.raw_bytes:
            digest.update(hashlib.sha256(self.raw_bytes).digest())
        return digest.hexdigest()[:16]


class ReadingSourceAdapter(Protocol):
    """Convert a concrete source into a store-ready reading payload."""

    def build(self) -> ReadingSourcePayload: ...


@dataclass(frozen=True, slots=True)
class SnapshotAsset:
    asset_id: str
    mime: str
    data: bytes


_IMAGE_MARKDOWN_URL = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<url><[^>]+>|[^\s)]+)(?:\s+['\"][^'\"]*['\"])?\)"
)
_IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
MAX_SNAPSHOT_IMAGE_BYTES = 8 * 1024 * 1024
MAX_SNAPSHOT_IMAGES = 12


async def localize_snapshot_images(
    payload: ReadingSourcePayload,
    *,
    client: httpx.AsyncClient | None = None,
) -> ReadingSourcePayload:
    """Cache remote Markdown images and replace them with authenticated paths."""
    from dataclasses import replace

    from deeptutor.services.web_source.crawler import _is_crawler_disallowed_host

    documents = list(payload.units) + [
        value
        for group in payload.bilingual_groups
        for value in (group.source_markdown, group.translation_markdown)
    ]
    urls: list[str] = []
    for document in documents:
        for match in _IMAGE_MARKDOWN_URL.finditer(document):
            value = match.group("url").strip("<>")
            if urlparse(value).scheme.lower() in {"http", "https"} and value not in urls:
                urls.append(value)
    if not urls:
        return payload

    owned_client = client is None
    session = client or httpx.AsyncClient(timeout=4.0)
    replacements: dict[str, str] = {}
    assets: list[SnapshotAsset] = []
    try:
        semaphore = asyncio.Semaphore(6)

        async def fetch(url: str) -> tuple[str, SnapshotAsset | None]:
            async with semaphore:
                return (
                    url,
                    await _download_snapshot_image(
                        url,
                        session,
                        host_validator=_is_crawler_disallowed_host,
                    ),
                )

        attempted = urls[:MAX_SNAPSHOT_IMAGES]
        downloaded = await asyncio.gather(*(fetch(url) for url in attempted))
        for url, asset in downloaded:
            if asset is not None:
                assets.append(asset)
                replacements[url] = f"/api/v1/reading/snapshot-assets/{asset.asset_id}"
            else:
                replacements[url] = ""
        for url in urls[MAX_SNAPSHOT_IMAGES:]:
            replacements[url] = ""
    finally:
        if owned_client:
            await session.aclose()

    def rewrite(markdown: str) -> str:
        def replace_image(match: re.Match[str]) -> str:
            url = match.group("url").strip("<>")
            replacement = replacements.get(url)
            if replacement is None:
                return match.group(0)
            if not replacement:
                alt = match.group("alt").strip() or "image"
                return f"*Image unavailable: {alt}*"
            return f"![{match.group('alt')}]({replacement})"

        return _IMAGE_MARKDOWN_URL.sub(replace_image, markdown)

    groups = tuple(
        BilingualGroup(
            group_id=group.group_id,
            locator=group.locator,
            source_markdown=rewrite(group.source_markdown),
            translation_markdown=rewrite(group.translation_markdown),
            source_language=group.source_language,
            target_language=group.target_language,
            confidence=group.confidence,
            low_confidence=group.low_confidence,
        )
        for group in payload.bilingual_groups
    )
    return replace(
        payload,
        units=tuple(rewrite(unit) for unit in payload.units),
        bilingual_groups=groups,
        snapshot_assets=tuple(assets),
    )


async def _download_snapshot_image(
    url: str,
    client: httpx.AsyncClient,
    *,
    host_validator: Any,
) -> SnapshotAsset | None:
    current = url
    for _redirect in range(6):
        parsed = urlparse(current)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if host_validator(parsed.hostname):
            return None
        try:
            async with client.stream(
                "GET",
                current,
                headers={"Accept": "image/png,image/jpeg,image/gif,image/webp"},
                follow_redirects=False,
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location", "").strip()
                    if not location:
                        return None
                    current = urljoin(str(response.url), location)
                    continue
                mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if response.status_code >= 400 or mime not in _IMAGE_MIMES:
                    return None
                declared = int(response.headers.get("content-length") or 0)
                if declared > MAX_SNAPSHOT_IMAGE_BYTES:
                    return None
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_SNAPSHOT_IMAGE_BYTES:
                        return None
        except (httpx.HTTPError, ValueError):
            return None
        raw = bytes(data)
        return SnapshotAsset(asset_id=hashlib.sha256(raw).hexdigest(), mime=mime, data=raw)
    return None


@dataclass(frozen=True, slots=True)
class FileSourceAdapter:
    path: Path
    filename: str = ""
    source_type: SourceType = "upload"
    source_ref: str = ""
    source_url: str = ""
    kb_name: str = ""
    kb_path: str = ""

    def build(self) -> ReadingSourcePayload:
        extraction: Extraction = extract_material(self.path)
        filename = self.filename or self.path.name
        raw = self.path.read_bytes()
        is_markdown = Path(filename).suffix.lower() in {".md", ".markdown"}
        if is_markdown:
            clean_markdown = sanitize_snapshot_markdown(raw.decode("utf-8"))
            extraction = Extraction(
                units=split_into_sections(clean_markdown),
                unit="section",
                title=extraction.title,
                outline=extraction.outline,
                extractor=extraction.extractor,
            )
            raw = clean_markdown.encode("utf-8")
        return ReadingSourcePayload(
            source_type=self.source_type,
            source_ref=self.source_ref or f"upload:{hashlib.sha256(raw).hexdigest()}",
            filename=filename,
            title=extraction.title or Path(filename).stem,
            units=extraction.units,
            unit=extraction.unit,
            outline=extraction.outline,
            unit_refs=extraction.unit_refs,
            source_url=self.source_url,
            kb_name=self.kb_name,
            kb_path=self.kb_path,
            extractor=extraction.extractor,
            raw_bytes=raw,
            has_raw_view=extraction.has_raw_view,
            render_mode=extraction.render_mode,
            content_format=(
                extraction.render_mode
                if extraction.render_mode in ("pdf", "epub")
                else ("markdown" if is_markdown else "plain_text")
            ),
        )


_LEADING_SOURCE_COMMENT = re.compile(
    r"\A(?:\\?<!--\s*source:\s*.*?\s*\\?-->\s*(?:\r?\n)*)",
    flags=re.IGNORECASE,
)


def sanitize_snapshot_markdown(markdown: str) -> str:
    """Remove crawler provenance only when it is the document's first token.

    Comments inside prose or fenced code are intentionally untouched. Older
    snapshots escaped the comment delimiters, hence the optional backslashes.
    """

    clean = markdown.lstrip("\ufeff")
    return _LEADING_SOURCE_COMMENT.sub("", clean, count=1).lstrip("\r\n")


_INLINE_MARKDOWN_URL = re.compile(
    r"(?P<prefix>!?\[[^\]]*\]\()(?P<url><[^>]+>|[^\s)]+)(?P<suffix>(?:\s+['\"][^'\"]*['\"])?\))"
)


def normalize_snapshot_links(markdown: str, source_url: str) -> str:
    """Resolve relative Markdown links against captured-page provenance."""
    if not source_url:
        return markdown

    def replace_url(match: re.Match[str]) -> str:
        raw = match.group("url")
        wrapped = raw.startswith("<") and raw.endswith(">")
        value = raw[1:-1] if wrapped else raw
        parsed = urlparse(value)
        if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
            return match.group(0)
        resolved = urljoin(source_url, value)
        shown = f"<{resolved}>" if wrapped else resolved
        return f"{match.group('prefix')}{shown}{match.group('suffix')}"

    return _INLINE_MARKDOWN_URL.sub(replace_url, markdown)


def json_bilingual_group(group: BilingualGroup) -> str:
    import json

    return json.dumps(group.to_dict(), ensure_ascii=False, sort_keys=True)


def markdown_payload(
    *,
    source_type: SourceType,
    source_ref: str,
    title: str,
    markdown: str,
    filename: str,
    source_url: str = "",
    kb_name: str = "",
    kb_path: str = "",
    outline: tuple[OutlineEntry, ...] = (),
) -> ReadingSourcePayload:
    """Build a Markdown payload, preserving supplied tutorial structure."""
    markdown = normalize_snapshot_links(sanitize_snapshot_markdown(markdown), source_url)
    units = split_into_sections(markdown)
    return ReadingSourcePayload(
        source_type=source_type,
        source_ref=source_ref,
        filename=filename,
        title=title,
        units=units,
        unit="section",
        outline=outline,
        source_url=source_url,
        kb_name=kb_name,
        kb_path=kb_path,
        raw_bytes=markdown.encode("utf-8"),
        has_raw_view=False,
        content_format="markdown",
    )


__all__ = [
    "FileSourceAdapter",
    "ReadingSourceAdapter",
    "ReadingSourcePayload",
    "SnapshotAsset",
    "localize_snapshot_images",
    "sanitize_snapshot_markdown",
    "normalize_snapshot_links",
    "markdown_payload",
]
