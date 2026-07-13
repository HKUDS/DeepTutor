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
    """One parameter in a tool's function-calling schema.

    Attributes:
        items: Inner JSON Schema for ``type="array"`` parameters. **Required
            by strict providers (Gemini, Anthropic)** even though OpenAI
            silently tolerates its absence — leaving it out causes a 400
            on Gemini. When ``type="array"`` and ``items`` is None we fall
            back to ``{"type": "string"}`` so callers that just declare
            ``ToolParameter(type="array")`` still emit a valid schema.
    """

    name: str
    type: str  # "string" | "integer" | "boolean" | "number" | "array" | "object"
    description: str = ""
    required: bool = True
    default: Any = None
    enum: list[str] | None = None
    items: dict[str, Any] | None = None

    def to_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema property dict."""
        schema: dict[str, Any] = {"type": self.type, "description": self.description}
        if self.enum:
            schema["enum"] = self.enum
        if self.type == "array":
            schema["items"] = self.items if self.items is not None else {"type": "string"}
        return schema


@dataclass
class ToolDefinition:
    """
    Metadata that describes a tool to the LLM (OpenAI function-calling format).

    ``raw_parameters`` carries a complete JSON-Schema object verbatim and
    takes precedence over ``parameters`` — used by adapter tools (e.g. MCP)
    whose upstream schemas are arbitrary JSON Schema that would be lossy to
    re-encode as :class:`ToolParameter` rows.
    """

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)
    raw_parameters: dict[str, Any] | None = None

    def to_openai_schema(self) -> dict[str, Any]:
        """Build an OpenAI-compatible function tool schema."""
        if self.raw_parameters is not None:
            schema = dict(self.raw_parameters)
            schema.setdefault("type", "object")
            schema.setdefault("properties", {})
            return {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": schema,
                },
            }
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
    """Standardised return value from a tool execution.

    Attributes:
        content: Text returned to the LLM as the ``role=tool`` message body.
        sources: Citation rows surfaced through ``stream.sources``.
        metadata: Free-form payload — also used by the chat pipeline as a
            channel for structured UI hints (e.g. ``ask_user.options``
            for chip rendering).
        success: ``False`` marks an explicit failure path; the LLM is
            still allowed to read ``content`` (often an error message).
        terminate_turn: When ``True`` the agentic chat loop must stop
            iterating after dispatching this tool, treating the tool's
            output as the assistant's final turn artefact. Reserved for
            tools that genuinely end the turn (no future planned use —
            ``ask_user`` now uses ``pause_for_user`` instead).
        pause_for_user: When set, the chat loop **pauses** after this
            tool call, emits a ``pending_user_input`` event with this
            payload, awaits the user's reply via the runtime's reply
            queue, then resumes the same loop iteration with the
            reply substituted into the tool message body. Used by
            ``ask_user`` to keep the turn alive across the user's
            answer instead of ending and starting a new turn.
            Shape mirrors ``AskUserPayload.to_dict()``.
    """

    content: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    terminate_turn: bool = False
    pause_for_user: dict[str, Any] | None = None

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

    ``deferred`` marks a tool for progressive disclosure: its schema is NOT
    included in the initial per-turn tool list. Instead, the system prompt
    carries a one-line entry per deferred tool and the model loads full
    schemas on demand via the ``load_tools`` tool. Source-agnostic — any
    registered tool may set it (all MCP tools do).

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

    deferred: bool = False

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
