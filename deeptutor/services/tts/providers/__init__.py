from __future__ import annotations

"""TTS provider factory."""

from deeptutor.services.tts.base import BaseTTSProvider
from deeptutor.services.tts.config import TTSConfig


def get_tts_provider(config: TTSConfig) -> BaseTTSProvider:
    """Return a concrete TTS provider from config.

    Args:
        config: Runtime TTS config.

    Returns:
        Provider instance implementing ``BaseTTSProvider``.

    Raises:
        ValueError: If provider is unsupported.
    """
    match config.provider:
        case "dashscope":
            from .dashscope import DashScopeTTSProvider

            return DashScopeTTSProvider(config)
        case "openai":
            from .openai_tts import OpenAITTSProvider

            return OpenAITTSProvider(config)
        case "edge":
            from .edge import EdgeTTSProvider

            return EdgeTTSProvider(config)
        case _:
            raise ValueError(
                f"Unknown TTS provider: '{config.provider}'. Supported: dashscope, openai, edge"
            )


__all__ = ["get_tts_provider"]
