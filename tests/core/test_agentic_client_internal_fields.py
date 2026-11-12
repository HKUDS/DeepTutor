"""DeepTutor-internal message fields must never reach a raw provider wire.

Issue #2622: a Fireworks binding (``api_format=openai_chat``) answered every
post-tool-call turn with 400 "Extra inputs are not permitted" because the
agent loop's next request serialized the assistant message's private
``_provider_response_state`` replay envelope verbatim. Provider-backed
adapters strip (and consume) the envelope per their own wire contract, but a
raw Chat Completions client — what ``build_openai_client`` returns for
chat-completions bindings — must send clean messages.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.runtime.agentic import client as agentic_client
from deeptutor.runtime.agentic.client import (
    LLMClientConfig,
    _build_openai_client,
    strip_internal_message_fields,
)
from deeptutor.services.llm.provider_core.base import LLMResponse

FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"

# One full turn shape: the assistant answered by calling a tool (so its
# message carries the round's private provider-response replay state), the
# tool result was appended, and the next round's request is being built.
TOOL_ROUND_MESSAGES: list[dict[str, Any]] = [
    {"role": "system", "content": "You are a tutor."},
    {"role": "user", "content": "Save a checkpoint."},
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_ab12cd34e",
                "type": "function",
                "function": {
                    "name": "save_checkpoint",
                    "arguments": '{"note": "module 2 done"}',
                },
            }
        ],
        "reasoning_content": "The learner finished module 2; persist progress.",
        "_provider_response_state": {
            "reasoning_content": "The learner finished module 2; persist progress.",
        },
    },
    {
        "role": "tool",
        "tool_call_id": "call_ab12cd34e",
        "content": '{"saved": true}',
    },
]


class _RecordingSDK:
    """Minimal ``AsyncOpenAI`` double that records ``create`` kwargs."""

    def __init__(self, captured: list[dict[str, Any]], **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self._captured = captured
        completions = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=completions)

    async def _create(self, **kwargs: Any) -> Any:
        self._captured.append(kwargs)
        return SimpleNamespace(choices=[], usage=None)


def _fireworks_client(monkeypatch: pytest.MonkeyPatch, captured: list[dict[str, Any]]) -> Any:
    monkeypatch.setattr(
        agentic_client, "AsyncOpenAI", lambda **kwargs: _RecordingSDK(captured, **kwargs)
    )
    return _build_openai_client(
        LLMClientConfig(
            binding="custom",
            model="kimi-k2-instruct",
            api_key="fwk-secret",
            base_url=FIREWORKS_BASE_URL,
            api_format="openai_chat",
        ),
        disable_ssl_verify=False,
    )


def test_openai_chat_payload_strips_internal_fields_and_keeps_tool_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The next-round request carries no underscore fields; the tool pair is intact."""
    captured: list[dict[str, Any]] = []
    client = _fireworks_client(monkeypatch, captured)

    import asyncio

    messages = deepcopy(TOOL_ROUND_MESSAGES)
    asyncio.run(client.chat.completions.create(messages=messages, model="kimi-k2-instruct"))

    assert len(captured) == 1
    wire_messages = captured[0]["messages"]
    assert len(wire_messages) == len(TOOL_ROUND_MESSAGES)
    for message in wire_messages:
        assert not [key for key in message if str(key).startswith("_")], message

    assistant = wire_messages[2]
    tool_calls = assistant["tool_calls"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["id"] == "call_ab12cd34e"
    assert tool_calls[0]["type"] == "function"
    assert tool_calls[0]["function"]["name"] == "save_checkpoint"
    assert tool_calls[0]["function"]["arguments"] == '{"note": "module 2 done"}'
    # Chat-dialect reasoning replay is a provider field, not internal state.
    assert assistant["reasoning_content"] == "The learner finished module 2; persist progress."

    tool_result = wire_messages[3]
    assert tool_result["role"] == "tool"
    assert tool_result["tool_call_id"] == "call_ab12cd34e"
    assert tool_result["content"] == '{"saved": true}'

    # The caller's conversation list is untouched — later rounds and the
    # persistence layer still see the replay state.
    assert messages[2]["_provider_response_state"] == {
        "reasoning_content": "The learner finished module 2; persist progress."
    }


def test_provider_backed_client_keeps_replay_state_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Responses-wire adapter still receives the state its provider replays."""

    recorded: dict[str, Any] = {}

    class FakeOpenAICompatProvider:
        def __init__(self, **kwargs: Any) -> None:
            recorded["constructor"] = kwargs

        async def chat_stream(self, **kwargs: Any) -> LLMResponse:
            recorded["messages"] = kwargs["messages"]
            return LLMResponse(content="ok", finish_reason="stop")

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.OpenAICompatProvider",
        FakeOpenAICompatProvider,
    )
    client = _build_openai_client(
        LLMClientConfig(
            binding="custom",
            model="gpt-5",
            api_key="k",
            base_url=FIREWORKS_BASE_URL,
            api_format="openai_responses",
        ),
        disable_ssl_verify=False,
    )
    assert isinstance(client, agentic_client._ProviderOpenAIAdapter)

    import asyncio

    async def _consume() -> None:
        stream = await client.chat.completions.create(
            messages=deepcopy(TOOL_ROUND_MESSAGES), model="gpt-5", stream=True
        )
        async for _chunk in stream:
            pass

    asyncio.run(_consume())

    provider_messages = recorded["messages"]
    state = provider_messages[2]["_provider_response_state"]
    assert state == {"reasoning_content": "The learner finished module 2; persist progress."}
    assert provider_messages[2]["tool_calls"][0]["function"]["name"] == "save_checkpoint"


def test_key_rotating_client_sanitizes_each_upstream_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    class RecordingPoolSDK:
        def __init__(self, **kwargs: Any) -> None:
            pool_client = _RecordingSDK(captured, **kwargs)
            self.chat = pool_client.chat

    monkeypatch.setattr(agentic_client, "AsyncOpenAI", RecordingPoolSDK)
    client = _build_openai_client(
        LLMClientConfig(
            binding="custom",
            model="kimi-k2-instruct",
            api_key=["key-a", "key-b"],
            base_url=FIREWORKS_BASE_URL,
            api_format="openai_chat",
        ),
        disable_ssl_verify=False,
    )

    import asyncio

    asyncio.run(
        client.chat.completions.create(
            messages=deepcopy(TOOL_ROUND_MESSAGES), model="kimi-k2-instruct"
        )
    )

    assert captured, "the pooled request never reached a per-key client"
    for request in captured:
        for message in request["messages"]:
            assert not [key for key in message if str(key).startswith("_")]


def test_strip_internal_message_fields_is_targeted_and_non_mutating() -> None:
    dirty = deepcopy(TOOL_ROUND_MESSAGES)
    cleaned = strip_internal_message_fields(dirty)

    assert cleaned is not dirty
    assert "_provider_response_state" not in cleaned[2]
    assert cleaned[2]["tool_calls"] == dirty[2]["tool_calls"]
    assert dirty[2]["_provider_response_state"] is not None

    clean = [{"role": "user", "content": "hi"}]
    assert strip_internal_message_fields(clean) is clean
    assert strip_internal_message_fields("not-a-list") == "not-a-list"
