"""Reasoning-content handling for OpenAI-compatible providers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.services.llm.provider_core.openai_compat_provider import (
    OpenAICompatProvider as ServicesOpenAICompatProvider,
)
from deeptutor.services.provider_registry import find_by_name as find_service_provider
from deeptutor.tutorbot.providers.openai_compat_provider import (
    OpenAICompatProvider as TutorBotOpenAICompatProvider,
)
from deeptutor.tutorbot.providers.registry import find_by_name as find_tutorbot_provider


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
    [ServicesOpenAICompatProvider, TutorBotOpenAICompatProvider],
)
def test_parse_keeps_reasoning_content_out_of_visible_content(provider_cls) -> None:
    provider = provider_cls.__new__(provider_cls)

    response = provider._parse(_response_with_reasoning_only())

    assert response.content is None
    assert response.reasoning_content == "internal reasoning"


@pytest.mark.parametrize(
    "provider_cls",
    [ServicesOpenAICompatProvider, TutorBotOpenAICompatProvider],
)
def test_parse_chunks_keeps_reasoning_content_out_of_visible_content(provider_cls) -> None:
    response = provider_cls._parse_chunks([_reasoning_only_chunk()])

    assert response.content is None
    assert response.reasoning_content == "internal reasoning"


def _build_services_kwargs(provider_name: str, reasoning_effort: str) -> dict:
    provider = ServicesOpenAICompatProvider.__new__(ServicesOpenAICompatProvider)
    provider.default_model = "deepseek-v4-pro"
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


def _build_tutorbot_kwargs(provider_name: str, reasoning_effort: str) -> dict:
    provider = TutorBotOpenAICompatProvider.__new__(TutorBotOpenAICompatProvider)
    provider.default_model = "deepseek-v4-pro"
    provider._spec = find_tutorbot_provider(provider_name)
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


def test_services_dashscope_minimal_reasoning_uses_enable_thinking_only() -> None:
    kwargs = _build_services_kwargs("dashscope", "minimal")

    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"] == {"enable_thinking": False}


def test_tutorbot_provider_minimal_reasoning_uses_extra_body_only() -> None:
    kwargs = _build_tutorbot_kwargs("deepseek", "minimal")

    assert "reasoning_effort" not in kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
