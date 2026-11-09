"""DeepSeek Fetch backend — the first remote alternative to local extraction.

``POST {base_url}/v1/tools/fetch`` with ``{"url": ...}`` and Bearer auth
(the same key as chat); the response is ``{"title", "content"}`` with
``content`` as page Markdown. Billed per successful request, which is why
this backend is opt-in and never used by the crawler / KB site sync.

All network I/O goes through the injectable ``client_factory`` so tests
run fully offline; the production default is a plain
``httpx.AsyncClient``.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import httpx

from ..base import BaseFetchProvider, FetchProviderError, redact_fetch_error
from ..providers import register_fetch_provider

if TYPE_CHECKING:
    from deeptutor.tools.web_fetch import FetchOutcome

DEFAULT_BASE_URL = "https://api.deepseek.com"
FETCH_PATH = "/v1/tools/fetch"

# Statuses that say "this backend can't serve right now" — bad key, unpaid
# balance, throttling, server trouble — versus ones that describe the
# request itself and would fail identically everywhere (issue #2448
# semantics). Any other 4xx keeps local extraction in play rather than
# guessing it means the same for every backend.
_HARD_FAILURE_STATUSES = frozenset({400, 404, 413})


def _first_env(*names: str) -> str:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _declared_content_length(headers: Any) -> int | None:
    """Content-Length when the response carries a usable one, else ``None``."""
    try:
        raw = str(headers.get("content-length") or "").strip()
    except Exception:  # noqa: BLE001 - header access must never break fetch
        return None
    return int(raw) if raw.isdigit() else None


def _content_encoding(headers: Any) -> str:
    """``Content-Encoding`` lowercased, or ``""`` when absent/unreadable."""
    try:
        return str(headers.get("content-encoding") or "").strip().lower()
    except Exception:  # noqa: BLE001 - header access must never break fetch
        return ""


def _catalog_deepseek_api_key() -> str:
    """The DeepSeek key already stored for chat, if any LLM profile holds one.

    The issue asks for "the same key as chat", so the model catalog is the
    last credential source after explicit argument and env vars. Best
    effort only: a catalog that cannot be read simply means no key.
    """
    try:
        from deeptutor.services.config import CATALOG_SECRET_MASK, get_model_catalog_service

        catalog = get_model_catalog_service().load()
        profiles = catalog.get("services", {}).get("llm", {}).get("profiles", [])
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            binding = str(profile.get("binding") or profile.get("provider") or "")
            if binding.strip().lower() != "deepseek":
                continue
            key = str(profile.get("api_key") or "").strip()
            if key and key != CATALOG_SECRET_MASK:
                return key
    except Exception:  # noqa: BLE001 - credential lookup must never break fetch
        return ""
    return ""


@register_fetch_provider("deepseek")
class DeepSeekFetchProvider(BaseFetchProvider):
    """Remote fetch backend backed by DeepSeek's Fetch API."""

    description = (
        "DeepSeek Fetch API — server-side extraction to Markdown "
        "(billed per successful request; falls back to local on backend errors)."
    )
    BASE_URL = DEFAULT_BASE_URL
    API_KEY_ENV_VARS = ("DEEPSEEK_FETCH_API_KEY", "DEEPSEEK_API_KEY")
    BASE_URL_ENV_VARS = ("DEEPSEEK_FETCH_BASE_URL",)

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.api_key = (
            api_key or _first_env(*self.API_KEY_ENV_VARS) or _catalog_deepseek_api_key()
        ).strip()
        self.base_url = (
            base_url or _first_env(*self.BASE_URL_ENV_VARS) or DEFAULT_BASE_URL
        ).rstrip("/")

    async def fetch(
        self,
        url: str,
        *,
        timeout_s: float = 15.0,
        client_factory: Any = None,
        **_ignored: Any,
    ) -> FetchOutcome:
        from deeptutor.tools.web_fetch import MAX_RESPONSE_BYTES, FetchOutcome

        if not self.api_key:
            raise FetchProviderError(
                "DeepSeek Fetch selected but no API key is configured "
                "(DEEPSEEK_FETCH_API_KEY / DEEPSEEK_API_KEY or a DeepSeek chat profile).",
                retryable=True,
            )
        endpoint = f"{self.base_url}{FETCH_PATH}"
        factory = client_factory or self._default_client_factory
        # The remote body is bounded by the same cap as the local download
        # path; a JSON payload of unbounded size must not be buffered whole.
        # Over the cap the error is retryable (backend anomaly, not the
        # page's fault) so the dispatcher falls back to local extraction.
        cap = int(MAX_RESPONSE_BYTES)
        try:
            async with factory(timeout=timeout_s) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    json={"url": url},
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        # Insist on an identity body: the cap below bounds the
                        # bytes actually buffered, and a gzip/br body would
                        # expand to many times that while decoding. A server
                        # that compresses anyway is rejected below instead of
                        # being decompressed without a bound.
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    status = response.status_code
                    if status in _HARD_FAILURE_STATUSES:
                        return FetchOutcome(
                            ok=False,
                            url=url,
                            error=f"HTTP {status} from DeepSeek Fetch for {url}.",
                        )
                    if status >= 400:
                        # 401/402/403/408/429/5xx (and any other 4xx):
                        # retryable at the backend level, so the dispatcher
                        # falls back to local.
                        raise FetchProviderError(
                            f"HTTP {status} from DeepSeek Fetch.", retryable=True
                        )
                    declared = _declared_content_length(response.headers)
                    if declared is not None and declared > cap:
                        raise FetchProviderError(
                            f"DeepSeek Fetch response exceeds the {cap}-byte cap "
                            f"(Content-Length: {declared}).",
                            retryable=True,
                        )
                    encoding = _content_encoding(response.headers)
                    if encoding and encoding != "identity":
                        # The cap bounds bytes held in memory; a compressed
                        # body would only be safe to read behind a bounded
                        # decompressor, which this path does not have. Reject
                        # retryably so local extraction serves the call.
                        raise FetchProviderError(
                            "DeepSeek Fetch returned a compressed response "
                            f"(Content-Encoding: {encoding}); refusing to "
                            f"decompress beyond the {cap}-byte cap.",
                            retryable=True,
                        )
                    buf = bytearray()
                    # Raw (undecoded) bytes: aiter_bytes would transparently
                    # inflate any content encoding, defeating the cap above.
                    async for chunk in response.aiter_raw():
                        # Check remaining capacity BEFORE extending so an
                        # oversized chunk is never copied into memory whole.
                        if len(buf) + len(chunk) > cap:
                            raise FetchProviderError(
                                f"DeepSeek Fetch response exceeds the {cap}-byte cap.",
                                retryable=True,
                            )
                        buf.extend(chunk)
        except httpx.HTTPError as exc:
            raise FetchProviderError(
                f"DeepSeek Fetch network error: {redact_fetch_error(exc, secret=self.api_key)}.",
                retryable=True,
            ) from exc

        try:
            payload = json.loads(bytes(buf))
        except ValueError as exc:
            raise FetchProviderError(
                f"DeepSeek Fetch returned a non-JSON body ({type(exc).__name__}).",
                retryable=True,
            ) from exc
        if not isinstance(payload, dict):
            raise FetchProviderError(
                "DeepSeek Fetch returned an unexpected payload shape.", retryable=True
            )
        raw_content = payload.get("content")
        if not isinstance(raw_content, str):
            # An object/array/number where Markdown belongs is a malformed
            # backend response — retryable, so local extraction serves the call.
            raise FetchProviderError("DeepSeek Fetch returned non-string content.", retryable=True)
        raw_title = payload.get("title")
        content = raw_content.strip()
        title = raw_title.strip() if isinstance(raw_title, str) else ""
        if not content:
            # Per the failure semantics: an empty Markdown body is a hard
            # failure, the same meaning as the local path's HTTP >= 400
            # branch — it describes the page, not the backend.
            return FetchOutcome(
                ok=False,
                url=url,
                error=f"DeepSeek Fetch returned no content for {url}.",
            )
        # Remote backends don't see the post-redirect final URL, so the
        # requested URL is what citations get (documented trade-off).
        return FetchOutcome(ok=True, markdown=content, url=url, title=title)

    @staticmethod
    def _default_client_factory(*, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout)


__all__ = ["DeepSeekFetchProvider"]
