"""Resolve PageIndex Cloud credentials and OSS readiness.

The Cloud key lives in ``data/.../settings/pageindex.json`` (managed by
``RuntimeSettingsService``), surfaced to users under Knowledge → RAG pipeline
settings. A single deployment credential is shared by every ``pageindex`` KB;
the SDK owns the official Cloud endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageIndexConfig:
    api_key: str


def get_pageindex_config(*, require_key: bool = True) -> PageIndexConfig:
    """Load the active PageIndex credential.

    Raises when ``require_key`` and the key is empty, so callers fail with a
    clear, actionable message instead of an opaque 401 from the API.
    """
    from deeptutor.services.config import get_runtime_settings_service

    settings = get_runtime_settings_service().load_pageindex()
    api_key = str(settings.get("api_key") or "").strip()
    if require_key and not api_key:
        raise RuntimeError(
            "PageIndex API key is not configured. Add it under "
            "Knowledge → RAG pipeline settings before using a PageIndex knowledge base."
        )
    return PageIndexConfig(api_key=api_key)


def is_pageindex_configured() -> bool:
    """Best-effort check used to flag the provider as ready in the UI."""
    try:
        return bool(get_pageindex_config(require_key=False).api_key)
    except Exception:
        return False


__all__ = [
    "PageIndexConfig",
    "get_pageindex_config",
    "is_pageindex_configured",
]
