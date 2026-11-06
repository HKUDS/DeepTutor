"""Stage-contract tests for the deep_research ResearchPipeline orchestration.

Locks the rephrase → decompose → research → report four-phase contract at the
pipeline boundary: stage emission order, the outline-preview and final result
envelope field contracts, the confirmed-outline planning skip, the empty
retrieval short-circuit straight to the report phase, and the report assembly
order. The LLM seam is mocked at the ``deeptutor.runtime.agentic`` primitives
(``run_agentic_loop`` / ``run_labeled_step``) so the real orchestration code
runs end to end with no network access.

Evidence: coverage gap 7 — ``deeptutor/agents/research/pipeline.py``
(origin/main @ ef2d9e5c3, 408 statements missing / 62.6%).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
from unittest.mock import patch

import pytest

from deeptutor.agents.research.pipeline import ResearchPipeline, SubTopicItem
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.agentic import LabeledStepResult, LoopOutcome
from deeptutor.runtime.stream_bus import StreamBus

pytestmark = pytest.mark.asyncio

SOURCE = "deep_research"
REPHRASE_REPLY = "Refined research topic (from rephrase)"
DECOMPOSE_REPLY = (
    '[{"title": "History of the topic", "overview": "Background and context."},'
    ' {"title": "Current state of the topic", "overview": "Recent developments."}]'
)
REPORT_OUTLINE_REPLY = (
    '{"title": "Refined research topic", "sections": ['
    '{"id": "S1", "title": "Background", "intent": "Cover history.", "block_ids": ["block_1"]},'
    '{"id": "S2", "title": "Findings", "intent": "Cover findings.", "block_ids": ["block_2"]}]}'
)
REPORT_FILLER = (
    "Detailed prose for the final report, long enough to satisfy the minimum body "
    "length the report validator enforces before a part may be persisted."
)

CONFIRMED_OUTLINE = [
    SubTopicItem(title="History of the topic", overview="Background and context."),
    SubTopicItem(title="Current state of the topic", overview="Recent developments."),
]


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

    def get(self, name):
        if name == "ask_user":
            return object()
        return None

    def get_enabled(self, _names):
        return []


class _FakeAgenticLoopLLM:
    """Stand-in for ``run_agentic_loop``: rephrase and block loops."""

    def __init__(
        self, *, rephrase_reply: str = REPHRASE_REPLY, block_reply: str = "consolidated"
    ) -> None:
        self.rephrase_reply = rephrase_reply
        self.block_reply = block_reply
        self.calls: list[str] = []

    async def __call__(self, **kwargs):
        stage = kwargs["stage"]
        self.calls.append(stage)
        if stage == "rephrasing":
            return LoopOutcome(
                final_label="FINISH", final_text=self.rephrase_reply, iterations=1, completed=True
            )
        if stage == "researching":
            return LoopOutcome(
                final_label="FINISH", final_text=self.block_reply, iterations=2, completed=True
            )
        raise AssertionError(f"unexpected agentic loop stage {stage!r}")


class _FakeLabeledStepLLM:
    """Stand-in for ``run_labeled_step``: one call, one canned labeled reply."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self._sections_written = 0
        self._section_titles = [
            section["title"] for section in json.loads(REPORT_OUTLINE_REPLY)["sections"]
        ]

    async def __call__(self, **kwargs):
        label = kwargs["allowed_labels"][0]
        stage = kwargs["stage"]
        self.calls.append((stage, label))
        if label == "OUTLINE":
            text = DECOMPOSE_REPLY if stage == "decomposing" else REPORT_OUTLINE_REPLY
        elif label == "INTRO":
            text = f"## 1. Introduction\n\n{REPORT_FILLER}"
        elif label == "SECTION":
            self._sections_written += 1
            title = self._section_titles[self._sections_written - 1]
            text = f"## {self._sections_written + 1}. {title}\n\n{REPORT_FILLER}"
        elif label == "CONCLUSION":
            text = f"## {self._sections_written + 2}. Conclusion\n\n{REPORT_FILLER}"
        else:
            raise AssertionError(f"unexpected labeled step {label!r} in stage {stage!r}")
        return LabeledStepResult(label=label, text=text, finish_reason="stop")


class _RecordingStreamBus(StreamBus):
    def __init__(self) -> None:
        super().__init__()
        self.stages_started: list[str] = []
        self.stages_ended: list[str] = []

    @asynccontextmanager
    async def stage(self, name, source="", metadata=None):
        self.stages_started.append(name)
        try:
            yield
        finally:
            self.stages_ended.append(name)


def _make_pipeline() -> ResearchPipeline:
    with (
        patch("deeptutor.agents.research.pipeline.get_llm_config", lambda: _FakeLLM()),
        patch("deeptutor.agents.research.pipeline.get_tool_registry", lambda: _FakeRegistry()),
    ):
        pipeline = ResearchPipeline(language="en", runtime_config={"queue": {"max_length": 5}})

    async def _no_pageindex() -> None:
        return None

    pipeline._prepare_pageindex_tools = _no_pageindex
    pipeline._build_client = lambda: object()
    return pipeline


async def _run(
    pipeline: ResearchPipeline,
    *,
    topic: str,
    confirmed_outline: list[SubTopicItem] | None,
    loop: _FakeAgenticLoopLLM,
    step: _FakeLabeledStepLLM,
) -> tuple[dict, list[dict], _RecordingStreamBus]:
    bus = _RecordingStreamBus()
    emitted: list[dict] = []

    async def fake_emit(stream, payload, *, source=None, usage=None):
        emitted.append({"source": source, "payload": payload})

    with (
        patch("deeptutor.agents.research.pipeline.run_agentic_loop", loop),
        patch("deeptutor.agents.research.pipeline.run_labeled_step", step),
        patch("deeptutor.agents.research.pipeline.emit_capability_result", fake_emit),
    ):
        result = await pipeline.run(
            context=UnifiedContext(session_id="s1", user_message=topic),
            topic=topic,
            confirmed_outline=confirmed_outline,
            stream=bus,
        )
    return result, emitted, bus


async def test_planning_run_stage_order_and_outline_preview_contract() -> None:
    pipeline = _make_pipeline()
    loop = _FakeAgenticLoopLLM()
    step = _FakeLabeledStepLLM()
    bus = _RecordingStreamBus()
    emitted: list[dict] = []
    decompose_topics: list[str] = []
    original_decompose = pipeline._decompose

    async def spy_decompose(*, topic, **kwargs):
        decompose_topics.append(topic)
        return await original_decompose(topic=topic, **kwargs)

    pipeline._decompose = spy_decompose

    async def fake_emit(stream, payload, *, source=None, usage=None):
        emitted.append({"source": source, "payload": payload})

    with (
        patch("deeptutor.agents.research.pipeline.run_agentic_loop", loop),
        patch("deeptutor.agents.research.pipeline.run_labeled_step", step),
        patch("deeptutor.agents.research.pipeline.emit_capability_result", fake_emit),
    ):
        result = await pipeline.run(
            context=UnifiedContext(session_id="s1", user_message="Raw research topic"),
            topic="Raw research topic",
            confirmed_outline=None,
            stream=bus,
        )

    assert bus.stages_started == ["rephrasing", "decomposing"]
    assert bus.stages_ended == ["rephrasing", "decomposing"]
    assert loop.calls == ["rephrasing"]
    assert step.calls == [("decomposing", "OUTLINE")]
    assert decompose_topics == [REPHRASE_REPLY]

    assert result == {
        "response": "",
        "output_dir": "",
        "outline_preview": True,
        "topic": REPHRASE_REPLY,
        "sub_topics": [
            {"title": "History of the topic", "overview": "Background and context."},
            {"title": "Current state of the topic", "overview": "Recent developments."},
        ],
    }
    assert emitted == []


async def test_rephrase_disabled_keeps_stage_but_skips_llm_loop() -> None:
    pipeline = _make_pipeline()
    pipeline.rephrase_enabled = False
    loop = _FakeAgenticLoopLLM()
    step = _FakeLabeledStepLLM()

    result, _emitted, bus = await _run(
        pipeline, topic="  Raw topic  ", confirmed_outline=None, loop=loop, step=step
    )

    assert bus.stages_started == ["rephrasing", "decomposing"]
    assert loop.calls == []
    assert result["outline_preview"] is True
    assert result["topic"] == "Raw topic"


async def test_confirmed_run_stage_order_result_envelope_and_report_assembly() -> None:
    pipeline = _make_pipeline()
    loop = _FakeAgenticLoopLLM()
    step = _FakeLabeledStepLLM()

    result, emitted, bus = await _run(
        pipeline, topic="Confirmed topic", confirmed_outline=CONFIRMED_OUTLINE, loop=loop, step=step
    )

    assert bus.stages_started == ["researching", "reporting"]
    assert bus.stages_ended == ["researching", "reporting"]
    assert loop.calls == ["researching", "researching"]
    assert step.calls == [
        ("reporting", "OUTLINE"),
        ("reporting", "INTRO"),
        ("reporting", "SECTION"),
        ("reporting", "SECTION"),
        ("reporting", "CONCLUSION"),
    ]

    assert result["output_dir"] == ""
    assert result["metadata"] == {
        "mode": "agentic_research",
        "topic": "Confirmed topic",
        "block_count": 2,
        "citation_count": 0,
        "partial": False,
        "failed_block_count": 0,
        "failed_block_titles": [],
    }

    response = result["response"]
    for part in (
        "# Refined research topic",
        "## 1. Introduction",
        "## 2. Background",
        "## 3. Findings",
        "## 4. Conclusion",
    ):
        assert part in response
    positions = [
        response.index(part)
        for part in (
            "## 1. Introduction",
            "## 2. Background",
            "## 3. Findings",
            "## 4. Conclusion",
        )
    ]
    assert positions == sorted(positions)

    assert len(emitted) == 1
    assert emitted[0]["source"] == SOURCE
    assert emitted[0]["payload"] == result


async def test_confirmed_run_skips_rephrase_and_decompose() -> None:
    pipeline = _make_pipeline()
    loop = _FakeAgenticLoopLLM()
    step = _FakeLabeledStepLLM()

    _result, _emitted, bus = await _run(
        pipeline, topic="Confirmed topic", confirmed_outline=CONFIRMED_OUTLINE, loop=loop, step=step
    )

    assert "rephrasing" not in bus.stages_started
    assert "decomposing" not in bus.stages_started
    assert "rephrasing" not in loop.calls
    assert all(stage == "reporting" for stage, _label in step.calls)


async def test_empty_confirmed_outline_short_circuits_straight_to_report() -> None:
    pipeline = _make_pipeline()
    loop = _FakeAgenticLoopLLM()
    step = _FakeLabeledStepLLM()

    result, emitted, bus = await _run(
        pipeline, topic="Confirmed topic", confirmed_outline=[], loop=loop, step=step
    )

    assert bus.stages_started == ["researching", "reporting"]
    assert loop.calls == []
    assert result["metadata"] == {
        "mode": "agentic_research",
        "topic": "Confirmed topic",
        "block_count": 0,
        "citation_count": 0,
        "partial": False,
        "failed_block_count": 0,
        "failed_block_titles": [],
    }
    response = result["response"]
    assert "## 1. Introduction" in response
    assert "## 4. Conclusion" in response
    assert len(emitted) == 1


async def test_completed_blocks_with_empty_knowledge_still_report() -> None:
    pipeline = _make_pipeline()
    loop = _FakeAgenticLoopLLM(block_reply="")
    step = _FakeLabeledStepLLM()

    result, _emitted, bus = await _run(
        pipeline, topic="Confirmed topic", confirmed_outline=CONFIRMED_OUTLINE, loop=loop, step=step
    )

    assert bus.stages_started == ["researching", "reporting"]
    assert loop.calls == ["researching", "researching"]
    meta = result["metadata"]
    assert meta["block_count"] == 2
    assert meta["partial"] is False
    assert meta["failed_block_count"] == 0
    assert result["response"].strip()
