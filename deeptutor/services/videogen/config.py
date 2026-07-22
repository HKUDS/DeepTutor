"""Resolved runtime configuration for video-generation providers.

Unlike image generation, text-to-video has no synchronous OpenAI standard: the
common shape is an async task (submit → poll → download). This dataclass carries
the generation knobs plus the polling budget used by the async-task adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from deeptutor.services.generation_http import AUTH_BEARER


@dataclass(slots=True)
class VideogenConfig:
    """Resolved text-to-video configuration for one generation call."""

    model: str
    provider_name: str = "volcengine"
    adapter: str = "async_task"
    auth_style: str = AUTH_BEARER
    api_key: str = ""
    base_url: str = ""
    api_version: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    # Provider/model-specific generation knobs. Empty → omit.
    aspect_ratio: str = ""  # e.g. "16:9"
    duration: str = ""  # seconds, free-form (e.g. "5")
    resolution: str = ""  # e.g. "720p" | "1080p"
    # Polling budget. ``request_timeout`` bounds each submit/poll HTTP call;
    # ``poll_timeout`` bounds the whole render; ``poll_interval`` is the gap
    # between status checks.
    request_timeout: int = 60
    poll_interval: float = 5.0
    poll_timeout: int = 600


__all__ = ["VideogenConfig"]
