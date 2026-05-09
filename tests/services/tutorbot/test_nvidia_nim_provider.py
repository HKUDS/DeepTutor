from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.tutorbot.config.schema import ProviderConfig, ProvidersConfig
from deeptutor.tutorbot.providers.openai_compat_provider import OpenAICompatProvider
from deeptutor.tutorbot.providers.registry import find_by_name, find_gateway


class _EmptyAsyncStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _FakeCompletions:
    def __init__(self) -> None:
        self.kwargs: dict | None = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return _EmptyAsyncStream()


def test_tutorbot_registry_includes_nvidia_nim_gateway() -> None:
    spec = find_by_name("nvidia_nim")

    assert spec is not None
    assert spec.display_name == "NVIDIA NIM"
    assert spec.default_api_base == "https://integrate.api.nvidia.com/v1"
    assert spec.supports_stream_options is False
    assert find_gateway(api_key="nvapi-test-key") == spec
    assert find_gateway(api_base="https://integrate.api.nvidia.com/v1") == spec


def test_tutorbot_schema_accepts_nvidia_nim_provider_config() -> None:
    providers = ProvidersConfig()

    assert isinstance(providers.nvidia_nim, ProviderConfig)


@pytest.mark.asyncio
async def test_tutorbot_nvidia_nim_stream_omits_stream_options() -> None:
    spec = find_by_name("nvidia_nim")
    assert spec is not None
    completions = _FakeCompletions()
    provider = OpenAICompatProvider(
        api_key="nvapi-test-key",
        default_model="meta/llama-3.1-70b-instruct",
        spec=spec,
    )
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    await provider.chat_stream(
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=32,
    )

    assert completions.kwargs is not None
    assert completions.kwargs["stream"] is True
    assert "stream_options" not in completions.kwargs
