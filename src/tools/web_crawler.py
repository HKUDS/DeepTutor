#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Web Crawler Tool - Fetch and extract main content from URLs.

Uses httpx + readability + markdownify for robust content extraction.
Falls back to basic HTML parsing if readability is unavailable.
"""

import asyncio
import hashlib
import re
from typing import Optional
from urllib.parse import urlparse

import httpx

from src.logging import get_logger

logger = get_logger("WebCrawler")

# Max content length per page (chars) to avoid blowing up the KB
MAX_CONTENT_LENGTH = 50_000
REQUEST_TIMEOUT = 30.0

# Common non-content URL patterns to skip
_SKIP_EXTENSIONS = {
    ".pdf", ".zip", ".tar", ".gz", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".mp3", ".mp4", ".avi", ".mov",
    ".exe", ".dmg", ".deb", ".rpm",
}


def _sanitize_filename(url: str) -> str:
    """Create a safe filename from a URL."""
    parsed = urlparse(url)
    name = re.sub(r"[^\w\-.]", "_", f"{parsed.netloc}{parsed.path}")
    name = re.sub(r"_+", "_", name).strip("_")
    if len(name) > 120:
        name = name[:100] + "_" + hashlib.md5(url.encode()).hexdigest()[:8]
    return name or hashlib.md5(url.encode()).hexdigest()[:16]


def _extract_with_readability(html: str, url: str) -> tuple[str, str]:
    """Extract main content using readability-lxml + markdownify."""
    from readability import Document
    from markdownify import markdownify as md

    doc = Document(html, url=url)
    title = doc.title() or ""
    content_html = doc.summary()
    content_md = md(content_html, heading_style="ATX", strip=["img", "script", "style"])
    return title, content_md.strip()


def _extract_basic(html: str) -> tuple[str, str]:
    """Fallback: strip tags and return plain text."""
    from html.parser import HTMLParser

    class _Stripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts: list[str] = []
            self.title = ""
            self._in_title = False
            self._skip = False

        def handle_starttag(self, tag, attrs):
            if tag == "title":
                self._in_title = True
            if tag in ("script", "style", "nav", "footer", "header"):
                self._skip = True

        def handle_endtag(self, tag):
            if tag == "title":
                self._in_title = False
            if tag in ("script", "style", "nav", "footer", "header"):
                self._skip = False

        def handle_data(self, data):
            if self._in_title:
                self.title += data
            elif not self._skip:
                self.parts.append(data)

    s = _Stripper()
    s.feed(html)
    text = "\n".join(s.parts)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return s.title.strip(), text.strip()


async def fetch_url(url: str, timeout: float = REQUEST_TIMEOUT) -> dict:
    """
    Fetch a single URL and extract its main content.

    Returns:
        dict with keys: url, title, content, error (if any), filename
    """
    result = {"url": url, "title": "", "content": "", "error": None, "filename": _sanitize_filename(url)}

    # Skip non-HTML resources
    parsed = urlparse(url)
    ext = parsed.path.rsplit(".", 1)[-1].lower() if "." in parsed.path else ""
    if f".{ext}" in _SKIP_EXTENSIONS:
        result["error"] = f"Skipped non-HTML resource (.{ext})"
        return result

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": "Mozilla/5.0 (compatible; DeepTutor/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                result["error"] = f"Non-HTML content-type: {content_type}"
                return result

            html = resp.text

        # Try readability first, fall back to basic
        try:
            title, content = _extract_with_readability(html, url)
        except Exception:
            title, content = _extract_basic(html)

        if not content:
            result["error"] = "No content extracted"
            return result

        # Truncate if too long
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + "\n\n[Content truncated]"

        result["title"] = title
        result["content"] = content

    except httpx.TimeoutException:
        result["error"] = f"Request timed out ({timeout}s)"
    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}"
    except Exception as e:
        result["error"] = str(e)

    return result


async def fetch_urls(urls: list[str], concurrency: int = 5) -> list[dict]:
    """
    Fetch multiple URLs concurrently.

    Args:
        urls: List of URLs to fetch
        concurrency: Max concurrent requests

    Returns:
        List of result dicts (same format as fetch_url)
    """
    sem = asyncio.Semaphore(concurrency)

    async def _limited(url: str):
        async with sem:
            return await fetch_url(url)

    tasks = [_limited(u) for u in urls]
    return await asyncio.gather(*tasks)
