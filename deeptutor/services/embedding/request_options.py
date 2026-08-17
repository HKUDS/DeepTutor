"""Shared request-option decisions for embedding transports."""

from __future__ import annotations

from deeptutor.services.config.embedding_endpoint import canonical_embedding_provider_name

_JINA_VARIABLE_DIMENSIONS: dict[str, frozenset[int]] = {
    "jina-embeddings-v3": frozenset({32, 64, 128, 256, 512, 768, 1024}),
    "jina-embeddings-v4": frozenset({32, 64, 128, 256, 512, 768, 1024}),
}


def should_send_embedding_dimensions(
    *,
    binding: str | None,
    model: str | None,
    dimension: int | None,
    send_dimensions: bool | None,
) -> bool:
    """Apply DeepTutor's tri-state ``dimensions`` request policy.

    Explicit user choices always win. In automatic mode, Jina uses its known
    Matryoshka dimensions while OpenAI-compatible transports use the model
    families already supported by DeepTutor's regular embedding adapters.
    """
    if not dimension:
        return False
    if send_dimensions is True:
        return True
    if send_dimensions is False:
        return False

    provider = canonical_embedding_provider_name(binding)
    model_name = str(model or "").strip()
    if provider == "jina":
        return dimension in _JINA_VARIABLE_DIMENSIONS.get(model_name, frozenset())

    lowered = model_name.lower()
    return (
        lowered.startswith("text-embedding-3")
        or "qwen3-embedding" in lowered
        or "qwen3-vl-embedding" in lowered
    )


__all__ = ["should_send_embedding_dimensions"]
