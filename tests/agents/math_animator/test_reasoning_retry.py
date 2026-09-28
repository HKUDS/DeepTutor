"""A reasoning-only structured stage must not silently become an empty plan."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from deeptutor.agents.math_animator.agents.concept_analysis_agent import (
    ConceptAnalysisAgent,
)
from deeptutor.agents.math_animator.agents.concept_design_agent import ConceptDesignAgent
from deeptutor.agents.math_animator.agents.summary_agent import SummaryAgent
from deeptutor.agents.math_animator.models import ConceptAnalysis, RenderResult, SceneDesign
from deeptutor.services.llm.reasoning_params import RETRY_REASONING_EFFORT


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["analysis", "design", "summary"])
async def test_structured_manim_stage_retries_reasoning_only_response(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    if stage == "analysis":
        agent = ConceptAnalysisAgent()
        agent.prompts = {
            "system": "Analyze the concept.",
            "user_template": (
                "{user_input} {history_context} {output_mode} {style_hint} {reference_count}"
            ),
        }
        call = agent.process(
            user_input="Explain a circle",
            history_context="",
            output_mode="video",
            style_hint="",
            attachments=[],
        )
        answer = '{"learning_goal":"understand a circle","visual_targets":["radius"]}'
        expected = ("learning_goal", "understand a circle")
    elif stage == "design":
        agent = ConceptDesignAgent()
        agent.prompts = {
            "system": "Design the scene.",
            "user_template": "{user_input} {output_mode} {style_hint} {analysis_json}",
        }
        call = agent.process(
            user_input="Explain a circle",
            output_mode="video",
            analysis=ConceptAnalysis(learning_goal="understand a circle"),
            style_hint="",
        )
        answer = '{"scene_outline":["draw a circle"],"title":"Circle"}'
        expected = ("scene_outline", ["draw a circle"])
    else:
        agent = SummaryAgent()
        agent.prompts = {
            "system": "Summarize the result.",
            "user_template": (
                "{user_input} {output_mode} {analysis_json} {design_json} {render_json}"
            ),
        }
        call = agent.process(
            user_input="Explain a circle",
            output_mode="video",
            analysis=ConceptAnalysis(learning_goal="understand a circle"),
            design=SceneDesign(scene_outline=["draw a circle"]),
            render_result=RenderResult(output_mode="video"),
        )
        answer = '{"summary_text":"A circle animation is ready."}'
        expected = ("summary_text", "A circle animation is ready.")

    calls: list[dict[str, object]] = []

    async def fake_provider(**kwargs) -> AsyncIterator[str]:
        calls.append(kwargs)
        yield "<think>I will plan the animation first.</think>" if len(calls) == 1 else answer

    monkeypatch.setattr(agent, "stream_llm", fake_provider)
    result = await call

    assert getattr(result, expected[0]) == expected[1]
    assert [entry["reasoning_effort"] for entry in calls] == [
        None,
        RETRY_REASONING_EFFORT,
    ]
    assert calls[0]["trace_meta"]["call_id"] != calls[1]["trace_meta"]["call_id"]
    if stage == "analysis":
        assert [message["role"] for message in calls[1]["messages"]] == ["system", "user"]


@pytest.mark.asyncio
async def test_analysis_does_not_accept_two_empty_reasoning_only_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = ConceptAnalysisAgent()
    agent.prompts = {
        "system": "Analyze the concept.",
        "user_template": (
            "{user_input} {history_context} {output_mode} {style_hint} {reference_count}"
        ),
    }

    async def fake_provider(**_kwargs) -> AsyncIterator[str]:
        yield "<think>Still thinking.</think>"

    monkeypatch.setattr(agent, "stream_llm", fake_provider)
    with pytest.raises(ValueError, match="concept analysis returned no learning goal"):
        await agent.process(
            user_input="Explain a circle",
            history_context="",
            output_mode="video",
            style_hint="",
            attachments=[],
        )


@pytest.mark.asyncio
async def test_empty_summary_after_retry_keeps_a_completed_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SummaryAgent()
    agent.prompts = {
        "system": "Summarize the result.",
        "user_template": ("{user_input} {output_mode} {analysis_json} {design_json} {render_json}"),
    }
    calls = 0

    async def fake_provider(**_kwargs) -> AsyncIterator[str]:
        nonlocal calls
        calls += 1
        yield "<think>Still thinking.</think>"

    monkeypatch.setattr(agent, "stream_llm", fake_provider)
    summary = await agent.process(
        user_input="Explain a circle",
        output_mode="video",
        analysis=ConceptAnalysis(learning_goal="understand a circle"),
        design=SceneDesign(scene_outline=["draw a circle"]),
        render_result=RenderResult(output_mode="video"),
    )

    assert calls == 2
    assert summary.summary_text == ""
