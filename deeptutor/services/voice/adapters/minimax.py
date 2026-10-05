"""Native MiniMax synchronous speech synthesis with hex-encoded audio."""

from __future__ import annotations

import math
from typing import Any

import httpx

from deeptutor.services.voice.base import BaseTTSAdapter, VoiceProviderError, join_audio_path
from deeptutor.services.voice.config import TTSConfig


class MiniMaxTTSAdapter(BaseTTSAdapter):
    """Synthesize audio through the MiniMax text-to-audio HTTP API."""

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        """Return decoded audio only after successful, complete synthesis."""
        if not config.api_key or config.api_key == "***":
            raise VoiceProviderError("Configure a MiniMax API key for speech synthesis.")
        if not config.voice:
            raise VoiceProviderError("Choose a MiniMax voice ID for speech synthesis.")
        if not text.strip() or len(text) >= 10000:
            raise VoiceProviderError("MiniMax speech input must contain 1 to 9999 characters.")
        fmt = config.response_format or "mp3"
        if fmt not in {"mp3", "wav", "flac", "pcm"}:
            raise VoiceProviderError("MiniMax TTS supports mp3, wav, flac, or pcm.")
        if config.sample_rate not in {8000, 16000, 22050, 24000, 32000, 44100}:
            raise VoiceProviderError("Unsupported MiniMax TTS sample rate.")
        voice: dict[str, Any] = {"voice_id": config.voice}
        if config.speed is not None:
            if not math.isfinite(config.speed) or not 0.5 <= config.speed <= 2:
                raise VoiceProviderError("MiniMax speech speed must be between 0.5 and 2.")
            voice["speed"] = config.speed
        payload = {
            "model": config.model,
            "text": text,
            "stream": False,
            "output_format": "hex",
            "voice_setting": voice,
            "audio_setting": {
                "format": fmt,
                "sample_rate": config.sample_rate,
                "channel": 1,
            },
            "language_boost": config.language or "auto",
        }
        headers = {
            **config.extra_headers,
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        url = join_audio_path(config.base_url, "t2a_v2")
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                raise VoiceProviderError(
                    f"MiniMax TTS request failed (HTTP {response.status_code})."
                )
            result = response.json()
        except httpx.HTTPError as exc:
            raise VoiceProviderError("MiniMax TTS connection failed or timed out.") from exc
        except ValueError as exc:
            raise VoiceProviderError("Malformed MiniMax TTS response.") from exc
        if not isinstance(result, dict):
            raise VoiceProviderError("Malformed MiniMax TTS response.")
        status = result.get("base_resp")
        if not isinstance(status, dict) or status.get("status_code") != 0:
            # Provider bodies can echo private text or credentials; do not expose them.
            raise VoiceProviderError(
                "MiniMax TTS synthesis failed; check the credentials, model and voice."
            )
        data = result.get("data")
        if not isinstance(data, dict) or data.get("status") != 2:
            raise VoiceProviderError("MiniMax TTS synthesis did not complete.")
        encoded = data.get("audio")
        if not isinstance(encoded, str):
            raise VoiceProviderError("Malformed MiniMax TTS audio response.")
        try:
            audio = bytes.fromhex(encoded)
        except ValueError as exc:
            raise VoiceProviderError("Malformed MiniMax TTS audio response.") from exc
        if not audio:
            raise VoiceProviderError("MiniMax TTS returned empty audio.")
        return audio, {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "flac": "audio/flac",
            "pcm": f"audio/pcm;rate={config.sample_rate};channels=1",
        }[fmt]
