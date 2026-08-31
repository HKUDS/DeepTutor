from __future__ import annotations

"""DashScope CosyVoice TTS provider."""

import asyncio
from importlib import import_module
import logging
import os

from deeptutor.services.tts.base import BaseTTSProvider
from deeptutor.services.tts.config import TTSConfig

logger = logging.getLogger(__name__)


class DashScopeTTSProvider(BaseTTSProvider):
    """DashScope TTS provider using CosyVoice models."""

    _DEFAULT_MODEL = "cosyvoice-v3-flash"
    _DEFAULT_VOICES = {"zh": "longxiaochun_v3", "en": "loongbella_v3"}

    def __init__(self, config: TTSConfig) -> None:
        """Initialize provider with runtime config.

        Args:
            config: Resolved TTS configuration.
        """
        self.config = config

    def _resolve_api_key(self) -> str:
        """Resolve DashScope API key with provider-specific precedence."""
        return os.environ.get("DASHSCOPE_API_KEY") or self.config.api_key

    def _resolve_voice(self, text: str, voice: str | None) -> str:
        """Resolve final voice name for synthesis."""
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
        """Synthesize text with DashScope and return MP3 bytes.

        Args:
            text: Text to synthesize.
            voice: Optional voice override.
            model: Optional model override.

        Returns:
            MP3 audio bytes.
        """
        api_key = self._resolve_api_key()
        if not api_key:
            raise ValueError("DashScope TTS requires an API key.")

        selected_voice = self._resolve_voice(text, voice)
        selected_model = model or self.config.model or self._DEFAULT_MODEL

        def _synthesize_sync() -> bytes:
            dashscope = import_module("dashscope")
            tts_module = import_module("dashscope.audio.tts_v2")
            speech_synthesizer = getattr(tts_module, "SpeechSynthesizer")

            setattr(dashscope, "api_key", api_key)
            synthesizer = speech_synthesizer(model=selected_model, voice=selected_voice)
            result = synthesizer.call(text)
            if isinstance(result, bytes):
                return result
            raise RuntimeError("DashScope TTS returned non-bytes audio payload.")

        loop = asyncio.get_event_loop()
        logger.debug("DashScope TTS synthesize model=%s voice=%s", selected_model, selected_voice)
        return await loop.run_in_executor(None, _synthesize_sync)


__all__ = ["DashScopeTTSProvider"]
