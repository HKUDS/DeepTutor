from __future__ import annotations

"""Edge TTS provider implementation."""

from importlib import import_module
import logging

from deeptutor.services.tts.base import BaseTTSProvider
from deeptutor.services.tts.config import TTSConfig

logger = logging.getLogger(__name__)


class EdgeTTSProvider(BaseTTSProvider):
    """Microsoft Edge TTS provider."""

    _DEFAULT_VOICES = {"zh": "zh-CN-XiaoxiaoNeural", "en": "en-US-JennyNeural"}

    def __init__(self, config: TTSConfig) -> None:
        """Initialize provider.

        Args:
            config: Resolved TTS configuration.
        """
        self.config = config

    def _resolve_voice(self, text: str, voice: str | None) -> str:
        """Resolve voice used for synthesis."""
        if voice:
            return voice
        if self.config.voice:
            return self.config.voice
        merged = dict(self._DEFAULT_VOICES)
        merged.update(self.config.voices)
        return self.detect_voice(text, merged)

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        model: str | None = None,
    ) -> bytes:
        """Synthesize text to MP3 bytes via Edge TTS.

        Args:
            text: Input text.
            voice: Optional voice override.
            model: Unused for edge-tts, accepted for API compatibility.

        Returns:
            MP3 audio bytes.
        """
        del model
        selected_voice = self._resolve_voice(text, voice)
        logger.debug("Edge TTS synthesize voice=%s", selected_voice)

        edge_tts_module = import_module("edge_tts")
        communicate = edge_tts_module.Communicate(text=text, voice=selected_voice)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                data = chunk.get("data")
                if isinstance(data, bytes):
                    chunks.append(data)
        return b"".join(chunks)


__all__ = ["EdgeTTSProvider"]
