"""Formula block – KaTeX-rendered formulas with captions.

Prompts live in ``deeptutor/book/prompts/{en,zh}/formula.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType
from ._math_base import GenerationFailure, MathBlockGenerator


class FormulaGenerator(MathBlockGenerator):
    block_type = BlockType.FORMULA
    prompt_name = "formula"
    expected_key = "formulas"
    max_tokens = 1000

    def build_payload(self, data: dict[str, Any], focus: str) -> dict[str, Any]:
        raw = data.get("formulas")
        formulas: list[dict[str, str]] = []
        if isinstance(raw, list):
            for item in raw[:12]:
                if not isinstance(item, dict):
                    continue
                tex = str(item.get("tex") or item.get("latex") or item.get("formula") or "").strip()
                if not tex:
                    continue
                formulas.append(
                    {
                        "tex": tex[:300],
                        "caption": str(item.get("caption") or item.get("note") or "").strip()[:400],
                    }
                )
        if not formulas:
            raise GenerationFailure("LLM did not return any formulas.")
        return {
            "title": str(data.get("title") or focus).strip()[:200],
            "description": str(data.get("description") or "").strip()[:600],
            "formulas": formulas,
        }


__all__ = ["FormulaGenerator"]
