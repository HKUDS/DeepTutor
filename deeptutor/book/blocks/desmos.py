"""Desmos block – function expressions for the embedded Desmos calculator.

Prompts live in ``deeptutor/book/prompts/{en,zh}/desmos.yaml``.
"""

from __future__ import annotations

from typing import Any

from ..models import BlockType
from ._math_base import GenerationFailure, MathBlockGenerator


class DesmosGenerator(MathBlockGenerator):
    block_type = BlockType.DESMOS
    prompt_name = "desmos"
    expected_key = "expressions"
    max_tokens = 900

    def build_payload(self, data: dict[str, Any], focus: str) -> dict[str, Any]:
        raw = data.get("expressions")
        expressions: list[str] = []
        if isinstance(raw, list):
            for item in raw[:12]:
                if isinstance(item, dict):
                    expr = str(
                        item.get("formula") or item.get("latex") or item.get("expression") or ""
                    ).strip()
                else:
                    expr = str(item).strip()
                if expr:
                    expressions.append(expr[:120])
        if not expressions:
            single = str(data.get("expression") or "").strip()
            if single:
                expressions = [single[:120]]
        if not expressions:
            raise GenerationFailure("LLM did not return any Desmos expressions.")
        return {
            "title": str(data.get("title") or focus).strip()[:200],
            "description": str(data.get("description") or "").strip()[:600],
            "expressions": expressions,
        }


__all__ = ["DesmosGenerator"]
