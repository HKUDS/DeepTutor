"""Image-generation service — text-to-image via the active model catalog.

Public facade used by the chat tool, the API router and the config test runner.
Config is resolved from ``services.imagegen`` exactly like llm/embedding/tts, so
image providers are configured through the same Settings catalog UI.
"""

from __future__ import annotations

from typing import Any

from deeptutor.services.generation_http import GenerationProviderError
from deeptutor.services.imagegen.adapters import get_imagegen_adapter
from deeptutor.services.imagegen.config import ImagegenConfig


async def generate_image(
    prompt: str,
    *,
    catalog: dict[str, Any] | None = None,
    size: str | None = None,
    quality: str | None = None,
    style: str | None = None,
    n: int = 1,
) -> list[tuple[bytes, str]]:
    """Generate ``n`` images for ``prompt`` using the active imagegen selection.

    Returns a list of ``(image_bytes, content_type)``. ``size`` / ``quality`` /
    ``style`` override the catalog defaults for this call.
    """
    from deeptutor.services.config.provider_runtime import resolve_imagegen_runtime_config

    prompt = (prompt or "").strip()
    if not prompt:
        raise GenerationProviderError("Cannot generate an image from an empty prompt.")
    config = resolve_imagegen_runtime_config(catalog=catalog)
    if size:
        config.size = size
    if quality:
        config.quality = quality
    if style:
        config.style = style
    adapter = get_imagegen_adapter(config.adapter)
    return await adapter.generate(prompt, config, n=max(1, n))


__all__ = ["GenerationProviderError", "ImagegenConfig", "generate_image"]
