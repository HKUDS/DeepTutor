"""Resolved runtime configuration for voice (TTS / STT) providers.

These dataclasses are the read-side adapter between the model catalog
(``services.tts`` / ``services.stt``) and the HTTP adapters. They mirror the
shape of :class:`ResolvedEmbeddingConfig` so a single OpenAI-compatible
adapter can cover OpenAI, Groq, SiliconFlow, OpenRouter, Azure OpenAI and
local vLLM/LM Studio by swapping ``base_url`` + ``api_key`` + ``model``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Auth header styles understood by the OpenAI-compatible adapter.
AUTH_BEARER = "bearer"  # Authorization: Bearer <key>  (OpenAI, Groq, SiliconFlow, OpenRouter)
AUTH_API_KEY_HEADER = "api_key_header"  # api-key: <key>  (Azure OpenAI)
AUTH_TOKEN = "token"  # Authorization: Token <key>  (reserved for Deepgram-style)

# STT request encodings.
STT_MULTIPART = "multipart"  # OpenAI/Groq/SiliconFlow/Azure: file upload + form fields
STT_BASE64_JSON = "base64_json"  # OpenRouter: {model, input_audio:{data,format}}

# OpenAI caps speech input at 4096 chars; keep a safe generic ceiling.
DEFAULT_MAX_INPUT_CHARS = 4096


@dataclass(slots=True)
class TTSConfig:
    """Resolved text-to-speech configuration for one synthesis call."""

    model: str
    provider_name: str = "openai"
    adapter: str = "openai_compat"
    auth_style: str = AUTH_BEARER
    api_key: str = ""
    base_url: str = ""
    api_version: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    voice: str = ""
    response_format: str = "mp3"
    speed: float | None = None
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS
    request_timeout: int = 60


@dataclass(slots=True)
class STTConfig:
    """Resolved speech-to-text configuration for one transcription call."""

    model: str
    provider_name: str = "openai"
    adapter: str = "openai_compat"
    request_style: str = STT_MULTIPART
    auth_style: str = AUTH_BEARER
    api_key: str = ""
    base_url: str = ""
    api_version: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    language: str | None = None
    request_timeout: int = 120


__all__ = [
    "AUTH_BEARER",
    "AUTH_API_KEY_HEADER",
    "AUTH_TOKEN",
    "STT_MULTIPART",
    "STT_BASE64_JSON",
    "DEFAULT_MAX_INPUT_CHARS",
    "TTSConfig",
    "STTConfig",
]
