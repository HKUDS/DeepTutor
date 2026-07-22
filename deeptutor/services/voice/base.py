"""Base abstractions and shared helpers for voice providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
import re

from deeptutor.services.voice.config import (
    AUTH_API_KEY_HEADER,
    AUTH_TOKEN,
    STTConfig,
    TTSConfig,
)

logger = logging.getLogger(__name__)


class VoiceProviderError(RuntimeError):
    """Raised when a TTS/STT provider request fails or is misconfigured."""


class VoiceProviderHTTPError(VoiceProviderError):
    """Provider returned a non-2xx HTTP response."""

    def __init__(self, message: str, *, status_code: int, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class BaseTTSAdapter(ABC):
    """Abstract text-to-speech adapter."""

    @abstractmethod
    async def synthesize(self, text: str, config: TTSConfig) -> tuple[bytes, str]:
        """Synthesize ``text`` to audio.

        Returns:
            ``(audio_bytes, content_type)`` — content type is best-effort, e.g.
            ``audio/mpeg`` for mp3.
        """


class BaseSTTAdapter(ABC):
    """Abstract speech-to-text adapter."""

    @abstractmethod
    async def transcribe(
        self,
        audio: bytes,
        config: STTConfig,
        *,
        filename: str = "audio.webm",
        content_type: str = "application/octet-stream",
    ) -> str:
        """Transcribe ``audio`` bytes to text."""


def build_auth_headers(auth_style: str, api_key: str) -> dict[str, str]:
    """Map an ``auth_style`` + key onto request headers.

    ``bearer`` (default) → ``Authorization: Bearer``; ``api_key_header`` →
    ``api-key`` (Azure); ``token`` → ``Authorization: Token`` (Deepgram-style).
    """
    if not api_key:
        return {}
    if auth_style == AUTH_API_KEY_HEADER:
        return {"api-key": api_key}
    if auth_style == AUTH_TOKEN:
        return {"Authorization": f"Token {api_key}"}
    return {"Authorization": f"Bearer {api_key}"}


def join_audio_path(base_url: str, suffix: str) -> str:
    """Append an OpenAI audio path to a configured base URL.

    ``base_url`` is the API base (e.g. ``https://api.openai.com/v1``). If the
    admin already pasted a full ``.../audio/...`` endpoint (some gateways /
    Azure deployments), it is used verbatim and the query string preserved.
    """
    base = (base_url or "").strip()
    if not base:
        raise VoiceProviderError("No endpoint URL configured for this provider.")
    head, sep, query = base.partition("?")
    if "/audio/" in head:
        return base
    joined = f"{head.rstrip('/')}/{suffix.lstrip('/')}"
    return f"{joined}?{query}" if sep else joined


# Content blocks that should never be spoken aloud, stripped before synthesis.
_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_LIST_MARKER = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3}|~~)(\S.*?\S|\S)\1")
_HTML_TAG = re.compile(r"<[^>]+>")
_TABLE_PIPE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def strip_markdown_for_speech(text: str, *, max_chars: int = 0) -> str:
    """Reduce Markdown to plain prose suitable for TTS.

    Drops code blocks and tables outright (they read terribly), unwraps links
    and emphasis to their visible text, and removes structural markers. This is
    deliberately lossy — the goal is natural speech, not faithful rendering.
    """
    if not text:
        return ""
    out = _FENCED_CODE.sub(" ", text)
    out = _TABLE_PIPE.sub(" ", out)
    out = _IMAGE.sub(" ", out)
    out = _LINK.sub(r"\1", out)
    out = _INLINE_CODE.sub(r"\1", out)
    out = _HEADING.sub("", out)
    out = _BLOCKQUOTE.sub("", out)
    out = _LIST_MARKER.sub("", out)
    out = _EMPHASIS.sub(r"\2", out)
    out = _HTML_TAG.sub("", out)
    out = _WHITESPACE.sub(" ", out)
    out = _BLANK_LINES.sub("\n\n", out).strip()
    if max_chars and len(out) > max_chars:
        # Cut on a sentence/space boundary near the cap so speech ends cleanly.
        window = out[:max_chars]
        cut = max(window.rfind("."), window.rfind("\n"), window.rfind(" "))
        out = window[: cut + 1].strip() if cut > max_chars // 2 else window.strip()
    return out


__all__ = [
    "VoiceProviderError",
    "VoiceProviderHTTPError",
    "BaseTTSAdapter",
    "BaseSTTAdapter",
    "build_auth_headers",
    "join_audio_path",
    "strip_markdown_for_speech",
]
