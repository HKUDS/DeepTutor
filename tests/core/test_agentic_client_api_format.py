"""``api_format`` on the agentic OpenAI-compatible client handle."""

from __future__ import annotations

from deeptutor.runtime.agentic import client as agentic_client
from deeptutor.runtime.agentic.client import LLMClientConfig, can_use_native_tool_calling
from deeptutor.services.llm.capabilities import set_catalog_capability_overrides


def test_api_format_and_wire_api_stay_in_step() -> None:
    assert (
        LLMClientConfig(
            binding="custom", model="m", api_key="k", base_url=None, api_format="openai_responses"
        ).wire_api
        == "responses"
    )
    assert (
        LLMClientConfig(
            binding="custom", model="m", api_key="k", base_url=None, wire_api="responses"
        ).api_format
        == "openai_responses"
    )
    assert (
        LLMClientConfig(binding="anthropic", model="m", api_key="k", base_url=None).api_format
        == "anthropic"
    )
    # Clamped: OpenAI does not serve Anthropic Messages.
    clamped = LLMClientConfig(
        binding="openai", model="m", api_key="k", base_url=None, api_format="anthropic"
    )
    assert (clamped.api_format, clamped.wire_api) == ("auto", "auto")


def test_custom_endpoint_in_anthropic_format_routes_through_anthropic_adapter(monkeypatch) -> None:
    captured: dict = {}

    class FakeAnthropicProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.AnthropicProvider", FakeAnthropicProvider
    )
    client = agentic_client._build_openai_client(
        LLMClientConfig(
            binding="custom",
            model="claude-relay",
            api_key="k",
            base_url="https://relay.example/anthropic",
            api_format="anthropic",
        ),
        disable_ssl_verify=False,
    )
    assert isinstance(client, agentic_client._ProviderOpenAIAdapter)
    assert captured["api_base"] == "https://relay.example/anthropic"


def test_minimax_anthropic_format_falls_back_to_the_vendor_anthropic_endpoint(monkeypatch) -> None:
    captured: dict = {}

    class FakeAnthropicProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.AnthropicProvider", FakeAnthropicProvider
    )
    agentic_client._build_openai_client(
        LLMClientConfig(
            binding="minimax",
            model="MiniMax-M3",
            api_key="k",
            base_url=None,
            api_format="anthropic",
        ),
        disable_ssl_verify=False,
    )
    assert captured["api_base"] == "https://api.minimax.io/anthropic"


def test_declared_tool_capability_decides_before_every_other_rule() -> None:
    try:
        set_catalog_capability_overrides(
            [
                ("ollama", "llama3", {"tools": True}),
                ("openai", "gpt-4o", {"tools": False}),
            ]
        )
        assert can_use_native_tool_calling(binding="ollama", model="llama3") is True
        assert can_use_native_tool_calling(binding="openai", model="gpt-4o") is False
        assert can_use_native_tool_calling(binding="openai", model="gpt-4o-mini") is True
    finally:
        set_catalog_capability_overrides([])
