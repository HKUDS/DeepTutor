"""Pre-loop KB grounding (#532).

With knowledge bases attached, the pipeline must retrieve passages for the
user's question BEFORE the agent loop starts and inline them into the turn
context the model sees — so KB grounding never depends on the model emitting
a native ``rag`` tool_call. Models without reliable tool calling otherwise
answer from parametric memory with the KB silently unused.

The seed rides in the trailing user message of the loop conversation
(the system prompt stays cache-stable for the whole turn).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.tool_protocol import ToolResult


async def _collect_bus_events(bus: StreamBus) -> tuple[list[StreamEvent], asyncio.Task[Any]]:
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    return events, consumer  # type: ignore[return-value]


def _llm_chunk(*, content: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=None))]
    )


async def _async_llm_stream(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


class _ScriptedChatClient:
    def __init__(self, scripted: list[list[SimpleNamespace]]) -> None:
        self._script = list(scripted)
        self.call_count = 0
        self.calls: list[dict[str, Any]] = []

        class _Completions:
            def __init__(self, parent: _ScriptedChatClient) -> None:
                self.parent = parent

            async def create(self, **kwargs):
                self.parent.call_count += 1
                self.parent.calls.append({**kwargs, "messages": list(kwargs.get("messages") or [])})
                if not self.parent._script:
                    raise RuntimeError("Scripted client exhausted")
                return _async_llm_stream(self.parent._script.pop(0))

        class _Chat:
            def __init__(self, parent: _ScriptedChatClient) -> None:
                self.completions = _Completions(parent)

        self.chat = _Chat(self)


_PASSAGE = "This textbook targets senior undergraduate and beginning graduate students."


class _SeedRegistry:
    """Registry whose ``rag`` mirrors the real RAGTool result contract:
    passages live in ``ToolResult.metadata`` (the raw rag result dict)."""

    def __init__(self, *, metadata: dict[str, Any] | None = None, raise_exc: bool = False) -> None:
        self.executed: list[dict[str, Any]] = []
        self._metadata = metadata if metadata is not None else {"content": _PASSAGE}
        self._raise = raise_exc

    def build_prompt_text(self, *_args, **_kwargs):
        return "- rag: retrieve from a knowledge base"

    def build_openai_schemas(self, _enabled_tools):
        return [
            {
                "type": "function",
                "function": {
                    "name": "rag",
                    "description": "Retrieve",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "kb_name": {"type": "string"},
                        },
                        "required": ["query", "kb_name"],
                    },
                },
            }
        ]

    async def execute(self, name: str, **kwargs):
        self.executed.append({"name": name, "kwargs": kwargs})
        if self._raise:
            raise RuntimeError("retrieval backend down")
        return ToolResult(
            content=str(self._metadata.get("content") or ""),
            sources=[
                {"type": "rag", "query": kwargs.get("query"), "kb_name": kwargs.get("kb_name")}
            ],
            metadata=self._metadata,
        )


def _make_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    registry: _SeedRegistry,
    client: _ScriptedChatClient,
) -> AgenticChatPipeline:
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["rag"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)
    return pipeline


async def _run(pipeline: AgenticChatPipeline, context: UnifiedContext):
    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)
    await pipeline.run(context, bus)
    await asyncio.sleep(0)
    await bus.close()
    await consumer
    return events


@pytest.mark.asyncio
async def test_run_injects_kb_seed_into_turn_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _SeedRegistry()
    client = _ScriptedChatClient([[_llm_chunk(content="Senior undergraduates.")]])
    pipeline = _make_pipeline(monkeypatch, registry, client)

    context = UnifiedContext(
        session_id="s1",
        user_message="Intended Audience",
        knowledge_bases=["uc_berkeley"],
        language="en",
        metadata={"turn_id": "t1"},
    )
    events = await _run(pipeline, context)

    # Seed retrieval ran once, server-side, with the user's message as query.
    assert [e["name"] for e in registry.executed] == ["rag"]
    kwargs = registry.executed[0]["kwargs"]
    assert kwargs["query"] == "Intended Audience"
    assert kwargs["kb_name"] == "uc_berkeley"

    # Passages landed in the turn context the very first LLM call saw.
    turn_context = client.calls[0]["messages"][-1]["content"]
    assert "[Knowledge Base Context]" in turn_context
    assert "## uc_berkeley" in turn_context
    assert _PASSAGE in turn_context

    result = [e for e in events if e.type == StreamEventType.RESULT][-1]
    assert result.metadata["completed"] is True
    assert result.metadata["response"] == "Senior undergraduates."

    # The seed surfaced in the trace like an in-loop rag call.
    retrieve_events = [
        e
        for e in events
        if e.type == StreamEventType.PROGRESS and e.metadata.get("trace_role") == "retrieve"
    ]
    assert any("Intended Audience" in e.content for e in retrieve_events)


@pytest.mark.asyncio
async def test_run_seeds_each_attached_kb(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _SeedRegistry()
    client = _ScriptedChatClient([[_llm_chunk(content="Done.")]])
    pipeline = _make_pipeline(monkeypatch, registry, client)

    context = UnifiedContext(
        session_id="s1",
        user_message="Intended Audience",
        knowledge_bases=["kb-a", "kb-b"],
        language="en",
        metadata={"turn_id": "t1"},
    )
    await _run(pipeline, context)

    assert sorted(e["kwargs"]["kb_name"] for e in registry.executed) == ["kb-a", "kb-b"]
    turn_context = client.calls[0]["messages"][-1]["content"]
    assert "## kb-a" in turn_context
    assert "## kb-b" in turn_context


@pytest.mark.asyncio
async def test_run_skips_seed_without_kb(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _SeedRegistry()
    client = _ScriptedChatClient([[_llm_chunk(content="Plain answer.")]])
    pipeline = _make_pipeline(monkeypatch, registry, client)

    context = UnifiedContext(
        session_id="s1",
        user_message="Intended Audience",
        knowledge_bases=[],
        language="en",
        metadata={"turn_id": "t1"},
    )
    events = await _run(pipeline, context)

    assert registry.executed == []
    first_call_text = "\n".join(
        m["content"] for m in client.calls[0]["messages"] if isinstance(m.get("content"), str)
    )
    assert "[Knowledge Base Context]" not in first_call_text
    result = [e for e in events if e.type == StreamEventType.RESULT][-1]
    assert result.metadata["completed"] is True


@pytest.mark.asyncio
async def test_run_degrades_gracefully_when_seed_retrieval_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken retrieval backend must not break the turn — the loop runs
    exactly as before the seed seam existed."""
    registry = _SeedRegistry(raise_exc=True)
    client = _ScriptedChatClient([[_llm_chunk(content="Ungrounded answer.")]])
    pipeline = _make_pipeline(monkeypatch, registry, client)

    context = UnifiedContext(
        session_id="s1",
        user_message="Intended Audience",
        knowledge_bases=["uc_berkeley"],
        language="en",
        metadata={"turn_id": "t1"},
    )
    events = await _run(pipeline, context)

    assert len(registry.executed) == 1  # attempted
    first_call_text = "\n".join(
        m["content"] for m in client.calls[0]["messages"] if isinstance(m.get("content"), str)
    )
    assert "[Knowledge Base Context]" not in first_call_text
    result = [e for e in events if e.type == StreamEventType.RESULT][-1]
    assert result.metadata["completed"] is True


@pytest.mark.asyncio
async def test_run_skips_seed_result_that_needs_reindex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A needs-reindex / error result must not masquerade as KB passages."""
    registry = _SeedRegistry(
        metadata={"content": "This knowledge base has no index.", "needs_reindex": True}
    )
    client = _ScriptedChatClient([[_llm_chunk(content="Done.")]])
    pipeline = _make_pipeline(monkeypatch, registry, client)

    context = UnifiedContext(
        session_id="s1",
        user_message="Intended Audience",
        knowledge_bases=["uc_berkeley"],
        language="en",
        metadata={"turn_id": "t1"},
    )
    await _run(pipeline, context)

    first_call_text = "\n".join(
        m["content"] for m in client.calls[0]["messages"] if isinstance(m.get("content"), str)
    )
    assert "[Knowledge Base Context]" not in first_call_text


@pytest.mark.asyncio
async def test_run_clips_oversized_seed_passages(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.agents.chat.agentic_pipeline import KB_SEED_CHARS_PER_KB

    registry = _SeedRegistry(metadata={"content": "x" * (KB_SEED_CHARS_PER_KB + 500)})
    client = _ScriptedChatClient([[_llm_chunk(content="Done.")]])
    pipeline = _make_pipeline(monkeypatch, registry, client)

    context = UnifiedContext(
        session_id="s1",
        user_message="Intended Audience",
        knowledge_bases=["uc_berkeley"],
        language="en",
        metadata={"turn_id": "t1"},
    )
    await _run(pipeline, context)

    turn_context = client.calls[0]["messages"][-1]["content"]
    assert "...[truncated]" in turn_context
    # The block contributes at most the per-KB budget plus the header,
    # section title, truncation marker, and the trailing template line.
    seed_block = turn_context.split("[Knowledge Base Context]", 1)[1]
    assert len(seed_block) < KB_SEED_CHARS_PER_KB + 400
