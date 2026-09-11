from __future__ import annotations

from collections.abc import AsyncIterator

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

    with pytest.raises(GeneratedCodeOutputError, match="after 2 attempts"):
        await agent.generate(
            user_input="Animate a proof",
            output_mode="video",
            analysis=ConceptAnalysis(),
            design=SceneDesign(),
        )
