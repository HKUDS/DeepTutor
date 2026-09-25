from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from deeptutor.agents.math_animator.agents.code_generator_agent import (
    CodeGeneratorAgent,
    GeneratedCodeOutputError,
)
from deeptutor.agents.math_animator.models import ConceptAnalysis, SceneDesign
from deeptutor.services.llm.reasoning_params import RETRY_REASONING_EFFORT


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
    assert [call["reasoning_effort"] for call in calls] == [
        None,
        RETRY_REASONING_EFFORT,
        RETRY_REASONING_EFFORT,
    ]
    assert "token limit" in str(calls[1]["user_prompt"])
    assert "token limit" not in str(calls[0]["user_prompt"])
    # The failure names the cause instead of "no usable code after 3 attempts".
    message = str(raised.value)
    assert "cut off at the 16000-token output cap" in message
    assert "chain-of-thought" in message
    assert "reasoning_tokens=7800" in message


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["generation", "repair"])
async def test_truncated_reasoning_only_response_recovers_with_less_reasoning(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    agent = _agent(monkeypatch, [])
    monkeypatch.setattr(agent, "get_max_tokens", lambda: 8000)
    calls: list[dict[str, object]] = []

    async def fake_provider(**kwargs) -> AsyncIterator[str]:
        calls.append(kwargs)
        if len(calls) == 1:
            kwargs["outcome"].finish_reason = "length"
            kwargs["outcome"].usage = {"reasoning_tokens": 7900}
            yield "<think>I need to plan every scene first.</think>"
        else:
            kwargs["outcome"].finish_reason = "stop"
            yield '{"code":"from manim import Scene","rationale":"ok"}'

    monkeypatch.setattr(agent, "stream_llm", fake_provider)
    if stage == "generation":
        generated = await agent.generate(
            user_input="Animate a proof",
            output_mode="video",
            analysis=ConceptAnalysis(),
            design=SceneDesign(),
        )
    else:
        agent.prompts.update(
            {
                "retry_system": "Repair the script.",
                "retry_user_template": (
                    "{user_input} {output_mode} {attempt} {duration_requirement} "
                    "{error_message} {current_code}"
                ),
            }
        )
        generated = await agent.repair(
            user_input="Animate a proof",
            output_mode="video",
            current_code="broken code",
            error_message="SyntaxError",
            attempt=1,
        )

    assert generated.code == "from manim import Scene"
    assert [call["reasoning_effort"] for call in calls] == [None, RETRY_REASONING_EFFORT]
    assert [call["max_tokens"] for call in calls] == [8000, 12000]


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
