"""GeoGebra block – material id or initial commands for the embedded applet.

Prompts live in ``deeptutor/book/prompts/{en,zh}/geogebra.yaml``.

GeoGebra material ids are opaque (e.g. ``kungfmxk``). The LLM should return a real
id only if it knows one; otherwise it leaves ``materialId`` empty and the renderer
falls back to the online calculator. ``commands`` are shown in a collapsible panel.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType
from ._math_base import MathBlockGenerator


class GeoGebraGenerator(MathBlockGenerator):
    block_type = BlockType.GEOGEBRA
    prompt_name = "geogebra"
    expected_key = "materialId"
    max_tokens = 700

    def build_payload(self, data: dict[str, Any], focus: str) -> dict[str, Any]:
        material_id = str(data.get("materialId") or data.get("material_id") or "").strip()[:40]
        commands: list[str] = []
        raw_cmds = data.get("commands")
        if isinstance(raw_cmds, list):
            commands = [str(c).strip()[:200] for c in raw_cmds[:20] if str(c).strip()]
        # No hard fail: empty materialId -> calculator mode is a valid fallback.
        return {
            "title": str(data.get("title") or focus).strip()[:200],
            "description": str(data.get("description") or "").strip()[:600],
            "materialId": material_id,
            "commands": commands,
        }


__all__ = ["GeoGebraGenerator"]
