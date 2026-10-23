from __future__ import annotations

import copy
import dataclasses
import json
import logging
from typing import Any

import pytest

from deeptutor.agents.loop.pipeline import CONTEXT_WINDOW_GUARD_RATIO, AgenticLoopPipeline
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.session.context_builder import _count_model_context_tokens, count_tokens

WINDOW = 8192
BUDGET = int(WINDOW * CONTEXT_WINDOW_GUARD_RATIO)


def _text(tokens: int) -> str:
    """Prose that costs about ``tokens`` under the counter the guard uses."""
    unit = "alpha beta gamma delta "
    per_unit = count_tokens(unit * 100) / 100  # repeated units merge tokens at the seams
    return unit * max(1, round(tokens / per_unit))


def _pipeline() -> AgenticLoopPipeline:
    pipeline = AgenticLoopPipeline(language="en")
    pipeline.llm_config = dataclasses.replace(pipeline.llm_config, context_window=WINDOW)
    return pipeline


def _exec_round(index: int, *, arguments_tokens: int, result_tokens: int) -> list[dict[str, Any]]:
    call_id = f"call-{index}"
    arguments = json.dumps({"command": _text(arguments_tokens)})
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "exec", "arguments": arguments},
                }
            ],
        },
        {"role": "tool", "tool_call_id": call_id, "content": _text(result_tokens)},
    ]


def _snipped(pipeline: AgenticLoopPipeline, messages: list[dict[str, Any]]) -> list[bool]:
    marker = pipeline._tool_result_snip_marker()
    return [msg["content"] == marker for msg in messages if msg["role"] == "tool"]


@pytest.mark.asyncio
async def test_guard_counts_tool_call_arguments_and_trims_oldest_results_first() -> None:
    pipeline = _pipeline()
    messages: list[dict[str, Any]] = [{"role": "user", "content": "Plot the projectile ranges."}]
    for index in range(3):
        messages += _exec_round(index, arguments_tokens=1400, result_tokens=2000)
    arguments_before = [msg["tool_calls"] for msg in messages if msg["role"] == "assistant"]

    await pipeline._guard_context_window(messages, StreamBus())

    assert _snipped(pipeline, messages) == [True, True, False]
    assert [msg["tool_calls"] for msg in messages if msg["role"] == "assistant"] == arguments_before
    assert pipeline._estimate_messages_tokens(messages) <= BUDGET


@pytest.mark.asyncio
async def test_guard_counts_the_tool_schemas_the_request_carries() -> None:
    pipeline = _pipeline()
    messages: list[dict[str, Any]] = [{"role": "user", "content": "Summarise the figures."}]
    for index in range(2):
        messages += _exec_round(index, arguments_tokens=10, result_tokens=1500)
    schemas = [
        {
            "type": "function",
            "function": {
                "name": f"tool_{index}",
                "description": _text(1000),
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for index in range(6)
    ]

    await pipeline._guard_context_window(messages, StreamBus(), tool_schemas=schemas)

    assert _snipped(pipeline, messages) == [True, True]
    fitted = pipeline._estimate_messages_tokens(messages) + _count_model_context_tokens(schemas)
    assert fitted <= BUDGET


def test_estimate_counts_tool_call_arguments_like_history_planning() -> None:
    messages = _exec_round(0, arguments_tokens=1500, result_tokens=20)
    arguments = messages[0]["tool_calls"][0]["function"]["arguments"]

    estimate = AgenticLoopPipeline._estimate_messages_tokens(messages)

    assert estimate >= count_tokens(arguments)
    assert estimate == sum(_count_model_context_tokens(msg) for msg in messages)


@pytest.mark.asyncio
async def test_guard_warns_and_proceeds_when_nothing_is_left_to_trim(caplog) -> None:
    pipeline = _pipeline()
    messages: list[dict[str, Any]] = [{"role": "user", "content": _text(BUDGET + 1000)}]
    before = copy.deepcopy(messages)
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="deeptutor.agents.loop.pipeline"):
        await pipeline._guard_context_window(messages, StreamBus())

    assert messages == before
    assert any(
        "no tool results are left to trim" in record.getMessage() for record in caplog.records
    )


@pytest.mark.asyncio
async def test_guard_leaves_a_request_that_fits_alone(caplog) -> None:
    pipeline = _pipeline()
    messages: list[dict[str, Any]] = [{"role": "user", "content": "Hi"}]
    messages += _exec_round(0, arguments_tokens=50, result_tokens=50)
    before = copy.deepcopy(messages)
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="deeptutor.agents.loop.pipeline"):
        await pipeline._guard_context_window(messages, StreamBus())

    assert messages == before
    assert not caplog.records
