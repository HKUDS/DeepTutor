"""Safe, local image assets for captured web Markdown."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import hashlib
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from deeptutor.tools.web_fetch import (
    ALLOWED_SCHEMES,
    DEFAULT_TIMEOUT_S,
    DEFAULT_USER_AGENT,
    MAX_REDIRECTS,
    _is_disallowed_host,
)

logger = logging.getLogger(__name__)

MAX_SNAPSHOT_IMAGES = 24
MAX_SNAPSHOT_IMAGE_BYTES = 8 * 1024 * 1024
_IMAGE = re.compile(
    r"!\[([^\]]*)\]\(\s*(https?://[^\s)]+)(?:\s+[\"'][^)]*[\"'])?\s*\)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SnapshotAsset:
    data: bytes
    mime: str
    extension: str


ImageFetcher = Callable[[str], Awaitable[SnapshotAsset | None]]


async def localize_snapshot_images(
    markdown: str,
    material_id: str,
    *,
    fetcher: ImageFetcher | None = None,
) -> tuple[str, dict[str, bytes]]:
    """Cache bounded raster images and replace hotlinks with local API URLs."""
    matches = list(_IMAGE.finditer(markdown))
    urls = list(dict.fromkeys(match.group(2) for match in matches))[:MAX_SNAPSHOT_IMAGES]
    if not urls:
        return markdown, {}

    resolved_fetcher = fetcher or fetch_snapshot_image
    semaphore = asyncio.Semaphore(4)

    async def load(url: str) -> tuple[str, SnapshotAsset | None]:
        try:
            async with semaphore:
                return url, await resolved_fetcher(url)
        except Exception:
            logger.info("Snapshot image could not be localized: %s", url, exc_info=True)
            return url, None

    fetched = dict(await asyncio.gather(*(load(url) for url in urls)))
    assets: dict[str, bytes] = {}
    replacements: dict[str, str | None] = {}
    for url, asset in fetched.items():
        if asset is None:
            replacements[url] = None
            continue
        digest = hashlib.sha256(url.encode("utf-8") + asset.data).hexdigest()[:20]
        name = f"{digest}.{asset.extension}"
        assets[name] = asset.data
        replacements[url] = f"/api/reading/materials/{material_id}/assets/{name}"

    def replace(match: re.Match[str]) -> str:
        alt, url = match.group(1), match.group(2)
        local = replacements.get(url)
        if local:
            return f"![{alt}]({local})"
        label = alt.strip() or "image"
        return f"*Image unavailable: {label}*"

    return _IMAGE.sub(replace, markdown), assets


async def fetch_snapshot_image(
    url: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    client_factory: Any = None,
    host_validator: Any = None,
) -> SnapshotAsset | None:
    """Fetch one public raster image with redirect, MIME, and size guards."""
    current_url = str(url or "").strip()
    validator = host_validator or _is_disallowed_host
    factory = client_factory or _default_client_factory
    try:
        async with factory(timeout=timeout_s) as client:
            for hop in range(MAX_REDIRECTS + 1):
                parsed = urlsplit(current_url)
                host = (parsed.hostname or "").strip()
                if parsed.scheme.lower() not in ALLOWED_SCHEMES or not host:
                    return None
                if validator(host):
                    return None
                async with client.stream(
                    "GET",
                    current_url,
                    headers={
                        "User-Agent": DEFAULT_USER_AGENT,
                        "Accept": "image/png,image/jpeg,image/gif,image/webp;q=0.9",
                    },
                    follow_redirects=False,
                ) as response:
                    location = response.headers.get("location", "")
                    if response.status_code in {301, 302, 303, 307, 308} and location:
                        if hop >= MAX_REDIRECTS:
                            return None
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status_code >= 400:
                        return None
                    data = await _bounded_image_read(response)
                    return _sniff_raster(data)
    except httpx.HTTPError:
        return None
    return None


def _default_client_factory(*, timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, max_redirects=MAX_REDIRECTS)


async def _bounded_image_read(response: httpx.Response) -> bytes:
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data) > MAX_SNAPSHOT_IMAGE_BYTES:
            return b""
    return bytes(data)


def _sniff_raster(data: bytes) -> SnapshotAsset | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return SnapshotAsset(data, "image/png", "png")
    if data.startswith(b"\xff\xd8\xff"):
        return SnapshotAsset(data, "image/jpeg", "jpg")
    if data.startswith((b"GIF87a", b"GIF89a")):
        return SnapshotAsset(data, "image/gif", "gif")
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return SnapshotAsset(data, "image/webp", "webp")
    return None


def snapshot_asset_mime(data: bytes) -> str | None:
    asset = _sniff_raster(data)
    return asset.mime if asset else None


__all__ = [
    "MAX_SNAPSHOT_IMAGE_BYTES",
    "MAX_SNAPSHOT_IMAGES",
    "SnapshotAsset",
    "fetch_snapshot_image",
    "localize_snapshot_images",
    "snapshot_asset_mime",
]
