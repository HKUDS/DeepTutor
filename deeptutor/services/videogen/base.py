"""Base abstraction for video-generation adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from deeptutor.services.generation_http import GenerationProviderError
from deeptutor.services.videogen.config import VideogenConfig

# Optional async progress callback invoked during long renders. Receives a short
# human-readable status line (the tool layer forwards it to the chat stream).
ProgressFn = Callable[[str], Awaitable[None]]


@asynccontextmanager
async def video_poll_budget(seconds: float, task_id: str) -> AsyncIterator[None]:
    """Bound the complete polling loop, including HTTP, progress and sleeps."""
    budget = asyncio.timeout(seconds)
    try:
        async with budget:
            yield
    except TimeoutError as exc:
        if not budget.expired():
            raise
        raise GenerationProviderError(f"Video task {task_id} timed out after {seconds}s.") from exc


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


__all__ = ["BaseVideogenAdapter", "ProgressFn", "video_poll_budget"]
