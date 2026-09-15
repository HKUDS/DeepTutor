"""Chart block – categorical series for an ECharts bar/line/pie chart.

Prompts live in ``deeptutor/book/prompts/{en,zh}/chart.yaml``.

The LLM returns structured ``categories`` + ``series`` (name/type/data) rather
than a raw ECharts option, so the payload stays plain JSON (no functions / no
``echarts.graphic`` gradient objects) and the renderer builds the option.
"""

from __future__ import annotations

import math
from typing import Any

from ..models import BlockType
from ._math_base import GenerationFailure, MathBlockGenerator


def _numbers(value: Any) -> list[float | None]:
    if not isinstance(value, list):
        return []
    out: list[float | None] = []
    for item in value[:60]:
        if isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item):
            out.append(float(item))
        else:
            out.append(None)
    return out


class ChartGenerator(MathBlockGenerator):
    block_type = BlockType.CHART
    prompt_name = "chart"
    expected_key = "series"
    max_tokens = 1400

    def build_payload(self, data: dict[str, Any], focus: str) -> dict[str, Any]:
        raw_series = data.get("series")
        series: list[dict[str, Any]] = []
        if isinstance(raw_series, list):
            for item in raw_series[:6]:
                if not isinstance(item, dict):
                    continue
                data_arr = _numbers(item.get("data"))
                if not data_arr:
                    continue
                chart_type = str(item.get("type") or "bar").strip()
                if chart_type not in ("bar", "line", "pie"):
                    chart_type = "bar"
                series.append(
                    {
                        "name": str(item.get("name") or "series").strip()[:60],
                        "type": chart_type,
                        "data": data_arr,
                    }
                )
        if not series:
            raise GenerationFailure("LLM did not return any chart series.")
        categories: list[str] = []
        raw_cats = data.get("categories")
        if isinstance(raw_cats, list):
            categories = [str(c).strip()[:40] for c in raw_cats[:60] if str(c).strip()]
        return {
            "title": str(data.get("title") or focus).strip()[:200],
            "description": str(data.get("description") or "").strip()[:600],
            "categories": categories,
            "series": series,
        }


__all__ = ["ChartGenerator"]
