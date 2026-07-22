from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.tool_protocol import ToolResult
from deeptutor.core.trace import build_trace_metadata


async def _collect_bus_events(bus: StreamBus) -> tuple[list[StreamEvent], asyncio.Task[Any]]:
    events: list[StreamEvent] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    return events, consumer  # type: ignore[return-value]


def _llm_chunk(
    *,
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> SimpleNamespace:
    delta_fields: dict[str, Any] = {"content": content}
    if tool_calls is not None:
        delta_fields["tool_calls"] = [
            SimpleNamespace(
                index=tc.get("index", i),
                id=tc.get("id"),
                function=SimpleNamespace(
                    name=tc.get("name"),
                    arguments=tc.get("arguments"),
                ),
            )
            for i, tc in enumerate(tool_calls)
        ]
    else:
        delta_fields["tool_calls"] = None
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(**delta_fields))])


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


@pytest.mark.asyncio
async def test_execute_tool_call_streams_retrieve_progress_for_rag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )

    class FakeRegistry:
        def get_enabled(self, selected):
            return [SimpleNamespace(name=name) for name in selected]

        async def execute(self, name: str, **kwargs):
            event_sink = kwargs.get("event_sink")
            if event_sink is not None:
                await event_sink(
                    "status", "Selecting provider: llamaindex", {"provider": "llamaindex"}
                )
                await event_sink("status", "Retrieving chunks...", {"mode": "hybrid"})
            return ToolResult(
                content=f"{name} => grounded answer",
                sources=[{"tool": name}],
                metadata={"tool": name},
                success=True,
            )

    registry = FakeRegistry()
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_tool_registry", lambda: registry
    )

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry

    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)
    context = UnifiedContext(
        session_id="session-1",
        user_message="what is a transformer",
        enabled_tools=["rag"],
        knowledge_bases=["demo-kb"],
        language="en",
        metadata={"turn_id": "turn-1"},
    )
    trace_meta = build_trace_metadata(
        call_id="chat-react-1",
        phase="acting",
        label="Round 1",
        call_kind="react_round",
        trace_id="chat-react-1",
        trace_role="thought",
        trace_group="react_round",
        round=1,
    )
    retrieve_meta = pipeline._retrieve_trace_metadata(
        trace_meta,
        context=context,
        tool_name="rag",
        tool_args={"query": "transformer model", "kb_name": "demo-kb"},
    )

    result = await pipeline._execute_tool_call(
        "rag",
        {"query": "transformer model", "kb_name": "demo-kb"},
        stream=bus,
        retrieve_meta=retrieve_meta,
    )
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    assert result["success"] is True
    retrieve_events = [
        event
        for event in events
        if event.type == StreamEventType.PROGRESS and event.metadata.get("trace_role") == "retrieve"
    ]
    assert [event.content for event in retrieve_events] == [
        "Query: transformer model",
        "Selecting provider: llamaindex",
        "Retrieving chunks...",
        "Retrieve complete (22 chars)",
    ]


_ALWAYS_ON_TOOLS = ["write_memory", "web_fetch", "github", "ask_user", "cron"]


def _stub_optional_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin auto-mount gates to ``False`` so tests see ONLY the tools each
    case explicitly asserts on. Without this the dev workspace's real
    memory / notebook contents could non-deterministically inject extra
    tools and flake the assertions."""
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_raw=lambda *_args, **_kwargs: ""),
    )
    monkeypatch.setattr(
        "deeptutor.services.notebook.get_notebook_manager",
        lambda: SimpleNamespace(list_notebooks=lambda: []),
    )
    monkeypatch.setattr(
        "deeptutor.services.cron.get_cron_service",
        lambda: SimpleNamespace(),
    )


def test_compose_enabled_tools_injects_rag_when_kb_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_optional_services(monkeypatch)
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline.registry = SimpleNamespace(
        get_enabled=lambda selected: [SimpleNamespace(name=n) for n in selected]
    )
    context = UnifiedContext(
        user_message="hi",
        enabled_tools=["web_search"],
        knowledge_bases=["kb-a"],
    )
    assert pipeline._compose_enabled_tools(context) == [
        "web_search",
        "rag",
        *_ALWAYS_ON_TOOLS,
    ]


def test_compose_enabled_tools_omits_rag_when_no_kb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_optional_services(monkeypatch)
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline.registry = SimpleNamespace(
        get_enabled=lambda selected: [SimpleNamespace(name=n) for n in selected]
    )
    # ``rag`` is not user-toggleable — even if a caller passes it in
    # ``enabled_tools``, the ``CHAT_OPTIONAL_TOOLS`` filter drops it, and
    # without an attached KB it does not get auto-mounted either.
    context = UnifiedContext(
        user_message="hi",
        enabled_tools=["rag", "web_search"],
        knowledge_bases=[],
    )
    assert pipeline._compose_enabled_tools(context) == [
        "web_search",
        *_ALWAYS_ON_TOOLS,
    ]


def test_compose_enabled_tools_auto_mounts_read_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``read_memory`` joins the tool set iff the active user has memory."""
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_raw=lambda *_args, **_kwargs: "some content"),
    )
    monkeypatch.setattr(
        "deeptutor.services.notebook.get_notebook_manager",
        lambda: SimpleNamespace(list_notebooks=lambda: []),
    )
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline.registry = SimpleNamespace(
        get_enabled=lambda selected: [SimpleNamespace(name=n) for n in selected]
    )
    context = UnifiedContext(
        user_message="hi",
        enabled_tools=[],
        knowledge_bases=[],
    )
    assert pipeline._compose_enabled_tools(context) == [
        "read_memory",
        *_ALWAYS_ON_TOOLS,
    ]


def test_compose_enabled_tools_auto_mounts_notebook_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``list_notebook`` + ``write_note`` mount together iff user has notebooks."""
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_raw=lambda *_args, **_kwargs: ""),
    )
    monkeypatch.setattr(
        "deeptutor.services.notebook.get_notebook_manager",
        lambda: SimpleNamespace(list_notebooks=lambda: [{"id": "nb-1", "name": "Math"}]),
    )
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline.registry = SimpleNamespace(
        get_enabled=lambda selected: [SimpleNamespace(name=n) for n in selected]
    )
    context = UnifiedContext(user_message="hi", enabled_tools=[], knowledge_bases=[])
    assert pipeline._compose_enabled_tools(context) == [
        "list_notebook",
        "write_note",
        *_ALWAYS_ON_TOOLS,
    ]


def test_augment_tool_kwargs_injects_geogebra_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``geogebra_analysis`` is server-side wired: the LLM never sees the
    raw image bytes, so the pipeline must inject the first image
    attachment's base64 into the kwargs (overwriting any value the LLM
    may have hallucinated) before the tool runs. Without this, the
    underlying VisionSolverAgent fails fast with 'No image provided.'.
    """
    from deeptutor.core.context import Attachment

    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline.language = "zh"
    context = UnifiedContext(
        user_message="solve this triangle",
        attachments=[
            Attachment(
                type="image",
                base64="REAL_IMG_BYTES",
                filename="problem.png",
                mime_type="image/png",
            ),
        ],
        language="zh",
    )

    # LLM-provided kwargs may include a hallucinated image_base64; we
    # must overwrite it from the attachment AND wrap it as a data URI so
    # the vision LLM accepts the image (otherwise all 4 pipeline stages
    # silently fail with a malformed image_url).
    augmented = pipeline._augment_tool_kwargs(
        "geogebra_analysis",
        {"image_base64": "HALLUCINATED", "question": "stale question"},
        context,
    )

    assert augmented["image_base64"] == "data:image/png;base64,REAL_IMG_BYTES"
    assert augmented["language"] == "zh"


def test_augment_tool_kwargs_geogebra_no_image_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the user toggled geogebra_analysis on but uploaded no image,
    the pipeline leaves ``image_base64`` empty; the tool itself reports
    the friendly 'No image provided.' error rather than the pipeline
    silently hiding the tool. This keeps the contract observable in
    chat history."""
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline.language = "en"
    context = UnifiedContext(
        user_message="describe figure",
        attachments=[],
        language="en",
    )
    augmented = pipeline._augment_tool_kwargs("geogebra_analysis", {}, context)
    assert "image_base64" not in augmented or augmented["image_base64"] == ""
    assert augmented["language"] == "en"


def test_kb_note_lists_attached_knowledge_bases() -> None:
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline.language = "en"
    context = UnifiedContext(
        user_message="hi",
        enabled_tools=["rag"],
        knowledge_bases=["kb-a", "kb-b"],
    )
    note = pipeline._kb_system_note(context)
    assert "kb-a" in note and "kb-b" in note
    assert "kb_name must" in note


@pytest.mark.asyncio
async def test_dispatch_records_pause_when_tool_emits_pause_for_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ask_user``-style pause requests surface on ``_DispatchOutcome``.

    The dispatch step must (a) preserve the paused tool's ``tool_call_id``
    so the pipeline can later overwrite the right ``role=tool`` message
    content, and (b) carry the structured ``ask_user`` payload through to
    the loop for the pending-user-input UI hint. Terminate/pause are
    mutually exclusive — pause does NOT set the terminate flag.
    """
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )

    class _PausingRegistry:
        def get_enabled(self, selected):
            return [SimpleNamespace(name=name) for name in selected]

        async def execute(self, name: str, **kwargs):
            assert name == "ask_user"
            ask_user = {"question": "Lecture or exam?", "options": ["Lecture", "Exam"]}
            return ToolResult(
                content="[awaiting user reply]",
                metadata={"ask_user": ask_user},
                pause_for_user=ask_user,
            )

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _PausingRegistry()

    context = UnifiedContext(
        session_id="s1",
        user_message="help me",
        metadata={"turn_id": "t1"},
    )
    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)

    outcome = await pipeline._dispatch_tool_calls(
        tool_calls=[
            {"id": "call-1", "name": "ask_user", "arguments": "{}"},
        ],
        context=context,
        stream=bus,
        iteration_index=0,
    )
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    assert outcome.pause is True
    assert outcome.terminate is False
    assert outcome.pause_tool_call_id == "call-1"
    assert outcome.pause_payload is not None
    assert outcome.pause_payload["tool_name"] == "ask_user"
    assert outcome.pause_payload["ask_user"]["question"] == "Lecture or exam?"
    # The placeholder content still lands in the role=tool message; the
    # pipeline (not _dispatch_tool_calls) is responsible for overwriting
    # it with the user's reply once it arrives.
    assert outcome.tool_messages[0]["content"].startswith("[awaiting user reply")


@pytest.mark.asyncio
async def test_dispatch_collapses_duplicate_parallel_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identical parallel tool_calls execute once; later duplicates get a stub.

    Guards against the LLM emitting two ``ask_user`` calls with the same
    args in a single assistant message (which would otherwise render two
    cards and only resolve the first one). The protocol-level
    tool_call/tool_message pairing is preserved internally — one
    ``role=tool`` message per emitted ``tool_call_id`` — but duplicate
    ``ask_user`` calls are hidden from the user-facing trace stream.
    """
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )

    exec_count = 0

    class _PausingRegistry:
        def get_enabled(self, selected):
            return [SimpleNamespace(name=name) for name in selected]

        async def execute(self, name: str, **kwargs):
            nonlocal exec_count
            exec_count += 1
            assert name == "ask_user"
            ask_user = {"question": "Lecture or exam?", "options": ["Lecture", "Exam"]}
            return ToolResult(
                content="[awaiting user reply]",
                metadata={"ask_user": ask_user},
                pause_for_user=ask_user,
            )

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _PausingRegistry()

    context = UnifiedContext(
        session_id="s1",
        user_message="help me",
        metadata={"turn_id": "t1"},
    )
    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)

    outcome = await pipeline._dispatch_tool_calls(
        tool_calls=[
            {"id": "call-1", "name": "ask_user", "arguments": "{}"},
            {"id": "call-2", "name": "ask_user", "arguments": "{}"},
        ],
        context=context,
        stream=bus,
        iteration_index=0,
    )
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    # Tool was only run for the primary; duplicate short-circuited.
    assert exec_count == 1
    # Pause is tracked on the primary; the duplicate does not produce a
    # second pause payload.
    assert outcome.pause is True
    assert outcome.pause_tool_call_id == "call-1"
    # Both tool_call_ids get a role=tool message so the next OpenAI call
    # has matched pairs, but only one carries the awaiting placeholder.
    assert len(outcome.tool_messages) == 2
    assert outcome.tool_messages[0]["tool_call_id"] == "call-1"
    assert outcome.tool_messages[0]["content"].startswith("[awaiting user reply")
    assert outcome.tool_messages[1]["tool_call_id"] == "call-2"
    assert "duplicate parallel ask_user" in outcome.tool_messages[1]["content"]
    assert "call-1" in outcome.tool_messages[1]["content"]
    # Only the primary ask_user call is visible in the trace stream; the
    # duplicate stub stays internal so the frontend renders one trace row
    # and one card.
    ask_user_tool_calls = [e for e in events if e.type == "tool_call" and e.content == "ask_user"]
    assert len(ask_user_tool_calls) == 1
    tool_results_with_ask_user = [
        e
        for e in events
        if e.type == "tool_result"
        and isinstance(e.metadata.get("tool_metadata"), dict)
        and "ask_user" in e.metadata["tool_metadata"]
    ]
    assert len(tool_results_with_ask_user) == 1


@pytest.mark.asyncio
async def test_dispatch_allows_only_one_parallel_ask_user_even_with_different_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any second ask_user in the same tool batch is suppressed.

    The LLM is instructed to bundle multiple questions into one
    ``questions`` array. If it instead emits multiple ask_user tool_calls
    with different args, the first call is the only one that pauses and
    the only one visible to the frontend; later calls get internal stub
    tool messages to preserve API protocol pairing.
    """
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )

    executed: list[dict[str, object]] = []

    class _PausingRegistry:
        def get_enabled(self, selected):
            return [SimpleNamespace(name=name) for name in selected]

        async def execute(self, name: str, **kwargs):
            executed.append({"name": name, "kwargs": kwargs})
            assert name == "ask_user"
            ask_user = {
                "questions": [
                    {
                        "id": "q",
                        "prompt": str(kwargs.get("question") or "Question?"),
                        "options": [],
                    }
                ]
            }
            return ToolResult(
                content="[awaiting user reply]",
                metadata={"ask_user": ask_user},
                pause_for_user=ask_user,
            )

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _PausingRegistry()
    context = UnifiedContext(
        session_id="s1",
        user_message="help me",
        metadata={"turn_id": "t1"},
    )
    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)

    outcome = await pipeline._dispatch_tool_calls(
        tool_calls=[
            {"id": "call-1", "name": "ask_user", "arguments": '{"question":"First?"}'},
            {"id": "call-2", "name": "ask_user", "arguments": '{"question":"Second?"}'},
        ],
        context=context,
        stream=bus,
        iteration_index=0,
    )
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    assert len(executed) == 1
    assert outcome.pause is True
    assert outcome.pause_tool_call_id == "call-1"
    assert len(outcome.tool_messages) == 2
    assert outcome.tool_messages[0]["content"].startswith("[awaiting user reply")
    assert "duplicate parallel ask_user" in outcome.tool_messages[1]["content"]
    assert "call-1" in outcome.tool_messages[1]["content"]
    ask_user_tool_calls = [e for e in events if e.type == "tool_call" and e.content == "ask_user"]
    assert len(ask_user_tool_calls) == 1
    ask_user_results = [
        e
        for e in events
        if e.type == "tool_result"
        and isinstance(e.metadata.get("tool_metadata"), dict)
        and "ask_user" in e.metadata["tool_metadata"]
    ]
    assert len(ask_user_results) == 1


@pytest.mark.asyncio
async def test_await_user_reply_overwrites_matching_tool_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The waiter result must land in the *paused* tool message, not the
    sibling ones — matched by ``tool_call_id``."""
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )
    pipeline = AgenticChatPipeline(language="en")

    from deeptutor.agents.chat.agentic_pipeline import _DispatchOutcome

    paused_msg = {
        "role": "tool",
        "tool_call_id": "call-pause",
        "name": "ask_user",
        "content": "[awaiting user reply]",
    }
    sibling_msg = {
        "role": "tool",
        "tool_call_id": "call-other",
        "name": "rag",
        "content": "rag answer",
    }
    dispatch = _DispatchOutcome(
        sources=[],
        tool_messages=[paused_msg, sibling_msg],
        pause=True,
        pause_payload={
            "tool_name": "ask_user",
            "ask_user": {"question": "?", "options": []},
        },
        pause_tool_call_id="call-pause",
    )

    async def _waiter() -> str:
        return "Lecture"

    context = UnifiedContext(
        session_id="s1",
        user_message="m",
        metadata={"turn_id": "t1", "wait_for_user_reply": _waiter},
    )
    bus = StreamBus()
    _events, consumer = await _collect_bus_events(bus)

    resumed = await pipeline._await_user_reply_and_resolve(
        context=context, stream=bus, dispatch=dispatch
    )
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    assert resumed is True
    # The paused tool's content is overwritten with a directive body
    # that (a) preserves the user's literal answer and (b) instructs
    # the model to continue addressing the original request rather
    # than ending the turn with a one-line acknowledgment.
    assert paused_msg["content"].startswith("User answered: Lecture")
    assert "ask_user resolved" in paused_msg["content"]
    assert "Do not stop" in paused_msg["content"]
    # Sibling untouched — only the paused tool_call_id gets resolved.
    assert sibling_msg["content"] == "rag answer"


@pytest.mark.asyncio
async def test_await_user_reply_handles_structured_v2_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v2 multi-question payload from the runtime is rendered as one
    ``- <prompt>\\n  → <answer>`` line per question and skipped answers
    surface as ``(skipped)``."""
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )
    pipeline = AgenticChatPipeline(language="en")
    from deeptutor.agents.chat.agentic_pipeline import _DispatchOutcome

    paused_msg = {
        "role": "tool",
        "tool_call_id": "call-pause",
        "name": "ask_user",
        "content": "[awaiting user reply]",
    }
    dispatch = _DispatchOutcome(
        sources=[],
        tool_messages=[paused_msg],
        pause=True,
        pause_payload={
            "tool_name": "ask_user",
            "ask_user": {
                "intro": None,
                "questions": [
                    {"id": "scope", "prompt": "Which direction?", "options": []},
                    {"id": "depth", "prompt": "How deep?", "options": []},
                    {"id": "format", "prompt": "What format?", "options": []},
                ],
            },
        },
        pause_tool_call_id="call-pause",
    )

    async def _waiter() -> dict:
        return {
            "text": "",
            "answers": [
                {"questionId": "scope", "text": "applications"},
                {"questionId": "depth", "text": ""},
                {"questionId": "format", "text": "learning path"},
            ],
        }

    context = UnifiedContext(
        session_id="s1",
        user_message="m",
        metadata={"turn_id": "t1", "wait_for_user_reply": _waiter},
    )
    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)

    resumed = await pipeline._await_user_reply_and_resolve(
        context=context, stream=bus, dispatch=dispatch
    )
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    assert resumed is True
    body = paused_msg["content"]
    assert body.startswith("User answered:")
    assert "Which direction?" in body
    assert "-> applications" in body
    assert "How deep?" in body
    assert "-> (skipped)" in body
    assert "What format?" in body
    assert "-> learning path" in body
    assert "ask_user resolved" in body

    resolved_events = [
        e
        for e in events
        if e.type == StreamEventType.PROGRESS and e.metadata.get("ask_user_resolved") is True
    ]
    assert resolved_events
    assert resolved_events[-1].metadata.get("answers") == [
        {"questionId": "scope", "text": "applications"},
        {"questionId": "depth", "text": ""},
        {"questionId": "format", "text": "learning path"},
    ]


@pytest.mark.asyncio
async def test_await_user_reply_falls_back_to_terminator_without_waiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct unit-test invocation has no runtime → emit terminator fallback."""
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )
    pipeline = AgenticChatPipeline(language="en")
    from deeptutor.agents.chat.agentic_pipeline import _DispatchOutcome

    dispatch = _DispatchOutcome(
        sources=[],
        tool_messages=[{"role": "tool", "tool_call_id": "p", "name": "ask_user", "content": "?"}],
        pause=True,
        pause_payload={
            "tool_name": "ask_user",
            "ask_user": {"question": "Lecture or exam?", "options": []},
        },
        pause_tool_call_id="p",
    )
    context = UnifiedContext(session_id="s1", user_message="m", metadata={})
    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)

    resumed = await pipeline._await_user_reply_and_resolve(
        context=context, stream=bus, dispatch=dispatch
    )
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    assert resumed is False
    # Should have emitted a content event carrying the ask_user payload
    # so the frontend can still surface the question as a terminal turn.
    content_events = [e for e in events if e.type == StreamEventType.CONTENT]
    assert content_events, "expected fallback to emit a content event"
    assert "Lecture or exam?" in content_events[0].content


@pytest.mark.asyncio
async def test_run_does_not_finish_on_unlabeled_reply_after_ask_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After ask_user resumes, plain unlabeled text is a protocol violation,
    not a final answer. The loop must repair and keep going until FINISH."""
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )

    ask_user_payload = {"question": "Lecture or exam?", "options": ["Lecture", "Exam"]}

    class _AskUserOnlyRegistry:
        def build_prompt_text(self, *_args, **_kwargs):
            return "- ask_user: ask a clarifying question"

        def deferred_tools(self):
            return []

        def build_openai_schemas(self, _enabled_tools):
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "ask_user",
                        "description": "Ask user",
                        "parameters": {
                            "type": "object",
                            "properties": {"question": {"type": "string"}},
                            "required": ["question"],
                        },
                    },
                }
            ]

        async def execute(self, name: str, **_kwargs):
            assert name == "ask_user"
            return ToolResult(
                content="[awaiting user reply]",
                metadata={"ask_user": ask_user_payload},
                pause_for_user=ask_user_payload,
            )

    client = _ScriptedChatClient(
        [
            [
                _llm_chunk(content="``TOOL``\nI need to clarify."),
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "call-ask",
                            "name": "ask_user",
                            "arguments": json.dumps(
                                {
                                    "question": ask_user_payload["question"],
                                    "options": ask_user_payload["options"],
                                }
                            ),
                        }
                    ]
                ),
            ],
            [_llm_chunk(content="Okay, lecture mode.")],
            [_llm_chunk(content="``FINISH``\nHere is the lecture-focused answer.")],
        ]
    )

    async def _waiter() -> str:
        return "Lecture"

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _AskUserOnlyRegistry()
    monkeypatch.setattr(
        pipeline,
        "_compose_enabled_tools",
        lambda _context: ["ask_user"],
    )
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    context = UnifiedContext(
        session_id="s1",
        user_message="Help me prepare",
        language="en",
        metadata={"turn_id": "t1", "wait_for_user_reply": _waiter},
    )
    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)

    await pipeline.run(context, bus)
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    assert client.call_count == 2
    result_events = [e for e in events if e.type == StreamEventType.RESULT]
    assert result_events
    assert result_events[-1].content == ""
    assert result_events[-1].source == "chat"
    result_payload = result_events[-1]
    assert result_payload.metadata["completed"] is True
    assert result_payload.metadata["response"] == "Okay, lecture mode."


@pytest.mark.asyncio
async def test_run_forces_finish_after_iteration_budget_ends_on_think(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loop must not end on a THINK trace when max_iterations is hit."""
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )
    client = _ScriptedChatClient(
        [
            [_llm_chunk(content="``THINK``\nI still need to organize the answer.")],
            [_llm_chunk(content="``THINK``\nI am still thinking.")],
            [_llm_chunk(content="``FINISH``\nFinal answer after forced finish.")],
        ]
    )

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = SimpleNamespace(build_prompt_text=lambda *_args, **_kwargs: "- none")
    pipeline._max_iterations = 1
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)
    await pipeline.run(UnifiedContext(session_id="s1", user_message="Explain X"), bus)
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    assert client.call_count == 3
    result = [e for e in events if e.type == StreamEventType.RESULT][-1]
    assert result.metadata["completed"] is True
    assert result.metadata["iterations"] == 3
    assert result.metadata["response"] == "Final answer after forced finish."
    assert client.calls[1].get("tools") is None
    assert "first line must be ``FINISH``" in client.calls[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_run_repairs_multiple_labels_in_one_llm_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single LLM call may not say THINK and then TOOL/FINISH in the body."""
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )
    client = _ScriptedChatClient(
        [
            [_llm_chunk(content="``THINK``\nFirst thought.\n``TOOL``\nMaybe search.")],
            [_llm_chunk(content="``FINISH``\nClean final.")],
        ]
    )

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = SimpleNamespace(build_prompt_text=lambda *_args, **_kwargs: "- none")
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)
    await pipeline.run(UnifiedContext(session_id="s1", user_message="Help"), bus)
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    result = [e for e in events if e.type == StreamEventType.RESULT][-1]
    assert result.metadata["completed"] is True
    assert result.metadata["response"] == "Clean final."
    protocol_warnings = [
        e
        for e in events
        if e.type == StreamEventType.PROGRESS
        and e.metadata.get("protocol_violation") == "multiple_labels"
    ]
    assert protocol_warnings
    assert any(
        "multiple protocol labels" in (m.get("content") or "") for m in client.calls[1]["messages"]
    )


@pytest.mark.asyncio
async def test_invalid_finish_body_is_not_streamed_before_protocol_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A FINISH reply containing another label is rejected before answer streaming."""
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )
    client = _ScriptedChatClient(
        [
            [_llm_chunk(content="``FINISH``\nPremature answer.\n``THINK``\nActually...")],
            [_llm_chunk(content="``FINISH``\nClean final.")],
        ]
    )

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = SimpleNamespace(build_prompt_text=lambda *_args, **_kwargs: "- none")
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)
    await pipeline.run(UnifiedContext(session_id="s1", user_message="Help"), bus)
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    content_events = [e for e in events if e.type == StreamEventType.CONTENT]
    assert [e.content for e in content_events] == ["Clean final."]
    result = [e for e in events if e.type == StreamEventType.RESULT][-1]
    assert result.metadata["completed"] is True
    assert result.metadata["response"] == "Clean final."


@pytest.mark.asyncio
async def test_run_emits_final_fallback_if_forced_finish_never_complies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even pathological non-compliance should not leave THINK as the last UI artefact."""
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )
    client = _ScriptedChatClient(
        [
            [_llm_chunk(content="``THINK``\nInitial thought.")],
            [_llm_chunk(content="``THINK``\nStill thinking 1.")],
            [_llm_chunk(content="``THINK``\nStill thinking 2.")],
            [_llm_chunk(content="``THINK``\nStill thinking 3.")],
        ]
    )

    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = SimpleNamespace(build_prompt_text=lambda *_args, **_kwargs: "- none")
    pipeline._max_iterations = 1
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)
    await pipeline.run(UnifiedContext(session_id="s1", user_message="Explain X"), bus)
    await asyncio.sleep(0)
    await bus.close()
    await consumer

    result = [e for e in events if e.type == StreamEventType.RESULT][-1]
    assert result.metadata["completed"] is False
    assert "valid ``FINISH`` response" in result.metadata["response"]
    content_events = [e for e in events if e.type == StreamEventType.CONTENT]
    assert content_events
    assert content_events[-1].metadata.get("protocol_fallback") is True
    assert "valid ``FINISH`` response" in content_events[-1].content


def test_build_llm_tool_schemas_kb_name_enum_matches_attached() -> None:
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)

    class FakeRegistry:
        def build_openai_schemas(self, _enabled_tools):
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "rag",
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

    pipeline.registry = FakeRegistry()

    context = UnifiedContext(
        user_message="hi",
        enabled_tools=["rag"],
        knowledge_bases=["kb-a", "kb-b"],
    )
    [schema] = pipeline._build_llm_tool_schemas(["rag"], context)
    parameters = schema["function"]["parameters"]
    assert parameters["properties"]["kb_name"]["enum"] == ["kb-a", "kb-b"]
    assert parameters["properties"]["query"].get("minLength") == 1
    assert parameters["required"] == ["query", "kb_name"]
    assert parameters["additionalProperties"] is False
