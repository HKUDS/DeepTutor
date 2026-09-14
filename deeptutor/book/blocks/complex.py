"""Complex plane block – initial real/imaginary components.

Prompts live in ``deeptutor/book/prompts/{en,zh}/complex.yaml``.
"""

from __future__ import annotations

import math
from typing import Any

from ..models import BlockType
from ._math_base import GenerationFailure, MathBlockGenerator


def _finite(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


class ComplexGenerator(MathBlockGenerator):
    block_type = BlockType.COMPLEX
    prompt_name = "complex"
    expected_key = "re"
    max_tokens = 600

    def build_payload(self, data: dict[str, Any], focus: str) -> dict[str, Any]:
        re = _finite(data.get("re"), 3.0)
        im = _finite(data.get("im"), 2.0)
        # Clamp into the slider range used by the renderer (-5..5).
        re = max(-5.0, min(5.0, re))
        im = max(-5.0, min(5.0, im))
        if not isinstance(data.get("re"), (int, float)) and not isinstance(data.get("im"), (int, float)):
            raise GenerationFailure("LLM did not return complex components.")
        return {
            "title": str(data.get("title") or focus).strip()[:200],
            "description": str(data.get("description") or "").strip()[:600],
            "re": re,
            "im": im,
        }


__all__ = ["ComplexGenerator"]
