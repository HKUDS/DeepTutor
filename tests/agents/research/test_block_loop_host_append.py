"""Unit tests for ``_BlockLoopHost.on_intermediate`` — APPEND handling.

The hook is the only place where the dynamic topic queue is mutated
during the per-block agentic loop, so this is the most behaviourally
load-bearing piece of the new pipeline. We exercise it directly
(without spinning up the full loop) by constructing a host and calling
the hook against an in-memory queue.

Note summarization, tool dispatch, and the actual LLM calls aren't
covered here; they happen earlier in dispatch_tools and are mocked at
that boundary by the broader pipeline tests (task 15).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.agents.research.data_structures import DynamicTopicQueue, ToolTrace
from deeptutor.agents.research.pipeline import (
    LABEL_APPEND,
    LABEL_FINISH,
    LABEL_THINK,
    ResearchedBlock,
    ResearchPipeline,
    _BlockLoopHost,
)
from deeptutor.agents.research.utils.citation_manager import CitationManager
from deeptutor.core.agentic.tool_dispatch import DispatchOutcome
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus


def _make_pipeline(monkeypatch: pytest.MonkeyPatch) -> ResearchPipeline:
    """Build a pipeline without touching real LLM config / registry I/O."""

    class _FakeLLM:
        binding = "openai"
        model = "gpt-x"
        api_key = "k"
        base_url = "u"
        api_version = None
        extra_headers = {}

    monkeypatch.setattr("deeptutor.agents.research.pipeline.get_llm_config", lambda: _FakeLLM())
    monkeypatch.setattr(
        "deeptutor.agents.research.pipeline.get_tool_registry", lambda: _FakeRegistry()
    )
    return ResearchPipeline(language="en", runtime_config={"queue": {"max_length": 5}})


class _FakeRegistry:
    def build_openai_schemas(self, _names):
        return []

    def build_prompt_text(self, _names, **_kwargs):
        return "- none"

    def get(self, _name):
        return None

    def get_enabled(self, _names):
        return []


class _ToolRegistry:
    def __init__(self, names: set[str]) -> None:
        self.names = names

    def build_openai_schemas(self, names):
        return [
            {"type": "function", "function": {"name": name, "parameters": {}}}
            for name in names
            if name in self.names
        ]

    def build_prompt_text(self, names, **_kwargs):
        return "\n".join(f"- {name}" for name in names)

    def get(self, name):
        return SimpleNamespace(name=name) if name in self.names else None

    def get_enabled(self, names):
        return [SimpleNamespace(name=name) for name in names if name in self.names]


class _FakeCitationManager:
    def __init__(self) -> None:
        self.calls = []
        self._counter = 0

    def generate_research_citation_id(self, block_id: str) -> str:
        self._counter += 1
        return f"CIT-{block_id}-{self._counter:02d}"

    def add_citation(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return True

    def get_all_citations(self):
        return {}


async def _drain_bus(bus: StreamBus) -> list:
    events: list = []

    async def _consume():
        async for event in bus.subscribe():
            events.append(event)

    import asyncio

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    return events, task


def _make_host(
    pipeline: ResearchPipeline,
    queue: DynamicTopicQueue,
    bus: StreamBus,
):
    parent_block = queue.blocks[0]
    return _BlockLoopHost(
        pipeline=pipeline,
        block=parent_block,
        queue=queue,
        citations=_FakeCitationManager(),
        topic="Test topic",
        stream=bus,
        context=UnifiedContext(session_id="s1", user_message="m"),
        client=None,
    ), parent_block


def _make_pipeline_with_registry(
    monkeypatch: pytest.MonkeyPatch,
    *,
    registry: _ToolRegistry,
    enabled_tools: list[str],
    kb_name: str | None = None,
    binding: str = "openai",
    model: str = "gpt-x",
) -> ResearchPipeline:
    fake_binding = binding
    fake_model = model

    class _FakeLLM:
        binding = fake_binding
        model = fake_model
        api_key = "k"
        base_url = "u"
        api_version = None
        extra_headers = {}

    monkeypatch.setattr("deeptutor.agents.research.pipeline.get_llm_config", lambda: _FakeLLM())
    monkeypatch.setattr("deeptutor.agents.research.pipeline.get_tool_registry", lambda: registry)
    monkeypatch.setattr("deeptutor.agents.research.pipeline.user_has_memory", lambda: False)
    monkeypatch.setattr("deeptutor.agents.research.pipeline.user_has_notebooks", lambda: False)
    # code_execution is now auto-mounted under sandbox availability; simulate a
    # configured sandbox so the block loop exposes it as an evidence tool.
    monkeypatch.setattr(
        "deeptutor.agents.research.pipeline.exec_capability_available", lambda: True
    )
    return ResearchPipeline(
        language="en",
        runtime_config={"queue": {"max_length": 5}},
        enabled_tools=enabled_tools,
        kb_name=kb_name,
    )


def test_block_tool_names_keep_only_research_evidence_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The research block loop should not inherit chat's always-on
    convenience tools. It should expose only tools that can back block
    evidence and citations."""
    registry = _ToolRegistry(
        {
            "rag",
            "web_search",
            "paper_search",
            "code_execution",
            "reason",
            "write_memory",
            "web_fetch",
            "github",
        }
    )
    pipeline = _make_pipeline_with_registry(
        monkeypatch,
        registry=registry,
        enabled_tools=["web_search", "paper_search", "code_execution", "reason"],
        kb_name="kb-main",
    )

    # Order follows compose_enabled_tools: user-toggled tools first, then the
    # conditional auto-mounts (rag for the attached KB, then code_execution
    # under sandbox availability).
    assert pipeline._block_tool_names() == [
        "web_search",
        "paper_search",
        "rag",
        "code_execution",
    ]


@pytest.mark.asyncio
async def test_block_host_rejects_finish_before_tool_when_tools_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _ToolRegistry({"web_search"})
    pipeline = _make_pipeline_with_registry(
        monkeypatch,
        registry=registry,
        enabled_tools=["web_search"],
    )
    queue = DynamicTopicQueue("t", max_length=5)
    queue.add_block("Parent topic", "")
    bus = StreamBus()
    host, _parent = _make_host(pipeline, queue, bus)

    assert await host.validate_terminal(LABEL_FINISH, "direct answer") == ("finish_without_tool")
    host._tool_rounds_used = 1
    assert await host.validate_terminal(LABEL_FINISH, "after evidence") is None


@pytest.mark.asyncio
async def test_block_host_allows_finish_when_model_cannot_call_native_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _ToolRegistry({"web_search"})
    pipeline = _make_pipeline_with_registry(
        monkeypatch,
        registry=registry,
        enabled_tools=["web_search"],
        binding="ollama",
        model="llama3.2",
    )
    queue = DynamicTopicQueue("t", max_length=5)
    queue.add_block("Parent topic", "")
    bus = StreamBus()
    host, _parent = _make_host(pipeline, queue, bus)

    assert pipeline._block_tool_names() == ["web_search"]
    assert pipeline._use_native_block_tools(["web_search"]) is False
    assert await host.validate_terminal(LABEL_FINISH, "direct answer") is None


@pytest.mark.asyncio
async def test_block_host_records_citable_tool_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    registry = _ToolRegistry({"web_search"})
    pipeline = _make_pipeline_with_registry(
        monkeypatch,
        registry=registry,
        enabled_tools=["web_search"],
    )

    async def _fake_summary(**_kwargs):
        return "Agentic RAG uses an agent-controlled retrieval loop."

    monkeypatch.setattr(pipeline, "_summarise_tool_result", _fake_summary)
    queue = DynamicTopicQueue("t", max_length=5)
    queue.add_block("Agentic RAG definition", "")
    block = queue.blocks[0]
    citations = CitationManager("test-research", cache_dir=tmp_path)
    host = _BlockLoopHost(
        pipeline=pipeline,
        block=block,
        queue=queue,
        citations=citations,
        topic="Agentic RAG",
        stream=StreamBus(),
        context=UnifiedContext(session_id="s1", user_message="m"),
        client=None,
    )
    outcome = DispatchOutcome(
        tool_messages=[
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "name": "web_search",
                "content": "raw web answer",
            }
        ]
    )

    await host._summarise_and_record(
        [{"id": "call-1", "name": "web_search", "arguments": {"query": "agentic rag"}}],
        outcome,
    )

    assert block.tool_traces
    assert block.tool_traces[0].citation_id == "CIT-1-01"
    assert outcome.tool_messages[0]["content"].startswith("[CIT-1-01]")
    assert "CIT-1-01" in citations.get_all_citations()
    references = pipeline._render_reference_list(citations)
    assert '<details id="references" open' in references
    assert '<li id="ref-cit-1-01" data-citation-id="CIT-1-01">' in references
    assert "<strong>" not in references
    assert '<span data-ref-number="1">' in references
    linked = pipeline._linkify_report_citations(
        "Agentic RAG [CIT-1-01] uses evidence; unknown [CIT-9-01] stays raw.",
        citations,
    )
    assert '[1](#ref-cit-1-01 "citation")' in linked
    assert "[CIT-9-01]" not in linked


@pytest.mark.asyncio
async def test_report_markdown_normalises_headings_and_prelinked_citations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    registry = _ToolRegistry({"web_search"})
    pipeline = _make_pipeline_with_registry(
        monkeypatch,
        registry=registry,
        enabled_tools=["web_search"],
    )
    queue = DynamicTopicQueue("t", max_length=5)
    block = queue.add_block("Agentic RAG definition", "")
    citations = CitationManager("test-research", cache_dir=tmp_path)
    tool_trace = ToolTrace.create_with_size_limit(
        tool_id="tool-1",
        citation_id="CIT-1-01",
        tool_type="web_search",
        query="agentic rag definition",
        raw_answer="raw",
        summary="Agentic RAG adds an agent control layer.",
    )
    block.add_tool_trace(tool_trace)
    await citations.add_citation_async("CIT-1-01", "web_search", tool_trace, "raw")

    cleaned = pipeline._normalise_report_markdown(
        '## ## [S1]: Definition\nBody [CIT-1-01](#ref-cit-1-01 "citation") and [CIT-9-01].',
        citations,
    )
    linked = pipeline._linkify_report_citations(
        cleaned, citations, citation_numbers={"CIT-1-01": 1}
    )

    assert cleaned.startswith("## Definition")
    assert "[CIT-9-01]" not in cleaned
    assert '[1](#ref-cit-1-01 "citation")' in linked


@pytest.mark.asyncio
async def test_on_intermediate_ignores_non_append_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _make_pipeline(monkeypatch)
    queue = DynamicTopicQueue("t", max_length=5)
    queue.add_block("Parent", "")
    bus = StreamBus()
    events, consumer = await _drain_bus(bus)

    host, _parent = _make_host(pipeline, queue, bus)
    feedback = await host.on_intermediate(LABEL_THINK, "thinking aloud")
    await bus.close()
    await consumer

    assert feedback is None
    assert len(queue.blocks) == 1
    assert events == []


@pytest.mark.asyncio
async def test_on_intermediate_append_adds_block_and_returns_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _make_pipeline(monkeypatch)
    queue = DynamicTopicQueue("t", max_length=5)
    queue.add_block("Parent topic", "")
    bus = StreamBus()
    events, consumer = await _drain_bus(bus)

    host, parent = _make_host(pipeline, queue, bus)
    body = "Quantum entanglement basics\nFoundational concepts and definitions"
    feedback = await host.on_intermediate(LABEL_APPEND, body)
    await bus.close()
    await consumer

    assert feedback is not None
    assert "Quantum entanglement basics" in feedback
    assert len(queue.blocks) == 2
    new_block = queue.blocks[-1]
    assert new_block.sub_topic == "Quantum entanglement basics"
    assert new_block.overview == "Foundational concepts and definitions"
    assert new_block.metadata.get("parent_block_id") == parent.block_id

    queue_append_events = [
        e for e in events if (e.metadata or {}).get("trace_kind") == "queue_append"
    ]
    assert queue_append_events
    assert queue_append_events[-1].metadata["new_block_id"] == new_block.block_id


@pytest.mark.asyncio
async def test_on_intermediate_append_rejects_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _make_pipeline(monkeypatch)
    queue = DynamicTopicQueue("t", max_length=5)
    queue.add_block("Quantum entanglement basics", "")
    bus = StreamBus()
    events, consumer = await _drain_bus(bus)

    host, _parent = _make_host(pipeline, queue, bus)
    feedback = await host.on_intermediate(LABEL_APPEND, "quantum entanglement basics")
    await bus.close()
    await consumer

    assert feedback is not None
    assert "similar" in feedback.lower() or "rejected" in feedback.lower()
    # Queue size unchanged.
    assert len(queue.blocks) == 1
    rejected = [
        e for e in events if (e.metadata or {}).get("trace_kind") == "queue_append_rejected"
    ]
    assert rejected
    assert rejected[-1].metadata.get("reason") == "duplicate"


@pytest.mark.asyncio
async def test_on_intermediate_append_rejects_when_queue_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _make_pipeline(monkeypatch)
    queue = DynamicTopicQueue("t", max_length=2)
    queue.add_block("a", "")
    queue.add_block("b", "")
    bus = StreamBus()
    events, consumer = await _drain_bus(bus)

    host, _parent = _make_host(pipeline, queue, bus)
    feedback = await host.on_intermediate(LABEL_APPEND, "c\n(overview)")
    await bus.close()
    await consumer

    assert feedback is not None
    # No new block added.
    assert len(queue.blocks) == 2
    rejected = [
        e for e in events if (e.metadata or {}).get("trace_kind") == "queue_append_rejected"
    ]
    assert rejected
    # The retained host emits ``"full"`` as the reason value. (Older
    # drafts used ``"queue_full"`` — verify against the canonical key.)
    assert rejected[-1].metadata.get("reason") == "full"


@pytest.mark.asyncio
async def test_on_intermediate_append_strips_markdown_heading_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLMs sometimes prefix the title with ``#`` markers — strip them so
    the queue stores a clean title."""
    pipeline = _make_pipeline(monkeypatch)
    queue = DynamicTopicQueue("t", max_length=5)
    queue.add_block("Parent", "")
    bus = StreamBus()
    events, consumer = await _drain_bus(bus)

    host, _parent = _make_host(pipeline, queue, bus)
    feedback = await host.on_intermediate(LABEL_APPEND, "## Cleaner title")
    await bus.close()
    await consumer

    assert feedback is not None
    new_block = queue.blocks[-1]
    assert new_block.sub_topic == "Cleaner title"


@pytest.mark.asyncio
async def test_on_intermediate_append_rejects_empty_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _make_pipeline(monkeypatch)
    queue = DynamicTopicQueue("t", max_length=5)
    queue.add_block("Parent", "")
    bus = StreamBus()
    events, consumer = await _drain_bus(bus)

    host, _parent = _make_host(pipeline, queue, bus)
    feedback = await host.on_intermediate(LABEL_APPEND, "   \n   ")
    await bus.close()
    await consumer

    assert feedback is not None
    # No new block added.
    assert len(queue.blocks) == 1


def test_report_outline_parser_repairs_missing_block_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _make_pipeline(monkeypatch)
    queue = DynamicTopicQueue("t", max_length=5)
    b1 = queue.add_block("Background", "history and definitions")
    b2 = queue.add_block("Risk analysis", "safety and failure modes")
    b3 = queue.add_block("Deployment playbook", "rollout and monitoring")
    blocks = [
        ResearchedBlock(block=b1, knowledge="Foundational context."),
        ResearchedBlock(block=b2, knowledge="Risk controls."),
        ResearchedBlock(block=b3, knowledge="Operational rollout."),
    ]

    outline = pipeline._parse_report_outline(
        "AI safety operations",
        """
        {
          "title": "AI Safety Operations",
          "sections": [
            {
              "id": "S1",
              "title": "Background",
              "intent": "Definitions and history",
              "block_ids": ["block_1"]
            },
            {
              "id": "S2",
              "title": "## [S2]：Deployment",
              "intent": "Rollout plan",
              "block_ids": []
            }
          ]
        }
        """,
        blocks,
    )

    covered = {block_id for section in outline.sections for block_id in section.block_ids}
    assert covered == {"block_1", "block_2", "block_3"}
    assert all(section.block_ids for section in outline.sections)
    assert outline.sections[1].title == "Deployment"
