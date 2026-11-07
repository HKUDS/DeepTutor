#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Thin mimic entrypoint.

The orchestration now lives in src/agents/question/coordinator.py.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Callable

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.agents.question import AgentCoordinator
from src.services.llm.config import get_llm_config

WsCallback = Callable[[str, dict[str, Any]], Any]


async def mimic_exam_questions(
    pdf_path: str | None = None,
    paper_dir: str | None = None,
    kb_name: str | None = None,
    output_dir: str | None = None,
    max_questions: int | None = None,
    ws_callback: WsCallback | None = None,
) -> dict[str, Any]:
    """
    Backward utility wrapper that delegates to the new coordinator pipeline.
    """
    if not pdf_path and not paper_dir:
        return {"success": False, "error": "Either pdf_path or paper_dir must be provided."}
    if pdf_path and paper_dir:
        return {"success": False, "error": "pdf_path and paper_dir cannot be used together."}

    llm_config = get_llm_config()
    coordinator = AgentCoordinator(
        api_key=llm_config.api_key,
        base_url=llm_config.base_url,
        api_version=getattr(llm_config, "api_version", None),
        kb_name=kb_name,
        output_dir=output_dir,
    )

    if ws_callback:
        async def _forward(data: dict[str, Any]) -> None:
            event_type = data.get("type", "progress")
            await ws_callback(event_type, data)
        coordinator.set_ws_callback(_forward)

    if pdf_path:
        summary = await coordinator.generate_from_exam(
            exam_paper_path=pdf_path,
            max_questions=max_questions or 10,
            paper_mode="upload",
        )
    else:
        summary = await coordinator.generate_from_exam(
            exam_paper_path=paper_dir or "",
            max_questions=max_questions or 10,
            paper_mode="parsed",
        )

    return {
        "success": bool(summary.get("success", False)),
        "summary": summary,
        "generated_questions": [r.get("qa_pair", {}) for r in summary.get("results", [])],
        "failed_questions": [r for r in summary.get("results", []) if not r.get("success")],
        "total_reference_questions": summary.get("template_count", 0),
    }
