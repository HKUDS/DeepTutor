"""Explicit prompt-cache breakpoints for GPT-5.6+ on the native Responses API.

The answer loop appends the runtime snapshot and the learner's message as
consecutive user items. GPT-5.6+ implicit caching only writes a breakpoint at
the end of the latest eligible message, so that trailing block never matches
the previous turn. One explicit breakpoint before the trailing block makes the
durable history reusable again (#2297).
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider
from deeptutor.services.llm.provider_core.openai_responses import (
    mark_stable_history_breakpoint,
    supports_explicit_prompt_cache,
)
from deeptutor.services.provider_registry import find_by_name

_MESSAGES: list[dict[str, Any]] = [
    {"role": "system", "content": "You are DeepTutor."},
    {"role": "user", "content": "First question"},
    {"role": "assistant", "content": "First answer"},
    {"role": "user", "content": "[Runtime context: workspace]\nCurrent turn"},
    {"role": "user", "content": "Second question"},
]


def _provider(spec_name: str, base_url: str, model: str) -> OpenAICompatProvider:
    provider = OpenAICompatProvider(
        api_key="test-key",
        api_base=base_url,
        default_model=model,
        spec=find_by_name(spec_name),
        provider_name=spec_name,
    )

    provider._prompt_cache_options_supported = True
    return provider


def test_sdk_without_explicit_cache_support_omits_breakpoints():
    provider = _provider("openai", "https://api.openai.com/v1", "gpt-6")
    provider._prompt_cache_options_supported = False
    assert "prompt_cache_options" not in _body(provider, "gpt-6")


def _body(provider: OpenAICompatProvider, model: str) -> dict[str, Any]:
    return provider._build_responses_body(_MESSAGES, None, model, 256, 0.7, None, None)


def test_gpt_6_marks_the_last_durable_user_message() -> None:
    provider = _provider("openai", "https://api.openai.com/v1", "gpt-6.1-terra")

    body = _body(provider, "gpt-6.1-terra")

    assert body["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    items = body["input"]
    first_user = next(
        item for item in items if item.get("content", [{}])[0].get("text") == "First question"
    )
    assert first_user["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    # The transient snapshot and the current message stay outside the breakpoint.
    trailing = [item for item in items if item is not first_user and item.get("role") == "user"]
    assert all(
        "prompt_cache_breakpoint" not in block
        for item in trailing
        for block in item.get("content", [])
    )


def test_breakpoint_window_keeps_the_previous_turn_discoverable() -> None:
    provider = _provider("openai", "https://api.openai.com/v1", "gpt-6.1-terra")
    messages: list[dict[str, Any]] = [{"role": "system", "content": "You are DeepTutor."}]
    for index in range(6):
        messages.append({"role": "user", "content": f"question {index}"})
        messages.append({"role": "assistant", "content": f"answer {index}"})
    messages.append({"role": "user", "content": "[Runtime context: workspace]\nsnapshot"})
    messages.append({"role": "user", "content": "current"})

    body = provider._build_responses_body(messages, None, "gpt-6.1-terra", 256, 0.7, None, None)

    marked = {
        block["text"]
        for item in body["input"]
        for block in item.get("content", [])
        if "prompt_cache_breakpoint" in block
    }
    assert marked == {"question 2", "question 3", "question 4", "question 5"}


def test_older_model_keeps_implicit_caching() -> None:
    provider = _provider("openai", "https://api.openai.com/v1", "gpt-5.5")

    body = _body(provider, "gpt-5.5")

    assert "prompt_cache_options" not in body


def test_non_openai_endpoint_keeps_implicit_caching() -> None:
    provider = _provider("deepseek", "https://api.deepseek.com", "gpt-6.1-terra")

    body = _body(provider, "gpt-6.1-terra")

    assert "prompt_cache_options" not in body


def test_first_turn_keeps_implicit_caching() -> None:
    provider = _provider("openai", "https://api.openai.com/v1", "gpt-6.1-terra")
    messages = [
        {"role": "system", "content": "You are DeepTutor."},
        {"role": "user", "content": "Only question"},
    ]

    body = provider._build_responses_body(messages, None, "gpt-6.1-terra", 256, 0.7, None, None)

    assert "prompt_cache_options" not in body


@pytest.mark.asyncio
async def test_prompt_cache_rejection_retries_without_the_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider("openai", "https://api.openai.com/v1", "gpt-6.1-terra")
    body = _body(provider, "gpt-6.1-terra")
    seen: list[dict[str, Any]] = []

    class Rejected(Exception):
        status_code = 400
        body = {"error": {"message": "Unknown parameter: prompt_cache_options"}}

    async def fake_create(_create: Any, request_body: dict[str, Any]) -> Any:
        seen.append(request_body)
        if len(seen) == 1:
            raise Rejected()
        return {"ok": True}

    monkeypatch.setattr(provider, "_create_with_key_rotation", fake_create)

    assert await provider._create_responses_with_status_retry(body) == {"ok": True}
    assert "prompt_cache_options" not in seen[1]
    assert all(
        "prompt_cache_breakpoint" not in block
        for item in seen[1]["input"]
        for block in item.get("content", [])
    )
    assert provider._supports_explicit_prompt_cache("gpt-6.1-terra") is False


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5.6", True),
        ("gpt-5.6-codex", True),
        ("gpt-6", True),
        ("openai/gpt-6.1-terra", True),
        ("gpt-5.5", False),
        ("gpt-5.1-codex", False),
        ("claude-sonnet-4", False),
        ("", False),
    ],
)
def test_explicit_cache_model_gate(model: str, expected: bool) -> None:
    assert supports_explicit_prompt_cache(model) is expected


def test_breakpoint_requires_a_durable_user_message() -> None:
    assert mark_stable_history_breakpoint([]) is False
    assert (
        mark_stable_history_breakpoint(
            [{"role": "user", "content": [{"type": "input_text", "text": "only"}]}]
        )
        is False
    )
