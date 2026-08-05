"""Provider-neutral type and normalization contract tests."""

from __future__ import annotations

from deeptutor.services.llm.exceptions import LLMError
from deeptutor.services.llm.provider_core.unified.common import (
    normalize_messages,
    normalize_tools,
)
from deeptutor.services.llm.provider_core.unified.types import (
    ALL_PROTOCOLS,
    EXPLICIT_PROTOCOLS,
    PROTOCOL_ANTHROPIC,
    PROTOCOL_AUTO,
    PROTOCOL_CHAT_COMPLETIONS,
    PROTOCOL_RESPONSES,
    UnifiedImageBlock,
    UnifiedMessage,
    UnifiedProtocolError,
    UnifiedReasoningBlock,
    UnifiedTextBlock,
    UnifiedToolCallBlock,
    UnifiedToolResultBlock,
)


class TestProtocolConstants:
    def test_all_protocols(self) -> None:
        assert ALL_PROTOCOLS == (
            PROTOCOL_AUTO,
            PROTOCOL_CHAT_COMPLETIONS,
            PROTOCOL_RESPONSES,
            PROTOCOL_ANTHROPIC,
        )
        assert len(EXPLICIT_PROTOCOLS) == 3
        assert PROTOCOL_AUTO not in EXPLICIT_PROTOCOLS


class TestNormalizeMessages:
    def test_normalizes_full_conversation(self) -> None:
        messages = normalize_messages(
            [
                {"role": "system", "content": "Be brief"},
                {"role": "user", "content": "Hi"},
                {
                    "role": "assistant",
                    "content": "Sure",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "f", "arguments": '{"a": 1}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
            ]
        )
        assert [m.role for m in messages] == ["system", "user", "assistant", "tool"]
        assert isinstance(messages[0].content[0], UnifiedTextBlock)
        assert messages[0].content[0].text == "Be brief"
        assert isinstance(messages[2].content[0], UnifiedTextBlock)
        tool_call = messages[2].content[1]
        assert isinstance(tool_call, UnifiedToolCallBlock)
        assert tool_call.id == "call_1"
        assert tool_call.arguments == {"a": 1}
        assert isinstance(messages[3].content[0], UnifiedToolResultBlock)
        assert messages[3].content[0].tool_call_id == "call_1"

    def test_normalizes_reasoning_and_image_blocks(self) -> None:
        messages = normalize_messages(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "think",
                    "thinking_blocks": [
                        {"type": "thinking", "thinking": "deep", "signature": "sig"}
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe"},
                        {"type": "image_url", "image_url": {"url": "https://x/img.png"}},
                    ],
                },
            ]
        )
        assistant = messages[0]
        assert any(
            isinstance(b, UnifiedReasoningBlock) and b.text == "deep" for b in assistant.content
        )
        user = messages[1]
        image = next(b for b in user.content if isinstance(b, UnifiedImageBlock))
        assert image.image_url == "https://x/img.png"

    def test_ignores_unknown_roles(self) -> None:
        messages = normalize_messages(
            [{"role": "system", "content": "s"}, {"role": "weird", "content": "x"}]
        )
        assert len(messages) == 1
        assert messages[0].role == "system"


class TestNormalizeTools:
    def test_normalizes_openai_tools(self) -> None:
        tools = normalize_tools(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "desc",
                        "parameters": {"type": "object", "properties": {}},
                        "strict": True,
                    },
                }
            ]
        )
        assert tools is not None
        assert tools[0].name == "get_weather"
        assert tools[0].description == "desc"
        assert tools[0].strict is True

    def test_returns_none_for_empty(self) -> None:
        assert normalize_tools(None) is None
        assert normalize_tools([]) is None


class TestUnifiedProtocolError:
    def test_is_an_llm_error_with_code(self) -> None:
        error = UnifiedProtocolError("boom", code="transport_error", protocol="openai_responses")
        assert isinstance(error, LLMError)
        assert error.code == "transport_error"
        assert error.protocol == "openai_responses"
        assert "boom" in str(error)


class TestMessageModel:
    def test_content_blocks_can_hold_multiple_types(self) -> None:
        message = UnifiedMessage(
            role="assistant",
            content=[
                UnifiedTextBlock(text="hi"),
                UnifiedToolCallBlock(id="c1", name="f", arguments={"x": 1}),
            ],
        )
        assert len(message.content) == 2
        assert message.role == "assistant"
