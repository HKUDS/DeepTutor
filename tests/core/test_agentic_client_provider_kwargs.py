from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.runtime.agentic import client as agentic_client
from deeptutor.runtime.agentic.client import (
    _NATIVE_ADAPTER_BUILDERS,
    _NATIVE_TOOL_BACKENDS,
    LLMClientConfig,
    _ProviderOpenAIAdapter,
    _ProviderOpenAIStream,
    build_completion_kwargs,
    build_openai_client,
    can_use_native_tool_calling,
)
from deeptutor.services.llm.exceptions import (
    LLMProviderError,
    LLMProviderTransportError,
)
from deeptutor.services.llm.provider_core.base import LLMResponse, ToolCallRequest
from deeptutor.services.llm.request_compat import is_transient_transport_error


def test_agentic_kwargs_leave_deepseek_flash_thinking_to_the_provider() -> None:
    """Flash is no longer switched off — see ``_THINKING_DISABLED_BY_DEFAULT_MODELS``."""
    kwargs = build_completion_kwargs(
        temperature=0.7,
        model="deepseek-v4-flash",
        max_tokens=1024,
        binding="deepseek",
    )

    assert kwargs["max_tokens"] == 1024
    assert "reasoning_effort" not in kwargs
    assert "extra_body" not in kwargs


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


@pytest.mark.asyncio
async def test_provider_stream_exposes_final_reasoning_content() -> None:
    class FakeProvider:
        async def chat_stream(self, **_kwargs):
            return LLMResponse(
                content="answer",
                finish_reason="stop",
                reasoning_content="private reasoning",
            )

    stream = _ProviderOpenAIStream(
        provider=FakeProvider(),
        messages=[],
        tools=None,
        model="deepseek-v4-pro",
        max_tokens=32,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
        extra_kwargs={},
    )

    chunks = [chunk async for chunk in stream]

    final_choice = chunks[-1].choices[0]
    assert final_choice.provider_specific_fields["reasoning_content"] == "private reasoning"
    # ``provider_specific_fields`` alone is not enough: the agent loop reads
    # reasoning off ``delta.reasoning_content``, so a provider that only
    # reported it on the finished message must still reach that channel.
    assert _reasoning_of(chunks) == "private reasoning"


def _reasoning_of(chunks: list) -> str:
    """Reasoning the agent loop would collect, read exactly as it reads it."""
    out = []
    for chunk in chunks:
        for choice in chunk.choices or []:
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            text = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            if text:
                out.append(text)
    return "".join(out)


def _content_of(chunks: list) -> str:
    out = []
    for chunk in chunks:
        for choice in chunk.choices or []:
            delta = getattr(choice, "delta", None)
            if delta is not None and getattr(delta, "content", None):
                out.append(delta.content)
    return "".join(out)


def _stream_for(provider: object) -> _ProviderOpenAIStream:
    return _ProviderOpenAIStream(
        provider=provider,
        messages=[],
        tools=None,
        model="m",
        max_tokens=32,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
        extra_kwargs={},
    )


@pytest.mark.asyncio
async def test_provider_stream_forwards_reasoning_deltas_as_they_arrive() -> None:
    """Reasoning streams on its own channel, not just as a final summary.

    The adapter used to accept ``on_content_delta`` only, so an extended
    thinking model's reasoning never reached the loop at all — neither live nor
    on the finished message, since the loop does not read the field the
    summary was left in.
    """
    seen: dict[str, object] = {}

    class ThinkingProvider:
        async def chat_stream(self, *, on_content_delta=None, on_reasoning_delta=None, **_kw):
            seen["got_reasoning_callback"] = on_reasoning_delta is not None
            for piece in ("weigh", "ing"):
                await on_reasoning_delta(piece)
            for piece in ("the ", "answer"):
                await on_content_delta(piece)
            return LLMResponse(
                content="the answer",
                finish_reason="stop",
                reasoning_content="weighing",
            )

    chunks = [chunk async for chunk in _stream_for(ThinkingProvider())]

    assert seen["got_reasoning_callback"] is True
    assert _reasoning_of(chunks) == "weighing"
    assert _content_of(chunks) == "the answer"


@pytest.mark.asyncio
async def test_provider_stream_raises_an_error_response_instead_of_streaming_it() -> None:
    """A provider's error text must not arrive as though the model wrote it.

    Providers in this family report failure by returning ``finish_reason ==
    "error"`` with the message in ``content``. Forwarded as a chunk, that
    string became the reply — and because nothing was raised, no retry ran.
    """

    class StalledProvider:
        async def chat_stream(self, **_kwargs):
            return LLMResponse(
                content="Error calling LLM: stream stalled for more than 90 seconds",
                finish_reason="error",
            )

    stream = _stream_for(StalledProvider())

    with pytest.raises(LLMProviderTransportError) as excinfo:
        [chunk async for chunk in stream]

    assert "stalled" in str(excinfo.value)
    # Retryable, and known not to have put a partial answer on screen.
    assert is_transient_transport_error(excinfo.value) is True
    assert excinfo.value.partial_response is False


@pytest.mark.asyncio
async def test_provider_stream_marks_an_error_after_output_as_partial() -> None:
    """An error that interrupts a visible answer must not be replayed."""

    class InterruptedProvider:
        async def chat_stream(self, *, on_content_delta=None, **_kwargs):
            await on_content_delta("half an ans")
            return LLMResponse(content="503 server error", finish_reason="error")

    with pytest.raises(LLMProviderTransportError) as excinfo:
        [chunk async for chunk in _stream_for(InterruptedProvider())]

    assert excinfo.value.partial_response is True


@pytest.mark.asyncio
async def test_provider_stream_does_not_retry_a_permanent_error() -> None:
    """An authentication failure is not a transport blip; retrying is waste."""

    class RejectedProvider:
        async def chat_stream(self, **_kwargs):
            return LLMResponse(
                content="Error: invalid x-api-key",
                finish_reason="error",
            )

    with pytest.raises(LLMProviderError) as excinfo:
        [chunk async for chunk in _stream_for(RejectedProvider())]

    assert not isinstance(excinfo.value, LLMProviderTransportError)
    assert "x-api-key" in str(excinfo.value)


@pytest.mark.parametrize("binding", ["moonshot", "openai", "custom"])
def test_agentic_kwargs_drop_temperature_for_bare_kimi_k3(binding: str) -> None:
    kwargs = build_completion_kwargs(
        temperature=0.2,
        model="k3",
        max_tokens=256,
        binding=binding,
    )

    assert kwargs == {"max_tokens": 256}


@pytest.mark.parametrize("model", ["sk3", "k30", "vendor/k3"])
def test_short_k3_override_does_not_match_unrelated_models(model: str) -> None:
    kwargs = build_completion_kwargs(
        temperature=0.2,
        model=model,
        max_tokens=256,
        binding="moonshot",
    )

    assert kwargs["temperature"] == pytest.approx(0.2)


def test_native_tool_backends_all_have_adapter_builders() -> None:
    # Every tool-gated backend must be adapter-routed, or tool schemas would be
    # attached to a plain AsyncOpenAI client speaking a non-OpenAI wire format.
    assert _NATIVE_TOOL_BACKENDS <= set(_NATIVE_ADAPTER_BUILDERS)


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

    assert isinstance(client, _ProviderOpenAIAdapter)
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

    assert isinstance(client, _ProviderOpenAIAdapter)
    assert captured["default_model"] == "openai-codex/gpt-5.5"


@pytest.mark.asyncio
async def test_build_openai_client_rotates_api_keys_after_429(monkeypatch) -> None:
    await agentic_client.close_agentic_client_pool()
    seen_keys: list[str] = []

    class RateLimitError(Exception):
        status_code = 429

    class FakeCompletions:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        async def create(self, **_kwargs):
            seen_keys.append(self.api_key)
            if self.api_key == "key-a":
                raise RateLimitError("rate limited")
            return "ok"

    class FakeClient:
        def __init__(self, api_key: str, **_kwargs) -> None:
            self.chat = type("Chat", (), {"completions": FakeCompletions(api_key)})()

        async def close(self) -> None:
            return None

    monkeypatch.setattr(agentic_client, "AsyncOpenAI", FakeClient)
    monkeypatch.setattr(
        agentic_client, "load_system_settings", lambda: {"disable_ssl_verify": False}
    )
    client = build_openai_client(
        LLMClientConfig(
            binding="openai",
            model="gpt-test",
            api_key=["key-a", "key-b"],
            base_url="https://example.test/v1",
        )
    )

    result = await client.chat.completions.create(model="gpt-test", messages=[])

    assert result == "ok"
    assert seen_keys == ["key-a", "key-b"]
    await agentic_client.close_agentic_client_pool()


def test_build_openai_client_routes_github_copilot_backend_through_adapter(monkeypatch) -> None:
    captured = {}

    class FakeProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.GitHubCopilotProvider",
        FakeProvider,
    )

    client = build_openai_client(
        LLMClientConfig(
            binding="github_copilot",
            model="github-copilot/gpt-4.1",
            api_key=None,
            base_url="https://api.githubcopilot.com",
        )
    )

    assert isinstance(client, _ProviderOpenAIAdapter)
    assert captured["default_model"] == "github-copilot/gpt-4.1"


def test_build_openai_client_routes_codebuddy_backend_through_adapter(monkeypatch) -> None:
    captured = {}

    class FakeProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.codebuddy_http_provider.CodeBuddyHTTPProvider",
        FakeProvider,
    )

    client = build_openai_client(
        LLMClientConfig(
            binding="codebuddy",
            model="codebuddy/hy3",
            api_key="sk-codebuddy",
            base_url=None,
        )
    )

    assert isinstance(client, _ProviderOpenAIAdapter)
    assert captured["api_key"] == "sk-codebuddy"
    assert captured["default_model"] == "codebuddy/hy3"


@pytest.mark.asyncio
async def test_direct_openai_gpt5_agentic_tools_use_provider_adapter(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponses:
        async def create(self, **kwargs):
            captured["request"] = kwargs
            item = SimpleNamespace(
                type="function_call",
                id="fc_123",
                call_id="call_123",
                name="web_search",
                arguments='{"query":"DeepTutor"}',
            )

            async def events():
                yield SimpleNamespace(type="response.output_item.added", item=item)
                yield SimpleNamespace(type="response.output_item.done", item=item)
                yield SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(status="completed", usage=None),
                )

            return events()

    class UnexpectedChatCompletions:
        async def create(self, **_kwargs):
            raise AssertionError("GPT-5 agentic calls must use the Responses API")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["init"] = kwargs
            self.responses = FakeResponses()
            self.chat = SimpleNamespace(completions=UnexpectedChatCompletions())

        async def close(self):
            pass

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.openai_compat_provider.AsyncOpenAI",
        FakeOpenAI,
    )
    await agentic_client.close_agentic_client_pool()
    client = build_openai_client(
        LLMClientConfig(
            binding="openai",
            model="gpt-5.6-luna",
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        )
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    stream = await client.chat.completions.create(
        model="gpt-5.6-luna",
        messages=[{"role": "user", "content": "Search"}],
        tools=tools,
        tool_choice="auto",
        max_completion_tokens=512,
        stream=True,
    )
    chunks = [chunk async for chunk in stream]

    assert isinstance(client, _ProviderOpenAIAdapter)
    assert captured["init"]["base_url"] == "https://api.openai.com/v1"
    assert captured["request"]["stream"] is True
    assert captured["request"]["tools"][0]["name"] == "web_search"
    assert "messages" not in captured["request"]
    tool_call = chunks[-2].choices[0].delta.tool_calls[0]
    assert tool_call.function.name == "web_search"
    assert chunks[-1].choices[0].finish_reason == "tool_calls"
    await agentic_client.close_agentic_client_pool()


def test_anthropic_backend_can_use_native_tool_calling() -> None:
    assert can_use_native_tool_calling(binding="custom_anthropic", model="claude-test") is True
    assert can_use_native_tool_calling(binding="minimax_anthropic", model="MiniMax-M3") is True


def test_custom_qwen_can_use_native_tool_calling() -> None:
    assert can_use_native_tool_calling(binding="custom", model="qwen3.6-plus") is True
    assert can_use_native_tool_calling(binding="dashscope", model="qwen-plus") is True


def test_siliconflow_deepseek_can_use_native_tool_calling() -> None:
    assert (
        can_use_native_tool_calling(
            binding="siliconflow",
            model="deepseek-ai/DeepSeek-V4-Pro",
        )
        is True
    )


def test_registered_cloud_openai_compat_providers_enable_native_tools() -> None:
    # Registered cloud OpenAI-compatible providers are tool-capable by default,
    # even without a dedicated PROVIDER_CAPABILITIES entry — function calling is
    # part of the OpenAI-compatible API contract. Guards against silently
    # disabling native tools when a new cloud provider joins the registry (the
    # gap that affected SiliconFlow before #584).
    for binding in (
        "gemini",
        "zhipu",
        "qianfan",
        "stepfun",
        "xiaomi_mimo",
        "nvidia_nim",
        "aihubmix",
        "atlascloud",
        "edenai",
        "novita",
        "volcengine_coding_plan",
        "byteplus_coding_plan",
    ):
        assert can_use_native_tool_calling(binding=binding, model=None) is True, binding


def test_openai_codex_backend_can_use_native_tool_calling() -> None:
    assert (
        can_use_native_tool_calling(
            binding="openai_codex",
            model="openai-codex/gpt-5.5",
        )
        is True
    )


def test_codebuddy_backend_can_use_native_tool_calling() -> None:
    assert can_use_native_tool_calling(binding="codebuddy", model="codebuddy/hy3") is True


def test_local_and_github_copilot_backends_stay_opted_out_of_native_tools() -> None:
    # Local OpenAI-compatible servers have model-dependent, unreliable tool support.
    # GitHub Copilot remains opted out until its native tool path is validated.
    for binding in (
        "ollama",
        "vllm",
        "lm_studio",
        "llama_cpp",
        "lemonade",
        "ovms",
        "github_copilot",
    ):
        assert can_use_native_tool_calling(binding=binding, model=None) is False, binding


def test_unknown_binding_does_not_enable_native_tools() -> None:
    assert can_use_native_tool_calling(binding="totally-unknown", model=None) is False


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

    client = _ProviderOpenAIAdapter(FakeProvider())
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

    client = _ProviderOpenAIAdapter(FakeProvider())
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


@pytest.mark.asyncio
async def test_agentic_client_pool_reuses_and_bounds_clients(monkeypatch) -> None:
    await agentic_client.close_agentic_client_pool()
    built = []

    class FakeClient:
        def __init__(self) -> None:
            self.closed = 0

        async def close(self) -> None:
            self.closed += 1

    def _build(config, *, disable_ssl_verify):
        client = FakeClient()
        built.append(client)
        return client

    monkeypatch.setattr(agentic_client, "_build_openai_client", _build)
    monkeypatch.setattr(
        agentic_client, "load_system_settings", lambda: {"disable_ssl_verify": False}
    )
    base = LLMClientConfig(
        binding="openai",
        model="model-0",
        api_key="secret",
        base_url="https://example.test/v1",
    )

    first = build_openai_client(base)
    assert build_openai_client(base) is first
    for index in range(1, agentic_client._AGENTIC_CLIENT_POOL_MAXSIZE + 1):
        build_openai_client(
            LLMClientConfig(
                binding="openai",
                model=f"model-{index}",
                api_key="secret",
                base_url="https://example.test/v1",
            )
        )

    import asyncio

    await asyncio.sleep(0)
    assert agentic_client.agentic_client_pool_size() == (
        agentic_client._AGENTIC_CLIENT_POOL_MAXSIZE
    )
    assert built[0].closed == 1
    await agentic_client.close_agentic_client_pool()


@pytest.mark.asyncio
async def test_provider_stream_reports_signed_thinking_blocks() -> None:
    """The adapter carries Anthropic's signed blocks back to the loop."""
    blocks = [{"type": "thinking", "thinking": "weighing", "signature": "sig-1"}]

    class SignedThinkingProvider:
        async def chat_stream(self, **_kwargs):
            return LLMResponse(
                content="done",
                finish_reason="stop",
                thinking_blocks=blocks,
            )

    chunks = [chunk async for chunk in _stream_for(SignedThinkingProvider())]

    final = chunks[-1].choices[0]
    assert final.provider_specific_fields["thinking_blocks"] == blocks
