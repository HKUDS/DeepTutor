"""Resolve the PageIndex credential from runtime settings.

The key + base URL live in ``data/.../settings/pageindex.json`` (managed by
``RuntimeSettingsService``), surfaced to users under Knowledge → RAG pipeline
settings. A single account key is shared by every ``pageindex`` KB.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_API_BASE_URL = "https://api.pageindex.ai"


@dataclass(frozen=True)
class PageIndexConfig:
    api_key: str
    api_base_url: str


class PageIndexNotConfiguredError(RuntimeError):
    """Raised when no PageIndex API key has been configured."""


def get_pageindex_config(*, require_key: bool = True) -> PageIndexConfig:
    """Load the active PageIndex credential.

    Raises :class:`PageIndexNotConfiguredError` when ``require_key`` and the key
    is empty, so callers (indexing / retrieval) fail with a clear, actionable
    message instead of an opaque 401 from the API.
    """
    from deeptutor.services.config import get_runtime_settings_service

    settings = get_runtime_settings_service().load_pageindex()
    api_key = str(settings.get("api_key") or "").strip()
    base_url = str(settings.get("api_base_url") or DEFAULT_API_BASE_URL).strip().rstrip("/")
    if require_key and not api_key:
        raise PageIndexNotConfiguredError(
            "PageIndex API key is not configured. Add it under "
            "Knowledge → RAG pipeline settings before using a PageIndex knowledge base."
        )
    return PageIndexConfig(api_key=api_key, api_base_url=base_url or DEFAULT_API_BASE_URL)


def is_pageindex_configured() -> bool:
    """Best-effort check used to flag the provider as ready in the UI."""
    try:
        return bool(get_pageindex_config(require_key=False).api_key)
    except Exception:
        return False


__all__ = [
    "PageIndexConfig",
    "PageIndexNotConfiguredError",
    "get_pageindex_config",
    "is_pageindex_configured",
    "DEFAULT_API_BASE_URL",
]
