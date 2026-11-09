"""Local fetch backend — the in-process extractor ``web_fetch`` always had."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..base import BaseFetchProvider
from ..providers import register_fetch_provider

if TYPE_CHECKING:
    from deeptutor.tools.web_fetch import FetchOutcome


@register_fetch_provider("local")
class LocalFetchProvider(BaseFetchProvider):
    """Registry entry for the default local extraction path.

    The HTTP + redirect + readability logic stays in
    ``deeptutor.tools.web_fetch`` (single source of truth for the SSRF
    gate and the extractor), and ``fetch_url_as_markdown`` dispatches
    straight to it for ``backend="local"`` instead of round-tripping
    through this adapter. The adapter exists so registry consumers treat
    local like any other backend — and so a remote backend's fallback has
    a first-class name.
    """

    description = "Fetch and extract readable content locally (default; no third party)."

    async def fetch(self, url: str, **kwargs: Any) -> FetchOutcome:
        from deeptutor.tools.web_fetch import fetch_url_as_markdown

        return await fetch_url_as_markdown(url, backend="local", **kwargs)


__all__ = ["LocalFetchProvider"]
