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
from deeptutor.core.agentic import AgenticModelError, LabelProtocol, LabeledStepResult
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
        return ResearchedBlock(block=block, knowledge=(f"knowledge for {block.block_id} " * 8))

    async def fake_write_report(self, *, topic, blocks, citations, stream, client):
        return "# Report\n\n" + ("substantive report body " * 12)

    pipeline._research_block = types.MethodType(fake_research_block, pipeline)
    pipeline._write_report = types.MethodType(fake_write_report, pipeline)

    result = await _run(pipeline)
    meta = result["metadata"]

    assert result["response"].startswith("# Report")  # surviving evidence still produces a report
    assert meta["partial"] is True
    assert meta["failed_block_count"] == 1
    assert meta["failed_block_titles"] == ["A"]
    assert meta["block_count"] == 2


async def test_all_blocks_complete_is_not_partial() -> None:
    pipeline = _make_pipeline()

    async def fake_research_block(self, *, block, queue, citations, topic, context, stream, client):
        queue.mark_researching(block.block_id)
        queue.mark_completed(block.block_id)
        return ResearchedBlock(block=block, knowledge=(f"knowledge for {block.block_id} " * 8))

    async def fake_write_report(self, *, topic, blocks, citations, stream, client):
        return "# Report\n\n" + ("substantive report body " * 12)

    pipeline._research_block = types.MethodType(fake_research_block, pipeline)
    pipeline._write_report = types.MethodType(fake_write_report, pipeline)

    result = await _run(pipeline)
    meta = result["metadata"]

    assert meta["partial"] is False
    assert meta["failed_block_count"] == 0
    assert meta["failed_block_titles"] == []


async def test_substantive_evidence_with_short_report_is_failed_and_retryable() -> None:
    pipeline = _make_pipeline()

    async def fake_research_block(self, *, block, queue, citations, topic, context, stream, client):
        queue.mark_researching(block.block_id)
        queue.mark_completed(block.block_id)
        return ResearchedBlock(block=block, knowledge=("usable evidence " * 10))

    async def fake_write_report(self, **_kwargs):
        return "# Report\n\nToo short"

    pipeline._research_block = types.MethodType(fake_research_block, pipeline)
    pipeline._write_report = types.MethodType(fake_write_report, pipeline)

    with pytest.raises(Exception) as excinfo:
        await _run(pipeline)
    result = excinfo.value.result
    assert result["metadata"]["outcome"] == "failed"
    assert result["metadata"]["partial"] is False
    assert result["metadata"]["failure"]["code"] == "report_generation_failed"


async def test_report_exception_keeps_lifecycle_diagnostics_in_checkpoint() -> None:
    pipeline = _make_pipeline()

    async def fake_research_block(self, *, block, queue, citations, topic, context, stream, client):
        queue.mark_researching(block.block_id)
        queue.mark_completed(block.block_id)
        return ResearchedBlock(block=block, knowledge=("usable evidence " * 10))

    async def fake_write_report(self, **_kwargs):
        raise AgenticModelError("model_output_incomplete", "safe", retryable=True,
                                normalized_result={"termination": {"provider_status": "incomplete"}})

    pipeline._research_block = types.MethodType(fake_research_block, pipeline)
    pipeline._write_report = types.MethodType(fake_write_report, pipeline)
    with pytest.raises(Exception) as excinfo:
        await _run(pipeline)
    result = excinfo.value.result
    failure = result["metadata"]["failure"]
    assert failure["code"] == "report_generation_failed"
    assert failure["retryable"] is True
    assert failure["termination"]["provider_status"] == "incomplete"
    assert excinfo.value.checkpoint["report"]["outcome"] == "failed"


@pytest.mark.parametrize("ceiling,expected_budgets", [(200, [100, 200]), (100, [100])])
async def test_one_shot_length_retry_uses_only_a_higher_legal_budget(
    monkeypatch: pytest.MonkeyPatch, ceiling: int, expected_budgets: list[int]
) -> None:
    pipeline = _make_pipeline()
    pipeline.llm_config.max_tokens = ceiling
    budgets: list[int] = []
    bus = StreamBus()

    async def fake_step(**kwargs):
        completion = kwargs["completion_kwargs"]
        budget = next(
            int(completion[key])
            for key in ("max_output_tokens", "max_completion_tokens", "max_tokens")
            if key in completion
        )
        budgets.append(budget)
        if len(budgets) == 1:
            raise AgenticModelError(
                "model_output_incomplete", "safe", retryable=True,
                normalized_result={
                    "termination": {
                        "provider_status": "incomplete",
                        "incomplete_details": {"reason": "max_output_tokens"},
                    }
                },
            )
        return LabeledStepResult(label="FINISH", text="ok")

    monkeypatch.setattr("deeptutor.agents.research.pipeline.run_labeled_step", fake_step)
    protocol = LabelProtocol(
        allowed=("FINISH",), terminal=frozenset({"FINISH"}),
        intermediate=frozenset(), final=frozenset({"FINISH"}), tool_label=None,
    )
    if ceiling > 100:
        result = await pipeline._run_labeled_step(
            client=object(), messages=[], tool_schemas=None, protocol=protocol,
            stream=bus, stage="reporting", iter_meta={}, max_tokens=100,
        )
        assert result.text == "ok"
        [retry] = [e for e in bus._history if e.metadata.get("trace_kind") == "automatic_retry"]
        assert retry.metadata["original_budget"] == 100
        assert retry.metadata["retry_budget"] == 200
    else:
        with pytest.raises(AgenticModelError):
            await pipeline._run_labeled_step(
                client=object(), messages=[], tool_schemas=None, protocol=protocol,
                stream=bus, stage="reporting", iter_meta={}, max_tokens=100,
            )
        assert not [e for e in bus._history if e.metadata.get("trace_kind") == "automatic_retry"]
    assert budgets == expected_budgets


async def test_one_shot_transport_retry_emits_safe_unchanged_budget_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _make_pipeline()
    budgets: list[int] = []
    bus = StreamBus()

    async def fake_step(**kwargs):
        completion = kwargs["completion_kwargs"]
        budgets.append(next(
            int(completion[key])
            for key in ("max_output_tokens", "max_completion_tokens", "max_tokens")
            if key in completion
        ))
        if len(budgets) == 1:
            raise TimeoutError("bearer-PRIVATE")
        return LabeledStepResult(label="FINISH", text="ok")

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr("deeptutor.agents.research.pipeline.run_labeled_step", fake_step)
    monkeypatch.setattr("deeptutor.agents.research.pipeline.asyncio.sleep", no_sleep)
    protocol = LabelProtocol(
        allowed=("FINISH",), terminal=frozenset({"FINISH"}),
        intermediate=frozenset(), final=frozenset({"FINISH"}), tool_label=None,
    )
    result = await pipeline._run_labeled_step(
        client=object(), messages=[], tool_schemas=None, protocol=protocol,
        stream=bus, stage="reporting", iter_meta={}, max_tokens=100,
    )

    assert result.text == "ok"
    assert budgets == [100, 100]
    [retry] = [event for event in bus._history if event.metadata.get("trace_kind") == "automatic_retry"]
    assert retry.metadata["reason"] == "transport_transient"
    assert retry.metadata["original_budget"] == 100
    assert retry.metadata["retry_budget"] == 100
    assert "PRIVATE" not in repr(retry.to_dict())
