from __future__ import annotations

"""Base abstractions for TTS providers."""

from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class BaseTTSProvider(ABC):
    """Abstract TTS provider interface."""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        model: str | None = None,
    ) -> bytes:
        """Synthesize text to MP3 audio bytes.

        Args:
            text: Input text to synthesize.
            voice: Optional provider voice override.
            model: Optional provider model override.

        Returns:
            MP3 audio bytes.
        """

    def detect_voice(self, text: str, voices: dict[str, str]) -> str:
        """Auto-detect language from text and choose a configured voice.

        Args:
            text: Input text.
            voices: Language-to-voice mapping.

        Returns:
            Selected voice name, preferring ``zh`` when CJK ratio exceeds 30%,
            otherwise ``en``.
        """
        if not voices:
            return ""

        cjk_count = 0
        total = 0
        for char in text:
            if char.isspace():
                continue
            total += 1
            code = ord(char)
            if (
                0x4E00 <= code <= 0x9FFF
                or 0x3400 <= code <= 0x4DBF
                or 0x3040 <= code <= 0x30FF
                or 0xAC00 <= code <= 0xD7AF
            ):
                cjk_count += 1

        ratio = (cjk_count / total) if total else 0.0
        lang = "zh" if ratio > 0.30 else "en"

        selected = voices.get(lang) or voices.get("en") or next(iter(voices.values()), "")
        logger.debug("Detected voice language=%s ratio=%.3f selected=%s", lang, ratio, selected)
        return selected


__all__ = ["BaseTTSProvider"]
