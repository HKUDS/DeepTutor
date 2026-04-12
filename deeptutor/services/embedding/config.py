"""Normalized embedding configuration resolved from catalog + env compatibility."""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config import resolve_embedding_runtime_config


@dataclass
class EmbeddingConfig:
    """Embedding runtime configuration."""

    model: str
    api_key: str
    base_url: str | None = None
    effective_url: str | None = None
    binding: str = "openai"
    provider_name: str = "openai"
    provider_mode: str = "standard"
    api_version: str | None = None
    extra_headers: dict[str, str] | None = None
    dim: int = 3072
    request_timeout: int = 60
    batch_size: int = 10


def get_embedding_config() -> EmbeddingConfig:
    """Load embedding config from provider runtime resolver."""
    resolved = resolve_embedding_runtime_config()

    if not resolved.model:
        raise ValueError("EMBEDDING_MODEL not set. Please configure it in Settings > Catalog.")

    if not resolved.effective_url:
        raise ValueError(
            "No effective embedding endpoint resolved. Please configure base_url/host for the active profile."
        )

    if resolved.provider_mode != "local" and not resolved.api_key:
        raise ValueError(
            "EMBEDDING_API_KEY not set. Please configure it in Settings > Catalog or via env fallback."
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
        request_timeout=max(1, resolved.request_timeout),
        batch_size=max(1, resolved.batch_size),
    )

