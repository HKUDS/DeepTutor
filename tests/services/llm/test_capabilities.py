"""Tests for LLM capability helpers."""

from deeptutor.services.llm.capabilities import (
    get_capability,
    get_effective_temperature,
    has_thinking_tags,
    supports_response_format,
    supports_tools,
    supports_vision,
)


def test_model_override_capability() -> None:
    """Model overrides should take precedence over provider defaults."""
    assert supports_response_format("openai", "deepseek-reasoner") is False
    assert has_thinking_tags("openai", "deepseek-reasoner") is True


def test_gemma_response_format_disabled() -> None:
    """Gemma models do not support json_object response_format (only json_schema/text).

    LM Studio with gemma-4 and similar models returns a 400 error when
    response_format={"type": "json_object"} is used.  See issue #344.
    """
    assert supports_response_format("lm_studio", "gemma-4-e2b") is False
    assert supports_response_format("lm_studio", "gemma-3-4b") is False
    assert supports_response_format("lm_studio", "gemma-2-9b") is False
    # Other non-gemma local models should still support response_format
    assert supports_response_format("lm_studio", "mistral-7b") is True
    assert supports_response_format("lm_studio", "llama-3") is True


def test_capability_fallback_default() -> None:
    """Unknown provider should fall back to defaults and explicit values."""
    assert get_capability("unknown", "supports_streaming") is True
    assert get_capability("unknown", "nonexistent", default=False) is False


def test_effective_temperature_override() -> None:
    """Forced temperature overrides should be applied for reasoning models."""
    assert get_effective_temperature("openai", "gpt-5") == 1.0
    assert get_effective_temperature("openai", "gpt-4o", requested_temp=0.4) == 0.4


def test_openai_codex_provider_is_vision_capable() -> None:
    """The Codex Responses provider accepts image input for its model catalog."""
    assert supports_vision("openai_codex", "gpt-5.6-sol") is True


def test_moonshot_vision_models() -> None:
    """Per Kimi docs the five vision-capable IDs flip supports_vision to True;
    other Moonshot models stay at the binding default (False).

    https://platform.kimi.com/docs/guide/use-kimi-vision-model
    """
    assert supports_vision("moonshot", "moonshot-v1-8k-vision-preview") is True
    assert supports_vision("moonshot", "moonshot-v1-32k-vision-preview") is True
    assert supports_vision("moonshot", "moonshot-v1-128k-vision-preview") is True
    assert supports_vision("moonshot", "kimi-k2.5") is True
    assert supports_vision("moonshot", "kimi-k2.6") is True
    # Text-only Moonshot models stay False
    assert supports_vision("moonshot", "moonshot-v1-8k") is False
    assert supports_vision("moonshot", "kimi-latest") is False


def test_minimax_openai_compat_supports_tools_without_response_format() -> None:
    """MiniMax M-series models support OpenAI-compatible tool calls, but
    the provider still should not receive json_object response_format."""
    # M3 is the current default model (1M-token context window, image input
    # support — note PROVIDER_CAPABILITIES["minimax"]["supports_vision"] is
    # still False while minimax_anthropic's is True).
    assert supports_tools("minimax", "MiniMax-M3") is True
    assert supports_response_format("minimax", "MiniMax-M3") is False
    # M2.7 and M2.7-highspeed remain as alternatives.
    assert supports_tools("minimax", "MiniMax-M2.7") is True
    assert supports_response_format("minimax", "MiniMax-M2.7") is False
    assert supports_tools("minimax", "MiniMax-M2.7-highspeed") is True
    assert supports_response_format("minimax", "MiniMax-M2.7-highspeed") is False


def test_siliconflow_openai_compat_supports_tools_for_deepseek() -> None:
    assert supports_tools("siliconflow", "deepseek-ai/DeepSeek-V4-Pro") is True
    assert supports_response_format("siliconflow", "deepseek-ai/DeepSeek-V4-Pro") is False
    assert has_thinking_tags("siliconflow", "deepseek-ai/DeepSeek-V4-Pro") is True


def test_custom_and_dashscope_openai_compat_support_native_tools_for_qwen() -> None:
    assert supports_tools("custom", "qwen3.6-plus") is True
    assert supports_tools("dashscope", "qwen-plus") is True
    assert has_thinking_tags("custom", "qwen3.6-plus") is True


def test_codebuddy_capabilities_use_agent_sdk_mcp_tools() -> None:
    assert supports_tools("codebuddy", "codebuddy/default") is True
    assert supports_response_format("codebuddy", "codebuddy/default") is False
    assert supports_vision("codebuddy", "codebuddy/default") is False


def test_qwen_model_override_enables_vision() -> None:
    assert supports_vision("dashscope", "qwen-vl-plus") is True
    assert supports_vision("openai", "qwen2.5-vl-72b-instruct") is True
    assert supports_vision("openai", "Qwen/Qwen3-VL-235B-A22B-Instruct") is True
    assert supports_vision("openai", "qwen-plus") is False
    assert supports_vision("openai", "Qwen/Qwen3-235B-A22B-Instruct") is False


def test_claude_model_ids_are_vision_capable() -> None:
    """Anthropic's post-Claude-3 ids are `claude-<family>-<version>`.

    The old "claude-4" override matched no real id, so every model from Sonnet 4
    onward fell through to the binding default and reported no vision support on
    OpenAI-compatible endpoints, including the Anthropic adapter's own default
    model.
    """
    for model in (
        "claude-3-5-sonnet-20241022",
        "claude-sonnet-4-20250514",
        "claude-sonnet-4-6",
        "claude-opus-4-1",
        "claude-opus-4-6",
        "claude-opus-4-7",
        "claude-haiku-4-5-20251001",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-fable-5",
    ):
        assert supports_vision("custom", model) is True, model


def test_claude_override_does_not_leak_to_other_vendors() -> None:
    assert supports_vision("custom", "gpt-3.5-turbo") is False
    assert supports_vision("lm_studio", "gemma-2-9b") is False


def test_kimi_k3_is_vision_capable() -> None:
    """Kimi K3 is natively multimodal, like the K2.5/K2.6 entries above it."""
    assert supports_vision("moonshot", "kimi-k3") is True
    assert supports_vision("custom", "kimi-k3") is True


def test_qwen38_max_enables_vision_without_legacy_vl_suffix() -> None:
    """Qwen3.8-Max is multimodal despite not carrying the legacy ``-vl`` suffix."""
    assert supports_vision("dashscope", "qwen3.8-max") is True
