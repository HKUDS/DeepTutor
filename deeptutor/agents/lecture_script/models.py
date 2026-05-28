"""Data models for lecture script generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScriptTiming:
    """Timing information for a script segment."""

    estimated_duration_seconds: float
    min_duration: float = 1.0  # Minimum 1 second per segment
    max_duration: float = 60.0  # Maximum 60 seconds per segment

    def clamp(self, duration: float) -> float:
        """Clamp duration to valid range."""
        return max(self.min_duration, min(duration, self.max_duration))


@dataclass
class LectureSegment:
    """A single segment of the lecture (corresponds to one step).

    Attributes:
        step_index: The step number in the solution
        title: Segment title
        script: The spoken narration text
        visual_description: Description of what to show visually
        timing: Timing information
        key_points: Key points to emphasize
        start_time_ms: Start time in milliseconds (set after TTS)
        end_time_ms: End time in milliseconds (set after TTS)
    """

    step_index: int
    title: str
    script: str
    visual_description: str
    timing: ScriptTiming = field(default_factory=ScriptTiming)
    key_points: list[str] = field(default_factory=list)
    start_time_ms: int = 0
    end_time_ms: int = 0

    @property
    def duration_ms(self) -> int:
        """Get segment duration in milliseconds."""
        return self.end_time_ms - self.start_time_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "title": self.title,
            "script": self.script,
            "visual_description": self.visual_description,
            "estimated_duration_seconds": self.timing.estimated_duration_seconds,
            "key_points": self.key_points,
            "start_time_ms": self.start_time_ms,
            "end_time_ms": self.end_time_ms,
        }


@dataclass
class LectureScript:
    """Complete lecture script for a problem.

    Attributes:
        problem_id: The MathNet problem ID
        intro: Opening segment introducing the problem
        segments: List of step-by-step segments
        conclusion: Closing segment with summary
        total_duration_seconds: Total estimated duration
    """

    problem_id: str
    intro: LectureSegment
    segments: list[LectureSegment]
    conclusion: LectureSegment
    total_duration_seconds: float = 0.0

    def __post_init__(self):
        """Calculate total duration from segments."""
        if not self.total_duration_seconds:
            self.total_duration_seconds = (
                self.intro.timing.estimated_duration_seconds
                + sum(s.timing.estimated_duration_seconds for s in self.segments)
                + self.conclusion.timing.estimated_duration_seconds
            )

    def get_full_script(self) -> str:
        """Get the complete narration script as a single string."""
        parts = [self.intro.script]
        parts.extend(s.script for s in self.segments)
        parts.append(self.conclusion.script)
        return "\n\n".join(parts)

    def apply_timing_from_tts(
        self, sentence_boundaries: list[dict[str, Any]]
    ) -> None:
        """Apply actual TTS timing to segments.

        Args:
            sentence_boundaries: List of sentence boundaries from TTS
        """
        # Simple mapping: distribute TTS boundaries across segments
        # This is a basic implementation - can be enhanced with better alignment

        boundary_idx = 0
        all_segments = [self.intro] + self.segments + [self.conclusion]

        for segment in all_segments:
            segment_script = segment.script
            segment_sentences = self._split_into_sentences(segment_script)

            if boundary_idx < len(sentence_boundaries):
                start_ms = sentence_boundaries[boundary_idx]["start_ms"]

                # Advance boundary_idx by number of sentences in this segment
                boundary_idx += len(segment_sentences)

                if boundary_idx <= len(sentence_boundaries):
                    end_ms = sentence_boundaries[boundary_idx - 1]["end_ms"]
                else:
                    end_ms = sentence_boundaries[-1]["end_ms"]

                segment.start_time_ms = start_ms
                segment.end_time_ms = end_ms

    @staticmethod
    def _split_into_sentences(text: str) -> list[str]:
        """Split text into sentences."""
        import re

        pattern = r"[^。！？.!?]+[。！？.!?]+"
        sentences = re.findall(pattern, text)
        return [s.strip() for s in sentences if s.strip()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "intro": self.intro.to_dict(),
            "segments": [s.to_dict() for s in self.segments],
            "conclusion": self.conclusion.to_dict(),
            "total_duration_seconds": self.total_duration_seconds,
        }
