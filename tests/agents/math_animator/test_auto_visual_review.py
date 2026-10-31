"""Visual review turns itself on when a vision-capable model is available, for limited rounds."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from deeptutor.agents.math_animator import pipeline as pipeline_module
from deeptutor.agents.math_animator.models import RenderResult, VisualReviewResult
from deeptutor.agents.math_animator.pipeline import MathAnimatorPipeline
from deeptutor.agents.math_animator.request_config import MathAnimatorRequestConfig
from deeptutor.services.llm import capabilities


def _agent(model: str = "chat-model"):
    return SimpleNamespace(get_model=lambda: model, binding="openai")


def test_chat_model_with_vision_is_used(monkeypatch) -> None:
    monkeypatch.setattr(
        capabilities, "supports_vision", lambda binding, model: model == "chat-model"
    )
    assert pipeline_module._auto_vision_model(_agent()) == "chat-model"


def test_declared_vision_model_is_used_when_chat_model_is_text_only(monkeypatch) -> None:
    monkeypatch.setattr(
        capabilities, "supports_vision", lambda binding, model: model == "vision-model"
    )
    monkeypatch.setattr(pipeline_module, "_catalog_vision_model", lambda: "vision-model")
    assert pipeline_module._auto_vision_model(_agent()) == "vision-model"


def test_no_vision_model_means_no_reviewer(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module, "_auto_vision_model", lambda agent: None)
    pipe = MathAnimatorPipeline(api_key="k", base_url="u", api_version=None, language="en")
    assert pipe.visual_review_agent is None


def test_auto_review_is_limited_to_its_rounds(monkeypatch) -> None:
    monkeypatch.setattr(pipeline_module, "_auto_vision_model", lambda agent: "vision-model")
    pipe = MathAnimatorPipeline(api_key="k", base_url="u", api_version=None, language="en")
    assert pipe.visual_review_agent.agent_config["model"] == "vision-model"

    async def failing_review(**kwargs) -> VisualReviewResult:
        return VisualReviewResult(passed=False, summary="label overlaps the curve")

    class _Service:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def build_attachments(self, render_result):
            return []

    captured: dict = {}

    class _RetryManager:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        async def render_with_retries(self, **kwargs):
            return "code", RenderResult(output_mode="video")

    monkeypatch.setattr(pipe.visual_review_agent, "process", failing_review)
    monkeypatch.setattr(pipeline_module, "VisualReviewService", _Service)
    monkeypatch.setattr(pipeline_module, "CodeRetryManager", _RetryManager)
    asyncio.run(
        pipe.run_render(
            turn_id="t",
            user_input="x",
            request_config=MathAnimatorRequestConfig(),
            initial_code="code",
        )
    )
    review = captured["review_callback"]
    result = RenderResult(output_mode="video")
    first = asyncio.run(review("code", result))
    second = asyncio.run(review("code", result))
    assert first.passed is False  # round 1 sends the scene back for repair
    assert second.passed is True  # out of rounds: kept, issues recorded
    assert second.summary.startswith("Visual issues remain")
