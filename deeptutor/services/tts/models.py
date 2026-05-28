"""Data models for TTS service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SentenceBoundary:
    """Sentence time boundary for animation synchronization.

    Attributes:
        text: The sentence text content
        start_ms: Start time in milliseconds
        end_ms: End time in milliseconds
        index: Sentence sequence number
    """

    text: str
    start_ms: int
    end_ms: int
    index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "index": self.index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SentenceBoundary:
        return cls(
            text=data["text"],
            start_ms=data["start_ms"],
            end_ms=data["end_ms"],
            index=data["index"],
        )


@dataclass
class TTSAudioResult:
    """Result of TTS synthesis.

    Attributes:
        audio_path: Path to the generated audio file
        sentence_boundaries: List of sentence time boundaries
        duration_seconds: Total audio duration in seconds
        sample_rate: Audio sample rate (Hz)
        channels: Number of audio channels
    """

    audio_path: str
    sentence_boundaries: list[SentenceBoundary]
    duration_seconds: float
    sample_rate: int = 24000
    channels: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "audio_path": self.audio_path,
            "sentence_boundaries": [b.to_dict() for b in self.sentence_boundaries],
            "duration_seconds": self.duration_seconds,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TTSAudioResult:
        return cls(
            audio_path=data["audio_path"],
            sentence_boundaries=[
                SentenceBoundary.from_dict(b) for b in data["sentence_boundaries"]
            ],
            duration_seconds=data["duration_seconds"],
            sample_rate=data.get("sample_rate", 24000),
            channels=data.get("channels", 1),
        )
