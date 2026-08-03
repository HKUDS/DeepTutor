from __future__ import annotations

from deeptutor.core.agentic.messages import assistant_message_with_tool_calls


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
