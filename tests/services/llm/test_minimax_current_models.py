"""Exercise current MiniMax discovery and real SDK request serialization offline."""

from __future__ import annotations

import importlib
import json

import httpx
import pytest

from deeptutor.runtime.agentic.client import (
    LLMClientConfig,
    _build_openai_client,
    build_completion_kwargs,
)
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.context_window import known_context_window
from deeptutor.services.llm.minimax_models import prioritize_model_names
from deeptutor.services.llm.provider_factory import _build_runtime_provider
from deeptutor.services.model_selection.reasoning import supported_reasoning_efforts


def mocked_sdk(sdk, handle):
    # Both supported SDK ranges include releases using httpx and httpx2.
    base = importlib.import_module(type(sdk).__module__.split(".")[0] + "._base_client")
    transport = getattr(base, "httpx2", None) or base.httpx

    def adapt(request):
        response = handle(request)
        return transport.Response(
            response.status_code, headers=response.headers, content=response.content
        )

    return sdk.with_options(
        http_client=transport.AsyncClient(transport=transport.MockTransport(adapt))
    )


FLASH = "MiniMax-M3.1-Flash"
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Look up a fact",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


@pytest.mark.parametrize(
    "binding,prefix,suffix",
    [("minimax", "", ""), ("minimax_anthropic", "", ""), ("openrouter", "minimax/", ":free")],
)
def test_active_discovery_preserves_unrelated_models(binding, prefix, suffix):
    flash = prefix + FLASH + suffix
    m3 = prefix + "MiniMax-M3"
    saved = [
        prefix + "MiniMax-M2.7",
        prefix + "MiniMax-M4",
        "custom-deployment",
        "speech-2.8-hd",
        m3,
        flash,
    ]
    assert prioritize_model_names(saved, binding) == [flash, m3, *saved[:4]]
    assert saved[0] == prefix + "MiniMax-M2.7"
    assert prioritize_model_names(saved, "custom") == saved
    assert prioritize_model_names([m3], binding) == [m3]
    assert prioritize_model_names([], binding) == []


def test_context_windows_keep_gateway_provenance():
    assert known_context_window(FLASH) == 1000000
    assert known_context_window("MiniMax-M3") == 1000000
    assert known_context_window("minimax/minimax-m3.1-flash:free") == 1000000
    assert known_context_window("minimax/minimax-m3") == 1048576
    assert known_context_window("MiniMax-M2.7") == 204800


@pytest.mark.parametrize("binding", ["minimax", "minimax_anthropic"])
def test_reasoning_choices_follow_model_contract(binding):
    assert supported_reasoning_efforts(binding, FLASH) == ["low", "medium", "high", "xhigh", "max"]
    assert supported_reasoning_efforts(binding, "MiniMax-M3") == ["none", "adaptive"]


@pytest.mark.asyncio
@pytest.mark.parametrize("api_format", ["openai_chat", "anthropic"])
@pytest.mark.parametrize("model", [FLASH, "MiniMax-M3"])
@pytest.mark.parametrize("effort", [None, "none", "low", "xhigh", "max"])
async def test_agentic_real_sdk_payload(api_format, model, effort):
    anthropic = api_format == "anthropic"
    client = _build_openai_client(
        LLMClientConfig(
            binding="minimax",
            model=model,
            api_key="fixture-key",
            base_url=None,
            api_format=api_format,
        ),
        disable_ssl_verify=False,
    )
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=response_payload(anthropic))

    sdk = client._provider._client if anthropic else client
    patched = mocked_sdk(sdk, handle)
    await sdk.close()
    if anthropic:
        client._provider._client = patched
    else:
        client = patched
    try:
        result = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hello"}],
            tools=TOOLS,
            **build_completion_kwargs(
                binding="minimax",
                model=model,
                temperature=0.7,
                max_tokens=4096,
                reasoning_effort=effort,
            ),
        )
        assert result.choices[0].message.content == "OK"
        body = json.loads(requests[0].content)
        assert body["model"] == model
        if model == FLASH:
            assert body["thinking"] == {"type": "adaptive"}
            if anthropic:
                assert "reasoning_split" not in body
                assert body.get("output_config", {}).get("effort") == (
                    effort if effort in {"low", "xhigh", "max"} else None
                )
        elif effort:
            assert body["thinking"] == {"type": "disabled" if effort == "none" else "adaptive"}
            assert "reasoning_effort" not in body
        elif anthropic:
            assert body["thinking"] == {"type": "disabled"}
        else:
            assert "thinking" not in body
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["minimax/minimax-m3.1-flash:free", "minimax/minimax-m3"])
async def test_openrouter_sdk_keeps_verified_route(model):
    provider = _build_runtime_provider(
        LLMConfig(
            provider_name="openrouter",
            binding="openrouter",
            model=model,
            api_key="fixture-key",
            base_url="https://openrouter.ai/api/v1",
        ),
        configure_env=False,
    )
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=response_payload(False))

    old_client = provider._client
    provider._client = mocked_sdk(old_client, handle)
    await old_client.close()
    try:
        result = await provider.chat(messages=[{"role": "user", "content": "Hello"}])
        assert result.content == "OK", result
        body = json.loads(requests[0].content)
        assert body["model"] == model
        assert str(requests[0].url) == "https://openrouter.ai/api/v1/chat/completions"
        assert "thinking" not in body
        assert "reasoning_split" not in body
    finally:
        await provider._client.close()


def response_payload(anthropic):
    if anthropic:
        return {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": FLASH,
            "content": [{"type": "text", "text": "OK"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    return {
        "id": "chat_test",
        "object": "chat.completion",
        "created": 1,
        "model": FLASH,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def stream_payload(anthropic):
    if anthropic:
        message = response_payload(True)
        message["content"] = []
        message["stop_reason"] = None
        events = [
            ("message_start", {"message": message}),
            ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "OK"}}),
            ("content_block_stop", {"index": 0}),
            (
                "message_delta",
                {
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 1},
                },
            ),
            ("message_stop", {}),
        ]
        return "".join(
            f"event: {kind}\ndata: {json.dumps({'type': kind, **data})}\n\n"
            for kind, data in events
        )
    return 'data: {"id":"chat_test","object":"chat.completion.chunk","created":1,"model":"MiniMax-M3.1-Flash","choices":[{"index":0,"delta":{"content":"OK"},"finish_reason":null}]}\n\ndata: {"id":"chat_test","object":"chat.completion.chunk","created":1,"model":"MiniMax-M3.1-Flash","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'


@pytest.mark.asyncio
@pytest.mark.parametrize("api_format", ["openai_chat", "anthropic"])
@pytest.mark.parametrize("host", ["api.minimax.io", "api.minimaxi.com"])
@pytest.mark.parametrize(
    "effort", [None, "", "low", "medium", "high", "xhigh", "max", "none", "minimal"]
)
async def test_flash_real_sdk_payload(api_format, host, effort):
    anthropic = api_format == "anthropic"
    base = f"https://{host}/" + ("anthropic" if anthropic else "v1")
    provider = _build_runtime_provider(
        LLMConfig(
            provider_name="minimax",
            binding="minimax",
            model=FLASH,
            api_key="fixture-key",
            base_url=base,
            api_format=api_format,
        ),
        configure_env=False,
    )
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=response_payload(anthropic))

    old_client = provider._client
    provider._client = mocked_sdk(old_client, handle)
    await old_client.close()
    try:
        response = await provider.chat(
            messages=[{"role": "user", "content": "Hello"}], tools=TOOLS, reasoning_effort=effort
        )
        assert response.content == "OK", response
        assert len(requests) == 1
        request = requests[0]
        body = json.loads(request.content)
        assert str(request.url) == base + ("/v1/messages" if anthropic else "/chat/completions")
        assert body["model"] == FLASH
        assert body["thinking"] == {"type": "adaptive"}
        assert "service_tier" not in body
        assert body.get("reasoning_split") is not False
        if anthropic:
            # Anthropic 2.x sends api_key as Bearer auth; 0.x uses X-Api-Key.
            # Verify the exact configured credential with either supported SDK.
            assert (
                request.headers.get("x-api-key"),
                request.headers.get("authorization"),
            ) in {("fixture-key", None), (None, "Bearer fixture-key")}
            assert body.get("output_config", {}).get("effort") == (
                effort if effort in {"low", "medium", "high", "xhigh", "max"} else None
            )
            assert "reasoning_effort" not in body
        else:
            assert request.headers["authorization"] == "Bearer fixture-key"
            assert body.get("reasoning_effort") == (
                effort if effort in {"low", "medium", "high", "xhigh", "max"} else None
            )
        assert body["tools"]
        image_url = "https://example.test/diagram.png"
        replay = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Read this"},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "Need lookup",
                "tool_calls": [
                    {
                        "id": "call_lookup",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_lookup", "content": "Found it"},
        ]
        if anthropic:
            replay[1]["_provider_response_state"] = {
                "thinking_blocks": [
                    {
                        "type": "thinking",
                        "thinking": "Need lookup",
                        "signature": "fixture-signature",
                    }
                ]
            }
        response = await provider.chat(messages=replay, tools=TOOLS, reasoning_effort=effort)
        assert response.content == "OK", response
        replay_body = json.loads(requests[1].content)
        assert replay_body["thinking"] == {"type": "adaptive"}
        assert image_url in json.dumps(replay_body)
        if anthropic:
            assert "call_lookup" in json.dumps(replay_body)
            assert "fixture-signature" in json.dumps(replay_body)
        else:
            assistant = replay_body["messages"][1]
            assert assistant["tool_calls"][0]["function"]["name"] == "lookup"
            assert assistant["tool_calls"][0]["id"] == replay_body["messages"][2]["tool_call_id"]
            assert assistant["reasoning_content"] == "Need lookup"
    finally:
        await provider._client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("api_format", ["openai_chat", "anthropic"])
@pytest.mark.parametrize("model", [FLASH, "MiniMax-M3", "MiniMax-M2.7", "saved-custom-deployment"])
async def test_saved_models_and_streaming_keep_ids(api_format, model):
    anthropic = api_format == "anthropic"
    provider = _build_runtime_provider(
        LLMConfig(
            provider_name="minimax",
            binding="minimax",
            model=model,
            api_key="fixture-key",
            base_url="https://gateway.example/anthropic"
            if anthropic
            else "https://gateway.example/v1",
            api_format=api_format,
        ),
        configure_env=False,
    )
    bodies = []

    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text=stream_payload(anthropic)
        )

    old_client = provider._client
    provider._client = mocked_sdk(old_client, handle)
    await old_client.close()
    try:
        response = await provider.chat_stream(messages=[{"role": "user", "content": "Hello"}])
        assert response.content == "OK", response
        assert bodies[0]["model"] == model
        assert bodies[0]["stream"] is True
        if model == FLASH:
            assert bodies[0]["thinking"] == {"type": "adaptive"}
        elif model == "MiniMax-M3":
            assert bodies[0].get("thinking") == ({"type": "disabled"} if anthropic else None)
            assert "reasoning_effort" not in bodies[0]
    finally:
        await provider._client.close()
