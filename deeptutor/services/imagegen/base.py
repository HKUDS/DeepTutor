"""Base abstraction for image-generation adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from deeptutor.services.imagegen.config import ImagegenConfig


class BaseImagegenAdapter(ABC):
    """Abstract text-to-image adapter."""

    @abstractmethod
    async def generate(
        self, prompt: str, config: ImagegenConfig, *, n: int = 1
    ) -> list[tuple[bytes, str]]:
        """Generate ``n`` images for ``prompt``.

        Returns a list of ``(image_bytes, content_type)`` — content type is
        best-effort, e.g. ``image/png``.
        """


__all__ = ["BaseImagegenAdapter"]
