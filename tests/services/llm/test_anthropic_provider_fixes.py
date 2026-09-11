"""Regression tests for Anthropic provider support of newer Claude models.

Covers three fixes:
1. A ``base_url`` ending in ``/v1`` must not be doubled by the SDK.
2. ``temperature`` is omitted for effort-based models that reject it.
3. ``cache_control`` breakpoints never exceed the Anthropic limit of 4.
"""

from __future__ import annotations

from typing import Any

import pytest

# Constructing AnthropicProvider imports the optional `anthropic` SDK ([cli]
# extra) — skip cleanly where it isn't installed (e.g. the CI python-tests job).
pytest.importorskip("anthropic")

from deeptutor.services.llm.provider_core.anthropic_provider import AnthropicProvider


def _provider(model: str = "claude-opus-4-8", api_base: str | None = None) -> AnthropicProvider:
    return AnthropicProvider(api_key="test-key", api_base=api_base, default_model=model)


def test_base_url_trailing_v1_is_not_doubled() -> None:
    # The SDK appends its own `/v1/...`; a base_url of `.../v1` would 404.
    provider = _provider(api_base="https://api.anthropic.com/v1")
    assert str(provider._client.base_url).rstrip("/") == "https://api.anthropic.com"


def test_base_url_without_v1_is_preserved() -> None:
    provider = _provider(api_base="https://proxy.example.com/anthropic")
    assert str(provider._client.base_url).rstrip("/") == "https://proxy.example.com/anthropic"


def _kwargs(provider: AnthropicProvider, model: str) -> dict[str, Any]:
    return provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model=model,
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )


def test_temperature_omitted_for_effort_based_models() -> None:
    provider = _provider()
    for model in (
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-opus-4-7",
        "claude-fable-5",
    ):
        assert "temperature" not in _kwargs(provider, model), model


def test_temperature_kept_for_models_that_accept_it() -> None:
    provider = _provider()
    # Opus 4.6 / Sonnet 4.6 still accept temperature — omitting it there
    # would silently drop the user's configured setting.
    #
    # anthropic-sdk-python >= 1.0 dropped `temperature` from the explicit
    # signature of `messages.create()` / `messages.stream()`; we tunnel it
    # through `extra_body` so it still reaches the Anthropic API as a
    # top-level request field. See test_temperature_is_routed_via_extra_body.
    for model in (
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-sonnet-4-5-20250929",
        "claude-haiku-4-5-20251001",
        "claude-opus-4-1",
    ):
        kw = _kwargs(provider, model)
        assert "temperature" not in kw, model
        assert kw.get("extra_body", {}).get("temperature") == 0.7, model


def test_temperature_is_routed_via_extra_body() -> None:
    """SDK >= 1.0 rejects ``temperature`` as a top-level kwarg.

    AnthropicProvider must therefore place it under ``extra_body`` instead,
    so the Anthropic API still receives it as a request-level field.
    """
    provider = _provider()
    kw = _kwargs(provider, "claude-sonnet-4-6")
    # No `temperature` at the top level — that's what the SDK rejects.
    assert "temperature" not in kw
    # But it lives in extra_body so the wire payload still carries it.
    assert kw["extra_body"]["temperature"] == 0.7


def test_temperature_is_routed_via_extra_body_for_thinking_models() -> None:
    """Older model families force ``temperature=1.0`` for extended thinking.

    anthropic-sdk-python >= 1.0 dropped ``temperature`` from the explicit
    signature of ``messages.create`` / ``messages.stream``; we tunnel it
    through ``extra_body`` so the Anthropic API still receives it as a
    top-level request field.
    """
    provider = _provider()
    kwargs = _kwargs_with_effort(provider, "claude-opus-4-6", "high")
    assert "temperature" not in kwargs
    assert kwargs["extra_body"]["temperature"] == 1.0


def _count_cache_control(system: Any, messages: list[dict[str, Any]], tools: list) -> int:
    s, msgs, tls = AnthropicProvider._apply_cache_control(system, messages, tools)
    total = 0
    if isinstance(s, list):
        total += sum("cache_control" in b for b in s)
    for m in msgs:
        c = m.get("content")
        if isinstance(c, list):
            total += sum("cache_control" in b for b in c)
    if tls:
        total += sum("cache_control" in t for t in tls)
    return total


def test_cache_control_never_exceeds_four() -> None:
    messages = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    for n_tools in (0, 1, 5, 12, 15, 25, 40):
        tools = [{"name": f"t{i}", "description": "d", "input_schema": {}} for i in range(n_tools)]
        assert _count_cache_control("system prompt", messages, tools) <= 4, n_tools


def _kwargs_with_effort(provider: AnthropicProvider, model: str, effort: str) -> dict[str, Any]:
    return provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model=model,
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort=effort,
        tool_choice=None,
    )


def test_effort_based_families_map_real_effort_to_adaptive_thinking() -> None:
    """Opus 4.7+/Opus 5/Sonnet 5/Fable 5 reject enabled+budget_tokens with a
    400 — a configured effort level must become adaptive thinking there."""
    provider = _provider()
    for model in (
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-opus-4-7",
        "claude-fable-5",
    ):
        kwargs = _kwargs_with_effort(provider, model, "high")
        assert kwargs["thinking"] == {"type": "adaptive"}, model
        assert "temperature" not in kwargs, model
        assert kwargs["max_tokens"] == 1024, model  # no budget headroom inflation


def test_effort_based_families_omit_thinking_for_off_sentinels() -> None:
    provider = _provider()
    kwargs = _kwargs_with_effort(provider, "claude-opus-4-8", "minimal")
    assert "thinking" not in kwargs
    assert "temperature" not in kwargs


def test_older_models_keep_budget_tokens_thinking() -> None:
    provider = _provider()
    kwargs = _kwargs_with_effort(provider, "claude-opus-4-6", "high")
    assert kwargs["thinking"]["type"] == "enabled"
    assert kwargs["thinking"]["budget_tokens"] >= 8192
    assert "temperature" not in kwargs  # SDK 1.x: must live in extra_body
    assert kwargs["extra_body"]["temperature"] == 1.0


def test_older_models_omit_thinking_for_off_sentinels() -> None:
    """An off-sentinel used to fall through to the budget branch, where an
    unrecognised value means "default budget" — so `none` turned thinking ON."""
    provider = _provider()
    for effort in ("none", "minimal", "minimum"):
        kwargs = _kwargs_with_effort(provider, "claude-opus-4-6", effort)
        assert "thinking" not in kwargs, effort
        assert "temperature" not in kwargs, effort
        assert kwargs["extra_body"]["temperature"] == 0.7, effort


def test_older_models_translate_adaptive_into_budget_thinking() -> None:
    """The older families reject `thinking: {type: adaptive}`, so a stored
    adaptive selection has to land on the budget form instead of a 400."""
    provider = _provider()
    kwargs = _kwargs_with_effort(provider, "claude-sonnet-4-5", "adaptive")
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 4096}
    assert "temperature" not in kwargs  # SDK 1.x: must live in extra_body
    assert kwargs["extra_body"]["temperature"] == 1.0


def test_off_sentinels_leave_tool_choice_to_the_caller() -> None:
    """Extended thinking forces tool_choice=auto; thinking-off must not."""
    provider = _provider()
    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"function": {"name": "t", "description": "", "parameters": {}}}],
        model="claude-opus-4-6",
        max_tokens=1024,
        temperature=0.7,
        reasoning_effort="none",
        tool_choice="required",
    )
    assert kwargs["tool_choice"] == {"type": "any"}


def _signed_block(signature: str = "sig-1") -> dict[str, Any]:
    return {"type": "thinking", "thinking": "weighing it", "signature": signature}


def test_assistant_blocks_replay_thinking_from_the_message() -> None:
    """A round still in this turn's working set carries the blocks directly."""
    blocks = AnthropicProvider._assistant_blocks(
        {
            "role": "assistant",
            "content": "the answer",
            "thinking_blocks": [_signed_block()],
        }
    )

    assert blocks[0] == {
        "type": "thinking",
        "thinking": "weighing it",
        "signature": "sig-1",
    }
    assert blocks[1] == {"type": "text", "text": "the answer"}


def test_assistant_blocks_replay_thinking_rebuilt_from_history() -> None:
    """A round rebuilt from history carries them in the private state.

    That is where they are persisted, so reading only the message field meant
    every reloaded conversation replayed without its signatures.
    """
    blocks = AnthropicProvider._assistant_blocks(
        {
            "role": "assistant",
            "content": "the answer",
            "_provider_response_state": {"thinking_blocks": [_signed_block("sig-2")]},
        }
    )

    assert blocks[0]["signature"] == "sig-2"


def test_assistant_blocks_prefer_the_live_message_over_history() -> None:
    blocks = AnthropicProvider._assistant_blocks(
        {
            "role": "assistant",
            "content": "the answer",
            "thinking_blocks": [_signed_block("live")],
            "_provider_response_state": {"thinking_blocks": [_signed_block("stale")]},
        }
    )

    assert blocks[0]["signature"] == "live"


def test_assistant_blocks_omit_unsigned_history_blocks() -> None:
    """An unsigned replay is rejected by the API, so it is not sent."""
    blocks = AnthropicProvider._assistant_blocks(
        {
            "role": "assistant",
            "content": "the answer",
            "_provider_response_state": {
                "thinking_blocks": [{"type": "thinking", "thinking": "weighing it"}]
            },
        }
    )

    assert all(block.get("type") != "thinking" for block in blocks)
