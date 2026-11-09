"""Pluggable fetch-backend layer for the ``web_fetch`` tool (issue #2448).

A fetch backend replaces one thing only: the *HTTP GET + readability
extraction* step inside
:func:`deeptutor.tools.web_fetch.fetch_url_as_markdown`. The decision of
whether a URL is safe to contact — scheme allow-list and the private /
loopback / link-local host gate — stays in ``web_fetch`` and runs **before**
any backend is invoked, so a remote backend (DeepSeek Fetch) can never be
used to hand an internal URL to a third party.

Structure mirrors web search: backend metadata lives in the
``FETCH_PROVIDERS`` spec table
(``deeptutor/services/config/provider_runtime.py``, next to
``SEARCH_PROVIDERS``) and adapters register themselves in
``deeptutor/services/fetch/providers``. ``local`` — the in-process extractor
every install already uses — is the default; ``deepseek`` is the first
remote alternative.

Failure semantics (split by what can be retried):

* Retryable (401/402/403/408/429/5xx from the backend, network errors, a
  missing API key) falls back to the local extractor — a bad key or an
  unpaid balance must not take ``web_fetch`` down.
* Hard (400/404/413, or an empty Markdown body) fails the call outright,
  the same meaning as the local path's ``HTTP >= 400`` branch.
"""

from __future__ import annotations

import logging
import os

from deeptutor.services.config import DEFAULT_FETCH_PROVIDER, SUPPORTED_FETCH_PROVIDERS
from deeptutor.services.fetch.providers import (
    get_fetch_provider,
    list_fetch_providers,
    register_fetch_provider,
)

logger = logging.getLogger(__name__)

# Deployment override for the default fetch backend. Read at call time so a
# change applies to the next ``web_fetch`` without a restart. Values must
# name an entry in ``FETCH_PROVIDERS``; anything else falls back to local
# with a warning instead of breaking the tool.
FETCH_BACKEND_ENV = "DEEPTUTOR_FETCH_BACKEND"


def resolve_fetch_backend() -> str:
    """Name of the fetch backend ``web_fetch`` uses by default.

    ``backend=None`` passed to :func:`fetch_url_as_markdown` lands here:
    ``DEEPTUTOR_FETCH_BACKEND`` when it names a registered backend,
    otherwise :data:`DEFAULT_FETCH_PROVIDER` — so an unconfigured install
    keeps the local extraction path exactly as it behaves today.
    """
    raw = (os.environ.get(FETCH_BACKEND_ENV) or "").strip().lower()
    if not raw:
        return DEFAULT_FETCH_PROVIDER
    if raw not in SUPPORTED_FETCH_PROVIDERS:
        logger.warning(
            "Ignoring unknown %s=%r; using the %s fetch backend.",
            FETCH_BACKEND_ENV,
            raw,
            DEFAULT_FETCH_PROVIDER,
        )
        return DEFAULT_FETCH_PROVIDER
    return raw


__all__ = [
    "FETCH_BACKEND_ENV",
    "get_fetch_provider",
    "list_fetch_providers",
    "register_fetch_provider",
    "resolve_fetch_backend",
]
