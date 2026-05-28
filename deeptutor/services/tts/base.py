"""Base class for TTS providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import TTSAudioResult


class BaseTTSProvider(ABC):
    """Abstract base class for TTS providers.

    All TTS providers must implement this interface.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the TTS provider.

        Args:
            **kwargs: Provider-specific configuration options
        """
        self.config = kwargs

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        output_path: str | None = None,
    ) -> TTSAudioResult:
        """Synthesize text to speech.

        Args:
            text: The text to synthesize
            voice: Voice identifier (provider-specific)
            output_path: Optional custom output path for audio file

        Returns:
            TTSAudioResult containing audio file path and sentence boundaries
        """
        raise NotImplementedError

    @abstractmethod
    async def list_voices(self) -> list[dict[str, Any]]:
        """List available voices for this provider.

        Returns:
            List of voice metadata dictionaries
        """
        raise NotImplementedError

    async def health_check(self) -> bool:
        """Check if the TTS service is available.

        Returns:
            True if service is healthy, False otherwise
        """
        try:
            voices = await self.list_voices()
            return len(voices) > 0
        except Exception:
            return False
