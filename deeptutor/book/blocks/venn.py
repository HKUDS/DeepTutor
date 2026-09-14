"""Venn diagram block – 2~3 set labels for the SVG renderer.

Prompts live in ``deeptutor/book/prompts/{en,zh}/venn.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType
from ._math_base import GenerationFailure, MathBlockGenerator


class VennGenerator(MathBlockGenerator):
    block_type = BlockType.VENN
    prompt_name = "venn"
    expected_key = "sets"
    max_tokens = 700

    def build_payload(self, data: dict[str, Any], focus: str) -> dict[str, Any]:
        raw = data.get("sets")
        sets: list[dict[str, str]] = []
        if isinstance(raw, list):
            for item in raw[:3]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or item.get("name") or "").strip()
                if label:
                    sets.append({"label": label[:40]})
        if not sets:
            raise GenerationFailure("LLM did not return any Venn set labels.")
        return {
            "title": str(data.get("title") or focus).strip()[:200],
            "description": str(data.get("description") or "").strip()[:600],
            "sets": sets,
            "center": str(data.get("center") or "").strip()[:60],
            "caption": str(data.get("caption") or "").strip()[:600],
        }


__all__ = ["VennGenerator"]
