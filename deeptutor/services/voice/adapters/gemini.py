"""Native Gemini speech synthesis through ``generateContent`` audio output.

Gemini TTS models are not reachable through the OpenAI-compatible
``/audio/speech`` endpoint; they only speak the native ``generateContent``
API with ``responseModalities: ["AUDIO"]`` and a prebuilt voice name.
Protocol: https://ai.google.dev/gemini-api/docs/speech-generation
"""

from __future__ import annotations

import base64
import binascii
from typing import Any
from urllib.parse import urlsplit

import httpx

from deeptutor.services.voice.adapters.openai_compat import _raise_for_provider
from deeptutor.services.voice.audio import pcm_to_wav
from deeptutor.services.voice.base import BaseTTSAdapter, VoiceProviderError
from deeptutor.services.voice.config import TTSConfig

# Gemini always answers with mono PCM16 at this rate, whatever format was asked.
GEMINI_TTS_SAMPLE_RATE = 24000
_GEMINI_API_HOST = "generativelanguage.googleapis.com"


def _model_id(model: str) -> str:
    """Normalize discovery (``models/gemini-...``) and gateway (``google/...``) ids."""
    stripped = (model or "").strip().strip("/")
    for prefix in ("models/", "google/"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
    if not stripped:
        raise VoiceProviderError("Enter a Gemini TTS model such as gemini-2.5-flash-preview-tts.")
    return stripped


def _auth_headers(config: TTSConfig) -> dict[str, str]:
    """Prefer Google's native key header on the Google host, Bearer elsewhere."""
    headers = {"Content-Type": "application/json"}
    if config.api_key and config.api_key != "***":
        if urlsplit(config.base_url).hostname == _GEMINI_API_HOST:
            headers["x-goog-api-key"] = config.api_key
        else:
            headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


class GeminiTTSAdapter(BaseTTSAdapter):
    """Synthesize Google prebuilt voices through native ``generateContent``."""

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        """Return WAV-wrapped (or raw) PCM16 24 kHz audio from the audio modality."""
        model_id = _model_id(config.model)
        voice = (config.voice or "").strip()
        if not voice:
            raise VoiceProviderError(
                "Choose a Google prebuilt voice name such as Kore or Puck for Gemini TTS."
            )
        audio_format = (config.response_format or "wav").strip().lower()
        if audio_format == "pcm16":
            audio_format = "pcm"
        if audio_format not in {"wav", "pcm"}:
            raise VoiceProviderError("Gemini TTS supports WAV or PCM in this adapter.")
        if config.speed is not None:
            raise VoiceProviderError("Gemini TTS has no speed parameter; use voice instructions.")
        # Style control is prompt-level: the documented way to steer delivery is
        # to lead the input text with a natural-language direction.
        spoken = f"{config.instructions}: {text}" if config.instructions else text
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": spoken}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
            },
        }
        base = (config.base_url or "").strip().rstrip("/")
        if not base:
            raise VoiceProviderError("No endpoint URL configured for this provider.")
        # A connection saved with Gemini's OpenAI-compatible URL still reaches
        # the native API once the compatibility suffix is dropped.
        if base.endswith("/openai"):
            base = base[: -len("/openai")]
        url = f"{base}/models/{model_id}:generateContent"
        headers = {**_auth_headers(config), **(config.extra_headers or {})}
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise VoiceProviderError("Gemini TTS connection failed or timed out.") from exc
        _raise_for_provider(response, "Gemini TTS synthesis")
        try:
            candidate = response.json()["candidates"][0]
            encoded_parts = [
                part["inlineData"]["data"]
                for part in candidate["content"]["parts"]
                if isinstance(part.get("inlineData"), dict)
                and isinstance(part["inlineData"].get("data"), str)
            ]
            # Each inlineData value is independently padded base64; decode parts
            # separately instead of concatenating the padded strings.
            audio = b"".join(base64.b64decode(part, validate=True) for part in encoded_parts)
        except (ValueError, KeyError, IndexError, TypeError, binascii.Error) as exc:
            # Provider bodies can echo the prompt; never surface them raw.
            raise VoiceProviderError(
                "Gemini TTS returned no audio; check the model, voice and API key."
            ) from exc
        if not audio:
            raise VoiceProviderError("Gemini TTS returned empty audio.")
        if audio_format == "pcm":
            return audio, f"audio/pcm;rate={GEMINI_TTS_SAMPLE_RATE};channels=1"
        return pcm_to_wav(audio, GEMINI_TTS_SAMPLE_RATE), "audio/wav"
