"""google-browser-scraper search provider.

Talks to a self-hosted ``google-browser-scraper serve`` endpoint, which runs each
Google query in a real browser through the user's own proxy and answers with
SerpApi-shaped JSON (``organic_results`` plus ``search_metadata``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests

from ..base import BaseSearchProvider
from ..types import Citation, SearchResult, WebSearchResponse
from . import register_provider

# A query is a page load in a real browser: typically 10-25 s, more when the
# server has to warm up a new browser identity first.
DEFAULT_TIMEOUT = 90


class GoogleBrowserScraperError(RuntimeError):
    """The endpoint replied, but without a usable results page."""


def _validate_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    try:
        parsed = urlparse(normalized if "://" in normalized else f"http://{normalized}")
        valid = parsed.scheme in {"http", "https"} and parsed.hostname
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise requests.exceptions.InvalidURL(
            "google-browser-scraper base_url must be a valid HTTP/HTTPS address."
        )
    return parsed.geturl().rstrip("/")


@register_provider("google_browser_scraper")
class GoogleBrowserScraperProvider(BaseSearchProvider):
    """Google results from a self-hosted google-browser-scraper server."""

    description = "Self-hosted Google search in a real browser (google-browser-scraper serve)"
    API_KEY_ENV_VARS = ()

    def search(
        self,
        query: str,
        base_url: str = "",
        max_results: int = 5,
        timeout: int = DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> WebSearchResponse:
        if not base_url:
            raise ValueError("google-browser-scraper requires base_url")
        endpoint = f"{_validate_base_url(base_url)}/search.json"
        headers = {"Accept": "application/json"}
        if self.api_key:
            # The server's optional GBS_API_KEY; a header keeps it out of logged URLs.
            headers["Authorization"] = f"Bearer {self.api_key}"
        request_kwargs: dict[str, Any] = {"params": {"q": query}, "headers": headers}
        if self.proxy:
            request_kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        resp = requests.get(endpoint, timeout=timeout, **request_kwargs)
        if resp.status_code != 200:
            # Keep the status for diagnostics, without echoing upstream bodies or keys.
            raise requests.HTTPError(
                f"google-browser-scraper returned HTTP {resp.status_code}.", response=resp
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise GoogleBrowserScraperError(
                "google-browser-scraper did not return valid JSON."
            ) from exc
        if isinstance(payload, list):  # several pages come back as a list of records
            payload = payload[0] if payload else {}
        if not isinstance(payload, dict):
            raise GoogleBrowserScraperError("google-browser-scraper returned an unexpected body.")
        meta = payload.get("search_metadata") or {}
        if meta.get("status") != "Success":
            # A captcha or a blocked exit is reported, not passed off as "no results",
            # so web_search can fall through to the next provider.
            verdict = meta.get("page_verdict") or "error"
            raise GoogleBrowserScraperError(
                f"google-browser-scraper got no results page ({verdict})."
            )

        citations: list[Citation] = []
        search_results: list[SearchResult] = []
        limit = max(1, min(int(max_results), 10))
        for row in payload.get("organic_results") or []:
            if len(search_results) >= limit:
                break
            if not isinstance(row, dict):
                continue
            url = row.get("link")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            title = str(row.get("title") or url)
            snippet = str(row.get("snippet") or "")
            date = str(row.get("date") or "")
            idx = len(search_results) + 1
            search_results.append(
                SearchResult(title=title, url=url, snippet=snippet, date=date, source="Google")
            )
            citations.append(
                Citation(
                    id=idx,
                    reference=f"[{idx}]",
                    url=url,
                    title=title,
                    snippet=snippet,
                    date=date,
                    source="Google",
                )
            )
        return WebSearchResponse(
            query=query,
            answer="",
            provider="google_browser_scraper",
            timestamp=datetime.now().isoformat(),
            model="google",
            citations=citations,
            search_results=search_results,
            metadata={"finish_reason": "stop"},
        )
