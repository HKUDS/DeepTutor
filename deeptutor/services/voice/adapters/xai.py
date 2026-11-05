"""Native xAI Grok Voice adapters.

xAI exposes two dedicated audio endpoints that are not OpenAI-compatible:

* ``POST {base}/tts`` with ``{text, voice_id, language, output_format, speed}``
  returns raw audio bytes.
* ``POST {base}/stt`` accepts multipart ``{model, file, language, format}`` and
  returns ``{text, duration, words}``.

They therefore get their own adapters instead of the shared
``openai_compat`` pair.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from deeptutor.services.voice.base import (
    BaseSTTAdapter,
    BaseTTSAdapter,
    VoiceProviderError,
    VoiceProviderHTTPError,
    build_auth_headers,
)
from deeptutor.services.voice.config import STTConfig, TTSConfig

logger = logging.getLogger(__name__)

_FORMATS: dict[str, tuple[str, str]] = {
    "mp3": ("mp3", "audio/mpeg"),
    "wav": ("wav", "audio/wav"),
    "pcm": ("pcm", "audio/pcm"),
}


def _join(base_url: str, suffix: str) -> str:
    """Append an API path to a configured base, preserving query strings."""
    base = (base_url or "").strip()
    if not base:
        raise VoiceProviderError("No endpoint URL configured for xAI voice.")
    head, sep, query = base.partition("?")
    suffix = suffix.strip("/")
    if head.rstrip("/").endswith(f"/{suffix}"):
        return base
    joined = f"{head.rstrip('/')}/{suffix}"
    return f"{joined}?{query}" if sep else joined


def _raise_for_provider(resp: httpx.Response, action: str) -> None:
    if resp.status_code < 400:
        return
    body = resp.text or ""
    raise VoiceProviderHTTPError(
        f"{action} failed with HTTP {resp.status_code}.",
        status_code=resp.status_code,
        body=body,
    )


class XaiTTSAdapter(BaseTTSAdapter):
    """POST ``{base}/tts`` and return the raw audio response."""

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        fmt = (config.response_format or "mp3").strip().lower()
        if fmt not in _FORMATS:
            raise VoiceProviderError("xAI TTS supports mp3, wav or pcm output.")
        codec, content_type = _FORMATS[fmt]
        output_format: dict[str, Any] = {"codec": codec, "sample_rate": 24000}
        if codec == "mp3":
            output_format["bit_rate"] = 128000

        payload: dict[str, Any] = {
            "text": text,
            "voice_id": config.voice or "eve",
            "language": config.language or "auto",
            "output_format": output_format,
        }
        if config.speed is not None:
            payload["speed"] = max(0.7, min(1.5, float(config.speed)))

        headers = {
            "Content-Type": "application/json",
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }
        url = _join(config.base_url, "tts")
        logger.debug("xAI TTS url=%s voice=%s fmt=%s", url, payload["voice_id"], codec)
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise VoiceProviderError(f"xAI TTS request error: {exc}") from exc
        _raise_for_provider(resp, "xAI TTS synthesis")
        if not resp.content:
            raise VoiceProviderError("xAI TTS returned empty audio.")
        return resp.content, content_type


class XaiSTTAdapter(BaseSTTAdapter):
    """POST ``{base}/stt`` with the file part last, as xAI requires."""

    async def transcribe(
        self,
        audio: bytes,
        config: STTConfig,
        *,
        filename: str = "audio.webm",
        content_type: str = "application/octet-stream",
    ) -> str:
        if not audio:
            raise VoiceProviderError("No audio data to transcribe.")
        model = config.model or "grok-voice-transcribe-2.0"
        multipart: list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]] = [
            ("model", (None, model)),
            ("format", (None, "true")),
        ]
        if config.language:
            multipart.append(("language", (None, config.language)))
        multipart.append(("file", (filename, audio, content_type)))

        headers = {
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }
        url = _join(config.base_url, "stt")
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(url, headers=headers, files=multipart)
        except httpx.HTTPError as exc:
            raise VoiceProviderError(f"xAI STT request error: {exc}") from exc
        _raise_for_provider(resp, "xAI STT transcription")
        try:
            body = resp.json()
        except ValueError as exc:
            raise VoiceProviderError("xAI STT returned invalid JSON.") from exc
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise VoiceProviderError("xAI STT returned no transcript.")
        return text.strip()


__all__ = ["XaiSTTAdapter", "XaiTTSAdapter"]
