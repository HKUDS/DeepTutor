"""Lecture Script Generator

Converts MathNet problem steps into lecture scripts for video generation.
"""

from .generator import LectureScriptGenerator
from .models import LectureScript, LectureSegment, ScriptTiming

__all__ = [
    "LectureScriptGenerator",
    "LectureScript",
    "LectureSegment",
    "ScriptTiming",
]
