"""Reasoning-content handling for OpenAI-compatible providers."""

from __future__ import annotations

import hashlib
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


def test_services_deepseek_v4_flash_disables_thinking_by_default() -> None:
    kwargs = _build_services_kwargs(
        "deepseek",
        None,
        model="deepseek-v4-flash",
    )

    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_openai_binding_deepseek_v4_flash_disables_thinking_by_default() -> None:
    """#1058: openai binding pointed at DeepSeek must still disable flash thinking."""
    kwargs = _build_services_kwargs(
        "openai",
        None,
        model="deepseek-v4-flash",
    )

    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


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


@pytest.mark.parametrize(
    ("responses", "include_state", "preserve_id"),
    [(False, True, False), (True, False, False), (True, True, True)],
)
def test_tool_id_sanitization_is_scoped_to_responses_replay(
    responses: bool,
    include_state: bool,
    preserve_id: bool,
) -> None:
    raw_id = "call_1|fc_1"
    assistant = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": raw_id,
                "type": "function",
                "function": {"name": "rag", "arguments": "{}"},
            }
        ],
    }
    if include_state:
        assistant["_responses_output_items"] = [{"type": "reasoning", "id": "rs_1"}]
    messages = [
        assistant,
        {"role": "tool", "tool_call_id": raw_id, "content": "context"},
    ]
    provider = ServicesOpenAICompatProvider.__new__(ServicesOpenAICompatProvider)

    sanitized = provider._sanitize_messages(messages, responses=responses)

    expected_id = raw_id if preserve_id else hashlib.sha256(raw_id.encode()).hexdigest()[:9]
    assert sanitized[0]["tool_calls"][0]["id"] == expected_id
    assert sanitized[1]["tool_call_id"] == expected_id
    assert ("_responses_output_items" in sanitized[0]) is preserve_id
