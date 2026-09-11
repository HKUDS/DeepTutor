"""Regression coverage for the live deep-research report stream."""

from __future__ import annotations

import types

import pytest

from deeptutor.agents.research.pipeline import (
    _PROTOCOL_REPORT_SECTION,
    LABEL_SECTION,
    ReportOutline,
    ResearchPipeline,
)
from deeptutor.agents.research.utils.citation_manager import CitationManager
from deeptutor.runtime.agentic import LabeledStepResult
from deeptutor.runtime.stream_bus import StreamBus

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


def _make_pipeline(monkeypatch: pytest.MonkeyPatch) -> ResearchPipeline:
    monkeypatch.setattr("deeptutor.agents.research.pipeline.get_llm_config", lambda: _FakeLLM())
    monkeypatch.setattr(
        "deeptutor.agents.research.pipeline.get_tool_registry", lambda: _FakeRegistry()
    )
    return ResearchPipeline(language="en", runtime_config={})


async def test_report_title_is_separated_before_the_streamed_introduction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """A heading needs a blank line *before* the intro begins streaming.

    The old ordering emitted the separator only after ``_write_intro`` had
    already streamed ``## 1. Introduction``. Markdown then treated it as part
    of the H1: ``# Title## 1. Introduction``.
    """

    pipeline = _make_pipeline(monkeypatch)
    stream = StreamBus()

    async def fake_outline(self, **_kwargs):
        return ReportOutline(title="Report title", sections=())

    async def fake_intro(self, *, stream, **_kwargs):
        await stream.content("## 1. Introduction", stage="reporting")
        return "## 1. Introduction"

    async def fake_conclusion(self, *, stream, **_kwargs):
        await stream.content("## 2. Conclusion", stage="reporting")
        return "## 2. Conclusion"

    pipeline._gen_report_outline = types.MethodType(fake_outline, pipeline)
    pipeline._write_intro = types.MethodType(fake_intro, pipeline)
    pipeline._write_conclusion = types.MethodType(fake_conclusion, pipeline)

    await pipeline._write_report(
        topic="topic",
        blocks=[],
        citations=CitationManager("test-report", cache_dir=tmp_path),
        stream=stream,
        client=None,
    )

    live_content = "".join(
        event.content for event in stream._history if event.type.value == "content"
    )
    assert live_content.startswith("# Report title\n\n## 1. Introduction")


async def test_report_step_retries_an_idle_truncated_response_before_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An idle provider stream must not leak a partial section or count as success."""

    pipeline = _make_pipeline(monkeypatch)
    stream = StreamBus()
    attempts = 0

    async def fake_run_labeled_step(self, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return LabeledStepResult(
                label=LABEL_SECTION,
                text="## 2. Partial section that stops in the middle",
                stream_idle_timeout=True,
            )
        return LabeledStepResult(
            label=LABEL_SECTION,
            text=(
                "## 2. Complete section\n\n"
                "This replacement is long enough to be a real report section, "
                "and it ends with a complete sentence."
            ),
            finish_reason="stop",
        )

    pipeline._run_labeled_step = types.MethodType(fake_run_labeled_step, pipeline)

    result = await pipeline._stream_report_step(
        system_prompt="system",
        user_prompt="user",
        protocol=_PROTOCOL_REPORT_SECTION,
        stream=stream,
        client=None,
        label="Write section",
        call_id_root="test-report-section",
        max_tokens=1000,
        extra_meta={"report_part": "section"},
    )

    live_content = "".join(
        event.content for event in stream._history if event.type.value == "content"
    )
    assert attempts == 2
    assert result == live_content
    assert "Partial section" not in live_content
    assert "Complete section" in live_content


async def test_report_step_rejects_empty_success_after_all_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _make_pipeline(monkeypatch)
    stream = StreamBus()

    async def fake_run_labeled_step(self, **_kwargs):
        return LabeledStepResult(label=LABEL_SECTION, text="", finish_reason="stop")

    pipeline._run_labeled_step = types.MethodType(fake_run_labeled_step, pipeline)

    with pytest.raises(RuntimeError, match="incomplete"):
        await pipeline._stream_report_step(
            system_prompt="system",
            user_prompt="user",
            protocol=_PROTOCOL_REPORT_SECTION,
            stream=stream,
            client=None,
            label="Write section",
            call_id_root="test-empty-section",
            max_tokens=1000,
        )

    assert not [event for event in stream._history if event.type.value == "content"]
