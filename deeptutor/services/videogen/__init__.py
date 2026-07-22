"""Video-generation service — text-to-video via the active model catalog.

Public facade used by the chat tool, the API router and the config test runner.
Config is resolved from ``services.videogen`` exactly like llm/embedding/tts, so
video providers are configured through the same Settings catalog UI.

Generation is an async task (submit → poll → download); pass ``progress`` to
forward render status to the caller (e.g. the chat stream).
"""

from __future__ import annotations

from typing import Any

from deeptutor.services.generation_http import GenerationProviderError
from deeptutor.services.videogen.adapters import get_videogen_adapter
from deeptutor.services.videogen.base import ProgressFn
from deeptutor.services.videogen.config import VideogenConfig


async def generate_video(
    prompt: str,
    *,
    catalog: dict[str, Any] | None = None,
    aspect_ratio: str | None = None,
    duration: str | None = None,
    resolution: str | None = None,
    progress: ProgressFn | None = None,
) -> tuple[bytes, str]:
    """Generate one video for ``prompt`` using the active videogen selection.

    Returns ``(video_bytes, content_type)``. ``aspect_ratio`` / ``duration`` /
    ``resolution`` override the catalog defaults for this call.
    """
    from deeptutor.services.config.provider_runtime import resolve_videogen_runtime_config

    prompt = (prompt or "").strip()
    if not prompt:
        raise GenerationProviderError("Cannot generate a video from an empty prompt.")
    config = resolve_videogen_runtime_config(catalog=catalog)
    if aspect_ratio:
        config.aspect_ratio = aspect_ratio
    if duration:
        config.duration = duration
    if resolution:
        config.resolution = resolution
    adapter = get_videogen_adapter(config.adapter)
    return await adapter.generate(prompt, config, progress=progress)


async def probe_video(prompt: str, *, catalog: dict[str, Any] | None = None) -> str:
    """Submit a video task and return its id without waiting for the render.

    Used by the Settings "Test connection" probe to validate endpoint + auth +
    model cheaply (a full render is slow and billable).
    """
    from deeptutor.services.config.provider_runtime import resolve_videogen_runtime_config

    prompt = (prompt or "").strip() or "A short test clip."
    config = resolve_videogen_runtime_config(catalog=catalog)
    adapter = get_videogen_adapter(config.adapter)
    return await adapter.submit_task(prompt, config)


__all__ = ["GenerationProviderError", "VideogenConfig", "generate_video", "probe_video"]
