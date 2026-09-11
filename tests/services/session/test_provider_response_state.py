from __future__ import annotations

from deeptutor.services.session.provider_response_state import (
    MAX_REASONING_CONTENT_CHARS,
    MAX_RESPONSE_OUTPUT_ITEMS,
    normalize_provider_response_state,
    redact_private_message_metadata,
)


def test_normalize_accepts_only_bounded_known_provider_state() -> None:
    state = normalize_provider_response_state(
        {
            "reasoning_content": "private reasoning",
            "responses_output_items": [
                {"type": "reasoning", "id": "rs_1", "summary": []},
                {"type": "web_search_call", "id": "ws_1", "status": "completed"},
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "search",
                    "arguments": "{}",
                },
            ],
            "unexpected": "discard me",
        }
    )

    assert state == {
        "reasoning_content": "private reasoning",
        "responses_output_items": [
            {"type": "reasoning", "id": "rs_1", "summary": []},
            {"type": "web_search_call", "id": "ws_1", "status": "completed"},
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "search",
                "arguments": "{}",
            },
        ],
    }


def test_normalize_drops_oversized_or_unknown_protocol_state() -> None:
    assert (
        normalize_provider_response_state(
            {"reasoning_content": "x" * (MAX_REASONING_CONTENT_CHARS + 1)}
        )
        is None
    )
    assert (
        normalize_provider_response_state(
            {
                "responses_output_items": [
                    {"type": "reasoning", "id": str(index), "summary": []}
                    for index in range(MAX_RESPONSE_OUTPUT_ITEMS + 1)
                ]
            }
        )
        is None
    )
    assert (
        normalize_provider_response_state(
            {"responses_output_items": [{"type": "function_call_output", "output": "x"}]}
        )
        is None
    )


def test_redact_private_message_metadata_preserves_public_metadata() -> None:
    messages = [
        {
            "metadata": {
                "provider_response_state": {"reasoning_content": "private"},
                "visible": "keep",
            }
        }
    ]

    redact_private_message_metadata(messages)

    assert messages == [{"metadata": {"visible": "keep"}}]
