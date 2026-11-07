from __future__ import annotations

from typing import Any


def build_tool_registry(tools: list[str] | None, language: str):
    from src.agents.solve.tools import ToolRegistry

    if tools is None:
        return ToolRegistry.create_default(language=language)
    return ToolRegistry.create_from_names(tools, language=language)


async def run_solver_pipeline(
    question: str,
    workspace: str,
    language: str = "en",
    tools: list[str] | None = None,
    model: str | None = None,
    image_url: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    from src.agents.solve import MainSolver

    registry = build_tool_registry(tools, language)
    has_rag = registry.get("rag_search") is not None

    solver = MainSolver(
        kb_name="" if not has_rag else "__benchmark__",
        language=language,
        output_base_dir=workspace,
        tool_registry=registry,
        disable_memory=True,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    await solver.ainit()
    return await solver.solve(question, image_url=image_url)
