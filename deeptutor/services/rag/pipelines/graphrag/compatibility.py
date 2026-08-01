"""Resolve and test GraphRAG completion-model candidates without activating them."""

from __future__ import annotations

from deeptutor.services.config import (
    get_model_catalog_service,
    resolve_llm_runtime_config,
)

from . import engine


async def probe_configured_completion_model(profile_id: str, model_id: str) -> dict:
    """Probe one configured model by ID while leaving the active catalog unchanged.

    Args:
        profile_id: Server-side model-catalog profile ID.
        model_id: Server-side model ID within the selected profile.

    Returns:
        A secret-free GraphRAG compatibility result.

    Raises:
        ValueError: If the profile/model selection does not exist.
    """
    service = get_model_catalog_service()
    llm_cfg = resolve_llm_runtime_config(
        catalog=service.load(),
        service=service,
        llm_selection={"profile_id": profile_id, "model_id": model_id},
    )
    return await engine.probe_completion_model(llm_cfg)


async def probe_active_completion_model() -> dict:
    """Probe the globally active chat model without changing catalog state."""
    service = get_model_catalog_service()
    llm_cfg = resolve_llm_runtime_config(catalog=service.load(), service=service)
    return await engine.probe_completion_model(llm_cfg)


__all__ = ["probe_active_completion_model", "probe_configured_completion_model"]
