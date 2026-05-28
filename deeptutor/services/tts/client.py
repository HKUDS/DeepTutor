"""Unified TTS client."""

from __future__ import annotations

from typing import Any

from .base import BaseTTSProvider
from .models import TTSAudioResult
from .providers.edge_tts import EdgeTTSProvider

# Registry of available providers
PROVIDER_REGISTRY: dict[str, type[BaseTTSProvider]] = {
    "edge": EdgeTTSProvider,
    # Future providers:
    # "azure": AzureTTSProvider,
    # "minimax": MiniMaxTTSProvider,
    # "elevenlabs": ElevenLabsProvider,
}


class TTSClient:
    """Unified TTS client supporting multiple providers.

    Usage:
        client = TTSClient(provider="edge")
        result = await client.synthesize("Hello, world!")
    """

    def __init__(
        self,
        provider: str = "edge",
        **provider_kwargs: Any,
    ) -> None:
        """Initialize TTS client.

        Args:
            provider: Provider name ("edge", "azure", etc.)
            **provider_kwargs: Provider-specific configuration
        """
        if provider not in PROVIDER_REGISTRY:
            raise ValueError(
                f"Unknown TTS provider: {provider}. "
                f"Available: {list(PROVIDER_REGISTRY.keys())}"
            )

        provider_class = PROVIDER_REGISTRY[provider]
        self._provider: BaseTTSProvider = provider_class(**provider_kwargs)
        self.provider_name = provider

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
            output_path: Optional custom output path

        Returns:
            TTSAudioResult with audio file and sentence boundaries
        """
        return await self._provider.synthesize(text, voice, output_path)

    async def list_voices(self) -> list[dict[str, Any]]:
        """List available voices."""
        return await self._provider.list_voices()

    async def health_check(self) -> bool:
        """Check if TTS service is available."""
        return await self._provider.health_check()


def get_tts_client(
    provider: str = "edge",
    **provider_kwargs: Any,
) -> TTSClient:
    """Get a configured TTS client.

    Args:
        provider: Provider name (default: "edge")
        **provider_kwargs: Provider-specific options

    Returns:
        Configured TTSClient instance
    """
    return TTSClient(provider=provider, **provider_kwargs)
