"""Deep Research must not report success when a research block fails (issue #595).

A subtopic that raises (or exhausts its iteration budget without finishing) is
backfilled with empty knowledge so the surviving subtopics still yield a report.
The fix keeps that resilience but makes the shortfall explicit in the result
envelope (``metadata.partial`` / ``failed_block_count`` / ``failed_block_titles``)
instead of returning a clean-success shape with missing evidence.
"""

from __future__ import annotations

import types
from unittest.mock import patch

import pytest

from deeptutor.agents.research.pipeline import ResearchedBlock, ResearchPipeline, SubTopicItem
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus

pytestmark = pytest.mark.asyncio


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

    def get(self, _name):
        return None

    def get_enabled(self, _names):
        return []


def _make_pipeline() -> ResearchPipeline:
    with (
        patch("deeptutor.agents.research.pipeline.get_llm_config", lambda: _FakeLLM()),
        patch("deeptutor.agents.research.pipeline.get_tool_registry", lambda: _FakeRegistry()),
    ):
        return ResearchPipeline(language="en", runtime_config={"queue": {"max_length": 5}})


async def _run(pipeline: ResearchPipeline) -> dict:
    async def fake_emit(*_args, **_kwargs):
        return None

    with patch("deeptutor.agents.research.pipeline.emit_capability_result", fake_emit):
        return await pipeline._run_inner(
            context=UnifiedContext(session_id="s1", user_message="research this"),
            topic="Research topic",
            image_attachments=[],
            confirmed_outline=[SubTopicItem(title="A"), SubTopicItem(title="B")],
            stream=StreamBus(),
            client=None,
        )


async def test_failed_block_marks_result_partial() -> None:
    pipeline = _make_pipeline()

    async def fake_research_block(self, *, block, queue, citations, topic, context, stream, client):
        queue.mark_researching(block.block_id)
        if block.block_id == "block_1":
            raise RuntimeError("synthetic block failure")
        queue.mark_completed(block.block_id)
        return ResearchedBlock(block=block, knowledge=f"knowledge for {block.block_id}")

    async def fake_write_report(self, *, topic, blocks, citations, stream, client):
        return "REPORT_OK"

    pipeline._research_block = types.MethodType(fake_research_block, pipeline)
    pipeline._write_report = types.MethodType(fake_write_report, pipeline)

    result = await _run(pipeline)
    meta = result["metadata"]

    assert result["response"] == "REPORT_OK"  # surviving evidence still produces a report
    assert meta["partial"] is True
    assert meta["failed_block_count"] == 1
    assert meta["failed_block_titles"] == ["A"]
    assert meta["block_count"] == 2


async def test_all_blocks_complete_is_not_partial() -> None:
    pipeline = _make_pipeline()

    async def fake_research_block(self, *, block, queue, citations, topic, context, stream, client):
        queue.mark_researching(block.block_id)
        queue.mark_completed(block.block_id)
        return ResearchedBlock(block=block, knowledge=f"knowledge for {block.block_id}")

    async def fake_write_report(self, *, topic, blocks, citations, stream, client):
        return "REPORT_OK"

    pipeline._research_block = types.MethodType(fake_research_block, pipeline)
    pipeline._write_report = types.MethodType(fake_write_report, pipeline)

    result = await _run(pipeline)
    meta = result["metadata"]

    assert meta["partial"] is False
    assert meta["failed_block_count"] == 0
    assert meta["failed_block_titles"] == []
