"""Persistence rules for Anthropic's signed thinking blocks.

The blocks are replay material, not display data: Anthropic validates the
signature, so a block that cannot be replayed exactly is worse than absent —
sending an unsigned one turns a missing signature into a failed request.
"""

from __future__ import annotations

from deeptutor.services.session.provider_response_state import (
    MAX_THINKING_BLOCKS,
    normalize_provider_response_state,
)


def _block(thinking: str = "weighing", signature: str = "sig-1") -> dict[str, object]:
    return {"type": "thinking", "thinking": thinking, "signature": signature}


def test_signed_blocks_survive_normalization() -> None:
    state = normalize_provider_response_state({"thinking_blocks": [_block()]})
    assert state == {"thinking_blocks": [_block()]}


def test_extra_keys_are_dropped_so_replay_is_exact() -> None:
    state = normalize_provider_response_state({"thinking_blocks": [{**_block(), "sneaked": "in"}]})
    assert state == {"thinking_blocks": [_block()]}


def test_a_block_without_a_signature_is_refused() -> None:
    assert (
        normalize_provider_response_state(
            {
                "thinking_blocks": [
                    {
                        "type": "thinking",
                        "thinking": "weighing",
                    }
                ]
            }
        )
        is None
    )
    assert (
        normalize_provider_response_state(
            {"thinking_blocks": [{"type": "thinking", "thinking": "weighing", "signature": ""}]}
        )
        is None
    )


def test_a_non_thinking_block_is_refused() -> None:
    assert (
        normalize_provider_response_state({"thinking_blocks": [{"type": "text", "text": "hello"}]})
        is None
    )


def test_too_many_blocks_are_refused() -> None:
    many = [_block(signature=f"sig-{i}") for i in range(MAX_THINKING_BLOCKS + 1)]
    assert normalize_provider_response_state({"thinking_blocks": many}) is None


def test_blocks_coexist_with_reasoning_content() -> None:
    state = normalize_provider_response_state(
        {"reasoning_content": "plain text", "thinking_blocks": [_block()]}
    )
    assert state == {
        "reasoning_content": "plain text",
        "thinking_blocks": [_block()],
    }
