from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from deeptutor.agents.chat import agent_loop as agent_loop_mod
from deeptutor.agents.chat.agent_loop import InlineThinkFilter
from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.capabilities.explore_context import explorer as explorer_mod
from deeptutor.capabilities.mastery import MASTERY_TOOL_NAMES
from deeptutor.core.context import Attachment, UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus
from deeptutor.core.tool_protocol import ToolResult
from deeptutor.services.llm import LLMProviderTransportError


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
    usage: Any = None,
    finish_reason: str | None = None,
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
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(**delta_fields),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )


def _usage_only_chunk(*, prompt: int, completion: int, total: int) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        ),
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


class _Registry:
    def __init__(self) -> None:
        self.executed: list[dict[str, Any]] = []

    def deferred_tools(self):
        return []

    def build_prompt_text(self, _enabled, **_kwargs):
        return "- `web_search` - Search the web"

    def build_openai_schemas(self, _enabled):
        return [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "ask_user",
                    "description": "Ask the user",
                    "parameters": {
                        "type": "object",
                        "properties": {"questions": {"type": "array"}},
                        "required": ["questions"],
                    },
                },
            },
        ]

    async def execute(self, name: str, **kwargs):
        self.executed.append({"name": name, "kwargs": kwargs})
        return ToolResult(
            content="tool answer",
            sources=[{"tool": name}],
            metadata={"tool": name},
            success=True,
        )


@pytest.fixture(autouse=True)
def _fake_llm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "deeptutor.agents.chat.agentic_pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai",
            model="gpt-test",
            api_key="k",
            base_url="u",
            api_version=None,
            extra_headers={},
            reasoning_effort=None,
        ),
    )


async def _run(pipeline: AgenticChatPipeline, context: UnifiedContext):
    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)
    await pipeline.run(context, bus)
    await asyncio.sleep(0)
    await bus.close()
    await consumer
    return events


def _contents(events: list[StreamEvent]) -> list[str]:
    return [e.content for e in events if e.type == StreamEventType.CONTENT]


def _call_roles(events: list[StreamEvent]) -> list[str]:
    """Ordered list of per-round call_role markers ('narration' | 'finish')."""
    return [
        str(e.metadata.get("call_role"))
        for e in events
        if e.type == StreamEventType.PROGRESS
        and e.metadata.get("call_state") == "complete"
        and "call_role" in e.metadata
    ]


def _result(events: list[StreamEvent]) -> StreamEvent:
    return [e for e in events if e.type == StreamEventType.RESULT][-1]


class TestInlineThinkFilter:
    @staticmethod
    def _run(chunks: list[str]) -> list[tuple[str, str]]:
        f = InlineThinkFilter()
        out: list[tuple[str, str]] = []
        for c in chunks:
            out.extend(f.feed(c))
        out.extend(f.flush())
        return out

    @staticmethod
    def _join(segments: list[tuple[str, str]], kind: str) -> str:
        return "".join(text for k, text in segments if k == kind)

    def test_plain_content_passes_through(self) -> None:
        segs = self._run(["hello ", "world"])
        assert self._join(segs, "content") == "hello world"
        assert self._join(segs, "thinking") == ""

    def test_think_block_split_to_thinking(self) -> None:
        segs = self._run(["<think>plan</think>answer"])
        assert self._join(segs, "thinking") == "plan"
        assert self._join(segs, "content") == "answer"

    def test_tag_split_across_chunks(self) -> None:
        segs = self._run(["before<thi", "nk>inner</th", "ink>after"])
        assert self._join(segs, "content") == "beforeafter"
        assert self._join(segs, "thinking") == "inner"

    def test_unclosed_think_stays_thinking(self) -> None:
        # Interrupted stream: an opened think block never closes — its text
        # must never surface as content (mirrors clean_thinking_tags).
        segs = self._run(["<think>only reasoning, no answer"])
        assert self._join(segs, "content") == ""
        assert "only reasoning" in self._join(segs, "thinking")

    def test_thinking_variant_tag(self) -> None:
        segs = self._run(["<thinking>x</thinking>y"])
        assert self._join(segs, "thinking") == "x"
        assert self._join(segs, "content") == "y"

    def test_non_think_tags_untouched(self) -> None:
        segs = self._run(["a <b>bold</b> ", "and a < b comparison"])
        assert self._join(segs, "content") == "a <b>bold</b> and a < b comparison"

    def test_multiple_think_blocks(self) -> None:
        segs = self._run(["<think>1</think>mid<think>2</think>end"])
        assert self._join(segs, "content") == "midend"
        assert self._join(segs, "thinking") == "12"


@pytest.mark.asyncio
async def test_inline_think_streams_to_trace_not_bubble(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Providers that inline <think> in the content channel: think text must
    stream as thinking events; only the post-think text is user content."""
    registry = _Registry()
    client = _ScriptedChatClient(
        [
            [
                _llm_chunk(content="<think>let me "),
                _llm_chunk(content="reason</think>"),
                _llm_chunk(content="The answer."),
            ]
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(pipeline, UnifiedContext(session_id="s1", user_message="Hi"))

    assert _contents(events) == ["The answer."]
    thinking = "".join(e.content for e in events if e.type == StreamEventType.THINKING)
    assert "let me reason" in thinking
    result = _result(events)
    assert result.metadata["response"] == "The answer."
    assert result.metadata["completed"] is True


@pytest.mark.asyncio
async def test_multi_chunk_usage_counts_as_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini OpenAI-compat (and similar) may attach usage to several stream
    chunks. Each completion must still count as one call with the final
    token totals — not N× inflated ``total_calls`` / tokens."""
    usage_partial = SimpleNamespace(prompt_tokens=100, completion_tokens=2, total_tokens=102)
    usage_final = SimpleNamespace(prompt_tokens=100, completion_tokens=5, total_tokens=105)
    registry = _Registry()
    client = _ScriptedChatClient(
        [
            [
                _llm_chunk(content="Hello", usage=usage_partial),
                _llm_chunk(content=" world", usage=usage_partial),
                _llm_chunk(content=".", finish_reason="stop", usage=usage_partial),
                _usage_only_chunk(prompt=100, completion=5, total=105),
            ]
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(pipeline, UnifiedContext(session_id="s1", user_message="Hi"))

    assert "".join(_contents(events)) == "Hello world."
    assert client.call_count == 1
    summary = pipeline.usage.summary()
    assert summary is not None
    assert summary["total_calls"] == 1
    assert summary["prompt_tokens"] == 100
    assert summary["completion_tokens"] == 5
    assert summary["total_tokens"] == 105
    # Final usage frame wins over earlier partials.
    assert usage_final.total_tokens == summary["total_tokens"]
    result = _result(events)
    cost = (result.metadata.get("metadata") or {}).get("cost_summary") or result.metadata.get(
        "cost_summary"
    )
    if cost is not None:
        assert cost["total_calls"] == 1
        assert cost["total_tokens"] == 105


@pytest.mark.asyncio
async def test_empty_finish_gets_one_nudge_then_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tool-less round that is ALL internal reasoning must not finalize as
    an empty answer: the loop nudges once and the model recovers."""
    registry = _Registry()
    client = _ScriptedChatClient(
        [
            # Round 1: the model "finishes" with nothing but think text.
            [_llm_chunk(content="<think>I wrote a whole script here</think>")],
            # Round 2 (after the nudge): a real answer.
            [_llm_chunk(content="Here is the real answer.")],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(pipeline, UnifiedContext(session_id="s1", user_message="Make a PDF"))

    assert client.call_count == 2
    # The nudge round keeps the raw think text in-conversation and appends
    # the nudge instruction as the trailing user message.
    second_round = client.calls[1]["messages"]
    assert second_round[-1]["role"] == "user"
    assert "internal reasoning" in second_round[-1]["content"]
    assert any(
        m.get("role") == "assistant" and "whole script" in str(m.get("content"))
        for m in second_round
    )
    result = _result(events)
    assert result.metadata["response"] == "Here is the real answer."
    assert result.metadata["completed"] is True


@pytest.mark.asyncio
async def test_explore_context_pre_pass_seeds_loop_without_polluting_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the user attaches fresh context, the explore_context pre-pass runs
    before the answer loop and folds an objective briefing into the loop's
    user-message seed — while its own output never appears as the answer."""

    def _fake_explore_stream(*_args, **_kwargs):
        async def _gen():
            yield "The user and the external agent updated the navigation."

        return _gen()

    monkeypatch.setattr(explorer_mod, "llm_stream", _fake_explore_stream)
    monkeypatch.setattr(
        explorer_mod,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="gpt-test", api_key="k", base_url="u", api_version=None, binding="openai"
        ),
    )

    registry = _Registry()
    client = _ScriptedChatClient([[_llm_chunk(content="Here is what that chat did.")]])
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    context = UnifiedContext(
        session_id="s1",
        user_message="what did this chat do?",
        source_manifest="[Attached Sources]\n- id=hs-imported_claude_code_x type=history",
        metadata={
            "source_index": {"hs-imported_claude_code_x": "## Claude Code\nI updated the nav."},
            "history_references": ["imported_claude_code_x"],
        },
    )
    events = await _run(pipeline, context)

    # The briefing rode into the answer loop's trailing user message (the seed).
    first_call_messages = client.calls[0]["messages"]
    seed_user_msg = first_call_messages[-1]["content"]
    assert "external agent updated the navigation" in seed_user_msg

    # The pre-pass streamed THINKING (reasoning trace), never CONTENT — the
    # answer is only the chat loop's finish text.
    assert _contents(events) == ["Here is what that chat did."]
    explore_thinking = "".join(
        e.content
        for e in events
        if e.type == StreamEventType.THINKING
        and str((e.metadata or {}).get("call_kind")) == "context_exploration"
    )
    assert "external agent updated the navigation" in explore_thinking


@pytest.mark.asyncio
async def test_finish_first_round_no_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request that needs no exploration: the first round emits no tool
    calls, so it IS the finish — one LLM call, streamed straight to the user."""
    registry = _Registry()
    client = _ScriptedChatClient([[_llm_chunk(content="A direct answer.")]])
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(pipeline, UnifiedContext(session_id="s1", user_message="Hello"))

    assert client.call_count == 1
    # The finish round's text streams to the user, not the trace.
    assert _contents(events) == ["A direct answer."]
    assert _call_roles(events) == ["finish"]
    result = _result(events)
    assert result.metadata["engine"] == "agent_loop"
    assert result.metadata["completed"] is True
    assert result.metadata["response"] == "A direct answer."
    assert result.metadata["rounds"] == 1
    assert result.metadata["tool_steps"] == 0


@pytest.mark.asyncio
async def test_tool_round_then_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tool round (narration text + a tool call) is followed by a tool-less
    finish round whose text is the answer — two LLM calls, no respond pass."""
    registry = _Registry()
    client = _ScriptedChatClient(
        [
            # Round 1: preamble (narration) text + a tool call.
            [
                _llm_chunk(content="Searching."),
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "web_search",
                            "arguments": json.dumps({"query": "Fourier transform"}),
                        }
                    ]
                ),
            ],
            # Round 2: the model sees the tool result in-protocol and finishes
            # by replying without tool calls.
            [_llm_chunk(content="Found what was needed.")],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["web_search"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(
        pipeline,
        UnifiedContext(
            session_id="s1", user_message="Look up Fourier", enabled_tools=["web_search"]
        ),
    )

    assert client.call_count == 2
    assert registry.executed[0]["name"] == "web_search"
    assert registry.executed[0]["kwargs"]["query"] == "Fourier transform"
    # Both rounds' text streams to the user; the round roles distinguish them.
    assert _contents(events) == ["Searching.", "Found what was needed."]
    assert _call_roles(events) == ["narration", "finish"]
    # Round 2 sees the tool exchange in-protocol: the assistant tool_calls
    # message (with its preamble text) followed by the role=tool result.
    second_round = client.calls[1]["messages"]
    assistant_tc = [m for m in second_round if m.get("role") == "assistant" and m.get("tool_calls")]
    assert assistant_tc and assistant_tc[0]["tool_calls"][0]["function"]["name"] == "web_search"
    assert assistant_tc[0]["content"] == "Searching."
    tool_msgs = [m for m in second_round if m.get("role") == "tool"]
    assert tool_msgs and "tool answer" in tool_msgs[0]["content"]
    result = _result(events)
    assert result.metadata["tool_steps"] == 1
    assert result.metadata["rounds"] == 2
    # Only the finish round's text is the persisted answer.
    assert result.metadata["response"] == "Found what was needed."


@pytest.mark.asyncio
async def test_mastery_tool_round_keeps_teaching_markdown_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mastery teaching may share a native tool round with quiz setup.

    The prose must stay in the answer surface after the round resolves instead
    of being demoted into the compact reasoning trace (issue #855).
    """

    class _MasteryRegistry(_Registry):
        def build_openai_schemas(self, enabled):
            schemas = super().build_openai_schemas(enabled)
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": "mastery_quiz",
                        "description": "Register a mastery quiz",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            )
            return schemas

        async def execute(self, name: str, **kwargs):
            if name == "ask_user":
                self.executed.append({"name": name, "kwargs": kwargs})
                return ToolResult(
                    content="Asked the learner.",
                    success=True,
                    pause_for_user={"questions": kwargs["questions"]},
                )
            return await super().execute(name, **kwargs)

    explanation = (
        "### Binary addition\n\n"
        "| Carry | Sum |\n"
        "| --- | --- |\n"
        "| 1 | 0 |\n\n"
        "Use the carry column to work through the next question."
    )
    registry = _MasteryRegistry()
    client = _ScriptedChatClient(
        [
            [
                _llm_chunk(content=explanation),
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "quiz-1",
                            "name": "mastery_quiz",
                            "arguments": "{}",
                        }
                    ]
                ),
            ],
            [_llm_chunk(content="Choose the answer when you are ready.")],
            [
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "ask-1",
                            "name": "ask_user",
                            "arguments": json.dumps(
                                {"questions": [{"id": "q1", "prompt": "Which sum?"}]}
                            ),
                        }
                    ]
                )
            ],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(
        pipeline,
        "_compose_enabled_tools",
        lambda _context: ["mastery_quiz", "ask_user"],
    )
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(
        pipeline,
        UnifiedContext(
            session_id="s1",
            user_message="Teach me binary addition",
            enabled_tools=["mastery_quiz"],
            metadata={"mastery_mode": True, "mastery_path_id": ""},
        ),
    )

    markers = [
        event.metadata
        for event in events
        if event.type == StreamEventType.PROGRESS
        and event.metadata.get("call_state") == "complete"
        and "call_role" in event.metadata
    ]
    assert markers[0]["call_role"] == "narration"
    assert markers[0]["answer_visible"] is True
    joined_content = "".join(_contents(events))
    assert joined_content.startswith(explanation)
    assert "Choose the answer when you are ready." not in joined_content
    assert "Which sum?" in joined_content
    assert client.call_count == 3
    assert [row["name"] for row in registry.executed] == ["mastery_quiz", "ask_user"]
    redirect = client.calls[2]["messages"][-1]
    assert redirect["role"] == "user"
    assert "mastery_quiz" in redirect["content"]
    assert "ask_user" in redirect["content"]
    result = _result(events)
    assert result.metadata["completed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plain_quiz",
    [
        (
            "Which expression builds a dictionary?\n\n"
            "- A. `{w: words.count(w) for w in words}`\n"
            "- B. `[w: words.count(w) for w in words]`\n"
            "- C. `{w for w in words}`\n"
            "- D. `(w: words.count(w) for w in words)`"
        ),
        (
            "请选择正确的字典推导式：\n\n"
            "- A. `{w: words.count(w) for w in words}`\n"
            "- B. `[w: words.count(w) for w in words]`\n"
            "- C. `{w for w in words}`\n"
            "- D. `(w: words.count(w) for w in words)`"
        ),
    ],
)
async def test_mastery_plain_choice_finish_gets_one_protocol_redirect(
    plain_quiz: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prose A-D quiz cannot bypass the registered-card assessment flow."""

    class _MasteryCardRegistry(_Registry):
        async def execute(self, name: str, **kwargs):
            if name == "ask_user":
                self.executed.append({"name": name, "kwargs": kwargs})
                return ToolResult(
                    content="Asked the learner.",
                    success=True,
                    pause_for_user={"questions": kwargs["questions"]},
                )
            return await super().execute(name, **kwargs)

    registry = _MasteryCardRegistry()
    client = _ScriptedChatClient(
        [
            [_llm_chunk(content=plain_quiz)],
            [
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "ask-1",
                            "name": "ask_user",
                            "arguments": json.dumps(
                                {"questions": [{"id": "q1", "prompt": "Which expression?"}]}
                            ),
                        }
                    ]
                )
            ],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["ask_user"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(
        pipeline,
        UnifiedContext(
            session_id="s1",
            user_message="Continue",
            enabled_tools=["ask_user"],
            metadata={"mastery_mode": True, "mastery_path_id": ""},
        ),
    )

    assert client.call_count == 2
    assert [row["name"] for row in registry.executed] == ["ask_user"]
    redirect = client.calls[1]["messages"][-1]
    assert redirect["role"] == "user"
    assert "plain text" in redirect["content"]
    assert "mastery_quiz" in redirect["content"]
    assert "ask_user" in redirect["content"]
    assert _result(events).metadata["completed"] is False
    assert plain_quiz not in "".join(_contents(events))


@pytest.mark.asyncio
async def test_repeated_plain_choice_failure_is_never_published_as_a_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One retry is bounded, but its second invalid quiz still cannot finish."""
    plain_quiz = "Which value is correct?\n\nA. one\nB. two\nC. three\nD. four"
    client = _ScriptedChatClient(
        [[_llm_chunk(content=plain_quiz)], [_llm_chunk(content=plain_quiz)]]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _Registry()
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["ask_user"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(
        pipeline,
        UnifiedContext(
            session_id="s1",
            user_message="Continue",
            enabled_tools=["ask_user"],
            metadata={"mastery_mode": True, "mastery_path_id": ""},
        ),
    )

    assert client.call_count == 2
    assert plain_quiz not in "".join(_contents(events))
    rejected_calls = [
        event.metadata
        for event in events
        if event.type == StreamEventType.PROGRESS and event.metadata.get("finish_rejected") is True
    ]
    assert len(rejected_calls) == 2
    assert all(metadata["call_state"] == "complete" for metadata in rejected_calls)
    assert all(metadata["call_role"] == "narration" for metadata in rejected_calls)
    result = _result(events)
    assert result.metadata["completed"] is False
    assert result.metadata["response"] == ""


@pytest.mark.asyncio
async def test_mastery_labelled_teaching_examples_stay_direct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A labelled teaching list is not itself an assessment prompt."""
    registry = _Registry()
    teaching = (
        "Here are container spellings to remember:\n\n"
        "- A. lists use brackets.\n"
        "- B. dictionaries answer key lookups with braces and a colon.\n"
        "- C. sets use braces without a colon."
    )
    client = _ScriptedChatClient([[_llm_chunk(content=teaching)]])
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(
        pipeline,
        UnifiedContext(
            session_id="s1",
            user_message="Teach me Python containers",
            metadata={"mastery_mode": True, "mastery_path_id": ""},
        ),
    )

    assert client.call_count == 1
    assert "".join(_contents(events)) == teaching
    assert _result(events).metadata["completed"] is True


@pytest.mark.asyncio
async def test_dsml_round_keeps_clean_prose_visible_and_decodes_container_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DSML call may share a content stream with tutor feedback.

    Only the call markup is hidden; prose on both sides stays in ``content``.
    The completion marker narrowly opts that cleaned prose out of the normal
    narration demotion, and schema-declared arrays reach the tool as arrays.
    """

    class _PausingRegistry(_Registry):
        async def execute(self, name: str, **kwargs):
            self.executed.append({"name": name, "kwargs": kwargs})
            return ToolResult(
                content="Asked the user.",
                success=True,
                pause_for_user={"questions": kwargs["questions"]},
            )

    registry = _PausingRegistry()
    dsml = (
        "Feedback before. "
        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="ask_user">'
        '<｜｜DSML｜｜parameter name="questions" string="true">'
        '[{"id":"q1","prompt":"Continue?"}]'
        "</｜｜DSML｜｜parameter></｜｜DSML｜｜invoke>"
        "</｜｜DSML｜｜tool_calls> Feedback after."
    )
    # Split inside special tokens, tag names, and the JSON parameter value.
    dsml_chunks = [dsml[index : index + 5] for index in range(0, len(dsml), 5)]
    client = _ScriptedChatClient([[_llm_chunk(content=piece) for piece in dsml_chunks]])
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["ask_user"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(
        pipeline,
        UnifiedContext(session_id="s1", user_message="Teach me", enabled_tools=["ask_user"]),
    )

    assert registry.executed[0]["name"] == "ask_user"
    assert registry.executed[0]["kwargs"]["questions"] == [{"id": "q1", "prompt": "Continue?"}]
    round_content = "".join(
        event.content
        for event in events
        if event.type == StreamEventType.CONTENT
        and event.metadata.get("call_kind") == "agent_loop_round"
    )
    assert round_content == "Feedback before.  Feedback after."
    assert "DSML" not in round_content
    thinking = "".join(event.content for event in events if event.type == StreamEventType.THINKING)
    assert "DSML" not in thinking

    markers = [
        event.metadata
        for event in events
        if event.type == StreamEventType.PROGRESS
        and event.metadata.get("call_state") == "complete"
        and "call_role" in event.metadata
    ]
    assert markers[0]["call_role"] == "narration"
    assert markers[0]["answer_visible"] is True
    result = _result(events)
    assert client.call_count == 1
    assert result.metadata["completed"] is False
    assert result.metadata["response"] == ""


@pytest.mark.asyncio
async def test_dsml_container_schema_survives_native_tool_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FallbackClient:
        def __init__(self, scripted: list[list[SimpleNamespace]]) -> None:
            self.scripted = list(scripted)
            self.calls: list[dict[str, Any]] = []

            class _Completions:
                def __init__(self, parent: _FallbackClient) -> None:
                    self.parent = parent

                async def create(self, **kwargs):
                    self.parent.calls.append(kwargs)
                    if kwargs.get("tools"):
                        raise RuntimeError("tool_choice is invalid")
                    return _async_llm_stream(self.parent.scripted.pop(0))

            self.chat = SimpleNamespace(completions=_Completions(self))

    class _PausingRegistry(_Registry):
        async def execute(self, name: str, **kwargs):
            self.executed.append({"name": name, "kwargs": kwargs})
            if name == "ask_user":
                return ToolResult(
                    content="Asked the user.",
                    success=True,
                    pause_for_user={"questions": kwargs["questions"]},
                )
            return ToolResult(content="search result", success=True)

    first = (
        '<｜DSML｜invoke name="web_search">'
        '<｜DSML｜parameter name="query" string="true">topic'
        "</｜DSML｜parameter></｜DSML｜invoke>"
    )
    second = (
        '<｜DSML｜invoke name="ask_user">'
        '<｜DSML｜parameter name="questions" string="true">'
        '[{"id":"q1","prompt":"Continue?"}]'
        "</｜DSML｜parameter></｜DSML｜invoke>"
    )
    client = _FallbackClient([[_llm_chunk(content=first)], [_llm_chunk(content=second)]])
    registry = _PausingRegistry()
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(
        pipeline, "_compose_enabled_tools", lambda _context: ["web_search", "ask_user"]
    )
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    await _run(
        pipeline,
        UnifiedContext(
            session_id="s1",
            user_message="Teach me",
            enabled_tools=["web_search", "ask_user"],
        ),
    )

    assert [item["name"] for item in registry.executed] == ["web_search", "ask_user"]
    assert registry.executed[-1]["kwargs"]["questions"] == [{"id": "q1", "prompt": "Continue?"}]
    assert "tools" in client.calls[0]
    assert all("tools" not in call for call in client.calls[1:])


@pytest.mark.asyncio
async def test_midloop_transport_failure_retries_current_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transport failure before the next round emits output retries that
    round without discarding the useful tool work already in context."""

    class _FailingThenFinishClient:
        def __init__(self) -> None:
            self.call_count = 0
            self.calls: list[dict[str, Any]] = []
            parent = self

            class _Completions:
                async def create(self, **kwargs):
                    parent.call_count += 1
                    parent.calls.append({**kwargs, "messages": list(kwargs.get("messages") or [])})
                    if parent.call_count == 1:
                        return _async_llm_stream(
                            [
                                _llm_chunk(content="Searching."),
                                _llm_chunk(
                                    tool_calls=[
                                        {
                                            "id": "call-1",
                                            "name": "web_search",
                                            "arguments": json.dumps({"query": "q"}),
                                        }
                                    ]
                                ),
                            ]
                        )
                    if parent.call_count == 2:
                        raise TimeoutError("Request timed out.")
                    return _async_llm_stream([_llm_chunk(content="Best-effort answer.")])

            class _Chat:
                def __init__(self) -> None:
                    self.completions = _Completions()

            self.chat = _Chat()

    registry = _Registry()
    client = _FailingThenFinishClient()
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["web_search"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(
        pipeline,
        UnifiedContext(session_id="s1", user_message="Look up", enabled_tools=["web_search"]),
    )

    # 1 tool round + 1 failed attempt + 1 retry = 3 create() calls.
    assert client.call_count == 3
    # The turn produced an answer instead of failing.
    result = _result(events)
    assert result.metadata["response"] == "Best-effort answer."
    # The retry is explicit in the trace, and no forced-finish path was needed.
    progress = [
        e.content
        for e in events
        if e.type == StreamEventType.PROGRESS
        and e.metadata.get("error_code") == "provider_transport"
    ]
    assert progress == ["The model provider connection was interrupted; retrying."]


@pytest.mark.asyncio
async def test_first_round_transport_failure_retries_then_becomes_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unavailable provider gets bounded retries and a safe UI error."""

    class _AlwaysFailClient:
        def __init__(self) -> None:
            self.call_count = 0
            parent = self

            class _Completions:
                async def create(self, **kwargs):
                    parent.call_count += 1
                    raise TimeoutError("Request timed out.")

            class _Chat:
                def __init__(self) -> None:
                    self.completions = _Completions()

            self.chat = _Chat()

    client = _AlwaysFailClient()
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _Registry()
    monkeypatch.setattr(agent_loop_mod, "_PROVIDER_RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["web_search"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    bus = StreamBus()
    _events, consumer = await _collect_bus_events(bus)
    with pytest.raises(LLMProviderTransportError) as raised:
        await pipeline.run(
            UnifiedContext(session_id="s1", user_message="x", enabled_tools=["web_search"]),
            bus,
        )
    await bus.close()
    await consumer

    assert client.call_count == 3
    assert raised.value.error_code == "provider_transport"
    assert raised.value.retryable is True
    assert raised.value.partial_response is False
    assert str(raised.value) == "Unable to reach the model provider. Please retry."


@pytest.mark.asyncio
async def test_transport_failure_before_output_recovers_without_duplicate_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RecoveringClient:
        def __init__(self) -> None:
            self.call_count = 0
            parent = self

            class _Completions:
                async def create(self, **kwargs):
                    parent.call_count += 1
                    if parent.call_count == 1:
                        raise httpx.ConnectTimeout("provider handshake timed out")
                    return _async_llm_stream([_llm_chunk(content="Recovered.")])

            self.chat = SimpleNamespace(completions=_Completions())

    client = _RecoveringClient()
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _Registry()
    monkeypatch.setattr(agent_loop_mod, "_PROVIDER_RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(pipeline, UnifiedContext(session_id="s1", user_message="Hi"))

    assert client.call_count == 2
    assert _contents(events) == ["Recovered."]
    retry_events = [
        event
        for event in events
        if event.type == StreamEventType.PROGRESS
        and event.metadata.get("error_code") == "provider_transport"
    ]
    assert len(retry_events) == 1
    assert retry_events[0].metadata["retry_attempt"] == 1


@pytest.mark.asyncio
async def test_midstream_transport_failure_is_not_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _interrupted_stream():
        yield _llm_chunk(content="Partial answer.")
        raise httpx.ReadError("peer closed the SSE stream")

    class _InterruptedClient:
        def __init__(self) -> None:
            self.call_count = 0
            parent = self

            class _Completions:
                async def create(self, **kwargs):
                    parent.call_count += 1
                    return _interrupted_stream()

            self.chat = SimpleNamespace(completions=_Completions())

    client = _InterruptedClient()
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _Registry()
    monkeypatch.setattr(agent_loop_mod, "_PROVIDER_RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)
    with pytest.raises(LLMProviderTransportError) as raised:
        await pipeline.run(UnifiedContext(session_id="s1", user_message="Hi"), bus)
    await bus.close()
    await consumer

    assert client.call_count == 1
    assert _contents(events) == ["Partial answer."]
    assert raised.value.partial_response is True
    failed_call = next(
        event
        for event in events
        if event.type == StreamEventType.PROGRESS and event.metadata.get("call_state") == "failed"
    )
    assert failed_call.metadata["error_code"] == "provider_transport"
    assert failed_call.metadata["partial_response"] is True


@pytest.mark.asyncio
async def test_later_round_midstream_transport_failure_is_not_forced_finished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Visible output after a tool round must not be mixed with a replay."""

    async def _interrupted_stream():
        yield _llm_chunk(content="Partial final answer.")
        raise httpx.ReadError("peer closed the SSE stream")

    class _ToolThenInterruptedClient:
        def __init__(self) -> None:
            self.call_count = 0
            parent = self

            class _Completions:
                async def create(self, **kwargs):
                    parent.call_count += 1
                    if parent.call_count == 1:
                        return _async_llm_stream(
                            [
                                _llm_chunk(
                                    tool_calls=[
                                        {
                                            "id": "call-1",
                                            "name": "web_search",
                                            "arguments": json.dumps({"query": "q"}),
                                        }
                                    ]
                                )
                            ]
                        )
                    return _interrupted_stream()

            self.chat = SimpleNamespace(completions=_Completions())

    client = _ToolThenInterruptedClient()
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _Registry()
    monkeypatch.setattr(agent_loop_mod, "_PROVIDER_RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["web_search"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    bus = StreamBus()
    events, consumer = await _collect_bus_events(bus)
    with pytest.raises(LLMProviderTransportError) as raised:
        await pipeline.run(
            UnifiedContext(session_id="s1", user_message="Look up", enabled_tools=["web_search"]),
            bus,
        )
    await bus.close()
    await consumer

    assert client.call_count == 2
    assert _contents(events).count("Partial final answer.") == 1
    assert raised.value.partial_response is True


@pytest.mark.asyncio
async def test_forced_finish_transport_failure_remains_structured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed salvage request must stay retryable instead of completing."""

    class _ToolThenFailingClient:
        def __init__(self) -> None:
            self.call_count = 0
            parent = self

            class _Completions:
                async def create(self, **kwargs):
                    parent.call_count += 1
                    if parent.call_count == 1:
                        return _async_llm_stream(
                            [
                                _llm_chunk(
                                    tool_calls=[
                                        {
                                            "id": "call-1",
                                            "name": "web_search",
                                            "arguments": json.dumps({"query": "q"}),
                                        }
                                    ]
                                )
                            ]
                        )
                    if parent.call_count == 2:
                        raise RuntimeError("mid-loop application failure")
                    raise TimeoutError("provider unavailable during forced finish")

            self.chat = SimpleNamespace(completions=_Completions())

    client = _ToolThenFailingClient()
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _Registry()
    monkeypatch.setattr(agent_loop_mod, "_PROVIDER_RETRY_DELAYS", (0, 0))
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["web_search"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    bus = StreamBus()
    _events, consumer = await _collect_bus_events(bus)
    with pytest.raises(LLMProviderTransportError) as raised:
        await pipeline.run(
            UnifiedContext(session_id="s1", user_message="Look up", enabled_tools=["web_search"]),
            bus,
        )
    await bus.close()
    await consumer

    # Tool round + failed ordinary round + three bounded finish attempts.
    assert client.call_count == 5
    assert raised.value.error_code == "provider_transport"
    assert raised.value.retryable is True
    assert raised.value.partial_response is False


@pytest.mark.asyncio
async def test_context_checkpoint_folds_completed_tool_rounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CheckpointRegistry(_Registry):
        async def execute(self, name: str, **kwargs):
            self.executed.append({"name": name, "kwargs": kwargs})
            query = str(kwargs.get("query") or "")
            return ToolResult(
                content=f"noisy tool result for {query}",
                success=True,
                metadata={"_context_checkpoint": {"summary": f"checkpoint: {query}"}},
            )

    registry = _CheckpointRegistry()
    client = _ScriptedChatClient(
        [
            [
                _llm_chunk(content="Searching step one."),
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "web_search",
                            "arguments": json.dumps({"query": "step one"}),
                        }
                    ]
                ),
            ],
            [
                _llm_chunk(content="Searching step two."),
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "call-2",
                            "name": "web_search",
                            "arguments": json.dumps({"query": "step two"}),
                        }
                    ]
                ),
            ],
            [_llm_chunk(content="Final from checkpoints.")],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["web_search"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(
        pipeline,
        UnifiedContext(
            session_id="s1",
            user_message="Research this",
            enabled_tools=["web_search"],
        ),
    )

    assert client.call_count == 3
    second_round = client.calls[1]["messages"]
    assert any(
        m.get("role") == "system" and "checkpoint: step one" in str(m.get("content"))
        for m in second_round
    )
    assert not any(m.get("role") == "tool" for m in second_round)
    assert not any("Searching step one." in str(m.get("content")) for m in second_round)
    third_round = client.calls[2]["messages"]
    checkpoint_text = "\n".join(
        str(m.get("content") or "") for m in third_round if m.get("role") == "system"
    )
    assert "checkpoint: step one" in checkpoint_text
    assert "checkpoint: step two" in checkpoint_text
    assert not any(m.get("role") == "tool" for m in third_round)
    assert not any("noisy tool result" in str(m.get("content")) for m in third_round)
    result = _result(events)
    assert result.metadata["response"] == "Final from checkpoints."


@pytest.mark.asyncio
async def test_ask_user_available_every_round(monkeypatch: pytest.MonkeyPatch) -> None:
    """The single loop offers the full tool belt — including ask_user — on
    every round; there is no respond stage that narrows tools to ask_user."""
    registry = _Registry()
    client = _ScriptedChatClient([[_llm_chunk(content="Final answer.")]])
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(
        pipeline, "_compose_enabled_tools", lambda _context: ["web_search", "ask_user"]
    )
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    await _run(
        pipeline,
        UnifiedContext(
            session_id="s1",
            user_message="Quick question",
            enabled_tools=["web_search", "ask_user"],
        ),
    )

    loop_tools = {t["function"]["name"] for t in client.calls[0]["tools"]}
    assert loop_tools == {"web_search", "ask_user"}


@pytest.mark.asyncio
async def test_initial_tool_choice_only_forces_first_round_and_hides_preamble(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _PausingRegistry(_Registry):
        async def execute(self, name: str, **kwargs):
            self.executed.append({"name": name, "kwargs": kwargs})
            return ToolResult(
                content="Asked the user.",
                success=True,
                pause_for_user={"questions": [{"id": "q1", "prompt": "What matters most?"}]},
            )

    registry = _PausingRegistry()
    client = _ScriptedChatClient(
        [
            [
                _llm_chunk(content="Let me ask one thing first."),
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "ask_user",
                            "arguments": json.dumps(
                                {"questions": [{"id": "q1", "prompt": "What matters most?"}]}
                            ),
                        }
                    ]
                ),
            ],
            [_llm_chunk(content="Completed with the added context.")],
        ]
    )
    pipeline = AgenticChatPipeline(language="en", initial_tool_choice="ask_user")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["ask_user"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    async def _waiter():
        return {"text": "Accuracy"}

    events = await _run(
        pipeline,
        UnifiedContext(
            session_id="s1",
            user_message="Help with this task",
            metadata={"wait_for_user_reply": _waiter},
        ),
    )

    assert client.calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "ask_user"},
    }
    assert client.calls[1]["tool_choice"] == "auto"
    assert _contents(events) == ["Completed with the added context."]


@pytest.mark.asyncio
async def test_ask_questions_uses_a_card_when_provider_rejects_tool_schemas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _PausingRegistry(_Registry):
        async def execute(self, name: str, **kwargs):
            self.executed.append({"name": name, "kwargs": kwargs})
            return ToolResult(
                content="Asked the user.",
                success=True,
                pause_for_user={"questions": kwargs["questions"]},
            )

    class _SchemaRejectingClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

            class _Completions:
                def __init__(self, parent: _SchemaRejectingClient) -> None:
                    self.parent = parent

                async def create(self, **kwargs):
                    self.parent.calls.append(kwargs)
                    if len(self.parent.calls) == 1:
                        raise ValueError("unsupported parameter: tools")
                    content = (
                        "Which outcome matters most?"
                        if len(self.parent.calls) == 2
                        else "Completed after clarification."
                    )
                    return _async_llm_stream([_llm_chunk(content=content)])

            self.chat = SimpleNamespace(completions=_Completions(self))

    registry = _PausingRegistry()
    client = _SchemaRejectingClient()
    pipeline = AgenticChatPipeline(language="en", initial_tool_choice="ask_user")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["ask_user"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    async def _waiter():
        return {"text": "Accuracy"}

    events = await _run(
        pipeline,
        UnifiedContext(
            session_id="s1",
            user_message="Help with this task",
            metadata={"wait_for_user_reply": _waiter},
        ),
    )

    assert "tools" in client.calls[0]
    assert "tools" not in client.calls[1]
    assert [item["name"] for item in registry.executed] == ["ask_user"]
    assert registry.executed[0]["kwargs"]["questions"] == [
        {
            "id": "clarification",
            "prompt": "Which outcome matters most?",
            "allow_free_text": True,
        }
    ]
    assert _contents(events) == ["Completed after clarification."]
    assert any(event.metadata.get("tool_schema_fallback") for event in events)


@pytest.mark.asyncio
async def test_ask_user_pause_resumes_and_streams_interleaved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _PausingRegistry(_Registry):
        async def execute(self, name: str, **kwargs):
            self.executed.append({"name": name, "kwargs": kwargs})
            if name == "ask_user":
                return ToolResult(
                    content="Asked the user.",
                    success=True,
                    pause_for_user={"questions": [{"id": "q1", "prompt": "Which topic?"}]},
                )
            return await super().execute(name, **kwargs)

    registry = _PausingRegistry()
    client = _ScriptedChatClient(
        [
            # Round 1: a clarification (narration text + ask_user tool call).
            [
                _llm_chunk(content="Let me check one thing."),
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "ask_user",
                            "arguments": json.dumps(
                                {"questions": [{"id": "q1", "prompt": "Which topic?"}]}
                            ),
                        }
                    ]
                ),
            ],
            # Round 2 finishes after the user's reply resumes the loop.
            [_llm_chunk(content="The answer.")],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["ask_user"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    async def _waiter():
        return {"text": "Topic A"}

    events = await _run(
        pipeline,
        UnifiedContext(
            session_id="s1",
            user_message="Quick question",
            enabled_tools=["ask_user"],
            metadata={"wait_for_user_reply": _waiter},
        ),
    )

    assert client.call_count == 2
    assert _contents(events) == ["Let me check one thing.", "The answer."]
    assert _call_roles(events) == ["narration", "finish"]
    # The reply was substituted into the role=tool message in-protocol.
    final_round = client.calls[-1]["messages"]
    tool_msgs = [m for m in final_round if m.get("role") == "tool"]
    assert tool_msgs and "Topic A" in tool_msgs[-1]["content"]
    result = _result(events)
    # The persisted answer is the finish round's text.
    assert result.metadata["response"] == "The answer."
    assert result.metadata["completed"] is True


@pytest.mark.asyncio
async def test_ask_user_resume_end_loop_skips_further_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neutral ``metadata['end_loop']`` after resume stops without another LLM round."""

    class _EndLoopOnResume:
        name = "end_loop_probe"
        owned_tools: tuple[str, ...] = ()

        def is_active(self, context: UnifiedContext) -> bool:
            return True

        def system_block(self, context, *, language, prompts):  # noqa: ANN001
            return None

        def augment_kwargs(self, tool_name, kwargs, context):  # noqa: ANN001
            return kwargs

        def pre_loop_seed(self, context: UnifiedContext) -> str:
            return ""

        async def on_user_resume(self, context, ask_user, *, reply_text, answers):  # noqa: ANN001
            _ = ask_user, reply_text, answers
            context.metadata["end_loop"] = True

    class _PausingRegistry(_Registry):
        async def execute(self, name: str, **kwargs):
            self.executed.append({"name": name, "kwargs": kwargs})
            if name == "ask_user":
                return ToolResult(
                    content="Asked the user.",
                    success=True,
                    pause_for_user={"questions": [{"id": "q1", "prompt": "Which topic?"}]},
                )
            return await super().execute(name, **kwargs)

    registry = _PausingRegistry()
    client = _ScriptedChatClient(
        [
            [
                _llm_chunk(content="One question."),
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "ask_user",
                            "arguments": json.dumps(
                                {"questions": [{"id": "q1", "prompt": "Which topic?"}]}
                            ),
                        }
                    ]
                ),
            ],
            # Must not be reached when end_loop is set on resume.
            [_llm_chunk(content="Should not stream.")],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["ask_user"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)
    monkeypatch.setattr(
        pipeline,
        "_active_loop_capabilities",
        lambda _context: (_EndLoopOnResume(),),
    )

    async def _waiter():
        return {"text": "abort please"}

    events = await _run(
        pipeline,
        UnifiedContext(
            session_id="s-end-loop",
            user_message="Quick question",
            enabled_tools=["ask_user"],
            metadata={"wait_for_user_reply": _waiter},
        ),
    )

    assert client.call_count == 1
    assert "Should not stream." not in _contents(events)
    result = _result(events)
    assert result.metadata["completed"] is False
    # The user did answer, so the reply must still reach the transcript — only
    # the further LLM rounds are skipped.
    replies = [
        event
        for event in events
        if (event.metadata or {}).get("trace_kind") == "user_reply"
        and (event.metadata or {}).get("reply_preview") == "abort please"
    ]
    assert len(replies) == 1


@pytest.mark.asyncio
async def test_unresolved_ask_user_halts_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    class _PausingRegistry(_Registry):
        async def execute(self, name: str, **kwargs):
            self.executed.append({"name": name, "kwargs": kwargs})
            return ToolResult(
                content="Asked the user.",
                success=True,
                pause_for_user={"questions": [{"id": "q1", "prompt": "Which topic?"}]},
            )

    registry = _PausingRegistry()
    client = _ScriptedChatClient(
        [
            [
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "ask_user",
                            "arguments": json.dumps({"questions": []}),
                        }
                    ]
                ),
            ],
            # No further scripted responses: with no wait_for_user_reply waiter
            # the loop must halt here instead of producing another answer.
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["ask_user"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(
        pipeline,
        UnifiedContext(session_id="s1", user_message="Help me study", enabled_tools=["ask_user"]),
    )

    assert client.call_count == 1
    assert _contents(events) == ["Which topic?"]
    result = _result(events)
    assert result.metadata["completed"] is False


@pytest.mark.asyncio
async def test_round_budget_enters_tool_enabled_settlement_then_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _Registry()
    client = _ScriptedChatClient(
        [
            [
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "web_search",
                            "arguments": json.dumps({"query": "step one"}),
                        }
                    ]
                ),
            ],
            [_llm_chunk(content="Best effort answer.")],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    pipeline._max_rounds = 1
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["web_search"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(
        pipeline,
        UnifiedContext(session_id="s1", user_message="Research this", enabled_tools=["web_search"]),
    )

    assert client.call_count == 2
    # The exploration budget is separate from bounded protocol settlement:
    # one follow-up round retains tools so already-started work can settle.
    assert "tools" in client.calls[-1]
    settlement_instruction = client.calls[-1]["messages"][-1]["content"]
    assert "exploration round budget" in settlement_instruction.lower()
    result = _result(events)
    assert result.metadata["response"] == "Best effort answer."
    assert result.metadata["completed"] is True
    assert result.metadata["settlement_rounds"] == 1


@pytest.mark.asyncio
async def test_budget_settlement_completes_quiz_ask_grade_and_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quiz registered on the final exploration round still gets shown,
    answered, graded, and followed by deterministic learner feedback."""

    class _MasteryRegistry(_Registry):
        def build_openai_schemas(self, _enabled):
            schemas = super().build_openai_schemas(_enabled)
            schemas.extend(
                [
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": name,
                            "parameters": {
                                "type": "object",
                                "properties": {},
                                "additionalProperties": True,
                            },
                        },
                    }
                    for name in ("mastery_quiz", "mastery_grade")
                ]
            )
            return schemas

        async def execute(self, name: str, **kwargs):
            self.executed.append({"name": name, "kwargs": kwargs})
            if name == "ask_user":
                return ToolResult(
                    content="Asked the learner.",
                    success=True,
                    pause_for_user={"questions": kwargs["questions"]},
                )
            if name == "mastery_quiz":
                return ToolResult(content="Quiz q1 registered.", success=True)
            if name == "mastery_grade":
                return ToolResult(content="Correct; objective mastered.", success=True)
            raise AssertionError(f"unexpected tool: {name}")

    registry = _MasteryRegistry()
    client = _ScriptedChatClient(
        [
            [
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "quiz-1",
                            "name": "mastery_quiz",
                            "arguments": "{}",
                        }
                    ]
                )
            ],
            [
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "ask-1",
                            "name": "ask_user",
                            "arguments": json.dumps(
                                {"questions": [{"id": "q1", "prompt": "Which answer?"}]}
                            ),
                        }
                    ]
                )
            ],
            [
                _llm_chunk(
                    tool_calls=[
                        {
                            "id": "grade-1",
                            "name": "mastery_grade",
                            "arguments": json.dumps({"question_id": "q1", "answer": "B"}),
                        }
                    ]
                )
            ],
            [_llm_chunk(content="Correct — here is why B is the right answer.")],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    pipeline._max_rounds = 1
    monkeypatch.setattr(
        pipeline,
        "_compose_enabled_tools",
        lambda _context: ["mastery_quiz", "ask_user", "mastery_grade"],
    )
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    async def _waiter():
        return {"text": "B"}

    events = await _run(
        pipeline,
        UnifiedContext(
            session_id="s1",
            user_message="Quiz me",
            enabled_tools=["mastery_quiz", "ask_user", "mastery_grade"],
            metadata={"wait_for_user_reply": _waiter},
        ),
    )

    assert [entry["name"] for entry in registry.executed] == [
        "mastery_quiz",
        "ask_user",
        "mastery_grade",
    ]
    assert client.call_count == 4
    # All three settlement rounds retain the tool contract; the final one
    # chooses to finish without calling another tool.
    assert all("tools" in call for call in client.calls)
    grade_round = client.calls[2]["messages"]
    assert any(
        message.get("role") == "tool" and "User answered" in str(message.get("content"))
        for message in grade_round
    )
    result = _result(events)
    assert result.metadata["response"] == "Correct — here is why B is the right answer."
    assert result.metadata["completed"] is True
    assert result.metadata["rounds"] == 4
    assert result.metadata["settlement_rounds"] == 3


@pytest.mark.asyncio
async def test_settlement_hard_limit_forces_one_tool_less_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model that ignores settlement instructions cannot loop forever."""
    registry = _Registry()
    repeated_tool_rounds = [
        [
            _llm_chunk(
                tool_calls=[
                    {
                        "id": f"call-{index}",
                        "name": "web_search",
                        "arguments": json.dumps({"query": f"step {index}"}),
                    }
                ]
            )
        ]
        for index in range(4)
    ]
    client = _ScriptedChatClient([*repeated_tool_rounds, [_llm_chunk(content="Hard-stop answer.")]])
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    pipeline._max_rounds = 1
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["web_search"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(
        pipeline,
        UnifiedContext(session_id="s1", user_message="Research", enabled_tools=["web_search"]),
    )

    # N exploration calls + 3 tool-enabled settlement calls + 1 hard finish.
    assert client.call_count == 5
    assert all("tools" in call for call in client.calls[:4])
    assert "tools" not in client.calls[4]
    assert len(registry.executed) == 4
    result = _result(events)
    assert result.metadata["response"] == "Hard-stop answer."
    assert result.metadata["completed"] is True
    assert result.metadata["rounds"] == 5
    assert result.metadata["settlement_rounds"] == 3


@pytest.mark.asyncio
async def test_length_finish_reason_continues_within_bounded_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token-truncated, tool-less round is incomplete, not a finish."""
    registry = _Registry()
    client = _ScriptedChatClient(
        [
            [_llm_chunk(content="Part one is incomplete. ", finish_reason="length")],
            [_llm_chunk(content="Part two completes the answer.", finish_reason="stop")],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    pipeline._max_rounds = 1
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: ["web_search"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(
        pipeline,
        UnifiedContext(session_id="s1", user_message="Explain fully", enabled_tools=["web_search"]),
    )

    assert client.call_count == 2
    continuation_messages = client.calls[1]["messages"]
    assert continuation_messages[-2] == {
        "role": "assistant",
        "content": "Part one is incomplete. ",
    }
    assert "token limit" in continuation_messages[-1]["content"].lower()
    markers = [
        event.metadata
        for event in events
        if event.type == StreamEventType.PROGRESS
        and event.metadata.get("call_state") == "complete"
        and "call_role" in event.metadata
    ]
    assert markers[0]["call_role"] == "narration"
    assert markers[0]["answer_visible"] is True
    assert markers[1]["call_role"] == "finish"
    result = _result(events)
    expected = "Part one is incomplete. Part two completes the answer."
    assert result.metadata["response"] == expected
    # RESULT/SDK and event-replay consumers use the exact same visible bytes.
    assert "".join(_contents(events)) == expected
    assert result.metadata["completed"] is True
    assert result.metadata["settlement_rounds"] == 1


@pytest.mark.asyncio
async def test_repeated_empty_finish_stops_after_one_nudge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty provider response gets one recovery chance, never a loop."""
    registry = _Registry()
    client = _ScriptedChatClient(
        [
            [_llm_chunk(content="<think>first empty</think>")],
            [_llm_chunk(content="<think>still empty</think>")],
        ]
    )
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    pipeline._max_rounds = 1
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _context: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)

    events = await _run(pipeline, UnifiedContext(session_id="s1", user_message="Answer"))

    assert client.call_count == 2
    result = _result(events)
    assert result.metadata["response"] == (
        "I could not produce a useful response from the model output. "
        "Please try again or narrow the request."
    )
    assert result.metadata["completed"] is True
    assert result.metadata["settlement_rounds"] == 1


def test_compose_enabled_tools_injects_rag_when_kb_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_raw=lambda *_args, **_kwargs: ""),
    )
    monkeypatch.setattr(
        "deeptutor.services.notebook.get_notebook_manager",
        lambda: SimpleNamespace(list_notebooks=lambda: []),
    )
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline._deferred_loader = None
    pipeline._exec_enabled = False
    pipeline.registry = SimpleNamespace(
        get_enabled=lambda selected: [SimpleNamespace(name=n) for n in selected]
    )
    context = UnifiedContext(
        user_message="hi",
        enabled_tools=["web_search"],
        knowledge_bases=["kb-a"],
    )
    assert "rag" in pipeline._compose_enabled_tools(context)
    assert "web_search" in pipeline._compose_enabled_tools(context)


def test_compose_enabled_tools_mounts_mastery_plugin_only_in_mastery_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_raw=lambda *_args, **_kwargs: ""),
    )
    monkeypatch.setattr(
        "deeptutor.services.notebook.get_notebook_manager",
        lambda: SimpleNamespace(list_notebooks=lambda: []),
    )
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline._deferred_loader = None
    pipeline._exec_enabled = False
    pipeline.registry = SimpleNamespace(
        get_enabled=lambda selected: [SimpleNamespace(name=n) for n in selected]
    )

    ordinary = UnifiedContext(user_message="hi")
    mastery = UnifiedContext(
        user_message="teach me",
        metadata={"mastery_mode": True, "mastery_path_id": "path-a"},
    )

    ordinary_tools = pipeline._compose_enabled_tools(ordinary)
    mastery_tools = pipeline._compose_enabled_tools(mastery)
    assert not set(MASTERY_TOOL_NAMES).intersection(ordinary_tools)
    assert set(MASTERY_TOOL_NAMES).issubset(mastery_tools)
    # Additive plugin surface: a mastery turn reuses chat's full built-in
    # surface (always-on defaults included) and just adds its owned tools.
    assert {"web_fetch", "github", "cron"}.issubset(mastery_tools)
    assert {"web_fetch", "github", "cron"}.issubset(ordinary_tools)


def test_augment_tool_kwargs_injects_mastery_path_id() -> None:
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    context = UnifiedContext(
        user_message="teach",
        metadata={"mastery_mode": True, "mastery_path_id": "book-1"},
    )

    augmented = pipeline._augment_tool_kwargs("mastery_status", {}, context)

    assert augmented["_mastery_path_id"] == "book-1"


def test_augment_tool_kwargs_injects_geogebra_image() -> None:
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

    augmented = pipeline._augment_tool_kwargs(
        "geogebra_analysis",
        {"image_base64": "HALLUCINATED"},
        context,
    )

    assert augmented["image_base64"] == "data:image/png;base64,REAL_IMG_BYTES"
    assert augmented["language"] == "zh"


def test_build_llm_tool_schemas_kb_name_enum_matches_attached() -> None:
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline.registry = _Registry()

    schemas = pipeline._build_llm_tool_schemas(
        ["web_search"],
        UnifiedContext(knowledge_bases=["kb-a", "kb-b"]),
    )

    assert schemas[0]["function"]["parameters"]["additionalProperties"] is False
