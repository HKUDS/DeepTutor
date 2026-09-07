"""Reasoning-content handling for OpenAI-compatible providers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.services.llm.provider_core.openai_compat_provider import (
    OpenAICompatProvider as ServicesOpenAICompatProvider,
)
from deeptutor.services.provider_registry import find_by_name as find_service_provider


def _response_with_reasoning_only():
    message = SimpleNamespace(
        content=None,
        reasoning_content="internal reasoning",
        reasoning=None,
        tool_calls=None,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="stop")],
    )


def _reasoning_only_chunk():
    delta = SimpleNamespace(
        content=None,
        reasoning_content="internal reasoning",
        reasoning=None,
        tool_calls=[],
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason="stop")],
    )


@pytest.mark.parametrize(
    "provider_cls",
    [ServicesOpenAICompatProvider],
)
def test_parse_keeps_reasoning_content_out_of_visible_content(provider_cls) -> None:
    provider = provider_cls.__new__(provider_cls)

    response = provider._parse(_response_with_reasoning_only())

    assert response.content is None
    assert response.reasoning_content == "internal reasoning"


@pytest.mark.parametrize(
    "provider_cls",
    [ServicesOpenAICompatProvider],
)
def test_parse_chunks_keeps_reasoning_content_out_of_visible_content(provider_cls) -> None:
    response = provider_cls._parse_chunks([_reasoning_only_chunk()])

    assert response.content is None
    assert response.reasoning_content == "internal reasoning"


def _build_services_kwargs(
    provider_name: str,
    reasoning_effort: str | None,
    *,
    model: str = "deepseek-v4-pro",
) -> dict:
    provider = ServicesOpenAICompatProvider.__new__(ServicesOpenAICompatProvider)
    provider.default_model = model
    provider._spec = find_service_provider(provider_name)
    return provider._build_kwargs(
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        model=None,
        max_tokens=32,
        temperature=0.7,
        reasoning_effort=reasoning_effort,
        tool_choice=None,
    )


def test_services_provider_minimal_reasoning_uses_extra_body_only() -> None:
    kwargs = _build_services_kwargs("deepseek", "minimal")

    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


@pytest.mark.parametrize("binding", ["deepseek", "openai"])
def test_deepseek_v4_flash_is_left_to_its_own_default(binding: str) -> None:
    """We no longer switch flash's thinking off, on any binding.

    It used to be disabled to dodge the mid-conversation ``reasoning_content
    must be passed back`` 400 (#1058). What actually fixes that is echoing the
    previous round's reasoning on the assistant turn that issued the tool calls
    — see ``test_assistant_message_with_tool_calls_replays_reasoning_content``, which is the
    test that guards #1058. Disabling thinking as well bought nothing and cost
    every flash user their whole reasoning stream, so the request now says
    nothing about thinking and the provider applies its own default (on).
    """
    kwargs = _build_services_kwargs(binding, None, model="deepseek-v4-flash")

    assert "reasoning_effort" not in kwargs
    assert "extra_body" not in kwargs


def test_openai_binding_deepseek_v4_pro_enables_thinking_by_default() -> None:
    kwargs = _build_services_kwargs(
        "openai",
        None,
        model="deepseek-v4-pro",
    )

    assert kwargs["reasoning_effort"] == "high"
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}


def test_services_deepseek_v4_pro_enables_thinking_by_default() -> None:
    kwargs = _build_services_kwargs("deepseek", None)

    assert kwargs["reasoning_effort"] == "high"
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}


def test_services_deepseek_replays_persisted_reasoning_content() -> None:
    provider = ServicesOpenAICompatProvider.__new__(ServicesOpenAICompatProvider)
    provider.default_model = "deepseek-v4-pro"
    provider._spec = find_service_provider("deepseek")

    kwargs = provider._build_kwargs(
        messages=[
            {
                "role": "assistant",
                "content": "previous answer",
                "_provider_response_state": {"reasoning_content": "private reasoning"},
            },
            {"role": "user", "content": "next question"},
        ],
        tools=None,
        model=None,
        max_tokens=32,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assistant_message = kwargs["messages"][0]
    assert assistant_message["reasoning_content"] == "private reasoning"
    assert "_provider_response_state" not in assistant_message


def test_non_deepseek_drops_persisted_reasoning_content() -> None:
    provider = ServicesOpenAICompatProvider.__new__(ServicesOpenAICompatProvider)
    provider.default_model = "gpt-test"
    provider._spec = find_service_provider("openai")

    kwargs = provider._build_kwargs(
        messages=[
            {
                "role": "assistant",
                "content": "previous answer",
                "_provider_response_state": {"reasoning_content": "private reasoning"},
            }
        ],
        tools=None,
        model="gpt-test",
        max_tokens=32,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert "reasoning_content" not in kwargs["messages"][0]
    assert "_provider_response_state" not in kwargs["messages"][0]


def test_responses_body_replays_persisted_native_output_items() -> None:
    provider = ServicesOpenAICompatProvider.__new__(ServicesOpenAICompatProvider)
    provider.default_model = "gpt-test"
    provider._spec = find_service_provider("openai")
    native_items = [{"type": "reasoning", "id": "rs_1", "summary": []}]

    body = provider._build_responses_body(
        messages=[
            {
                "role": "assistant",
                "content": "previous answer",
                "_provider_response_state": {"responses_output_items": native_items},
            }
        ],
        tools=None,
        model="gpt-test",
        max_tokens=32,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )

    assert body["input"] == native_items


def test_services_dashscope_minimal_reasoning_uses_enable_thinking_only() -> None:
    kwargs = _build_services_kwargs("dashscope", "minimal")

    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"] == {"enable_thinking": False}


def test_services_custom_qwen_enables_thinking_without_top_level_effort() -> None:
    kwargs = _build_services_kwargs(
        "custom",
        None,
        model="qwen3.6-plus",
    )

    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"] == {"enable_thinking": True}


@pytest.mark.parametrize(
    "model",
    [
        "kimi-k3",
        "kimi-k2.7-code",
        "kimi-k2.7-code-highspeed",
        "kimi-k2.6",
        "kimi-k2.5",
        "kimi-latest",
    ],
)
def test_services_moonshot_kimi_drops_temperature(model: str) -> None:
    # Kimi models reject any explicit temperature (HTTP 400 "only 1 is
    # allowed for this model"); the parameter must be omitted entirely.
    kwargs = _build_services_kwargs("moonshot", None, model=model)

    assert "temperature" not in kwargs


def test_services_moonshot_v1_keeps_temperature() -> None:
    # The tunable moonshot-v1-* series must still receive the caller's value.
    kwargs = _build_services_kwargs("moonshot", None, model="moonshot-v1-8k")

    assert kwargs["temperature"] == 0.7
