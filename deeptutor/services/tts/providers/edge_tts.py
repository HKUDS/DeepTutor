"""Edge TTS provider implementation.

Uses Microsoft Edge's online TTS service (free, no API key required).
Supports Chinese and multiple other languages.
"""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Any

import edge_tts

from ..base import BaseTTSProvider
from ..models import SentenceBoundary, TTSAudioResult

logger = logging.getLogger(__name__)


class EdgeTTSProvider(BaseTTSProvider):
    """Microsoft Edge TTS provider.

    Free TTS service using Edge browser's online voices.
    No API key required. Requires internet connection.

    Usage:
        provider = EdgeTTSProvider()
        result = await provider.synthesize("Hello, world!")
    """

    # Common Chinese voices
    VOICE_ZH_XIAOXIAO = "zh-CN-XiaoxiaoNeural"  # 晓晓，女声，标准
    VOICE_ZH_XIAOYI = "zh-CN-XiaoyiNeural"  # 晓伊，女声
    VOICE_ZH_YUNJIAN = "zh-CN-YunjianNeural"  # 云健，男声
    VOICE_ZH_YUNXI = "zh-CN-YunxiNeural"  # 云希，男声

    # Common English voices
    VOICE_EN_ARIA = "en-US-AriaNeural"
    VOICE_EN_GUY = "en-US-GuyNeural"
    VOICE_EN_JENNY = "en-US-JennyNeural"

    DEFAULT_VOICE_ZH = VOICE_ZH_XIAOXIAO
    DEFAULT_VOICE_EN = VOICE_EN_ARIA

    def __init__(
        self,
        default_voice: str | None = None,
        output_dir: str | None = None,
    ) -> None:
        """Initialize Edge TTS provider.

        Args:
            default_voice: Default voice to use
            output_dir: Directory for output files (default: tempfile)
        """
        super().__init__(default_voice=default_voice, output_dir=output_dir)
        self.default_voice = default_voice or self.DEFAULT_VOICE_ZH
        self.output_dir = Path(output_dir) if output_dir else Path(tempfile.gettempdir())
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _detect_language(self, text: str) -> str:
        """Detect if text is primarily Chinese or English."""
        # Simple heuristic: count Chinese characters
        chinese_chars = len(re.findall(r"[一-鿿]", text))
        total_chars = len(re.sub(r"\s", "", text))
        if total_chars == 0:
            return "en"
        return "zh" if chinese_chars / total_chars > 0.3 else "en"

    def _select_voice(self, text: str, voice: str | None = None) -> str:
        """Select appropriate voice for text."""
        if voice:
            return voice
        lang = self._detect_language(text)
        return self.DEFAULT_VOICE_ZH if lang == "zh" else self.DEFAULT_VOICE_EN

    def _split_into_sentences(self, text: str) -> list[str]:
        """Split text into sentences for boundary detection.

        Handles Chinese and English punctuation.
        """
        # Match sentence-ending punctuation
        pattern = r"[^。！？.!?]+[。！？.!?]+"
        sentences = re.findall(pattern, text)

        # Clean up and filter empty sentences
        result = []
        for s in sentences:
            s = s.strip()
            if s and len(s) > 3:  # Filter very short fragments
                result.append(s)

        # If no sentences found, treat whole text as one
        if not result and text.strip():
            result = [text.strip()]

        return result

    def _estimate_duration(self, text: str) -> float:
        """Estimate audio duration based on text length.

        Rough estimate: ~4 Chinese chars/second, ~10 English chars/second
        """
        chinese_chars = len(re.findall(r"[一-鿿]", text))
        english_chars = len(re.findall(r"[a-zA-Z]", text))

        chinese_duration = chinese_chars / 4.0
        english_duration = english_chars / 10.0

        return max(chinese_duration + english_duration, 1.0)  # At least 1 second

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        output_path: str | None = None,
    ) -> TTSAudioResult:
        """Synthesize text to speech using Edge TTS with REAL SentenceBoundary timing.

        Uses edge-tts stream() instead of save() to capture Azure's real per-sentence
        timing data (offset/duration in 100ns ticks). This is the KEY fix for subtitle-
        voice alignment — previously we used char-count estimates.

        Args:
            text: Text to synthesize
            voice: Voice identifier (e.g., "zh-CN-XiaoxiaoNeural")
            output_path: Custom output path (default: auto-generated)

        Returns:
            TTSAudioResult with audio file and REAL sentence boundaries
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        selected_voice = self._select_voice(text, voice)

        # Generate output filename
        if output_path:
            audio_path = Path(output_path)
        else:
            import uuid

            audio_path = self.output_dir / f"tts_{uuid.uuid4().hex[:8]}.mp3"

        # Use stream() to capture real SentenceBoundary + audio events
        # edge-tts v7.2.8 defaults to boundary="SentenceBoundary"
        communicate = edge_tts.Communicate(text, selected_voice)

        audio_chunks: list[bytes] = []
        real_boundaries: list[dict[str, Any]] = []

        async for chunk in communicate.stream():
            if chunk["type"] == "SentenceBoundary":
                # Azure TTS provides offset/duration in 100-nanosecond ticks
                # Convert to milliseconds: divide by 10000
                start_ms = chunk["offset"] // 10000
                end_ms = (chunk["offset"] + chunk["duration"]) // 10000
                real_boundaries.append({
                    "text": chunk["text"],
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                })
            elif chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])

        # Write audio file from collected chunks
        if audio_chunks:
            audio_path.write_bytes(b"".join(audio_chunks))
        else:
            # Fallback: use edge-tts save() if stream() yielded no audio
            communicate = edge_tts.Communicate(text, selected_voice)
            await communicate.save(str(audio_path))

        # Build SentenceBoundary objects
        boundaries: list[SentenceBoundary] = []
        total_duration = 0.0

        if real_boundaries:
            # Use REAL Azure TTS timing
            for idx, sb in enumerate(real_boundaries):
                boundaries.append(SentenceBoundary(
                    text=sb["text"],
                    start_ms=sb["start_ms"],
                    end_ms=sb["end_ms"],
                    index=idx,
                ))
            total_duration = real_boundaries[-1]["end_ms"] / 1000.0
            logger.info(
                f"Edge TTS stream: {len(real_boundaries)} real SentenceBoundaries, "
                f"total={total_duration:.1f}s"
            )
        else:
            # FALLBACK: char-count estimation (same as before)
            sentences = self._split_into_sentences(text)
            current_ms = 0

            for idx, sentence in enumerate(sentences):
                duration_ms = int(self._estimate_duration(sentence) * 1000)

                boundary = SentenceBoundary(
                    text=sentence,
                    start_ms=current_ms,
                    end_ms=current_ms + duration_ms,
                    index=idx,
                )
                boundaries.append(boundary)
                current_ms += duration_ms

            total_duration = current_ms / 1000.0
            logger.info(
                f"Edge TTS fallback (no SentenceBoundary events): "
                f"{len(sentences)} estimated boundaries, total={total_duration:.1f}s"
            )

        return TTSAudioResult(
            audio_path=str(audio_path),
            sentence_boundaries=boundaries,
            duration_seconds=total_duration,
            sample_rate=24000,
            channels=1,
        )

    async def list_voices(self) -> list[dict[str, Any]]:
        """List available Edge TTS voices.

        Returns a curated list of commonly used voices.
        """
        # Return curated list of voices
        # Full list can be obtained with: edge-tts --list-voices
        return [
            {
                "id": self.VOICE_ZH_XIAOXIAO,
                "name": "晓晓",
                "language": "zh-CN",
                "gender": "Female",
                "description": "中文女声，标准",
            },
            {
                "id": self.VOICE_ZH_XIAOYI,
                "name": "晓伊",
                "language": "zh-CN",
                "gender": "Female",
                "description": "中文女声",
            },
            {
                "id": self.VOICE_ZH_YUNJIAN,
                "name": "云健",
                "language": "zh-CN",
                "gender": "Male",
                "description": "中文男声",
            },
            {
                "id": self.VOICE_ZH_YUNXI,
                "name": "云希",
                "language": "zh-CN",
                "gender": "Male",
                "description": "中文男声，年轻",
            },
            {
                "id": self.VOICE_EN_ARIA,
                "name": "Aria",
                "language": "en-US",
                "gender": "Female",
                "description": "English (US), Female",
            },
            {
                "id": self.VOICE_EN_GUY,
                "name": "Guy",
                "language": "en-US",
                "gender": "Male",
                "description": "English (US), Male",
            },
            {
                "id": self.VOICE_EN_JENNY,
                "name": "Jenny",
                "language": "en-US",
                "gender": "Female",
                "description": "English (US), Female",
            },
        ]
