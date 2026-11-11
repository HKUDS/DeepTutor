"""Raw agent SDK requests must not leak private replay envelopes."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from deeptutor.runtime.agentic import client as agentic_client
from deeptutor.services.llm.provider_core.base import LLMResponse


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", ["custom", "azure_openai"])
async def test_raw_chat_replays_reasoning_without_private_state(monkeypatch, binding):
    sent = []
    marker = object()

    async def create(**kwargs):
        sent.append(kwargs)
        return marker

    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(agentic_client, "AsyncOpenAI", lambda **kwargs: sdk)
    monkeypatch.setattr(agentic_client, "AsyncAzureOpenAI", lambda **kwargs: sdk)
    config = agentic_client.LLMClientConfig(
        binding=binding,
        model="thinking-model",
        api_key="test-key",
        base_url="https://example.test/v1",
        api_format="openai_chat",
        api_version="2025-01-01" if binding == "azure_openai" else None,
    )
    client = agentic_client._build_openai_client(config, disable_ssl_verify=False)
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_original",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ],
            "_provider_response_state": {"reasoning_content": "retained reasoning"},
            "_responses_output_items": [{"type": "reasoning", "id": "rs_private"}],
        },
        {"role": "tool", "tool_call_id": "call_original", "content": "result"},
    ]
    original = deepcopy(messages)
    result = await client.chat.completions.create(
        model="thinking-model", messages=messages, stream=True
    )
    assert result is marker
    assert messages == original
    assistant, tool = sent[0]["messages"]
    assert "_provider_response_state" not in assistant
    assert "_responses_output_items" not in assistant
    assert assistant["reasoning_content"] == "retained reasoning"
    assert assistant["tool_calls"][0]["id"] == tool["tool_call_id"]
    assert sent[0]["stream"] is True


@pytest.mark.asyncio
async def test_responses_adapter_keeps_native_replay_state(monkeypatch):
    captured = {}

    class Provider:
        def __init__(self, **kwargs):
            pass

        async def chat(self, **kwargs):
            captured.update(kwargs)
            return LLMResponse(content="answer", tool_calls=[], usage={}, finish_reason="stop")

    monkeypatch.setattr("deeptutor.services.llm.provider_core.OpenAICompatProvider", Provider)
    client = agentic_client._build_openai_client(
        agentic_client.LLMClientConfig(
            binding="custom",
            model="responses-model",
            api_key="test-key",
            base_url="https://example.test/v1",
            api_format="openai_responses",
        ),
        disable_ssl_verify=False,
    )
    messages = [
        {
            "role": "assistant",
            "content": "previous",
            "_provider_response_state": {
                "responses_output_items": [{"type": "message", "id": "msg_1"}]
            },
        }
    ]
    await client.chat.completions.create(model="responses-model", messages=messages)
    assert captured["messages"] == messages
