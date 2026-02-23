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
import time
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

import httpx

from src.logging import get_logger

logger = get_logger("WebCrawler")

# Max content length per page (chars) to avoid blowing up the KB
MAX_CONTENT_LENGTH = 50_000
REQUEST_TIMEOUT = 30.0
MAX_PDF_SIZE = 50 * 1024 * 1024  # 50MB max for PDF files
MOBILE_RENDER_TIMEOUT = 20.0
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; DeepTutor/1.0)"
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)
_TOUTIAO_DOMAINS = {"toutiao.com", "www.toutiao.com", "m.toutiao.com"}
_MOBILE_UA_DOMAINS = _TOUTIAO_DOMAINS
_BROWSER_FALLBACK_DOMAINS = _TOUTIAO_DOMAINS
_LOW_QUALITY_MARKERS = (
    "您需要允许该网站执行 JavaScript",
    "you need to enable javascript",
    "你的浏览器版本过低，可能导致网站不能正常访问",
    "visit the bitauto international website",
)
_CAPTCHA_MARKERS = (
    "__captcha",
    "tcaptcha.js",
    "tencentcaptcha",
    "wafcaptcha",
    "captcha",
)
_CONTENT_TYPE_HTML = ("text/html", "text/plain")
_STATUS_SUCCESS_HTTP = "success_http"
_STATUS_SUCCESS_BROWSER = "success_browser"
_STATUS_BLOCKED_CAPTCHA = "blocked_captcha"
_STATUS_BLOCKED_JS = "blocked_js_placeholder"
_STATUS_FAILED_NETWORK = "failed_network"
_STATUS_FAILED_HTTP = "failed_http_status"
_STATUS_FAILED_EXTRACT = "failed_extract"
_STATUS_FAILED_UNSUPPORTED = "failed_unsupported_content"
_STATUS_FAILED_PDF_TOO_LARGE = "failed_pdf_too_large"
_STATUS_FAILED_PDF_DISABLED = "failed_pdf_disabled"
_ARXIV_DOMAINS = {"arxiv.org", "www.arxiv.org"}
_CONTENT_DISPOSITION_FILENAME_RE = re.compile(
    r"""filename\*?=(?:[A-Za-z0-9._-]+'')?"?([^";]+)""",
    re.IGNORECASE,
)

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


def _domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lower().split(":", 1)[0]


def _should_use_mobile_ua(url: str) -> bool:
    return _domain_from_url(url) in _MOBILE_UA_DOMAINS


def _build_headers(use_mobile_ua: bool) -> dict:
    return {"User-Agent": MOBILE_USER_AGENT if use_mobile_ua else DEFAULT_USER_AGENT}


def _should_try_browser_fallback(url: str) -> bool:
    return _domain_from_url(url) in _BROWSER_FALLBACK_DOMAINS


def _classify_low_quality_text(text: str) -> str | None:
    if not text:
        return _STATUS_FAILED_EXTRACT

    lowered = text.lower()
    if any(marker in lowered for marker in _CAPTCHA_MARKERS):
        return _STATUS_BLOCKED_CAPTCHA
    if any(marker.lower() in lowered for marker in _LOW_QUALITY_MARKERS):
        return _STATUS_BLOCKED_JS
    if "probe.js" in lowered:
        return _STATUS_BLOCKED_JS
    return None


def _is_low_quality_text(text: str) -> bool:
    return _classify_low_quality_text(text) is not None


def _url_looks_like_pdf(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.path.lower().endswith(".pdf"):
        return True
    if _domain_from_url(url) in _ARXIV_DOMAINS and parsed.path.startswith("/pdf/"):
        return True
    return False


def _filename_from_content_disposition(content_disposition: str) -> str:
    if not content_disposition:
        return ""
    match = _CONTENT_DISPOSITION_FILENAME_RE.search(content_disposition)
    if not match:
        return ""
    filename = unquote(match.group(1).strip().strip('"'))
    return Path(filename).name


def _is_pdf_response(
    requested_url: str,
    final_url: str,
    content_type: str,
    content_disposition: str,
    content: bytes,
) -> bool:
    lowered_type = content_type.lower()
    if "application/pdf" in lowered_type:
        return True
    if (
        "application/octet-stream" in lowered_type
        and _filename_from_content_disposition(content_disposition).lower().endswith(".pdf")
    ):
        return True
    if _url_looks_like_pdf(requested_url) or _url_looks_like_pdf(final_url):
        return True
    if content.startswith(b"%PDF-"):
        return True
    return False


def _pick_pdf_filename(
    requested_url: str,
    final_url: str,
    content_disposition: str,
    fallback: str,
) -> str:
    from_header = _filename_from_content_disposition(content_disposition)
    if from_header and from_header.lower().endswith(".pdf"):
        return from_header

    parsed_final = urlparse(final_url)
    final_name = Path(parsed_final.path).name
    if final_name.lower().endswith(".pdf"):
        return final_name

    parsed_requested = urlparse(requested_url)
    requested_name = Path(parsed_requested.path).name
    if requested_name.lower().endswith(".pdf"):
        return requested_name

    return f"{fallback}.pdf"


async def _fetch_html_with_browser(url: str, timeout: float) -> dict:
    """
    Best-effort browser rendering fallback.

    This is optional and only used for selected domains. If Playwright is
    unavailable at runtime, it returns an error and the caller keeps HTTP result.
    """
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        return {"html": "", "url": url, "error": f"browser runtime unavailable: {e}"}

    browser = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent=MOBILE_USER_AGENT if _should_use_mobile_ua(url) else DEFAULT_USER_AGENT
            )
            await page.goto(
                url,
                timeout=int(timeout * 1000),
                wait_until="domcontentloaded",
            )
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                # Some pages never reach networkidle; keep the current DOM.
                pass
            html = await page.content()
            return {"html": html, "url": page.url, "error": None}
    except Exception as e:
        return {"html": "", "url": url, "error": str(e)}
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass


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
        "requested_url": url,
        "final_url": url,
        "title": "",
        "file_path": None,
        "error": None,
        "filename": _sanitize_filename(url),
        "is_pdf": True,
        "fetch_method": "http",
        "fetch_status": "",
        "content_type": "",
        "content_chars": 0,
        "file_size": 0,
        "fetched_at": time.time(),
    }

    try:
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": DEFAULT_USER_AGENT},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            content_disposition = resp.headers.get("content-disposition", "")
            final_url = str(resp.url)
            result["url"] = final_url
            result["final_url"] = final_url
            result["content_type"] = content_type
            result["file_size"] = len(resp.content)
            is_pdf = _is_pdf_response(
                requested_url=url,
                final_url=final_url,
                content_type=content_type,
                content_disposition=content_disposition,
                content=resp.content,
            )
            if not is_pdf:
                result["error"] = f"Not a PDF content-type: {content_type}"
                result["fetch_status"] = _STATUS_FAILED_UNSUPPORTED
                return result

            # Check file size
            content_length = len(resp.content)
            if content_length > MAX_PDF_SIZE:
                result["error"] = (
                    "PDF too large: "
                    f"{content_length / 1024 / 1024:.1f}MB (max {MAX_PDF_SIZE / 1024 / 1024}MB)"
                )
                result["fetch_status"] = _STATUS_FAILED_PDF_TOO_LARGE
                return result

            # Generate filename
            filename = _pick_pdf_filename(
                requested_url=url,
                final_url=final_url,
                content_disposition=content_disposition,
                fallback=result["filename"],
            )

            # Save file
            file_path = save_dir / filename
            file_path.write_bytes(resp.content)

            result["file_path"] = str(file_path)
            result["title"] = Path(filename).stem  # Use filename without extension as title
            result["filename"] = filename
            result["fetch_status"] = _STATUS_SUCCESS_HTTP
            logger.info(f"Downloaded PDF: {url} -> {file_path} ({content_length / 1024:.1f}KB)")

    except httpx.TimeoutException:
        result["error"] = f"Request timed out ({timeout}s)"
        result["fetch_status"] = _STATUS_FAILED_NETWORK
    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}"
        result["fetch_status"] = _STATUS_FAILED_HTTP
    except Exception as e:
        result["error"] = str(e)
        result["fetch_status"] = _STATUS_FAILED_NETWORK

    return result


async def fetch_url(url: str, timeout: float = REQUEST_TIMEOUT, pdf_save_dir: Optional[Path] = None) -> dict:
    """
    Fetch a single URL and extract its main content.

    Detects PDFs by both URL extension and response content-type, so URLs like
    arxiv.org/pdf/2301.12345 (no .pdf suffix) are handled correctly.

    Args:
        url: The URL to fetch
        timeout: Request timeout in seconds
        pdf_save_dir: Directory to save PDF files (if None, PDFs will be skipped)

    Returns:
        dict with keys: url, title, content/file_path, error (if any), filename, is_pdf
    """
    result = {
        "url": url,
        "requested_url": url,
        "final_url": url,
        "title": "",
        "content": "",
        "error": None,
        "filename": _sanitize_filename(url),
        "is_pdf": False,
        "fetch_method": "http",
        "fetch_status": "",
        "content_type": "",
        "content_chars": 0,
        "file_size": 0,
        "fetched_at": time.time(),
    }

    parsed = urlparse(url)
    ext = parsed.path.rsplit(".", 1)[-1].lower() if "." in parsed.path else ""

    # Skip non-HTML resources that are definitely not PDFs.
    if f".{ext}" in _SKIP_EXTENSIONS:
        result["error"] = f"Skipped non-HTML resource (.{ext})"
        result["fetch_status"] = _STATUS_FAILED_UNSUPPORTED
        return result

    try:
        use_mobile_ua = _should_use_mobile_ua(url)
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
        ) as client:
            resp = await client.get(url, headers=_build_headers(use_mobile_ua))
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            content_disposition = resp.headers.get("content-disposition", "")
            final_url = str(resp.url)
            result["url"] = final_url
            result["final_url"] = final_url
            result["content_type"] = content_type
            result["file_size"] = len(resp.content)

            is_pdf = _is_pdf_response(
                requested_url=url,
                final_url=final_url,
                content_type=content_type,
                content_disposition=content_disposition,
                content=resp.content,
            )

            if is_pdf:
                if not pdf_save_dir:
                    return {
                        "url": final_url,
                        "requested_url": url,
                        "final_url": final_url,
                        "title": "",
                        "content": "",
                        "error": "PDF download not enabled (no save directory provided)",
                        "filename": _sanitize_filename(url),
                        "is_pdf": True,
                        "fetch_method": "http",
                        "fetch_status": _STATUS_FAILED_PDF_DISABLED,
                        "content_type": content_type,
                        "content_chars": 0,
                        "file_size": len(resp.content),
                        "fetched_at": result["fetched_at"],
                    }

                # Save the already-downloaded PDF bytes
                if len(resp.content) > MAX_PDF_SIZE:
                    return {
                        "url": final_url,
                        "requested_url": url,
                        "final_url": final_url,
                        "title": "",
                        "content": "",
                        "error": (
                            "PDF too large: "
                            f"{len(resp.content) / 1024 / 1024:.1f}MB "
                            f"(max {MAX_PDF_SIZE / 1024 / 1024}MB)"
                        ),
                        "filename": _sanitize_filename(url),
                        "is_pdf": True,
                        "fetch_method": "http",
                        "fetch_status": _STATUS_FAILED_PDF_TOO_LARGE,
                        "content_type": content_type,
                        "content_chars": 0,
                        "file_size": len(resp.content),
                        "fetched_at": result["fetched_at"],
                    }

                save_dir = Path(pdf_save_dir)
                save_dir.mkdir(parents=True, exist_ok=True)

                filename = _pick_pdf_filename(
                    requested_url=url,
                    final_url=final_url,
                    content_disposition=content_disposition,
                    fallback=_sanitize_filename(url),
                )

                file_path = save_dir / filename
                file_path.write_bytes(resp.content)
                logger.info(f"Downloaded PDF: {url} -> {file_path} ({len(resp.content) / 1024:.1f}KB)")

                return {
                    "url": final_url,
                    "requested_url": url,
                    "final_url": final_url,
                    "title": Path(filename).stem,
                    "file_path": str(file_path),
                    "error": None,
                    "filename": filename,
                    "is_pdf": True,
                    "fetch_method": "http",
                    "fetch_status": _STATUS_SUCCESS_HTTP,
                    "content_type": content_type,
                    "content_chars": 0,
                    "file_size": len(resp.content),
                    "fetched_at": result["fetched_at"],
                }

            # Not a PDF — handle as HTML
            if not any(t in content_type.lower() for t in _CONTENT_TYPE_HTML):
                result["error"] = f"Non-HTML content-type: {content_type}"
                result["fetch_status"] = _STATUS_FAILED_UNSUPPORTED
                return result

            html = resp.text
            low_quality_status = _classify_low_quality_text(html)
            if low_quality_status:
                if not use_mobile_ua:
                    # Retry once with mobile UA for JS-heavy sites that block desktop/robot UAs.
                    resp = await client.get(url, headers=_build_headers(True))
                    resp.raise_for_status()
                    content_type = resp.headers.get("content-type", "")
                    if not any(t in content_type.lower() for t in _CONTENT_TYPE_HTML):
                        result["error"] = f"Non-HTML content-type: {content_type}"
                        result["fetch_status"] = _STATUS_FAILED_UNSUPPORTED
                        return result
                    html = resp.text
                    result["url"] = str(resp.url)
                    result["final_url"] = str(resp.url)
                    result["content_type"] = content_type
                    result["file_size"] = len(resp.content)
                    low_quality_status = _classify_low_quality_text(html)

                if low_quality_status and _should_try_browser_fallback(url):
                    browser_result = await _fetch_html_with_browser(
                        url,
                        timeout=min(timeout, MOBILE_RENDER_TIMEOUT),
                    )
                    if browser_result.get("html"):
                        html = browser_result["html"]
                        result["url"] = browser_result.get("url") or result["url"]
                        result["final_url"] = result["url"]
                        result["fetch_method"] = "browser"
                        low_quality_status = _classify_low_quality_text(html)
                    elif browser_result.get("error"):
                        logger.warning(
                            "Browser fallback failed for %s: %s",
                            url,
                            browser_result["error"],
                        )

                if low_quality_status:
                    result["error"] = "Low-quality placeholder page"
                    result["fetch_status"] = low_quality_status
                    return result

        # Try readability first, fall back to basic
        try:
            title, content = _extract_with_readability(html, result["url"])
        except Exception:
            title, content = _extract_basic(html)

        if not content:
            result["error"] = "No content extracted"
            result["fetch_status"] = _STATUS_FAILED_EXTRACT
            return result
        low_quality_content_status = _classify_low_quality_text(content)
        if low_quality_content_status:
            result["error"] = "Low-quality extracted content"
            result["fetch_status"] = low_quality_content_status
            return result

        # Truncate if too long
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + "\n\n[Content truncated]"

        result["title"] = title
        result["content"] = content
        result["content_chars"] = len(content)
        result["fetch_status"] = (
            _STATUS_SUCCESS_BROWSER if result["fetch_method"] == "browser" else _STATUS_SUCCESS_HTTP
        )

    except httpx.TimeoutException:
        result["error"] = f"Request timed out ({timeout}s)"
        result["fetch_status"] = _STATUS_FAILED_NETWORK
    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}"
        result["fetch_status"] = _STATUS_FAILED_HTTP
    except Exception as e:
        result["error"] = str(e)
        result["fetch_status"] = _STATUS_FAILED_NETWORK

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
