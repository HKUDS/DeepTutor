"""Provider-neutral unified LLM protocol layer (MOD-02).

Brings together the provider-neutral types, deterministic per-protocol
converters, a transport interface (real + fake), and the
:class:`UnifiedLLMAdapter` that honors explicit ``api_protocol`` with strict
no-fallback semantics.
"""

from .adapter import UnifiedLLMAdapter, build_unified_adapter, parse_unified_response
from .anthropic import (
    ANTHROPIC_MESSAGES_PATH,
    AnthropicStreamParser,
    build_anthropic_request,
    parse_anthropic_response,
)
from .chat_completions import (
    CHAT_COMPLETIONS_PATH,
    ChatCompletionsStreamParser,
    build_chat_completions_request,
    parse_chat_completions_response,
)
from .responses import (
    RESPONSES_PATH,
    ResponsesStreamParser,
    build_responses_request,
    parse_responses_response,
    responses_cancel_path,
    responses_retrieve_path,
)
from .transport import FakeTransport, HttpTransport, LLMTransport, TransportError
from .types import (
    ALL_PROTOCOLS,
    EXPLICIT_PROTOCOLS,
    PROTOCOL_ANTHROPIC,
    PROTOCOL_AUTO,
    PROTOCOL_CHAT_COMPLETIONS,
    PROTOCOL_RESPONSES,
    UnifiedImageBlock,
    UnifiedMessage,
    UnifiedProtocolError,
    UnifiedReasoning,
    UnifiedReasoningBlock,
    UnifiedRequest,
    UnifiedResponse,
    UnifiedResponseEvent,
    UnifiedTextBlock,
    UnifiedToolCall,
    UnifiedToolCallBlock,
    UnifiedToolDefinition,
    UnifiedToolResult,
    UnifiedToolResultBlock,
    UnifiedUsage,
)

__all__ = [
    "ALL_PROTOCOLS",
    "ANTHROPIC_MESSAGES_PATH",
    "AnthropicStreamParser",
    "CHAT_COMPLETIONS_PATH",
    "ChatCompletionsStreamParser",
    "EXPLICIT_PROTOCOLS",
    "FakeTransport",
    "HttpTransport",
    "LLMTransport",
    "PROTOCOL_ANTHROPIC",
    "PROTOCOL_AUTO",
    "PROTOCOL_CHAT_COMPLETIONS",
    "PROTOCOL_RESPONSES",
    "RESPONSES_PATH",
    "ResponsesStreamParser",
    "TransportError",
    "UnifiedImageBlock",
    "UnifiedLLMAdapter",
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
    "build_anthropic_request",
    "build_chat_completions_request",
    "build_responses_request",
    "build_unified_adapter",
    "parse_anthropic_response",
    "parse_chat_completions_response",
    "parse_responses_response",
    "parse_unified_response",
    "responses_cancel_path",
    "responses_retrieve_path",
]
