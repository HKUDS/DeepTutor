from __future__ import annotations

import json

import httpx
from openai import AsyncOpenAI
import pytest

from deeptutor.runtime.agentic.messages import assistant_message_with_tool_calls


def test_assistant_message_with_tool_calls_normalizes_empty_values() -> None:
    message = assistant_message_with_tool_calls(
        content="",
        tool_calls=[{"id": "call-1", "name": "search"}],
    )

    assert message == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "search", "arguments": "{}"},
            }
        ],
    }


def test_assistant_message_with_tool_calls_preserves_order_and_arguments() -> None:
    message = assistant_message_with_tool_calls(
        content="I will inspect both sources.",
        tool_calls=[
            {"id": "call-1", "name": "search", "arguments": '{"q":"one"}'},
            {"id": "call-2", "name": "read", "arguments": '{"id":2}'},
        ],
    )

    assert message["content"] == "I will inspect both sources."
    assert [call["id"] for call in message["tool_calls"]] == ["call-1", "call-2"]
    assert message["tool_calls"][1]["function"] == {
        "name": "read",
        "arguments": '{"id":2}',
    }


def test_assistant_message_with_tool_calls_replays_reasoning_content() -> None:
    message = assistant_message_with_tool_calls(
        content="",
        tool_calls=[{"id": "call-1", "name": "search"}],
        reasoning_content="Need to look this up.",
    )

    assert message["reasoning_content"] == "Need to look this up."
    assert "reasoning_content" not in assistant_message_with_tool_calls(
        content="hi",
        tool_calls=[{"id": "call-1", "name": "search"}],
        reasoning_content="",
    )


def test_assistant_message_replays_gemini_thought_signature() -> None:
    message = assistant_message_with_tool_calls(
        content="",
        tool_calls=[
            {
                "id": "function-call-1",
                "name": "mastery_status",
                "arguments": "{}",
                "extra_content": {"google": {"thought_signature": "signature-from-gemini"}},
            }
        ],
    )

    assert message["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "signature-from-gemini"}
    }


@pytest.mark.asyncio
async def test_openai_sdk_keeps_gemini_signature_in_request_body() -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads((await request.aread()).decode()))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "gemini-test",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncOpenAI(
        api_key="test",
        base_url="https://example.test/v1",
        http_client=http_client,
    )
    message = assistant_message_with_tool_calls(
        content="",
        tool_calls=[
            {
                "id": "function-call-1",
                "name": "mastery_status",
                "arguments": "{}",
                "extra_content": {"google": {"thought_signature": "signature-from-gemini"}},
            }
        ],
    )

    try:
        await client.chat.completions.create(
            model="gemini-test",
            messages=[
                {"role": "user", "content": "status"},
                message,  # type: ignore[list-item]
                {
                    "role": "tool",
                    "tool_call_id": "function-call-1",
                    "content": "{}",
                },
            ],
        )
    finally:
        await client.close()

    assert captured["messages"][1]["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": "signature-from-gemini"}
    }


def test_assistant_message_replays_anthropic_thinking_blocks() -> None:
    """Extended thinking returns *signed* blocks that must be replayed.

    Anthropic rejects a turn that issued tool calls and then failed to send
    its thinking blocks back verbatim. The provider always read this field off
    the message; nothing wrote it, so every round dropped the signature.
    """
    blocks = [{"type": "thinking", "thinking": "weighing it", "signature": "sig-abc"}]
    message = assistant_message_with_tool_calls(
        "",
        [{"id": "call-1", "name": "rag", "arguments": "{}"}],
        thinking_blocks=blocks,
    )

    assert message["thinking_blocks"] == blocks
    assert "thinking_blocks" not in assistant_message_with_tool_calls(
        "",
        [{"id": "call-1", "name": "rag", "arguments": "{}"}],
    )
