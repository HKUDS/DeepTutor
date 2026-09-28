"""Voice services — text-to-speech and speech-to-text.

Public facade used by the API router and the config test runner. Config is
resolved from the model catalog (``services.tts`` / ``services.stt``) exactly
like embedding/LLM, so voice providers are configured through the same
Settings catalog UI.
"""

from __future__ import annotations

from typing import Any

from deeptutor.services.voice.adapters import get_stt_adapter, get_tts_adapter
from deeptutor.services.voice.base import (
    TranscriptCue,
    VoiceProviderError,
    strip_markdown_for_speech,
)
from deeptutor.services.voice.config import STTConfig, TTSConfig


def _math_speak_from_settings() -> bool:
    """Read the Math Speak UI preference; default on if settings are unavailable."""
    try:
        from deeptutor.services.settings.interface_settings import get_ui_settings

        return bool(get_ui_settings().get("voice_math_speak", True))
    except Exception:
        return True


async def synthesize_speech(
    text: str,
    *,
    catalog: dict[str, Any] | None = None,
    voice: str | None = None,
    response_format: str | None = None,
    strip_markdown: bool = True,
    math_speak: bool | None = None,
) -> tuple[bytes, str]:
    """Synthesize ``text`` using the active TTS catalog selection.

    Returns ``(audio_bytes, content_type)``. ``voice`` / ``response_format``
    override the catalog defaults for this call. ``math_speak`` defaults to
    the Settings › Text-to-Speech preference (on).
    """
    from deeptutor.services.config.provider_runtime import resolve_tts_runtime_config

    config = resolve_tts_runtime_config(catalog=catalog)
    if voice:
        config.voice = voice
    if response_format:
        config.response_format = response_format
    speak_math = _math_speak_from_settings() if math_speak is None else math_speak
    prepared = (
        strip_markdown_for_speech(text, max_chars=config.max_input_chars, math_speak=speak_math)
        if strip_markdown
        else text.strip()
    )
    if not prepared:
        raise VoiceProviderError("Nothing to speak after cleaning the text.")
    adapter = get_tts_adapter(config.adapter)
    return await adapter.synthesize(prepared, config)


async def transcribe_audio(
    audio: bytes,
    *,
    catalog: dict[str, Any] | None = None,
    filename: str = "audio.webm",
    content_type: str = "application/octet-stream",
    language: str | None = None,
) -> str:
    """Transcribe ``audio`` using the active STT catalog selection."""
    from deeptutor.services.config.provider_runtime import resolve_stt_runtime_config

    config = resolve_stt_runtime_config(catalog=catalog)
    if language:
        config.language = language
    adapter = get_stt_adapter(config.adapter)
    return await adapter.transcribe(audio, config, filename=filename, content_type=content_type)


async def transcribe_audio_cues(
    audio: bytes,
    *,
    catalog: dict[str, Any] | None = None,
    filename: str = "audio.webm",
    content_type: str = "application/octet-stream",
    language: str | None = None,
) -> list[TranscriptCue]:
    """Transcribe ``audio`` into timed cues using the active STT selection.

    Providers that cannot report timings answer with a single untimed cue, so
    the caller decides how to place it rather than losing the transcript.
    """
    from deeptutor.services.config.provider_runtime import resolve_stt_runtime_config

    config = resolve_stt_runtime_config(catalog=catalog)
    if language:
        config.language = language
    adapter = get_stt_adapter(config.adapter)
    return await adapter.transcribe_cues(
        audio, config, filename=filename, content_type=content_type
    )


__all__ = [
    "TranscriptCue",
    "VoiceProviderError",
    "TTSConfig",
    "STTConfig",
    "synthesize_speech",
    "transcribe_audio",
    "transcribe_audio_cues",
    "strip_markdown_for_speech",
]
