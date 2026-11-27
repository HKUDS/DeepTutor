"""Native Mistral Voxtral voice adapters.

Mistral TTS is close to the OpenAI speech shape (``/v1/audio/speech``) but uses
``voice_id`` and has no ``speed``/``instructions`` fields. STT sends the audio
as multipart data directly to ``/v1/audio/transcriptions``; it does not create
persistent uploaded files or signed URLs.
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

_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
    "flac": "audio/flac",
    "opus": "audio/opus",
}


def _join(base_url: str, suffix: str) -> str:
    """Append an API path to a configured base, preserving query strings."""
    base = (base_url or "").strip()
    if not base:
        raise VoiceProviderError("No endpoint URL configured for Mistral voice.")
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


class MistralTTSAdapter(BaseTTSAdapter):
    """POST ``{base}/audio/speech`` with Mistral's ``input``/``voice_id`` shape."""

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        fmt = (config.response_format or "mp3").strip().lower()
        payload: dict[str, Any] = {
            "model": config.model,
            "input": text,
            "response_format": fmt,
        }
        if config.voice:
            payload["voice_id"] = config.voice

        headers = {
            "Content-Type": "application/json",
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }
        url = _join(config.base_url, "audio/speech")
        logger.debug("Mistral TTS url=%s model=%s fmt=%s", url, config.model, fmt)
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise VoiceProviderError(f"Mistral TTS request error: {exc}") from exc
        _raise_for_provider(resp, "Mistral TTS synthesis")
        if not resp.content:
            raise VoiceProviderError("Mistral TTS returned empty audio.")
        return resp.content, _CONTENT_TYPES.get(fmt, "audio/mpeg")


class MistralSTTAdapter(BaseSTTAdapter):
    """Transcribe multipart audio without creating a persistent remote file."""

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
        base = (config.base_url or "").rstrip("/")
        if not base:
            raise VoiceProviderError("No endpoint URL configured for Mistral STT.")
        headers = {
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }
        model = config.model or "voxtral-mini-latest"

        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                form = [
                    ("file", (filename, audio, content_type)),
                    ("model", (None, model)),
                ]
                if config.language:
                    form.append(("language", (None, config.language)))
                transcription = await client.post(
                    _join(base, "audio/transcriptions"),
                    headers=headers,
                    files=form,
                )
        except httpx.HTTPError as exc:
            raise VoiceProviderError(f"Mistral STT request error: {exc}") from exc
        _raise_for_provider(transcription, "Mistral STT transcription")

        try:
            body = transcription.json()
        except ValueError as exc:
            raise VoiceProviderError("Mistral STT returned invalid JSON.") from exc
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str) or not text.strip():
            segments = body.get("segments") if isinstance(body, dict) else None
            if isinstance(segments, list):
                text = " ".join(
                    str(segment.get("text") or "").strip()
                    for segment in segments
                    if isinstance(segment, dict)
                ).strip()
        if not isinstance(text, str) or not text.strip():
            raise VoiceProviderError("Mistral STT returned no transcript.")
        return text.strip()


__all__ = ["MistralSTTAdapter", "MistralTTSAdapter"]
