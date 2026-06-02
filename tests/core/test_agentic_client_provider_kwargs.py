from __future__ import annotations

import pytest

from deeptutor.core.agentic.client import (
    LLMClientConfig,
    _AnthropicOpenAIAdapter,
    build_completion_kwargs,
    build_openai_client,
    can_use_native_tool_calling,
)
from deeptutor.services.llm.provider_core.base import LLMResponse, ToolCallRequest


def test_agentic_kwargs_disable_deepseek_flash_thinking_by_default() -> None:
    kwargs = build_completion_kwargs(
        temperature=0.7,
        model="deepseek-v4-flash",
        max_tokens=1024,
        binding="deepseek",
    )

    assert kwargs["max_tokens"] == 1024
    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_agentic_kwargs_enable_deepseek_pro_thinking_by_default() -> None:
    kwargs = build_completion_kwargs(
        temperature=0.7,
        model="deepseek-v4-pro",
        max_tokens=1024,
        binding="deepseek",
    )

    assert kwargs["reasoning_effort"] == "high"
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}


def test_agentic_kwargs_use_provider_minimal_thinking_without_top_level_effort() -> None:
    kwargs = build_completion_kwargs(
        temperature=0.7,
        model="deepseek-v4-pro",
        max_tokens=1024,
        binding="deepseek",
        reasoning_effort="minimal",
    )

    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_agentic_kwargs_enable_qwen_thinking_for_custom_binding() -> None:
    kwargs = build_completion_kwargs(
        temperature=0.7,
        model="qwen3.6-plus",
        max_tokens=1024,
        binding="custom",
    )

    assert kwargs["max_tokens"] == 1024
    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"] == {"enable_thinking": True}


def test_agentic_kwargs_disable_qwen_thinking_for_custom_minimal_reasoning() -> None:
    kwargs = build_completion_kwargs(
        temperature=0.7,
        model="Qwen/Qwen3-235B-A22B-Instruct",
        max_tokens=1024,
        binding="custom",
        reasoning_effort="minimal",
    )

    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"] == {"enable_thinking": False}


def test_agentic_kwargs_preserve_legacy_shape_without_binding() -> None:
    kwargs = build_completion_kwargs(
        temperature=0.2,
        model="plain-model",
        max_tokens=256,
    )

    assert kwargs == {"temperature": 0.2, "max_tokens": 256}


def test_build_openai_client_routes_anthropic_backend_through_adapter(monkeypatch) -> None:
    captured = {}

    class FakeProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.AnthropicProvider",
        FakeProvider,
    )

    client = build_openai_client(
        LLMClientConfig(
            binding="custom_anthropic",
            model="claude-test",
            api_key="sk-test",
            base_url="https://anthropic.example/v1",
            extra_headers={"X-Test": "1"},
        )
    )

    assert isinstance(client, _AnthropicOpenAIAdapter)
    assert captured["api_key"] == "sk-test"
    assert captured["api_base"] == "https://anthropic.example/v1"
    assert captured["default_model"] == "claude-test"
    assert captured["extra_headers"] == {"X-Test": "1"}


def test_build_openai_client_routes_oauth_backend_through_adapter(monkeypatch) -> None:
    captured = {}

    class FakeProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.OpenAICodexProvider",
        FakeProvider,
    )

    client = build_openai_client(
        LLMClientConfig(
            binding="openai_codex",
            model="openai-codex/gpt-5.5",
            api_key="unused",
            base_url="https://chatgpt.com/backend-api",
        )
    )

    assert isinstance(client, _AnthropicOpenAIAdapter)
    assert captured["default_model"] == "openai-codex/gpt-5.5"


def test_anthropic_backend_can_use_native_tool_calling() -> None:
    assert can_use_native_tool_calling(binding="custom_anthropic", model="claude-test") is True
    assert can_use_native_tool_calling(binding="minimax_anthropic", model="MiniMax-M2") is True


def test_custom_qwen_can_use_native_tool_calling() -> None:
    assert can_use_native_tool_calling(binding="custom", model="qwen3.6-plus") is True
    assert can_use_native_tool_calling(binding="dashscope", model="qwen-plus") is True


@pytest.mark.asyncio
async def test_anthropic_adapter_streams_openai_style_chunks() -> None:
    captured = {}

    class FakeProvider:
        async def chat_stream(self, **kwargs):
            captured.update(kwargs)
            await kwargs["on_content_delta"]("``FINISH``\n")
            await kwargs["on_content_delta"]("done")
            return LLMResponse(
                content="``FINISH``\ndone",
                finish_reason="stop",
                usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            )

    client = _AnthropicOpenAIAdapter(FakeProvider())
    stream = await client.chat.completions.create(
        model="claude-test",
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
        max_completion_tokens=12,
        temperature=0.2,
    )

    chunks = [chunk async for chunk in stream]

    assert [chunk.choices[0].delta.content for chunk in chunks[:2]] == [
        "``FINISH``\n",
        "done",
    ]
    assert chunks[-1].choices[0].finish_reason == "stop"
    assert chunks[-1].usage["total_tokens"] == 5
    assert captured["max_tokens"] == 12
    assert captured["temperature"] == 0.2


@pytest.mark.asyncio
async def test_anthropic_adapter_emits_final_tool_call_delta() -> None:
    class FakeProvider:
        async def chat_stream(self, **kwargs):
            return LLMResponse(
                content="``TOOL``",
                tool_calls=[
                    ToolCallRequest(
                        id="toolu_123",
                        name="read_file",
                        arguments={"path": "SOUL.md"},
                    )
                ],
                finish_reason="tool_calls",
            )

    client = _AnthropicOpenAIAdapter(FakeProvider())
    stream = await client.chat.completions.create(
        model="claude-test",
        messages=[{"role": "user", "content": "read"}],
        stream=True,
        max_tokens=8,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    chunks = [chunk async for chunk in stream]
    tool_delta = chunks[-2].choices[0].delta.tool_calls[0]

    assert tool_delta.id == "toolu_123"
    assert tool_delta.function.name == "read_file"
    assert '"SOUL.md"' in tool_delta.function.arguments
    assert chunks[-1].choices[0].finish_reason == "tool_calls"
