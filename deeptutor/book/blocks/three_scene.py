"""Three-scene block – title/hint for the hardcoded Three.js cube renderer.

Prompts live in ``deeptutor/book/prompts/{en,zh}/three_scene.yaml``.

The 3D scene itself is fixed (a translucent cube with edges and vertices) and
portable; the LLM only supplies a title and an instructional hint.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType
from ._math_base import GenerationFailure, MathBlockGenerator


class ThreeSceneGenerator(MathBlockGenerator):
    block_type = BlockType.THREE_SCENE
    prompt_name = "three_scene"
    expected_key = "title"
    max_tokens = 600

    def build_payload(self, data: dict[str, Any], focus: str) -> dict[str, Any]:
        title = str(data.get("title") or focus).strip()
        if not title:
            raise GenerationFailure("LLM did not return a 3D scene title.")
        return {
            "title": title[:200],
            "hint": str(data.get("hint") or "").strip()[:600],
            "description": str(data.get("description") or "").strip()[:600],
        }


__all__ = ["ThreeSceneGenerator"]
