"""Model catalog lookup for CodeBuddy.

The cloud has no public model-list route, so the catalog comes from the config
the CodeBuddy CLI caches on disk. The CLI subprocess probe is only used as a
fallback, and ``default`` resolves on every deployment.
"""

from __future__ import annotations

import importlib.util

from deeptutor.services.codebuddy_credentials import FALLBACK_MODEL_CATALOG, cached_model_catalog


async def fetch_codebuddy_models_with_source(
    api_key: str | None = None,
) -> tuple[list[str], str]:
    """Return ``(models, source)`` where ``source`` is ``"cache"``, ``"cli"``, or ``"fallback"``."""
    cached = cached_model_catalog()
    if cached:
        return cached, "cache"

    if importlib.util.find_spec("codebuddy_agent_sdk") is not None:
        from deeptutor.services.llm.provider_core.codebuddy_provider import (
            fetch_codebuddy_models as fetch_via_cli,
        )

        try:
            models = await fetch_via_cli(api_key)
        except Exception:  # noqa: BLE001 - CLI probe is best effort
            models = []
        if models:
            return models, "cli"

    return list(FALLBACK_MODEL_CATALOG), "fallback"


async def fetch_codebuddy_models(api_key: str | None = None) -> list[str]:
    """Return the model ids available to the signed-in CodeBuddy account."""
    models, _ = await fetch_codebuddy_models_with_source(api_key)
    return models


__all__ = ["fetch_codebuddy_models", "fetch_codebuddy_models_with_source"]
