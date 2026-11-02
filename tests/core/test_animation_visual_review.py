"""The public opt-in must reach each caller of the animation pipeline."""

from __future__ import annotations

import asyncio
import importlib.util
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from deeptutor.agents.math_animator.capability import MathAnimatorCapability
from deeptutor.agents.math_animator.models import (
    ConceptAnalysis,
    GeneratedCode,
    RenderResult,
    SceneDesign,
    SummaryPayload,
    VisualReviewResult,
)
from deeptutor.agents.math_animator.request_config import MathAnimatorRequestConfig
from deeptutor.agents.visualize.capability import VisualizeCapability
from deeptutor.book.blocks.animation import AnimationGenerator
from deeptutor.book.blocks.base import BlockContext, GenerationFailure
from deeptutor.book.models import Block, BlockType, Chapter, Page
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEventType
from deeptutor.runtime.bootstrap.builtin_capabilities import builtin_capability_manifest
from deeptutor.runtime.request_contracts import (
    CAPABILITY_REQUEST_SCHEMAS,
    VisualizeRequestConfig,
)
from deeptutor.runtime.stream_bus import StreamBus


@pytest.mark.parametrize(
    "model, capability",
    [(MathAnimatorRequestConfig, "math_animator"), (VisualizeRequestConfig, "visualize")],
)
def test_visual_review_defaults_and_public_schema(model, capability) -> None:
    assert model().enable_visual_review is False
    field = CAPABILITY_REQUEST_SCHEMAS[capability]["properties"]["enable_visual_review"]
    assert field["type"] == "boolean"
    assert field["default"] is False
    assert builtin_capability_manifest(capability).config_defaults["enable_visual_review"] is False


@pytest.mark.parametrize("model", [MathAnimatorRequestConfig, VisualizeRequestConfig])
@pytest.mark.parametrize("raw, expected", [(True, True), (False, False), ("false", False)])
def test_visual_review_boolean_validation(model, raw, expected) -> None:
    assert model(enable_visual_review=raw).enable_visual_review is expected


@pytest.mark.parametrize("model", [MathAnimatorRequestConfig, VisualizeRequestConfig])
def test_visual_review_rejects_invalid_values(model) -> None:
    with pytest.raises(ValidationError):
        model(enable_visual_review="sometimes")


@pytest.fixture
def animation_pipeline(monkeypatch):
    """Keep real capability/config code; replace rendering and model calls."""
    calls = []
    review = VisualReviewResult(passed=False, summary="Labels overlap.", reviewed_frames=3)

    class Pipeline:
        def __init__(self, **kwargs):
            self.options = kwargs
            calls.append(self)

        async def run_analysis(self, *, request_config, **kwargs):
            self.config = request_config
            return ConceptAnalysis(learning_goal="Explain a sine wave")

        async def run_design(self, **kwargs):
            return SceneDesign(title="Sine wave")

        async def run_code_generation(self, **kwargs):
            return GeneratedCode(code="pass")

        async def run_render(self, *, request_config, **kwargs):
            return "pass", RenderResult(
                output_mode=request_config.output_mode,
                visual_review=review if self.options.get("enable_visual_review") else None,
            )

        async def run_summary(self, **kwargs):
            return SummaryPayload(summary_text="Animation ready")

        async def run(self, *, request_config, **kwargs):
            self.config = request_config
            _, render = await self.run_render(request_config=request_config)
            return {
                "render_result": render,
                "summary": SummaryPayload(summary_text="Animation ready"),
                "analysis": ConceptAnalysis(learning_goal="Explain a sine wave"),
            }

    monkeypatch.setattr("deeptutor.agents.math_animator.pipeline.MathAnimatorPipeline", Pipeline)
    monkeypatch.setattr("deeptutor.modules.catalog.require_module", lambda _name: None)
    original_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        "importlib.util.find_spec",
        lambda name, *args: object() if name == "manim" else original_find_spec(name, *args),
    )
    monkeypatch.setattr(
        "deeptutor.services.llm.config.get_llm_config",
        lambda: SimpleNamespace(api_key="test", base_url=None, api_version=None),
    )
    return calls, review


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["math_animator", "manim_video", "manim_image", "book"])
@pytest.mark.parametrize(
    "config", [{}, {"enable_visual_review": True}, {"enable_visual_review": False}]
)
async def test_animation_entry_points_forward_review_and_expose_result(
    animation_pipeline, entry, config
) -> None:
    calls, review = animation_pipeline
    expected = config.get("enable_visual_review", False)
    if entry == "book":
        ctx = BlockContext(
            book_id="book-test",
            chapter=Chapter(title="Waves"),
            page=Page(),
            block=Block(type=BlockType.ANIMATION, params=config),
        )
        _, _, metadata = await AnimationGenerator()._generate(ctx)
    else:
        capability = MathAnimatorCapability() if entry == "math_animator" else VisualizeCapability()
        context = UnifiedContext(
            user_message="Animate a sine wave",
            active_capability=capability.name,
            config_overrides={
                **config,
                **({"render_mode": entry} if entry != "math_animator" else {}),
            },
        )
        bus = StreamBus()
        events = []

        async def consume():
            async for event in bus.subscribe():
                events.append(event)

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0)
        try:
            await capability.run(context, bus)
        finally:
            await bus.close()
            await consumer
        result = next(event for event in events if event.type == StreamEventType.RESULT)
        metadata = result.metadata["render"]

    assert len(calls) == 1
    assert calls[0].options["enable_visual_review"] is expected
    assert calls[0].config.enable_visual_review is expected
    assert metadata["visual_review"] == (review.model_dump() if expected else None)
    assert calls[0].config.output_mode == ("image" if entry == "manim_image" else "video")


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["false", "sometimes"])
async def test_book_validates_review_before_starting_pipeline(animation_pipeline, raw) -> None:
    calls, _ = animation_pipeline
    ctx = BlockContext(
        book_id="book-test",
        chapter=Chapter(title="Waves"),
        page=Page(),
        block=Block(type=BlockType.ANIMATION, params={"enable_visual_review": raw}),
    )
    if raw == "false":
        await AnimationGenerator()._generate(ctx)
        assert calls[0].options["enable_visual_review"] is False
    else:
        with pytest.raises(GenerationFailure, match="enable_visual_review"):
            await AnimationGenerator()._generate(ctx)
        assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("render_mode", ["auto", "html"])
async def test_other_visualizers_do_not_start_animation_review(monkeypatch, render_mode) -> None:
    from deeptutor.visualizers.protocol import VISUALIZATION_RESULT_KEY

    class ChatPipeline:
        usage = None

        def __init__(self, **kwargs):
            pass

        async def run(self, context, stream):
            context.metadata[VISUALIZATION_RESULT_KEY] = {
                "render_type": "html",
                "payload": {"data": "<p>Waves</p>"},
            }
            return {}

    def unexpected_animation(**kwargs):
        pytest.fail("Non-Manim visualizers must not construct the animation pipeline")

    monkeypatch.setattr("deeptutor.agents.chat.agentic_pipeline.AgenticChatPipeline", ChatPipeline)
    monkeypatch.setattr(
        "deeptutor.agents.math_animator.pipeline.MathAnimatorPipeline", unexpected_animation
    )
    monkeypatch.setattr(VisualizeCapability, "_tool_calling_disabled_for", staticmethod(lambda: ""))
    bus = StreamBus()
    try:
        await VisualizeCapability().run(
            UnifiedContext(
                user_message="Visualize waves",
                config_overrides={"render_mode": render_mode, "enable_visual_review": True},
            ),
            bus,
        )
    finally:
        await bus.close()
