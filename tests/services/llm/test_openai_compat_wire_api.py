import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.runtime.agentic import client as agentic_client
from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config
from deeptutor.services.llm import provider_factory
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.provider_core.openai_compat_provider import (
    OpenAICompatProvider,
)
from deeptutor.services.provider_registry import find_by_name


def _catalog(*, wire_api: str = "responses", binding: str = "custom") -> dict:
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "llm-p",
                "active_model_id": "llm-m",
                "profiles": [
                    {
                        "id": "llm-p",
                        "name": "Responses Gateway",
                        "binding": binding,
                        "wire_api": wire_api,
                        "base_url": "https://gateway.example/v1",
                        "api_key": "test-key",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": "llm-m",
                                "name": "Responses-only model",
                                "model": "responses-only-model",
                                "reasoning_effort": "xhigh",
                            }
                        ],
                    }
                ],
            },
            "embedding": {"active_profile_id": None, "profiles": []},
            "search": {"active_profile_id": None, "profiles": []},
        },
    }


def _provider(*, wire_api: str = "auto") -> OpenAICompatProvider:
    return OpenAICompatProvider(
        api_key="test-key",
        api_base="https://gateway.example/v1",
        default_model="responses-only-model",
        spec=find_by_name("custom"),
        provider_name="custom",
        wire_api=wire_api,
    )


def test_runtime_config_preserves_wire_api() -> None:
    resolved = resolve_llm_runtime_config(catalog=_catalog())

    assert resolved.wire_api == "responses"


@pytest.mark.parametrize("binding", ["azure_openai", "custom_anthropic"])
def test_runtime_config_ignores_wire_api_for_unsupported_backends(binding: str) -> None:
    resolved = resolve_llm_runtime_config(catalog=_catalog(binding=binding))

    assert resolved.wire_api == "auto"


def test_agentic_client_routes_forced_responses_through_adapter(monkeypatch) -> None:
    captured = {}

    class FakeProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.OpenAICompatProvider",
        FakeProvider,
    )
    client = agentic_client._build_openai_client(
        agentic_client.LLMClientConfig(
            binding="custom",
            model="responses-only-model",
            api_key="test-key",
            base_url="https://gateway.example/v1",
            wire_api="responses",
        ),
        disable_ssl_verify=False,
    )

    assert isinstance(client, agentic_client._ProviderOpenAIAdapter)
    assert captured["wire_api"] == "responses"


def test_agentic_client_does_not_force_responses_for_azure(monkeypatch) -> None:
    class FakeAzureClient:
        def __init__(self, **_kwargs):
            pass

    class UnexpectedCompatProvider:
        def __init__(self, **_kwargs):
            raise AssertionError("Azure must keep its native provider route")

    monkeypatch.setattr(agentic_client, "AsyncAzureOpenAI", FakeAzureClient)
    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.OpenAICompatProvider",
        UnexpectedCompatProvider,
    )

    client = agentic_client._build_openai_client(
        agentic_client.LLMClientConfig(
            binding="azure_openai",
            model="deployment-name",
            api_key="test-key",
            base_url="https://azure.example",
            api_version="2025-01-01-preview",
            wire_api="responses",
        ),
        disable_ssl_verify=False,
    )

    assert isinstance(client, FakeAzureClient)


def test_agentic_client_forced_chat_completions_beats_auto_responses(monkeypatch) -> None:
    class FakeChatCompletionsClient:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace())

    monkeypatch.setattr(agentic_client, "AsyncOpenAI", FakeChatCompletionsClient)

    client = agentic_client._build_openai_client(
        agentic_client.LLMClientConfig(
            binding="openai",
            model="gpt-5-test",
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            wire_api="chat_completions",
        ),
        disable_ssl_verify=False,
    )

    assert isinstance(client, FakeChatCompletionsClient)


def test_wire_api_participates_in_both_client_cache_keys() -> None:
    loop_marker = object()
    automatic = agentic_client.LLMClientConfig(
        binding="custom",
        model="responses-only-model",
        api_key="test-key",
        base_url="https://gateway.example/v1",
        wire_api="auto",
    )
    forced = agentic_client.LLMClientConfig(
        binding="custom",
        model="responses-only-model",
        api_key="test-key",
        base_url="https://gateway.example/v1",
        wire_api="responses",
    )
    assert agentic_client._client_cache_key(automatic, loop_marker, False) != (
        agentic_client._client_cache_key(forced, loop_marker, False)
    )

    automatic_runtime = LLMConfig(
        model="responses-only-model",
        api_key="test-key",
        base_url="https://gateway.example/v1",
        wire_api="auto",
    )
    forced_runtime = LLMConfig(
        model="responses-only-model",
        api_key="test-key",
        base_url="https://gateway.example/v1",
        wire_api="responses",
    )
    assert provider_factory._provider_cache_key(automatic_runtime, loop_marker) != (
        provider_factory._provider_cache_key(forced_runtime, loop_marker)
    )


def test_custom_base_can_force_responses_api() -> None:
    assert _provider(wire_api="responses")._should_use_responses_api(
        "responses-only-model", "xhigh"
    )


def test_direct_openai_can_force_chat_completions() -> None:
    provider = OpenAICompatProvider(
        api_key="test-key",
        api_base="https://api.openai.com/v1",
        default_model="gpt-5-test",
        spec=find_by_name("openai"),
        provider_name="openai",
        wire_api="chat_completions",
    )

    assert not provider._should_use_responses_api("gpt-5-test", "xhigh")


@pytest.mark.asyncio
async def test_forced_responses_agentic_stream_maps_tool_calls(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponses:
        async def create(self, **kwargs):
            captured["request"] = kwargs
            item = SimpleNamespace(
                type="function_call",
                id="fc_123",
                call_id="call_123",
                name="lookup",
                arguments='{"query":"protocol"}',
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
            raise AssertionError("forced Responses mode must not call chat completions")

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
    client = agentic_client._build_openai_client(
        agentic_client.LLMClientConfig(
            binding="custom",
            model="responses-only-model",
            api_key="test-key",
            base_url="https://gateway.example/v1",
            wire_api="responses",
        ),
        disable_ssl_verify=False,
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    stream = await client.chat.completions.create(
        model="responses-only-model",
        messages=[{"role": "user", "content": "Find it"}],
        tools=tools,
        tool_choice="auto",
        max_completion_tokens=512,
        stream=True,
    )
    chunks = [chunk async for chunk in stream]

    assert captured["init"]["base_url"] == "https://gateway.example/v1"
    assert captured["request"]["stream"] is True
    assert captured["request"]["tools"][0]["name"] == "lookup"
    assert "messages" not in captured["request"]
    assert chunks[-2].choices[0].delta.tool_calls[0].function.name == "lookup"
    assert chunks[-1].choices[0].finish_reason == "tool_calls"


class _EndpointError(RuntimeError):
    status_code = 400
    body = {"error": "Responses API unsupported"}


class _FailingResponses:
    async def create(self, **_kwargs):
        raise _EndpointError("responses request rejected")


class _TrackingChatCompletions:
    def __init__(self) -> None:
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        raise AssertionError("forced Responses mode must not call chat completions")


def _force_failing_client(provider: OpenAICompatProvider) -> _TrackingChatCompletions:
    completions = _TrackingChatCompletions()
    provider._client = SimpleNamespace(
        responses=_FailingResponses(),
        chat=SimpleNamespace(completions=completions),
    )
    return completions


def test_forced_responses_non_streaming_does_not_fallback_to_chat_completions() -> None:
    provider = _provider(wire_api="responses")
    completions = _force_failing_client(provider)

    result = asyncio.run(
        provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            reasoning_effort="xhigh",
        )
    )

    assert completions.calls == 0
    assert result.finish_reason == "error"


def test_forced_responses_streaming_does_not_fallback_to_chat_completions() -> None:
    provider = _provider(wire_api="responses")
    completions = _force_failing_client(provider)

    result = asyncio.run(
        provider.chat_stream(
            messages=[{"role": "user", "content": "hello"}],
            reasoning_effort="xhigh",
        )
    )

    assert completions.calls == 0
    assert result.finish_reason == "error"
