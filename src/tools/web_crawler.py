#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Web Crawler Tool - Fetch and extract main content from URLs.

Uses httpx + readability + markdownify for robust content extraction.
Falls back to basic HTML parsing if readability is unavailable.
Supports PDF download for later processing by RAGAnything.
"""

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from src.logging import get_logger

logger = get_logger("WebCrawler")

# Max content length per page (chars) to avoid blowing up the KB
MAX_CONTENT_LENGTH = 50_000
REQUEST_TIMEOUT = 30.0
MAX_PDF_SIZE = 50 * 1024 * 1024  # 50MB max for PDF files

# Common non-content URL patterns to skip (removed .pdf)
_SKIP_EXTENSIONS = {
    ".zip", ".tar", ".gz", ".rar",
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


async def fetch_pdf(url: str, save_dir: Path, timeout: float = REQUEST_TIMEOUT) -> dict:
    """
    Download a PDF file from a URL.

    Args:
        url: The PDF URL to download
        save_dir: Directory to save the PDF file
        timeout: Request timeout in seconds

    Returns:
        dict with keys: url, title, file_path, error (if any), filename, is_pdf
    """
    result = {
        "url": url,
        "title": "",
        "file_path": None,
        "error": None,
        "filename": _sanitize_filename(url),
        "is_pdf": True,
    }

    try:
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": "Mozilla/5.0 (compatible; DeepTutor/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "application/pdf" not in content_type and not url.lower().endswith(".pdf"):
                result["error"] = f"Not a PDF content-type: {content_type}"
                return result

            # Check file size
            content_length = len(resp.content)
            if content_length > MAX_PDF_SIZE:
                result["error"] = f"PDF too large: {content_length / 1024 / 1024:.1f}MB (max {MAX_PDF_SIZE / 1024 / 1024}MB)"
                return result

            # Generate filename
            parsed = urlparse(url)
            original_name = Path(parsed.path).name
            if original_name.lower().endswith(".pdf"):
                filename = original_name
            else:
                filename = f"{result['filename']}.pdf"

            # Save file
            file_path = save_dir / filename
            file_path.write_bytes(resp.content)

            result["file_path"] = str(file_path)
            result["title"] = Path(filename).stem  # Use filename without extension as title
            logger.info(f"Downloaded PDF: {url} -> {file_path} ({content_length / 1024:.1f}KB)")

    except httpx.TimeoutException:
        result["error"] = f"Request timed out ({timeout}s)"
    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}"
    except Exception as e:
        result["error"] = str(e)

    return result


async def fetch_url(url: str, timeout: float = REQUEST_TIMEOUT, pdf_save_dir: Optional[Path] = None) -> dict:
    """
    Fetch a single URL and extract its main content.

    If the URL is a PDF and pdf_save_dir is provided, downloads the PDF instead.

    Args:
        url: The URL to fetch
        timeout: Request timeout in seconds
        pdf_save_dir: Directory to save PDF files (if None, PDFs will be skipped)

    Returns:
        dict with keys: url, title, content/file_path, error (if any), filename, is_pdf
    """
    # Check if it's a PDF URL
    parsed = urlparse(url)
    ext = parsed.path.rsplit(".", 1)[-1].lower() if "." in parsed.path else ""

    if ext == "pdf" or url.lower().endswith(".pdf"):
        if pdf_save_dir:
            return await fetch_pdf(url, pdf_save_dir, timeout)
        else:
            return {
                "url": url,
                "title": "",
                "content": "",
                "error": "PDF download not enabled (no save directory provided)",
                "filename": _sanitize_filename(url),
                "is_pdf": True,
            }

    result = {"url": url, "title": "", "content": "", "error": None, "filename": _sanitize_filename(url), "is_pdf": False}

    # Skip non-HTML resources
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


async def fetch_urls(urls: list[str], concurrency: int = 5, pdf_save_dir: Optional[Path] = None) -> list[dict]:
    """
    Fetch multiple URLs concurrently.

    Args:
        urls: List of URLs to fetch
        concurrency: Max concurrent requests
        pdf_save_dir: Directory to save PDF files (if None, PDFs will be skipped)

    Returns:
        List of result dicts (same format as fetch_url)
    """
    sem = asyncio.Semaphore(concurrency)

    async def _limited(url: str):
        async with sem:
            return await fetch_url(url, pdf_save_dir=pdf_save_dir)

    tasks = [_limited(u) for u in urls]
    return await asyncio.gather(*tasks)
