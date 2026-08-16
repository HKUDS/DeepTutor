from __future__ import annotations

"""OpenAI-compatible HTTP TTS provider."""

import logging

import httpx

from deeptutor.services.tts.base import BaseTTSProvider
from deeptutor.services.tts.config import TTSConfig

logger = logging.getLogger(__name__)


class OpenAITTSProvider(BaseTTSProvider):
    """OpenAI speech synthesis provider."""

    _DEFAULT_MODEL = "tts-1"
    _DEFAULT_VOICES = {"zh": "alloy", "en": "nova"}
    _DEFAULT_BASE_URL = "https://api.openai.com/v1"

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
        """Synthesize text to MP3 bytes via OpenAI-compatible endpoint.

        Args:
            text: Input text.
            voice: Optional voice override.
            model: Optional model override.

        Returns:
            MP3 audio bytes.
        """
        if not self.config.api_key:
            raise ValueError("OpenAI TTS requires an API key.")

        base_url = (self.config.base_url or self._DEFAULT_BASE_URL).rstrip("/")
        url = f"{base_url}/audio/speech"
        selected_model = model or self.config.model or self._DEFAULT_MODEL
        selected_voice = self._resolve_voice(text, voice)

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "model": selected_model,
            "input": text,
            "voice": selected_voice,
            "format": "mp3",
        }

        logger.debug(
            "OpenAI TTS synthesize url=%s model=%s voice=%s", url, selected_model, selected_voice
        )
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"OpenAI TTS request failed: status={response.status_code}, body={response.text[:500]}"
                )
            return response.content


__all__ = ["OpenAITTSProvider"]
