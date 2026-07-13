"""ToolRegistry.execute: tool-name arg must not collide with a tool's own params.

Regression for the ``read_skill(name=...)`` dispatch bug: the registry takes
the tool *name* as its first parameter, which collided with any tool whose
schema declares a ``name`` argument (read_skill, and potentially MCP tools).
The fix makes the tool-name parameter positional-only.
"""

from __future__ import annotations

import pytest

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.runtime.registry.tool_registry import ToolRegistry


class _NameParamTool(BaseTool):
    """A tool whose own argument is literally called ``name``."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="thing_reader",
            description="reads a thing by name",
            parameters=[ToolParameter(name="name", type="string")],
        )

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(content=f"read:{kwargs.get('name')}")


@pytest.mark.asyncio
async def test_execute_passes_name_argument_without_collision() -> None:
    reg = ToolRegistry()
    reg.register(_NameParamTool())
    # Tool name positional, tool's own ``name`` arg as keyword — must not
    # raise "got multiple values for argument 'name'".
    result = await reg.execute("thing_reader", name="widget")
    assert result.content == "read:widget"


@pytest.mark.asyncio
async def test_execute_forwards_event_sink_alongside_name() -> None:
    reg = ToolRegistry()
    reg.register(_NameParamTool())
    # Mirrors the dispatcher, which always passes event_sink plus tool args.
    result = await reg.execute("thing_reader", event_sink=None, name="gadget")
    assert result.content == "read:gadget"
