from __future__ import annotations

from collections.abc import AsyncIterator
import logging
from typing import Any

import pytest

from deeptutor.agents.math_animator.agents.code_generator_agent import (
    _MAX_OUTPUT_TOKEN_BUDGET,
    CodeGeneratorAgent,
    GeneratedCodeOutputError,
)
from deeptutor.agents.math_animator.models import ConceptAnalysis, SceneDesign

_USABLE_CODE = '{"code":"from manim import Scene","rationale":"ok"}'
_THINKING = "<think>SECRET_CHAIN_DO_NOT_LEAK</think>"


def _agent(monkeypatch: pytest.MonkeyPatch, responses: list[str]) -> CodeGeneratorAgent:
    agent = CodeGeneratorAgent()
    agent.prompts = {
        "generate_system": "Return JSON.",
        "generate_user_template": (
            "{user_input}\n{output_mode}\n{duration_requirement}\n{analysis_json}\n{design_json}"
        ),
    }
    monkeypatch.setattr(agent, "get_max_retries", lambda: 1)

    async def fake_stream_llm(**_kwargs) -> AsyncIterator[str]:
        yield responses.pop(0)

    monkeypatch.setattr(agent, "stream_llm", fake_stream_llm)
    return agent


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_response", ["", "<think>reasoning only</think>"])
async def test_code_generation_retries_empty_or_reasoning_only_output(
    monkeypatch: pytest.MonkeyPatch,
    bad_response: str,
) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(
        "deeptutor.agents.math_animator.agents.code_generator_agent.asyncio.sleep",
        fake_sleep,
    )
    agent = _agent(
        monkeypatch,
        [bad_response, '{"code":"from manim import Scene","rationale":"ok"}'],
    )

    generated = await agent.generate(
        user_input="Animate a proof",
        output_mode="video",
        analysis=ConceptAnalysis(),
        design=SceneDesign(),
    )

    assert generated.code == "from manim import Scene"
    assert sleeps == [0.25]


@pytest.mark.asyncio
async def test_code_generation_fails_clearly_after_structured_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "deeptutor.agents.math_animator.agents.code_generator_agent.asyncio.sleep",
        fake_sleep,
    )
    agent = _agent(monkeypatch, ["", "{}"])

    with pytest.raises(GeneratedCodeOutputError, match="after 2 attempts"):
        await agent.generate(
            user_input="Animate a proof",
            output_mode="video",
            analysis=ConceptAnalysis(),
            design=SceneDesign(),
        )


def _stub_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(
        "deeptutor.agents.math_animator.agents.code_generator_agent.asyncio.sleep",
        fake_sleep,
    )
    return sleeps


def _scripted_agent(
    monkeypatch: pytest.MonkeyPatch,
    scripts: list[dict[str, str]],
    *,
    max_retries: int = 1,
    max_tokens: int = 1000,
) -> tuple[CodeGeneratorAgent, list[dict[str, Any]]]:
    agent = CodeGeneratorAgent()
    agent.prompts = {
        "generate_system": "Return JSON.",
        "generate_user_template": (
            "{user_input}\n{output_mode}\n{duration_requirement}\n{analysis_json}\n{design_json}"
        ),
    }
    monkeypatch.setattr(agent, "get_max_retries", lambda: max_retries)
    monkeypatch.setattr(agent, "get_max_tokens", lambda: max_tokens)
    monkeypatch.setattr(
        "deeptutor.agents.math_animator.agents.code_generator_agent.has_thinking_tags",
        lambda *_args, **_kwargs: False,
    )
    calls: list[dict[str, Any]] = []

    async def fake_stream_llm(**kwargs: Any) -> AsyncIterator[str]:
        calls.append(kwargs)
        script = scripts.pop(0)
        meta = kwargs.get("stream_meta")
        if isinstance(meta, dict) and "finish_reason" in script:
            meta["finish_reason"] = script["finish_reason"]
        yield script["text"]

    monkeypatch.setattr(agent, "stream_llm", fake_stream_llm)
    return agent, calls


async def _generate(agent: CodeGeneratorAgent):
    return await agent.generate(
        user_input="Animate a proof",
        output_mode="video",
        analysis=ConceptAnalysis(),
        design=SceneDesign(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["length", "max_tokens", "max_output_tokens", "LENGTH"])
async def test_truncated_reasoning_output_raises_budget_and_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    finish_reason: str,
) -> None:
    _stub_sleep(monkeypatch)
    agent, calls = _scripted_agent(
        monkeypatch,
        [
            {"text": _THINKING, "finish_reason": finish_reason},
            {"text": _USABLE_CODE, "finish_reason": "stop"},
        ],
        max_tokens=1000,
    )

    generated = await _generate(agent)

    assert generated.code == "from manim import Scene"
    assert [call["max_tokens"] for call in calls] == [1000, 2000]
    retry_prompt = calls[1]["user_prompt"]
    assert "Compress your reasoning" in retry_prompt
    assert "complete JSON" in retry_prompt
    assert "full Manim source" in retry_prompt
    assert _THINKING not in retry_prompt


@pytest.mark.asyncio
async def test_truncated_output_near_cap_stops_at_the_safety_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_sleep(monkeypatch)
    agent, calls = _scripted_agent(
        monkeypatch,
        [
            {"text": '{"code": "from manim import', "finish_reason": "length"},
            {"text": _USABLE_CODE, "finish_reason": "stop"},
        ],
        max_tokens=70_000,
    )

    generated = await _generate(agent)

    assert generated.code == "from manim import Scene"
    assert [call["max_tokens"] for call in calls] == [70_000, _MAX_OUTPUT_TOKEN_BUDGET]
    assert "Compress your reasoning" not in calls[1]["user_prompt"]
    assert "complete JSON" in calls[1]["user_prompt"]
    assert "full Manim source" in calls[1]["user_prompt"]


@pytest.mark.asyncio
async def test_thinking_model_flag_uses_the_compressed_retry_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_sleep(monkeypatch)
    agent, calls = _scripted_agent(
        monkeypatch,
        [
            {"text": '{"code": "from manim import', "finish_reason": "max_tokens"},
            {"text": _USABLE_CODE, "finish_reason": "stop"},
        ],
    )
    monkeypatch.setattr(
        "deeptutor.agents.math_animator.agents.code_generator_agent.has_thinking_tags",
        lambda *_args, **_kwargs: True,
    )

    await _generate(agent)

    assert "Compress your reasoning" in calls[1]["user_prompt"]
    assert calls[1]["max_tokens"] == 2000


@pytest.mark.asyncio
async def test_repeated_truncation_reports_the_token_budget(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _stub_sleep(monkeypatch)
    agent, calls = _scripted_agent(
        monkeypatch,
        [
            {"text": _THINKING, "finish_reason": "length"},
            {"text": _THINKING + '{"code": "self.play(', "finish_reason": "length"},
            {"text": _THINKING, "finish_reason": "length"},
        ],
        max_retries=2,
        max_tokens=1000,
    )
    caplog.set_level(logging.DEBUG, logger=agent.logger.name)

    with pytest.raises(GeneratedCodeOutputError, match="truncated by the token budget") as exc_info:
        await _generate(agent)

    message = str(exc_info.value)
    assert "finish_reason=length" in message
    assert "max_tokens=4000" in message
    assert "after 3 attempts" in message
    assert "no usable code" not in message
    assert "SECRET_CHAIN_DO_NOT_LEAK" not in message
    assert exc_info.value.__cause__ is not None
    assert "SECRET_CHAIN_DO_NOT_LEAK" not in str(exc_info.value.__cause__)
    assert [call["max_tokens"] for call in calls] == [1000, 2000, 4000]
    debug_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "finish_reason=length" in debug_text
    assert "response_chars=" in debug_text
    assert "requested_max_tokens=1000" in debug_text
    assert "retry_max_tokens=2000" in debug_text
    assert "SECRET_CHAIN_DO_NOT_LEAK" not in debug_text


@pytest.mark.asyncio
async def test_truncation_at_the_budget_cap_does_not_retry_the_same_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps = _stub_sleep(monkeypatch)
    agent, calls = _scripted_agent(
        monkeypatch,
        [{"text": _THINKING, "finish_reason": "max_output_tokens"}],
        max_retries=8,
        max_tokens=_MAX_OUTPUT_TOKEN_BUDGET,
    )

    with pytest.raises(GeneratedCodeOutputError, match="truncated by the token budget") as exc_info:
        await _generate(agent)

    message = str(exc_info.value)
    assert "finish_reason=max_output_tokens" in message
    assert f"max_tokens={_MAX_OUTPUT_TOKEN_BUDGET}" in message
    assert "after 1 attempt" in message
    assert "SECRET_CHAIN_DO_NOT_LEAK" not in message
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_non_truncation_retries_keep_the_configured_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_sleep(monkeypatch)
    agent, calls = _scripted_agent(
        monkeypatch,
        [
            {"text": _THINKING, "finish_reason": "length"},
            {"text": "", "finish_reason": "stop"},
            {"text": _USABLE_CODE, "finish_reason": "stop"},
        ],
        max_retries=2,
        max_tokens=1000,
    )

    generated = await _generate(agent)

    assert generated.code == "from manim import Scene"
    assert [call["max_tokens"] for call in calls] == [1000, 2000, 1000]
    assert "non-empty `code` field" in calls[2]["user_prompt"]
    assert "Compress your reasoning" not in calls[2]["user_prompt"]
    assert "cut off" not in calls[2]["user_prompt"]
