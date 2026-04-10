"""Tests for built-in tools and unified tool registry behavior."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.runtime.registry.tool_registry import ToolRegistry
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.tools.builtin import (
    BrainstormTool,
    CodeExecutionTool,
    GeoGebraAnalysisTool,
    PaperSearchToolWrapper,
    RAGTool,
    ReasonTool,
    WebSearchTool,
)


def _install_module(monkeypatch: pytest.MonkeyPatch, fullname: str, **attrs: Any) -> types.ModuleType:
    """Install a fake module (and missing parent packages) into sys.modules."""
    __import__("deeptutor")
    parts = fullname.split(".")
    for idx in range(1, len(parts)):
        pkg_name = ".".join(parts[:idx])
        if pkg_name not in sys.modules:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = []  # type: ignore[attr-defined]
            monkeypatch.setitem(sys.modules, pkg_name, pkg)
            if idx > 1:
                parent = sys.modules[".".join(parts[: idx - 1])]
                setattr(parent, parts[idx - 1], pkg)

    module = types.ModuleType(fullname)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, fullname, module)
    if len(parts) > 1:
        parent = sys.modules[".".join(parts[:-1])]
        setattr(parent, parts[-1], module)
    return module


@pytest.mark.asyncio
async def test_brainstorm_tool_passes_llm_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_brainstorm(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"answer": "## 1. Test idea\n- Rationale: worth exploring"}

    _install_module(monkeypatch, "deeptutor.tools.brainstorm", brainstorm=fake_brainstorm)

    result = await BrainstormTool().execute(
        topic="agent-native tutoring",
        context="Focus on fast ideation",
        model="gpt-test",
    )

    assert "Test idea" in result.content
    assert captured["topic"] == "agent-native tutoring"
    assert captured["context"] == "Focus on fast ideation"
    assert captured["model"] == "gpt-test"


@pytest.mark.asyncio
async def test_rag_tool_forwards_query_and_extra_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_rag_search(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"answer": "grounded answer", "provider": "fake"}

    _install_module(monkeypatch, "deeptutor.tools.rag_tool", rag_search=fake_rag_search)

    result = await RAGTool().execute(
        query="what is a tensor",
        kb_name="demo-kb",
        only_need_context=True,
    )

    assert result.content == "grounded answer"
    assert captured["query"] == "what is a tensor"
    assert captured["kb_name"] == "demo-kb"
    assert captured["only_need_context"] is True


@pytest.mark.asyncio
async def test_web_search_tool_wraps_sync_function(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_web_search(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "answer": "web summary",
            "citations": [{"url": "https://example.com", "title": "Example"}],
        }

    _install_module(monkeypatch, "deeptutor.tools.web_search", web_search=fake_web_search)

    result = await WebSearchTool().execute(query="latest benchmark", output_dir="/tmp/out")

    assert result.content == "web summary"
    assert captured["query"] == "latest benchmark"
    assert captured["output_dir"] == "/tmp/out"
    assert result.sources[0]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_code_execution_tool_uses_direct_code_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_code(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["code"] == "print(2 + 2)"
        assert kwargs["timeout"] == 5
        assert kwargs["workspace_dir"] == "/tmp/code-runs"
        return {
            "stdout": "4\n",
            "stderr": "",
            "exit_code": 0,
            "artifacts": [],
            "artifact_paths": [],
        }

    _install_module(monkeypatch, "deeptutor.tools.code_executor", run_code=fake_run_code)

    tool = CodeExecutionTool()
    result = await tool.execute(code="print(2 + 2)", timeout=5, workspace_dir="/tmp/code-runs")

    assert result.success is True
    assert result.content == "4"
    assert result.metadata["code"] == "print(2 + 2)"


@pytest.mark.asyncio
async def test_code_execution_tool_generates_code_from_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: dict[str, Any] = {}

    async def fake_run_code(**kwargs: Any) -> dict[str, Any]:
        executed.update(kwargs)
        return {
            "stdout": "42\n",
            "stderr": "",
            "exit_code": 0,
            "artifacts": ["plot.png"],
            "artifact_paths": ["/tmp/plot.png"],
        }

    _install_module(monkeypatch, "deeptutor.tools.code_executor", run_code=fake_run_code)
    tool = CodeExecutionTool()

    async def fake_generate_code(intent: str) -> str:
        assert intent == "compute the answer"
        return "print(42)"

    monkeypatch.setattr(tool, "_generate_code", fake_generate_code)

    result = await tool.execute(intent="compute the answer")

    assert executed["code"] == "print(42)"
    assert "42" in result.content
    assert result.sources[0]["file"] == "plot.png"


def test_code_execution_tool_strips_markdown_fences() -> None:
    fenced = "```python\nprint(7)\n```"
    assert CodeExecutionTool._strip_markdown_fences(fenced) == "print(7)"


@pytest.mark.asyncio
async def test_reason_tool_passes_llm_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_reason(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"answer": "reasoned"}

    _install_module(monkeypatch, "deeptutor.tools.reason", reason=fake_reason)

    result = await ReasonTool().execute(
        query="derive the formula",
        context="prior work",
        api_key="key",
        base_url="url",
        model="gpt-test",
    )

    assert result.content == "reasoned"
    assert captured["model"] == "gpt-test"
    assert captured["context"] == "prior work"


@pytest.mark.asyncio
async def test_paper_search_tool_formats_papers(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeArxivSearchTool:
        async def search_papers(self, **kwargs: Any) -> list[dict[str, Any]]:
            assert kwargs["query"] == "graph learning"
            return [
                {
                    "title": "Graph Learning 101",
                    "year": 2024,
                    "authors": ["Ada", "Grace"],
                    "arxiv_id": "1234.5678",
                    "url": "https://arxiv.org/abs/1234.5678",
                    "abstract": "A compact abstract.",
                }
            ]

    _install_module(
        monkeypatch,
        "deeptutor.tools.paper_search_tool",
        ArxivSearchTool=FakeArxivSearchTool,
    )

    result = await PaperSearchToolWrapper().execute(query="graph learning")

    assert "Graph Learning 101" in result.content
    assert result.sources[0]["provider"] == "arxiv"


@pytest.mark.asyncio
async def test_geogebra_analysis_tool_handles_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeVisionSolverAgent:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def process(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["question_text"] == "analyze this"
            return {
                "has_image": True,
                "final_ggb_commands": ["A=(0,0)", "B=(1,0)"],
                "analysis_output": {
                    "constraints": ["AB = 1"],
                    "geometric_relations": [{"description": "A and B are on x-axis"}],
                },
                "bbox_output": {"elements": [1, 2]},
                "reflection_output": {"issues_found": []},
            }

        def format_ggb_block(self, commands: list[str]) -> str:
            return "\n".join(commands)

    _install_module(
        monkeypatch,
        "deeptutor.agents.vision_solver.vision_solver_agent",
        VisionSolverAgent=FakeVisionSolverAgent,
    )
    _install_module(
        monkeypatch,
        "deeptutor.services.llm.config",
        get_llm_config=lambda: SimpleNamespace(api_key="k", base_url="u"),
    )

    result = await GeoGebraAnalysisTool().execute(
        question="analyze this",
        image_base64="ZmFrZQ==",
        language="en",
    )

    assert result.success is True
    assert "A=(0,0)" in result.content
    assert result.metadata["commands_count"] == 2


@pytest.mark.asyncio
async def test_tool_registry_resolves_aliases_and_argument_mapping() -> None:
    class DummyTool(BaseTool):
        def __init__(self, tool_name: str) -> None:
            self._tool_name = tool_name
            self.calls: list[dict[str, Any]] = []

        def get_definition(self) -> ToolDefinition:
            param_name = {
                "rag": "query",
                "code_execution": "intent",
            }[self._tool_name]
            return ToolDefinition(
                name=self._tool_name,
                description="dummy",
                parameters=[ToolParameter(name=param_name, type="string")],
            )

        async def execute(self, **kwargs: Any) -> ToolResult:
            self.calls.append(kwargs)
            return ToolResult(content=self._tool_name)

    rag = DummyTool("rag")
    code = DummyTool("code_execution")

    registry = ToolRegistry()
    registry.register(rag)
    registry.register(code)

    rag_result = await registry.execute("rag_hybrid", query="find this")
    code_result = await registry.execute("run_code", query="compute this")

    assert rag_result.content == "rag"
    assert rag.calls[0]["query"] == "find this"
    assert code.calls[0]["intent"] == "compute this"
