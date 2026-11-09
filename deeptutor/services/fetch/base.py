"""Base class and shared error type for web-fetch backend adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # runtime imports stay lazy to keep the layer cycle-free
    from deeptutor.tools.web_fetch import FetchOutcome

# Remote-fetch errors can echo request headers or credential fragments back
# (httpx and some gateways include the Authorization line in exception text).
# Anything that reaches a log line goes through redact_fetch_error first.
_BEARER_TOKEN_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{6,}")
_API_KEY_TOKEN_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{4,}\b")
_REDACTED_DETAIL_LIMIT = 200


def redact_fetch_error(
    error: str | BaseException,
    *,
    secret: str = "",
    limit: int = _REDACTED_DETAIL_LIMIT,
) -> str:
    """Render ``error`` as text that is safe to log or surface.

    Logs the exception *type* plus a redacted, truncated message: ``Bearer
    <token>`` headers and ``sk-…``-style keys are masked, the known API-key
    value (``secret``) is replaced outright, and the result is capped at
    ``limit`` characters so a hostile error body can't flood the log either.
    """
    text = f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error)
    if secret:
        text = text.replace(secret, "***")
    text = _BEARER_TOKEN_RE.sub("Bearer ***", text)
    text = _API_KEY_TOKEN_RE.sub("sk-***", text)
    return text[:limit]


class FetchProviderError(Exception):
    """A fetch backend failed before producing usable content.

    ``retryable`` splits failures the way issue #2448 specifies.
    ``retryable=True`` (401/402/403/408/429/5xx from the backend, network
    errors, a missing API key) means the *backend* is unusable right now —
    a bad key or an unpaid balance — and the dispatcher should fall back
    to the local extractor. ``retryable=False`` marks the request itself
    as bad (400/404/413), which no backend change would fix; it fails the
    call the same way the local path's ``HTTP >= 400`` branch does.
    """

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


class BaseFetchProvider(ABC):
    """One web-fetch backend: URL in, :class:`FetchOutcome` out.

    Adapters never decide whether a URL is *safe* to contact — the scheme
    allow-list and SSRF host gate in ``deeptutor/tools/web_fetch.py`` run
    before any backend is invoked, so a private/loopback URL can never be
    forwarded to a remote fetch service.
    """

    name: str = "base"
    display_name: str = "Base Fetch Provider"
    description: str = ""
    requires_api_key: bool = False
    requires_base_url: bool = False

    def __init__(self, **kwargs: Any) -> None:
        self.logger = logging.getLogger(__name__)
        self.config = kwargs

    @abstractmethod
    async def fetch(self, url: str, **kwargs: Any) -> FetchOutcome:
        """Fetch ``url`` and return a :class:`FetchOutcome`.

        Raise :class:`FetchProviderError` instead of returning a failing
        outcome when the failure describes the *backend* (credentials,
        throttling, reachability) so the dispatcher can decide about the
        local fallback.
        """
        raise NotImplementedError


__all__ = ["BaseFetchProvider", "FetchProviderError", "redact_fetch_error"]
