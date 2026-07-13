"""OpenAI-compatible HTTP adapters for TTS and STT.

A single pair of adapters covers the whole OpenAI-`/v1/audio/*` cluster —
OpenAI, Groq, SiliconFlow, OpenRouter, Azure OpenAI and local vLLM/LM Studio —
by varying ``base_url`` / ``api_key`` / ``model`` and a couple of config flags
(``auth_style``, ``api_version``, ``request_style``). Genuinely bespoke
providers (DashScope native, ElevenLabs, Gemini, Deepgram) get their own
adapters keyed in ``adapters/__init__.py``.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any

import httpx

from deeptutor.services.voice.base import (
    BaseSTTAdapter,
    BaseTTSAdapter,
    VoiceProviderError,
    VoiceProviderHTTPError,
    build_auth_headers,
    join_audio_path,
)
from deeptutor.services.voice.config import STT_BASE64_JSON, STTConfig, TTSConfig

logger = logging.getLogger(__name__)

_FORMAT_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
    "pcm16": "audio/pcm",
}

_OPENAI_TTS_VOICES = {
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
}


def _provider_error_message(action: str, status_code: int, body: str = "") -> str:
    detail = (body or "").strip()[:400]
    return f"{action} failed with HTTP {status_code}" + (f": {detail}" if detail else ".")


def _raise_for_provider(resp: httpx.Response, action: str) -> None:
    """Surface a provider error with a trimmed body for diagnostics."""
    if resp.status_code < 400:
        return
    body = resp.text or ""
    raise VoiceProviderHTTPError(
        _provider_error_message(action, resp.status_code, body),
        status_code=resp.status_code,
        body=body,
    )


def _join_api_path(base_url: str, suffix: str) -> str:
    """Append a generic API path to ``base_url`` while preserving query strings."""
    base = (base_url or "").strip()
    if not base:
        raise VoiceProviderError("No endpoint URL configured for this provider.")
    head, sep, query = base.partition("?")
    suffix = suffix.strip("/")
    if head.rstrip("/").endswith(f"/{suffix}"):
        return base
    joined = f"{head.rstrip('/')}/{suffix}"
    return f"{joined}?{query}" if sep else joined


def _chat_audio_format(response_format: str) -> str:
    """Map OpenAI speech formats onto OpenRouter chat audio formats."""
    fmt = (response_format or "mp3").strip().lower()
    return "pcm16" if fmt == "pcm" else fmt


def _openrouter_tts_hint(config: TTSConfig) -> str:
    """Return a provider/model-specific hint for opaque OpenRouter TTS errors."""
    model = (config.model or "").lower()
    voice = (config.voice or "").strip()
    if (
        config.provider_name == "openrouter"
        and "gemini" in model
        and "tts" in model
        and voice.lower() in _OPENAI_TTS_VOICES
    ):
        return (
            f" Voice `{voice}` is an OpenAI TTS voice; Gemini TTS expects Google "
            "prebuilt voice names such as `Kore` or `Puck`."
        )
    return ""


class OpenAICompatTTSAdapter(BaseTTSAdapter):
    """POST ``{base}/audio/speech`` with a JSON body, returning raw audio bytes."""

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        if not config.base_url:
            raise VoiceProviderError("No endpoint URL configured for TTS.")
        url = join_audio_path(config.base_url, "audio/speech")
        headers = {
            "Content-Type": "application/json",
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }
        response_format = (config.response_format or "mp3").lower()
        payload: dict[str, Any] = {
            "model": config.model,
            "input": text,
            "response_format": response_format,
        }
        if config.voice:
            payload["voice"] = config.voice
        if config.speed is not None:
            payload["speed"] = config.speed

        logger.debug(
            "TTS synthesize url=%s model=%s voice=%s fmt=%s chars=%d",
            url,
            config.model,
            config.voice,
            response_format,
            len(text),
        )
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise VoiceProviderError(f"TTS request error: {exc}") from exc
        try:
            _raise_for_provider(resp, "TTS synthesis")
        except VoiceProviderHTTPError as exc:
            hint = _openrouter_tts_hint(config)
            if hint:
                raise VoiceProviderError(f"{exc}{hint}") from exc
            raise
        audio = resp.content
        if not audio:
            raise VoiceProviderError("TTS provider returned empty audio.")
        content_type = resp.headers.get("content-type") or _FORMAT_CONTENT_TYPES.get(
            response_format, "application/octet-stream"
        )
        # Some gateways return JSON content-type with audio; trust the format map.
        if "json" in content_type:
            content_type = _FORMAT_CONTENT_TYPES.get(response_format, "audio/mpeg")
        return audio, content_type


class OpenRouterTTSAdapter(BaseTTSAdapter):
    """OpenRouter TTS with fallback for streaming chat-audio models.

    OpenRouter documents both a dedicated ``/audio/speech`` endpoint for TTS
    models and audio output through ``/chat/completions`` for models that expose
    the ``audio`` output modality. Try the dedicated endpoint first, then fall
    back to chat audio for configs pointed at audio-output chat models.
    """

    def __init__(self) -> None:
        self._speech = OpenAICompatTTSAdapter()

    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        try:
            return await self._speech.synthesize(text, config)
        except VoiceProviderHTTPError as exc:
            if exc.status_code in {401, 403, 429}:
                raise
            logger.info(
                "OpenRouter /audio/speech failed with HTTP %s; trying chat audio output.",
                exc.status_code,
            )
            return await self._synthesize_chat_audio(text, config, original_error=exc)

    async def _synthesize_chat_audio(
        self,
        text: str,
        config: TTSConfig,
        *,
        original_error: VoiceProviderHTTPError,
    ) -> tuple[bytes, str]:
        if not config.base_url:
            raise VoiceProviderError("No endpoint URL configured for TTS.")
        url = _join_api_path(config.base_url, "chat/completions")
        headers = {
            "Content-Type": "application/json",
            **build_auth_headers(config.auth_style, config.api_key),
            **(config.extra_headers or {}),
        }
        audio_format = _chat_audio_format(config.response_format)
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": [{"role": "user", "content": text}],
            "modalities": ["text", "audio"],
            "audio": {
                "voice": config.voice or "alloy",
                "format": audio_format,
            },
            "stream": True,
        }

        logger.debug(
            "OpenRouter chat-audio synthesize url=%s model=%s voice=%s fmt=%s chars=%d",
            url,
            config.model,
            config.voice,
            audio_format,
            len(text),
        )
        audio_chunks: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
            _raise_for_provider(resp, "OpenRouter chat audio synthesis")
            for line in (resp.text or "").splitlines():
                self._collect_audio_line(line, audio_chunks)
        except httpx.HTTPError as exc:
            detail = str(exc) or exc.__class__.__name__
            raise VoiceProviderError(f"TTS request error: {detail}") from exc
        except VoiceProviderHTTPError as exc:
            raise VoiceProviderError(
                f"{exc}; original /audio/speech error: {original_error}"
            ) from exc

        if not audio_chunks:
            raise VoiceProviderError(
                "OpenRouter chat audio returned no audio chunks; "
                f"original /audio/speech error: {original_error}"
            )
        try:
            audio = base64.b64decode("".join(audio_chunks))
        except binascii.Error as exc:
            raise VoiceProviderError("OpenRouter chat audio returned invalid base64.") from exc
        if not audio:
            raise VoiceProviderError("OpenRouter chat audio returned empty audio.")
        content_type = _FORMAT_CONTENT_TYPES.get(audio_format, "application/octet-stream")
        return audio, content_type

    @staticmethod
    def _collect_audio_line(line: str, audio_chunks: list[str]) -> None:
        if not line:
            return
        raw = line.strip()
        if not raw.startswith("data:"):
            return
        data = raw[len("data:") :].strip()
        if not data or data == "[DONE]":
            return
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            logger.debug("Ignoring malformed OpenRouter SSE line: %s", data[:160])
            return
        error = chunk.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or "unknown error"
            raise VoiceProviderError(f"OpenRouter chat audio error: {message}")
        choices = chunk.get("choices")
        if not isinstance(choices, list):
            return
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                continue
            audio = delta.get("audio") or {}
            if isinstance(audio, dict) and isinstance(audio.get("data"), str):
                audio_chunks.append(audio["data"])


class OpenAICompatSTTAdapter(BaseSTTAdapter):
    """POST ``{base}/audio/transcriptions``.

    Multipart ``file`` upload by default; OpenRouter uses a base64-JSON body
    (``request_style == "base64_json"``) sharing the same path.
    """

    async def transcribe(
        self,
        audio: bytes,
        config: STTConfig,
        *,
        filename: str = "audio.webm",
        content_type: str = "application/octet-stream",
    ) -> str:
        if not config.base_url:
            raise VoiceProviderError("No endpoint URL configured for STT.")
        if not audio:
            raise VoiceProviderError("No audio data to transcribe.")
        url = join_audio_path(config.base_url, "audio/transcriptions")
        auth = build_auth_headers(config.auth_style, config.api_key)

        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                if config.request_style == STT_BASE64_JSON:
                    resp = await self._post_base64(client, url, auth, audio, filename, config)
                else:
                    resp = await self._post_multipart(
                        client, url, auth, audio, filename, content_type, config
                    )
        except httpx.HTTPError as exc:
            raise VoiceProviderError(f"STT request error: {exc}") from exc
        _raise_for_provider(resp, "Transcription")
        return self._parse_text(resp)

    async def _post_multipart(
        self,
        client: httpx.AsyncClient,
        url: str,
        auth: dict[str, str],
        audio: bytes,
        filename: str,
        content_type: str,
        config: STTConfig,
    ) -> httpx.Response:
        files = {"file": (filename, audio, content_type or "application/octet-stream")}
        data: dict[str, str] = {"model": config.model, "response_format": "json"}
        if config.language:
            data["language"] = config.language
        headers = {**auth, **(config.extra_headers or {})}
        return await client.post(url, headers=headers, files=files, data=data)

    async def _post_base64(
        self,
        client: httpx.AsyncClient,
        url: str,
        auth: dict[str, str],
        audio: bytes,
        filename: str,
        config: STTConfig,
    ) -> httpx.Response:
        fmt = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webm"
        body: dict[str, Any] = {
            "model": config.model,
            "input_audio": {"data": base64.b64encode(audio).decode("ascii"), "format": fmt},
        }
        if config.language:
            body["language"] = config.language
        headers = {"Content-Type": "application/json", **auth, **(config.extra_headers or {})}
        return await client.post(url, headers=headers, json=body)

    @staticmethod
    def _parse_text(resp: httpx.Response) -> str:
        content_type = resp.headers.get("content-type", "")
        if "json" in content_type:
            data = resp.json()
            if isinstance(data, dict):
                text = data.get("text")
                if isinstance(text, str):
                    return text.strip()
                # OpenRouter/chat-style fallback.
                choices = data.get("choices")
                if isinstance(choices, list) and choices:
                    message = (choices[0] or {}).get("message") or {}
                    if isinstance(message.get("content"), str):
                        return message["content"].strip()
            raise VoiceProviderError("Transcription response had no `text` field.")
        # response_format=text returns a bare string.
        return (resp.text or "").strip()


__all__ = ["OpenAICompatTTSAdapter", "OpenRouterTTSAdapter", "OpenAICompatSTTAdapter"]
