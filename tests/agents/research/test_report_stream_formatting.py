from __future__ import annotations

import types
from unittest.mock import patch

import pytest

from deeptutor.agents.research.pipeline import ReportOutline, ResearchPipeline
from deeptutor.core.stream import StreamEventType
from deeptutor.core.stream_bus import StreamBus


class _FakeLLM:
    binding = "openai"
    model = "gpt-x"
    api_key = "k"
    base_url = "u"
    api_version = None
    extra_headers: dict = {}
    reasoning_effort = None


class _FakeRegistry:
    def build_openai_schemas(self, _names):
        return []

    def build_prompt_text(self, _names, **_kwargs):
        return "- none"


class _EmptyCitations:
    def get_all_citations(self):
        return {}


def _make_pipeline() -> ResearchPipeline:
    with (
        patch("deeptutor.agents.research.pipeline.get_llm_config", lambda: _FakeLLM()),
        patch("deeptutor.agents.research.pipeline.get_tool_registry", lambda: _FakeRegistry()),
    ):
        return ResearchPipeline(language="en", runtime_config={"queue": {"max_length": 5}})


@pytest.mark.asyncio
async def test_report_content_stream_matches_result_title_intro_boundary() -> None:
    pipeline = _make_pipeline()
    stream = StreamBus()
    intro = "## 1. Introduction\nIntro body"
    conclusion = "## 2. Conclusion\nConclusion body"

    async def fake_outline(self, **_kwargs):
        return ReportOutline(title="Report title", sections=())

    async def fake_intro(self, *, stream, **_kwargs):
        await stream.content(intro, source="deep_research", stage="reporting")
        return intro

    async def fake_conclusion(self, *, stream, **_kwargs):
        await stream.content(conclusion, source="deep_research", stage="reporting")
        return conclusion

    pipeline._gen_report_outline = types.MethodType(fake_outline, pipeline)
    pipeline._write_intro = types.MethodType(fake_intro, pipeline)
    pipeline._write_conclusion = types.MethodType(fake_conclusion, pipeline)

    report = await pipeline._write_report(
        topic="Research topic",
        blocks=[],
        citations=_EmptyCitations(),
        stream=stream,
        client=None,
    )
    streamed_answer = "".join(
        event.content for event in stream._history if event.type == StreamEventType.CONTENT
    )

    assert "# Report title\n\n## 1. Introduction" in report
    assert streamed_answer == report
