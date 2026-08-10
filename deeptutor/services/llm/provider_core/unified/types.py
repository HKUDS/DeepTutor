"""Provider-neutral types for the three supported LLM wire protocols.

The chat/learning layer only handles these types; no raw SDK object ever
crosses the provider boundary.  Concrete adapters are responsible for the
bidirectional conversion (unified <-> provider wire format) for OpenAI Chat
Completions, OpenAI Responses, and Anthropic Messages.

Legacy callers that still consume :class:`~deeptutor.services.llm.provider_core.base.LLMResponse`
stay compatible through :func:`deeptutor.services.llm.provider_core.unified.common.to_legacy_llm_response`.
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field

from deeptutor.services.llm.exceptions import LLMError

# ---------------------------------------------------------------------------
# Protocol identifiers (kept in sync with services/config model_catalog).
# ---------------------------------------------------------------------------

PROTOCOL_AUTO = "auto"
PROTOCOL_CHAT_COMPLETIONS = "openai_chat_completions"
PROTOCOL_RESPONSES = "openai_responses"
PROTOCOL_ANTHROPIC = "anthropic_messages"

EXPLICIT_PROTOCOLS = (
    PROTOCOL_CHAT_COMPLETIONS,
    PROTOCOL_RESPONSES,
    PROTOCOL_ANTHROPIC,
)
ALL_PROTOCOLS = (PROTOCOL_AUTO,) + EXPLICIT_PROTOCOLS


class UnifiedProtocolError(LLMError):
    """Stable normalized protocol error.

    Raised whenever an explicit protocol path is unsupported or fails and the
    adapter must not silently fall back to another protocol.  ``code`` lets
    callers branch deterministically without string matching.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "protocol_error",
        protocol: str | None = None,
        provider: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, details=details, provider=provider)
        self.code = code
        self.protocol = protocol
        self.status_code = status_code
        self.retryable = status_code in {408, 429} or (
            isinstance(status_code, int) and 500 <= status_code <= 599
        )


# ---------------------------------------------------------------------------
# Typed content blocks
# ---------------------------------------------------------------------------


class UnifiedTextBlock(BaseModel):
    """A plain text content block."""

    type: Literal["text"] = "text"
    text: str = ""


class UnifiedImageBlock(BaseModel):
    """An image content block (data URI or remote URL)."""

    type: Literal["image"] = "image"
    image_url: str = ""
    media_type: str | None = None
    base64: str | None = None


class UnifiedReasoningBlock(BaseModel):
    """Assistant reasoning / thinking content."""

    type: Literal["reasoning"] = "reasoning"
    text: str = ""
    signature: str | None = None


class UnifiedToolCallBlock(BaseModel):
    """An assistant-message request to invoke a tool."""

    type: Literal["tool_call"] = "tool_call"
    id: str = ""
    name: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class UnifiedToolResultBlock(BaseModel):
    """A tool-role message carrying a tool result."""

    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = ""
    output: str = ""
    is_error: bool = False


UnifiedContentBlock = Union[
    UnifiedTextBlock,
    UnifiedImageBlock,
    UnifiedReasoningBlock,
    UnifiedToolCallBlock,
    UnifiedToolResultBlock,
]


class UnifiedMessage(BaseModel):
    """One provider-neutral conversation message."""

    role: Literal["system", "user", "assistant", "tool"]
    content: list[UnifiedContentBlock] = Field(default_factory=list)
    # Responses-specific opaque continuation records. These are transient
    # request material, never persisted conversation metadata.
    responses_continuation_items: list[dict[str, Any]] = Field(default_factory=list)


class UnifiedToolDefinition(BaseModel):
    """A provider-neutral function/tool definition."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    strict: bool = False


class UnifiedToolCall(BaseModel):
    """A completed tool invocation returned by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class UnifiedToolResult(BaseModel):
    """The result bound to a prior tool call id."""

    tool_call_id: str
    output: str = ""
    is_error: bool = False


class UnifiedReasoning(BaseModel):
    """Normalized reasoning/thinking text."""

    text: str = ""
    signature: str | None = None


class UnifiedUsage(BaseModel):
    """Normalized token usage."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0


UnifiedFinishStatus = Literal[
    "stop",
    "length",
    "tool_calls",
    "content_filter",
    "error",
    "cancelled",
]


class UnifiedResponse(BaseModel):
    """A normalized, provider-neutral completion response."""

    id: str | None = None
    content: str | None = None
    tool_calls: list[UnifiedToolCall] = Field(default_factory=list)
    reasoning: UnifiedReasoning | None = None
    usage: UnifiedUsage | None = None
    finish_status: str = "stop"
    model: str | None = None
    provider: str = ""
    # Raw provider lifecycle status where meaningful (e.g. Responses
    # ``in_progress``/``completed``/``failed``/``cancelled``).
    status: str | None = None
    # Persistable metadata (e.g. Responses ``response_id`` for background
    # submit/retrieve/cancel round trips).
    metadata: dict[str, Any] = Field(default_factory=dict)


class UnifiedResponseEvent(BaseModel):
    """A normalized streaming event.

    One flat shape keeps stream parsers deterministic; only the fields
    relevant to ``type`` are populated.
    """

    type: Literal[
        "content_delta",
        "reasoning_delta",
        "tool_call_started",
        "tool_call_arguments_delta",
        "tool_call_completed",
        "usage",
        "finished",
        "error",
    ]
    delta: str = ""
    tool_call_id: str | None = None
    tool_call_name: str | None = None
    arguments_delta: str | None = None
    tool_call: UnifiedToolCall | None = None
    usage: UnifiedUsage | None = None
    finish_status: str | None = None
    status: str | None = None
    model: str | None = None
    error: str | None = None
    error_code: str | None = None


class UnifiedRequest(BaseModel):
    """A provider-neutral completion request."""

    messages: list[UnifiedMessage] = Field(default_factory=list)
    tools: list[UnifiedToolDefinition] | None = None
    model: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.7
    reasoning_effort: str | None = None
    tool_choice: str | dict[str, Any] | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    # OpenAI Responses background-mode flag (submit without waiting).
    background: bool = False


__all__ = [
    "ALL_PROTOCOLS",
    "EXPLICIT_PROTOCOLS",
    "PROTOCOL_ANTHROPIC",
    "PROTOCOL_AUTO",
    "PROTOCOL_CHAT_COMPLETIONS",
    "PROTOCOL_RESPONSES",
    "UnifiedContentBlock",
    "UnifiedFinishStatus",
    "UnifiedImageBlock",
    "UnifiedMessage",
    "UnifiedProtocolError",
    "UnifiedReasoning",
    "UnifiedReasoningBlock",
    "UnifiedRequest",
    "UnifiedResponse",
    "UnifiedResponseEvent",
    "UnifiedTextBlock",
    "UnifiedToolCall",
    "UnifiedToolCallBlock",
    "UnifiedToolDefinition",
    "UnifiedToolResult",
    "UnifiedToolResultBlock",
    "UnifiedUsage",
]
