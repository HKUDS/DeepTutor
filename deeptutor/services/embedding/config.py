"""Normalized embedding configuration resolved from the model catalog."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass

from deeptutor.services.config import resolve_embedding_runtime_config


@dataclass
class EmbeddingConfig:
    """Embedding runtime configuration."""

    model: str
    api_key: str | list[str]
    base_url: str | None = None
    effective_url: str | None = None
    binding: str = "openai"
    provider_name: str = "openai"
    provider_mode: str = "standard"
    api_version: str | None = None
    extra_headers: dict[str, str] | None = None
    dim: int = 0
    send_dimensions: bool | None = None
    request_timeout: int = 60
    batch_size: int = 10
    batch_delay: float = 0.0


_scoped_config: ContextVar[EmbeddingConfig | None] = ContextVar("embedding_config", default=None)


def scoped_embedding_config() -> EmbeddingConfig | None:
    return _scoped_config.get()


@contextmanager
def embedding_config_scope(config: EmbeddingConfig):
    """Bind one operation, including its worker threads, to a resolved model."""
    token = _scoped_config.set(config)
    try:
        yield
    finally:
        _scoped_config.reset(token)


def get_embedding_config(
    selection: dict | None = None, *, catalog: dict | None = None
) -> EmbeddingConfig:
    """Load embedding config from provider runtime resolver."""
    if selection is None and catalog is None and _scoped_config.get() is not None:
        return _scoped_config.get()
    if selection is not None:
        from deeptutor.services.config import get_model_catalog_service

        catalog = deepcopy(catalog if catalog is not None else get_model_catalog_service().load())
        service = catalog.get("services", {}).get("embedding", {})
        profile = next(
            (p for p in service.get("profiles", []) if p.get("id") == selection.get("profile_id")),
            None,
        )
        model = next(
            (
                m
                for m in (profile or {}).get("models", [])
                if m.get("id") == selection.get("model_id")
            ),
            None,
        )
        if profile is None or model is None:
            raise ValueError(
                "The embedding model bound to this knowledge base was deleted. Select another embedding model to re-index it."
            )
        service["active_profile_id"] = profile["id"]
        service["active_model_id"] = model["id"]
    resolved = (
        resolve_embedding_runtime_config(catalog=catalog)
        if catalog is not None
        else resolve_embedding_runtime_config()
    )

    if not resolved.model:
        raise ValueError("Embedding model not set. Please configure it in Settings > Catalog.")

    if not resolved.effective_url:
        raise ValueError(
            "No effective embedding endpoint resolved. Please configure base_url/host for the active profile."
        )

    if resolved.provider_mode != "local" and not resolved.api_key:
        raise ValueError(
            "Embedding API key not set. Please configure the active profile in Settings > Catalog."
        )

    return EmbeddingConfig(
        model=resolved.model,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        effective_url=resolved.effective_url,
        binding=resolved.binding,
        provider_name=resolved.provider_name,
        provider_mode=resolved.provider_mode,
        api_version=resolved.api_version,
        extra_headers=resolved.extra_headers,
        dim=resolved.dimension,
        send_dimensions=resolved.send_dimensions,
        request_timeout=max(1, resolved.request_timeout),
        batch_size=max(1, resolved.batch_size),
        batch_delay=max(0.0, resolved.batch_delay),
    )
