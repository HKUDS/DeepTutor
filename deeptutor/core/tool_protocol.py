"""
Tool Protocol
=============

Base classes for the Tool layer (Level 1).
Every tool — built-in or contributed via plugin — implements ``BaseTool``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolParameter:
    """One parameter in a tool's function-calling schema."""

    name: str
    type: str  # "string" | "integer" | "boolean" | "number" | "array" | "object"
    description: str = ""
    required: bool = True
    default: Any = None
    enum: list[str] | None = None

    def to_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema property dict."""
        schema: dict[str, Any] = {"type": self.type, "description": self.description}
        if self.enum:
            schema["enum"] = self.enum
        return schema


@dataclass
class ToolDefinition:
    """
    Metadata that describes a tool to the LLM (OpenAI function-calling format).
    """

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)

    def to_openai_schema(self) -> dict[str, Any]:
        """Build an OpenAI-compatible function tool schema."""
        properties = {}
        required = []
        for p in self.parameters:
            properties[p.name] = p.to_schema()
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


@dataclass
class ToolAlias:
    """Alternative tool name or sub-mode exposed in prompts."""

    name: str
    description: str = ""
    input_format: str = ""
    when_to_use: str = ""
    phase: str = ""


@dataclass
class ToolPromptHints:
    """Prompt-level guidance describing when and how to use a tool."""

    short_description: str = ""
    when_to_use: str = ""
    input_format: str = ""
    guideline: str = ""
    note: str = ""
    phase: str = ""
    aliases: list[ToolAlias] = field(default_factory=list)


@dataclass
class ToolResult:
    """Standardised return value from a tool execution."""

    content: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True

    def __str__(self) -> str:
        return self.content


class ToolEventSink(Protocol):
    """Async callback used by tools to stream internal progress."""

    async def __call__(
        self,
        event_type: str,
        message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None: ...


class BaseTool(ABC):
    """
    Abstract base for all tools.

    Subclasses must implement ``get_definition`` and ``execute``.

    Example::

        class MyTool(BaseTool):
            def get_definition(self) -> ToolDefinition:
                return ToolDefinition(
                    name="my_tool",
                    description="Does something useful.",
                    parameters=[ToolParameter(name="query", type="string")],
                )

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(content="result")
    """

    @abstractmethod
    def get_definition(self) -> ToolDefinition:
        """Return the tool's metadata & parameter schema."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool with the given keyword arguments."""
        ...

    def get_prompt_hints(self, language: str = "en") -> ToolPromptHints:
        """Return prompt-level metadata for dynamic prompt assembly."""
        definition = self.get_definition()
        return ToolPromptHints(
            short_description=definition.description,
        )

    @property
    def name(self) -> str:
        return self.get_definition().name
