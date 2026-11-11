"""Raw agent SDK requests must not leak private replay envelopes."""

from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
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
@pytest.mark.parametrize("binding", ["custom", "azure_openai"])
@pytest.mark.parametrize("stream", [False, True])
async def test_raw_sdk_projects_replay_state_on_http_wire(monkeypatch, binding, stream):
    sent = []

    def handle(request):
        sent.append(json.loads(request.content))
        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk" if stream else "chat.completion",
            "created": 0,
            "model": "thinking-model",
            "choices": [
                {
                    "index": 0,
                    "delta" if stream else "message": {"role": "assistant", "content": "answer"},
                    "finish_reason": "stop",
                }
            ],
        }
        if stream:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(200, json=payload)

    client_kwargs = agentic_client.openai_sdk_client_kwargs
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http_client:
        monkeypatch.setattr(
            agentic_client,
            "openai_sdk_client_kwargs",
            lambda **kwargs: {**client_kwargs(**kwargs), "http_client": http_client},
        )
        client = agentic_client._build_openai_client(
            agentic_client.LLMClientConfig(
                binding=binding,
                model="thinking-model",
                api_key="test-key",
                base_url="https://example.test/v1",
                api_version="2025-01-01" if binding == "azure_openai" else None,
                api_format="openai_chat",
            ),
            disable_ssl_verify=False,
        )
        messages = [
            {
                "role": "assistant",
                "content": "previous",
                "_provider_response_state": {"reasoning_content": "retained reasoning"},
                "_responses_output_items": [{"type": "reasoning", "id": "rs_private"}],
            },
            {"role": "user", "content": "continue"},
        ]
        original = deepcopy(messages)
        try:
            result = await client.chat.completions.create(
                model="thinking-model", messages=messages, stream=stream
            )
            if stream:
                chunks = [chunk async for chunk in result]
                assert chunks[0].choices[0].delta.content == "answer"
            else:
                assert result.choices[0].message.content == "answer"
        finally:
            await client.close()

    assert len(sent) == 1
    assert sent[0]["stream"] is stream
    assert sent[0]["messages"][0] == {
        "role": "assistant",
        "content": "previous",
        "reasoning_content": "retained reasoning",
    }
    assert messages == original


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
