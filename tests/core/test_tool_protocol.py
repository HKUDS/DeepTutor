"""Tests for tool protocol classes."""

from __future__ import annotations

import pytest

from deeptutor.core.tool_protocol import (
    BaseTool,
    ToolAlias,
    ToolDefinition,
    ToolParameter,
    ToolPromptHints,
    ToolResult,
)


def test_tool_parameter_to_schema_basic() -> None:
    """Basic parameter schema output."""
    param = ToolParameter(name="query", type="string", description="The search query")
    schema = param.to_schema()
    assert schema == {"type": "string", "description": "The search query"}


def test_tool_parameter_to_schema_with_enum() -> None:
    """Parameter schema correctly includes enums if present."""
    param = ToolParameter(
        name="mode",
        type="string",
        description="Search mode",
        enum=["fast", "deep"],
    )
    schema = param.to_schema()
    assert schema["enum"] == ["fast", "deep"]


def test_tool_definition_to_openai_schema() -> None:
    """ToolDefinition outputs correct OpenAI function schema format."""
    definition = ToolDefinition(
        name="calculator",
        description="Math calculator",
        parameters=[
            ToolParameter(name="a", type="number", required=True),
            ToolParameter(name="b", type="number", required=False),
        ],
    )
    
    schema = definition.to_openai_schema()
    
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "calculator"
    assert schema["function"]["description"] == "Math calculator"
    assert schema["function"]["parameters"]["type"] == "object"
    
    props = schema["function"]["parameters"]["properties"]
    assert "a" in props
    assert "b" in props
    assert props["a"]["type"] == "number"
    
    req = schema["function"]["parameters"]["required"]
    assert "a" in req
    assert "b" not in req


def test_tool_result_str_and_defaults() -> None:
    """ToolResult stringifies to content and defaults safely."""
    result = ToolResult(content="Found it")
    assert str(result) == "Found it"
    assert result.success is True
    assert result.sources == []
    assert result.metadata == {}


def test_tool_alias() -> None:
    """ToolAlias stores fields correctly."""
    alias = ToolAlias(
        name="quick_search",
        description="Fast search",
        input_format="plain string",
        when_to_use="Always",
        phase="information gathering",
    )
    assert alias.name == "quick_search"
    assert alias.phase == "information gathering"


def test_tool_prompt_hints() -> None:
    """ToolPromptHints mutable defaults verification."""
    hints1 = ToolPromptHints()
    hints2 = ToolPromptHints()
    
    hints1.aliases.append(ToolAlias(name="a1"))
    assert len(hints2.aliases) == 0


def test_base_tool_implementation() -> None:
    """BaseTool requires get_definition and execute; provides default name and hints."""
    
    class DummyTool(BaseTool):
        def get_definition(self) -> ToolDefinition:
            return ToolDefinition(name="dummy", description="A dummy tool")

        async def execute(self, **kwargs) -> ToolResult:
            return ToolResult(content="Success")

    tool = DummyTool()
    assert tool.name == "dummy"
    
    hints = tool.get_prompt_hints()
    assert hints.short_description == "A dummy tool"
    assert len(hints.aliases) == 0

def test_base_tool_is_abstract() -> None:
    """BaseTool missing abstract methods raises TypeError."""
    
    class IncompleteTool(BaseTool):
        pass
        
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        IncompleteTool()  # type: ignore
