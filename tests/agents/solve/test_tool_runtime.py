from __future__ import annotations

from typing import Any

import pytest

from deeptutor.agents.solve.agents.planner_agent import PlannerAgent
from deeptutor.agents.solve.tool_runtime import SolveToolRuntime
from deeptutor.core.tool_protocol import (
    ToolAlias,
    ToolDefinition,
    ToolParameter,
    ToolPromptHints,
    ToolResult,
)


class _FakeTool:
    def __init__(
        self,
        name: str,
        parameters: list[ToolParameter],
        *,
        aliases: list[ToolAlias] | None = None,
    ) -> None:
        self.name = name
        self._parameters = parameters
        self._aliases = aliases or []

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name, description=f"{self.name} tool", parameters=self._parameters
        )

    def get_prompt_hints(self, language: str = "en") -> ToolPromptHints:  # noqa: ARG002
        return ToolPromptHints(
            short_description=f"{self.name} short description",
            when_to_use=f"use {self.name}",
            input_format="Natural language",
            aliases=self._aliases,
        )


class _FakeCoreRegistry:
    def __init__(self, tools: dict[str, _FakeTool]) -> None:
        self._tools = tools
        self.prompt_calls: list[tuple[tuple[str, ...], str, dict[str, Any]]] = []
        self.exec_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, name: str):
        return self._tools.get(name)

    def build_prompt_text(
        self,
        names: list[str],
        format: str = "list",
        language: str = "en",  # noqa: ARG002
        **kwargs: Any,
    ) -> str:
        self.prompt_calls.append((tuple(names), format, kwargs))
        return f"{format}:{','.join(names)}"

    async def execute(self, name: str, **kwargs: Any) -> ToolResult:
        self.exec_calls.append((name, kwargs))
        return ToolResult(content="ok", metadata={})


def test_solve_tool_runtime_builds_prompt_text_via_core_registry() -> None:
    rag_tool = _FakeTool(
        "rag",
        [ToolParameter(name="query", type="string")],
        aliases=[ToolAlias(name="rag_hybrid")],
    )
    registry = _FakeCoreRegistry({"rag": rag_tool, "rag_hybrid": rag_tool})

    runtime = SolveToolRuntime(["rag"], language="en", core_registry=registry)

    description = runtime.build_solver_description()

    assert description == "table:rag\n\naliases:rag"
    assert runtime.tool_names == ["rag"]
    assert "rag_hybrid" in runtime.valid_actions
    assert ("rag",) == registry.prompt_calls[0][0]
    assert [call[1] for call in registry.prompt_calls] == ["table", "aliases"]


@pytest.mark.asyncio
async def test_solve_tool_runtime_executes_via_core_registry_with_context_binding() -> None:
    code_tool = _FakeTool(
        "code_execution",
        [ToolParameter(name="intent", type="string")],
        aliases=[ToolAlias(name="run_code")],
    )
    registry = _FakeCoreRegistry({"code_execution": code_tool, "run_code": code_tool})

    runtime = SolveToolRuntime(["code_execution"], language="en", core_registry=registry)

    result = await runtime.execute("run_code", "check determinant", output_dir="/tmp/solve")

    assert result.content == "ok"
    assert registry.exec_calls == [
        (
            "run_code",
            {
                "intent": "check determinant",
                "timeout": 30,
                "workspace_dir": "/tmp/solve/code_runs",
            },
        )
    ]


@pytest.mark.asyncio
async def test_solve_tool_runtime_passes_event_sink_to_registry() -> None:
    rag_tool = _FakeTool("rag", [ToolParameter(name="query", type="string")])
    registry = _FakeCoreRegistry({"rag": rag_tool})
    runtime = SolveToolRuntime(["rag"], language="en", core_registry=registry)

    async def _sink(
        _event_type: str, _message: str = "", _metadata: dict[str, Any] | None = None
    ) -> None:
        return None

    await runtime.execute("rag", "definition", kb_name="algebra", event_sink=_sink)

    assert registry.exec_calls == [
        (
            "rag",
            {
                "query": "definition",
                "event_sink": _sink,
                "kb_name": "algebra",
            },
        )
    ]


@pytest.mark.asyncio
async def test_solve_tool_runtime_rag_without_kb_returns_graceful_skip() -> None:
    """`rag` invoked without a kb_name must never reach the underlying RAG service.

    The runtime should return a structured ``ToolResult`` describing the skip
    so the ReAct loop can keep going (the LLM sees a clear observation and
    can replan or finalise).
    """
    rag_tool = _FakeTool("rag", [ToolParameter(name="query", type="string")])
    registry = _FakeCoreRegistry({"rag": rag_tool})
    runtime = SolveToolRuntime(["rag"], language="en", core_registry=registry)

    result = await runtime.execute("rag", "definition", kb_name=None)

    assert result.success is False
    assert result.metadata == {"skipped": True, "reason": "no_kb_selected"}
    assert "no knowledge base" in result.content.lower()
    assert registry.exec_calls == [], "rag must NOT be forwarded to the registry"


@pytest.mark.asyncio
async def test_solve_tool_runtime_rag_with_empty_kb_name_returns_graceful_skip() -> None:
    rag_tool = _FakeTool("rag", [ToolParameter(name="query", type="string")])
    registry = _FakeCoreRegistry({"rag": rag_tool})
    runtime = SolveToolRuntime(["rag"], language="en", core_registry=registry)

    result = await runtime.execute("rag", "definition", kb_name="")

    assert result.success is False
    assert result.metadata.get("reason") == "no_kb_selected"
    assert registry.exec_calls == []


@pytest.mark.asyncio
async def test_planner_agent_skips_retrieval_when_rag_not_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_tool = _FakeTool("web_search", [ToolParameter(name="query", type="string")])
    registry = _FakeCoreRegistry({"web_search": web_tool})
    runtime = SolveToolRuntime(["web_search"], language="en", core_registry=registry)
    agent = PlannerAgent(config={}, language="en", tool_runtime=runtime)

    async def _unexpected_queries(*_args, **_kwargs):
        raise AssertionError("query generation should not run when rag is disabled")

    monkeypatch.setattr(agent, "_generate_search_queries", _unexpected_queries)

    result = await agent._pre_retrieve("What is convolution?", "algebra")

    assert result == "(no knowledge base available)"


class TestAuditControlAction:
    def test_audit_in_valid_actions(self) -> None:
        from deeptutor.agents.solve.tool_runtime import SolveToolRuntime

        runtime = SolveToolRuntime([], language="en")
        assert "audit" in runtime.valid_actions

    def test_audit_action_in_en_control_actions(self) -> None:
        from deeptutor.agents.solve.tool_runtime import _CONTROL_ACTIONS

        en_actions = _CONTROL_ACTIONS["en"]
        names = {a["name"] for a in en_actions}
        assert "audit" in names
        audit_action = next(a for a in en_actions if a["name"] == "audit")
        assert "when_to_use" in audit_action
        assert "input_format" in audit_action

    def test_audit_action_in_zh_control_actions(self) -> None:
        from deeptutor.agents.solve.tool_runtime import _CONTROL_ACTIONS

        zh_actions = _CONTROL_ACTIONS["zh"]
        names = {a["name"] for a in zh_actions}
        assert "audit" in names
