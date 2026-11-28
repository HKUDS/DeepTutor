"""Explicit prompt-cache breakpoints for GPT-5.6+ on the native Responses API.

The answer loop appends the runtime snapshot and the learner's message as
consecutive user items. GPT-5.6+ implicit caching only writes a breakpoint at
the end of the latest eligible message, so that trailing block never matches
the previous turn. One explicit breakpoint before the trailing block makes the
durable history reusable again (#2297).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.runtime.agentic import client as agentic_client
from deeptutor.services.llm.capabilities import threads_session_id
from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider
from deeptutor.services.llm.provider_core.openai_responses import (
    build_prompt_cache_key,
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


def test_custom_responses_endpoint_sets_session_scoped_prompt_cache_key() -> None:
    provider = _provider("custom", "https://gateway.example/v1", "gpt-6.2-sol")

    body_a1 = provider._build_responses_body(
        _MESSAGES[:3],
        None,
        "gpt-6.2-sol",
        256,
        0.7,
        None,
        None,
        session_id="session-alpha",
    )
    body_a2 = provider._build_responses_body(
        _MESSAGES,
        None,
        "gpt-6.2-sol",
        256,
        0.7,
        None,
        None,
        session_id="session-alpha",
    )
    body_b = provider._build_responses_body(
        _MESSAGES,
        None,
        "gpt-6.2-sol",
        256,
        0.7,
        None,
        None,
        session_id="session-beta",
    )

    assert "prompt_cache_options" not in body_a1
    assert body_a1["prompt_cache_key"] == build_prompt_cache_key(_MESSAGES, "session-alpha")
    assert body_a1["prompt_cache_key"] == body_a2["prompt_cache_key"]
    assert body_a1["prompt_cache_key"] != body_b["prompt_cache_key"]
    assert "session-alpha" not in body_a1["prompt_cache_key"]


def test_prompt_cache_key_falls_back_to_leading_system_message() -> None:
    provider = _provider("custom", "https://gateway.example/v1", "gpt-6.2-sol")
    turn1 = [{"role": "system", "content": "You are DeepTutor."}, {"role": "user", "content": "hi"}]
    turn2 = [
        {"role": "system", "content": "You are DeepTutor."},
        {"role": "system", "content": "[Context checkpoint]\nsummary updated"},
        {"role": "user", "content": "next"},
    ]

    key1 = provider._build_responses_body(turn1, None, "gpt-6.2-sol", 256, 0.7, None, None)[
        "prompt_cache_key"
    ]
    key2 = provider._build_responses_body(turn2, None, "gpt-6.2-sol", 256, 0.7, None, None)[
        "prompt_cache_key"
    ]

    assert key1 == key2 == build_prompt_cache_key(turn1)


def test_sdk_without_prompt_cache_key_support_omits_key() -> None:
    provider = _provider("custom", "https://gateway.example/v1", "gpt-6.2-sol")
    provider._prompt_cache_key_supported = False

    body = _body(provider, "gpt-6.2-sol")

    assert "prompt_cache_key" not in body


@pytest.mark.asyncio
async def test_prompt_cache_key_rejection_retries_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider("custom", "https://gateway.example/v1", "gpt-6.2-sol")
    body = provider._build_responses_body(
        _MESSAGES,
        None,
        "gpt-6.2-sol",
        256,
        0.7,
        None,
        None,
        session_id="session-retry",
    )
    assert "prompt_cache_key" in body
    seen: list[dict[str, Any]] = []

    class Rejected(Exception):
        status_code = 400
        body = {"error": {"message": "Unknown parameter: prompt_cache_key"}}

    async def fake_create(_create: Any, request_body: dict[str, Any]) -> Any:
        seen.append(request_body)
        if len(seen) == 1:
            raise Rejected()
        return {"ok": True}

    monkeypatch.setattr(provider, "_create_with_key_rotation", fake_create)

    assert await provider._create_responses_with_status_retry(body) == {"ok": True}
    assert "prompt_cache_key" not in seen[1]
    assert provider._supports_prompt_cache_key("gpt-6.2-sol") is False
    assert "prompt_cache_key" not in provider._build_responses_body(
        _MESSAGES,
        None,
        "gpt-6.2-sol",
        256,
        0.7,
        None,
        None,
        session_id="session-retry",
    )


@pytest.mark.asyncio
async def test_responses_client_threads_session_id_into_prompt_cache_key_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    class FakeResponses:
        async def create(self, **kwargs: Any) -> Any:
            captured.append(dict(kwargs))

            async def events():
                yield SimpleNamespace(
                    type="response.output_text.delta",
                    delta="ok",
                )
                yield SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(status="completed", usage=None),
                )

            return events()

    class UnexpectedChatCompletions:
        async def create(self, **_kwargs: Any) -> Any:
            raise AssertionError("forced Responses mode must not call chat completions")

    class FakeOpenAI:
        def __init__(self, **_kwargs: Any) -> None:
            self.responses = FakeResponses()
            self.chat = SimpleNamespace(completions=UnexpectedChatCompletions())

        async def close(self) -> None:
            pass

    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.openai_compat_provider.AsyncOpenAI",
        FakeOpenAI,
    )
    client = agentic_client._build_openai_client(
        agentic_client.LLMClientConfig(
            binding="custom",
            model="gpt-6.2-sol",
            api_key="test-key",
            base_url="https://gateway.example/v1",
            wire_api="responses",
        ),
        disable_ssl_verify=False,
    )

    assert threads_session_id("custom", wire_api="responses") is True
    assert threads_session_id("custom") is False
    assert getattr(client, "_threads_session_id", False) is True

    stream = await client.chat.completions.create(
        model="gpt-6.2-sol",
        messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        stream=True,
        deeptutor_session_id="unified_chat_42",
    )
    _chunks = [chunk async for chunk in stream]

    assert len(captured) == 1
    assert captured[0]["prompt_cache_key"] == build_prompt_cache_key([], "unified_chat_42")
    assert "deeptutor_session_id" not in captured[0]


@pytest.mark.asyncio
async def test_chat_completions_client_strips_deeptutor_session_id() -> None:
    seen: list[dict[str, Any]] = []

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            seen.append(dict(kwargs))
            return {"ok": True}

    raw_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    wrapped = agentic_client._sanitize_chat_client(raw_client)

    await wrapped.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        deeptutor_session_id="should-not-leak",
    )

    assert len(seen) == 1
    assert "deeptutor_session_id" not in seen[0]


@pytest.mark.asyncio
async def test_openai_compat_strips_session_id_on_chat_completions() -> None:
    provider = _provider("custom", "https://gateway.example/v1", "gpt-4o")
    seen: list[dict[str, Any]] = []

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            seen.append(dict(kwargs))
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="ok", tool_calls=[]),
                        finish_reason="stop",
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12),
            )

    provider._client = SimpleNamespace(
        responses=SimpleNamespace(),
        chat=SimpleNamespace(completions=FakeCompletions()),
    )

    resp = await provider.chat(
        [{"role": "user", "content": "hi"}],
        model="gpt-4o",
        deeptutor_session_id="unified_chat_99",
    )

    assert resp.content == "ok"
    assert len(seen) == 1
    assert "deeptutor_session_id" not in seen[0]


@pytest.mark.asyncio
async def test_openai_compat_stream_strips_session_id_on_chat_completions() -> None:
    provider = _provider("custom", "https://gateway.example/v1", "gpt-4o")
    seen: list[dict[str, Any]] = []

    class FakeCompletions:
        async def create(self, **kwargs: Any) -> Any:
            seen.append(dict(kwargs))

            async def chunks():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="ok", tool_calls=None),
                            finish_reason="stop",
                        )
                    ],
                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12),
                )

            return chunks()

    provider._client = SimpleNamespace(
        responses=SimpleNamespace(),
        chat=SimpleNamespace(completions=FakeCompletions()),
    )

    resp = await provider.chat_stream(
        [{"role": "user", "content": "hi"}],
        model="gpt-4o",
        deeptutor_session_id="unified_chat_99",
    )

    assert resp.content == "ok"
    assert len(seen) == 1
    assert "deeptutor_session_id" not in seen[0]
