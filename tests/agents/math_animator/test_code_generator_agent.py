from __future__ import annotations

from collections.abc import AsyncIterator
import logging

import pytest

from deeptutor.agents.math_animator.agents.code_generator_agent import (
    CodeGeneratorAgent,
    GeneratedCodeOutputError,
)
from deeptutor.agents.math_animator.models import ConceptAnalysis, SceneDesign


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

    with pytest.raises(GeneratedCodeOutputError, match="after 2 attempts") as exc_info:
        await agent.generate(
            user_input="Animate a proof",
            output_mode="video",
            analysis=ConceptAnalysis(),
            design=SceneDesign(),
        )

    message = str(exc_info.value)
    assert "structured response has an empty code field" in message
    assert "len=2" in message
    assert "{}" in message


@pytest.mark.asyncio
async def test_truncated_generation_grows_the_budget_and_asks_for_less_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reasoning model that hits the cap must not be asked the same thing again.

    The reporter's run spent 21 minutes on 9 identical attempts: every one was
    cut off at ``max_tokens`` with the whole budget inside ``<think>``, and every
    retry sent the same prompt with the same budget (#1547).
    """

    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "deeptutor.agents.math_animator.agents.code_generator_agent.asyncio.sleep",
        fake_sleep,
    )
    agent = _agent(monkeypatch, [])
    monkeypatch.setattr(agent, "get_max_retries", lambda: 2)
    monkeypatch.setattr(agent, "get_max_tokens", lambda: 8000)
    calls: list[dict[str, object]] = []

    async def truncated_stream(**kwargs) -> AsyncIterator[str]:
        calls.append(kwargs)
        outcome = kwargs["outcome"]
        outcome.finish_reason = "length"
        outcome.usage = {"completion_tokens": 8000, "reasoning_tokens": 7800}
        yield '<think>Let me reconsider the scene once more…</think>{"code": "from man'

    monkeypatch.setattr(agent, "stream_llm", truncated_stream)

    with pytest.raises(GeneratedCodeOutputError) as raised:
        await agent.generate(
            user_input="Animate a proof",
            output_mode="video",
            analysis=ConceptAnalysis(),
            design=SceneDesign(),
        )

    # Each truncated attempt buys a larger budget, capped at twice the
    # configured one so the request stays inside the model's own output limit.
    assert [call["max_tokens"] for call in calls] == [8000, 12000, 16000]
    assert "token limit" in str(calls[1]["user_prompt"])
    assert "token limit" not in str(calls[0]["user_prompt"])
    # The failure names the cause instead of "no usable code after 3 attempts".
    message = str(raised.value)
    assert "cut off at the 16000-token output cap" in message
    assert "chain-of-thought" in message
    assert "reasoning_tokens=7800" in message


@pytest.mark.asyncio
async def test_malformed_output_is_reported_as_malformed_not_as_a_budget_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a truncated attempt is fixed by raising max tokens (#1545)."""
    agent = _agent(monkeypatch, [])
    monkeypatch.setattr(agent, "get_max_retries", lambda: 0)
    monkeypatch.setattr(agent, "get_max_tokens", lambda: 8000)

    async def prose_stream(**kwargs) -> AsyncIterator[str]:
        yield "I cannot write this animation."

    monkeypatch.setattr(agent, "stream_llm", prose_stream)

    with pytest.raises(GeneratedCodeOutputError) as raised:
        await agent.generate(
            user_input="Animate a proof",
            output_mode="video",
            analysis=ConceptAnalysis(),
            design=SceneDesign(),
        )

    message = str(raised.value)
    assert "no usable JSON object" in message
    assert "output cap" not in message


def _long_raw(middle: str) -> str:
    return ("H" * 200) + middle + ("T" * 200)


@pytest.mark.asyncio
async def test_exhausted_retries_summarize_last_raw_response_without_the_middle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "deeptutor.agents.math_animator.agents.code_generator_agent.asyncio.sleep",
        fake_sleep,
    )
    monkeypatch.delenv("DEEPTUTOR_DEBUG_LLM_RAW", raising=False)
    last = _long_raw("UNIQUE_MIDDLE_MARKER")
    agent = _agent(monkeypatch, ["", last])

    with pytest.raises(GeneratedCodeOutputError) as exc_info:
        await agent.generate(
            user_input="Animate a proof",
            output_mode="video",
            analysis=ConceptAnalysis(),
            design=SceneDesign(),
        )

    message = str(exc_info.value)
    assert "after 2 attempts" in message
    assert "No JSON object found" in message
    assert "structured response has an empty code field" not in message
    assert f"len={len(last)}" in message
    assert "H" * 200 in message
    assert "T" * 200 in message
    assert "UNIQUE_MIDDLE_MARKER" not in message


@pytest.mark.asyncio
async def test_debug_flag_logs_raw_response_for_every_failed_attempt(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "deeptutor.agents.math_animator.agents.code_generator_agent.asyncio.sleep",
        fake_sleep,
    )
    monkeypatch.setenv("DEEPTUTOR_DEBUG_LLM_RAW", "1")
    first = _long_raw("RAW_ATTEMPT_ONE")
    last = _long_raw("RAW_ATTEMPT_TWO")
    agent = _agent(monkeypatch, [first, last])

    with caplog.at_level(logging.DEBUG, logger=agent.logger.name):
        with pytest.raises(GeneratedCodeOutputError) as exc_info:
            await agent.generate(
                user_input="Animate a proof",
                output_mode="video",
                analysis=ConceptAnalysis(),
                design=SceneDesign(),
            )

    debug_text = "\n".join(
        record.getMessage() for record in caplog.records if record.levelno == logging.DEBUG
    )
    assert "RAW_ATTEMPT_ONE" in debug_text
    assert "RAW_ATTEMPT_TWO" in debug_text
    assert "RAW_ATTEMPT_ONE" not in str(exc_info.value)
    assert "RAW_ATTEMPT_TWO" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_raw_response_is_not_logged_without_debug_flag(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "deeptutor.agents.math_animator.agents.code_generator_agent.asyncio.sleep",
        fake_sleep,
    )
    monkeypatch.delenv("DEEPTUTOR_DEBUG_LLM_RAW", raising=False)
    first = _long_raw("RAW_ATTEMPT_ONE")
    last = _long_raw("RAW_ATTEMPT_TWO")
    agent = _agent(monkeypatch, [first, last])

    with caplog.at_level(logging.DEBUG, logger=agent.logger.name):
        with pytest.raises(GeneratedCodeOutputError):
            await agent.generate(
                user_input="Animate a proof",
                output_mode="video",
                analysis=ConceptAnalysis(),
                design=SceneDesign(),
            )

    assert "RAW_ATTEMPT_ONE" not in caplog.text
    assert "RAW_ATTEMPT_TWO" not in caplog.text
