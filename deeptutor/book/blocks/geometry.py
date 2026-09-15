"""Geometry block – JSXGraph element descriptors.

Prompts live in ``deeptutor/book/prompts/{en,zh}/geometry.yaml``.

The LLM produces ``elements`` as a list of ``{type, params, attrs}`` (plain JSON;
``params`` are coordinate arrays / point coords). The renderer iterates these and
calls ``board.create`` best-effort, so dirty elements are tolerated.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType
from ._math_base import MathBlockGenerator


def _bounding_box(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) < 4:
        return [-5, 5, 5, -5]
    return [float(value[i]) if isinstance(value[i], (int, float)) else 0 for i in range(4)]


class GeometryGenerator(MathBlockGenerator):
    block_type = BlockType.GEOMETRY
    prompt_name = "geometry"
    expected_key = "elements"
    max_tokens = 1400

    def build_payload(self, data: dict[str, Any], focus: str) -> dict[str, Any]:
        raw = data.get("elements")
        elements: list[dict[str, Any]] = []
        if isinstance(raw, list):
            for item in raw[:32]:
                if not isinstance(item, dict):
                    continue
                el_type = str(item.get("type") or "").strip()
                if not el_type:
                    continue
                entry: dict[str, Any] = {"type": el_type[:40]}
                if isinstance(item.get("params"), list):
                    entry["params"] = item["params"]
                if isinstance(item.get("attrs"), dict):
                    entry["attrs"] = item["attrs"]
                elements.append(entry)
        # No hard fail: empty elements -> renderer draws the default SSS triangle.
        return {
            "title": str(data.get("title") or focus).strip()[:200],
            "hint": str(data.get("hint") or "").strip()[:600],
            "boundingBox": _bounding_box(data.get("boundingBox") or data.get("boundingbox")),
            "axis": bool(data.get("axis", True)),
            "grid": bool(data.get("grid", True)),
            "elements": elements,
        }


__all__ = ["GeometryGenerator"]
