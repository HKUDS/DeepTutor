from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.agents.math_animator.capability import MathAnimatorCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus


async def _collect_events(run_coro) -> list[StreamEvent]:
    bus = StreamBus()
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    await run_coro(bus)
    await asyncio.sleep(0)
    await bus.close()
    await consumer
    return events


@pytest.mark.asyncio
async def test_math_animator_capability_emits_summary_and_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Unit test should not require real optional dependency installation.
    monkeypatch.setattr(
        "deeptutor.agents.math_animator.capability.importlib.util.find_spec",
        lambda name: object() if name == "manim" else None,
    )

    class FakePipeline:
        def __init__(self, **_kwargs) -> None:
            pass

        async def run_analysis(self, **_kwargs):
            return SimpleNamespace(model_dump=lambda: {"learning_goal": "teach parabola"})

        async def run_design(self, **_kwargs):
            return SimpleNamespace(model_dump=lambda: {"title": "Parabola animation"})

        async def run_code_generation(self, **_kwargs):
            return SimpleNamespace(
                code="from manim import *\n\nclass MainScene(Scene):\n    pass\n"
            )

        async def run_render(self, **_kwargs):
            return (
                "from manim import *\n\nclass MainScene(Scene):\n    pass\n",
                SimpleNamespace(
                    artifacts=[
                        SimpleNamespace(
                            model_dump=lambda: {
                                "type": "video",
                                "url": "/api/outputs/agent/math_animator/turn_1/artifacts/video.mp4",
                                "filename": "video.mp4",
                                "content_type": "video/mp4",
                                "label": "Animation video",
                            }
                        )
                    ],
                    retry_attempts=1,
                    retry_history=[
                        SimpleNamespace(model_dump=lambda: {"attempt": 1, "error": "boom"})
                    ],
                    source_code_path="/tmp/scene.py",
                ),
            )

        async def run_summary(self, **_kwargs):
            return SimpleNamespace(
                summary_text="用户想讲抛物线，系统生成了一个视频动画。",
                model_dump=lambda: {
                    "summary_text": "用户想讲抛物线，系统生成了一个视频动画。",
                    "user_request": "讲解抛物线",
                    "generated_output": "一个视频",
                    "key_points": ["parabola"],
                },
            )

    monkeypatch.setattr(
        "deeptutor.agents.math_animator.pipeline.MathAnimatorPipeline", FakePipeline
    )
    monkeypatch.setattr(
        "deeptutor.services.llm.config.get_llm_config",
        lambda: SimpleNamespace(api_key="k", base_url="u", api_version="v1"),
    )

    context = UnifiedContext(
        session_id="session_1",
        user_message="讲解抛物线",
        active_capability="math_animator",
        language="zh",
        metadata={"turn_id": "turn_1", "conversation_context_text": "之前讨论过函数图像"},
    )
    capability = MathAnimatorCapability()
    events = await _collect_events(lambda bus: capability.run(context, bus))

    assert [event.stage for event in events if event.type == StreamEventType.STAGE_START] == [
        "concept_analysis",
        "concept_design",
        "code_generation",
        "code_retry",
        "summary",
        "render_output",
    ]
    content_event = next(event for event in events if event.type == StreamEventType.CONTENT)
    assert "抛物线" in content_event.content
    result_event = next(event for event in events if event.type == StreamEventType.RESULT)
    assert result_event.metadata["output_mode"] == "video"
    assert result_event.metadata["code"]["language"] == "python"
    assert result_event.metadata["artifacts"][0]["filename"] == "video.mp4"
