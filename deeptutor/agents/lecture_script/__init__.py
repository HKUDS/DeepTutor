"""Lecture Script Generator

Converts MathNet problem steps into lecture scripts for video generation.
"""

from .generator import LectureScriptGenerator
from .llm_optimizer import LectureScriptOptimizer, optimize_script_with_llm
from .models import LectureScript, LectureSegment, ScriptTiming
from .visual_elements import (
    VisualElements,
    GeometryObject,
    extract_visual_elements,
    extract_geometry_objects,
    extract_formulas,
)

__all__ = [
    "LectureScriptGenerator",
    "LectureScriptOptimizer",
    "LectureScript",
    "LectureSegment",
    "ScriptTiming",
    "VisualElements",
    "GeometryObject",
    "extract_visual_elements",
    "extract_geometry_objects",
    "extract_formulas",
    "optimize_script_with_llm",
]
