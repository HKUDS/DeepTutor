"""MiMo preset speech through chat completions, with base64 audio output.

Protocol: https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/audio/speech-synthesis-v2.5
"""

from __future__ import annotations

import base64
import binascii

import httpx

from deeptutor.services.voice.adapters.openai_compat import _join_api_path, _raise_for_provider
from deeptutor.services.voice.base import BaseTTSAdapter, VoiceProviderError, build_auth_headers
from deeptutor.services.voice.config import TTSConfig


class MiMoTTSAdapter(BaseTTSAdapter):
    """Synthesize MiMo preset voices using non-streaming chat audio output."""

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        """Return decoded WAV or 24 kHz mono PCM16 audio."""
        if config.model != "mimo-v2.5-tts":
            raise VoiceProviderError("The MiMo preset speech adapter requires mimo-v2.5-tts.")
        audio_format = (config.response_format or "wav").strip().lower()
        if audio_format == "pcm":
            audio_format = "pcm16"
        if audio_format not in {"wav", "pcm16"}:
            raise VoiceProviderError("MiMo TTS supports WAV or PCM16 in this adapter.")
        if config.speed is not None:
            raise VoiceProviderError("Use MiMo voice instructions to control speech speed.")
        messages = []
        if config.instructions:
            messages.append({"role": "user", "content": config.instructions})
        messages.append({"role": "assistant", "content": text})
        payload = {
            "model": config.model,
            "messages": messages,
            "audio": {"format": audio_format, "voice": config.voice or "mimo_default"},
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            **build_auth_headers(config.auth_style, config.api_key),
            **config.extra_headers,
        }
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                response = await client.post(
                    _join_api_path(config.base_url, "chat/completions"),
                    headers=headers,
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise VoiceProviderError("MiMo TTS connection failed or timed out.") from exc
        _raise_for_provider(response, "MiMo TTS synthesis")
        try:
            encoded = response.json()["choices"][0]["message"]["audio"]["data"]
            if not isinstance(encoded, str):
                raise TypeError("Expected base64 audio data.")
            audio = base64.b64decode(encoded, validate=True)
        except (ValueError, KeyError, IndexError, TypeError, binascii.Error) as exc:
            raise VoiceProviderError("MiMo TTS returned malformed base64 audio.") from exc
        if not audio:
            raise VoiceProviderError("MiMo TTS returned empty audio.")
        content_type = "audio/wav" if audio_format == "wav" else "audio/pcm;rate=24000;channels=1"
        return audio, content_type
