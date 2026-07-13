"""Base abstraction for video-generation adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from deeptutor.services.videogen.config import VideogenConfig

# Optional async progress callback invoked during long renders. Receives a short
# human-readable status line (the tool layer forwards it to the chat stream).
ProgressFn = Callable[[str], Awaitable[None]]


class BaseVideogenAdapter(ABC):
    """Abstract text-to-video adapter (task lifecycle: submit → poll → download)."""

    @abstractmethod
    async def submit_task(self, prompt: str, config: VideogenConfig) -> str:
        """Submit a generation task and return its provider task id.

        Used both by :meth:`generate` and by the Settings "Test connection"
        probe, which validates endpoint + auth + model without waiting for the
        (slow, billable) render to finish.
        """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        config: VideogenConfig,
        *,
        progress: ProgressFn | None = None,
    ) -> tuple[bytes, str]:
        """Generate one video for ``prompt``.

        Returns ``(video_bytes, content_type)`` — content type is best-effort,
        e.g. ``video/mp4``.
        """


__all__ = ["BaseVideogenAdapter", "ProgressFn"]
