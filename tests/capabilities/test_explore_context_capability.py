"""Unit tests for the explore-context loop capability and its explorer."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.capabilities.explore_context import ExploreContextCapability
from deeptutor.capabilities.explore_context import explorer as explorer_mod
from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import Attachment, UnifiedContext
from deeptutor.core.stream import StreamEventType
from deeptutor.core.stream_bus import StreamBus


def _ctx(**metadata: Any) -> UnifiedContext:
    attachments = metadata.pop("_attachments", [])
    manifest = metadata.pop("_manifest", "")
    return UnifiedContext(
        session_id="s1",
        user_message="what did this chat do?",
        attachments=attachments,
        source_manifest=manifest,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# is_active
# ---------------------------------------------------------------------------


def test_is_active_requires_readable_sources() -> None:
    cap = ExploreContextCapability()
    # A readable source attached this turn → active.
    assert cap.is_active(_ctx(source_index={"hs-x": "t"}, history_references=["hs-x"])) is True
    # A source carried over from an earlier turn (no fresh ref this turn) is
    # ALSO active now — the investigation runs query-driven on every turn that
    # has sources to read.
    assert cap.is_active(_ctx(source_index={"hs-x": "t"})) is True
    # A fresh reference but no readable source index (e.g. non-chat turn) → skip.
    assert cap.is_active(_ctx(history_references=["hs-x"])) is False
    # Empty turn → skip.
    assert cap.is_active(_ctx()) is False


def test_is_active_image_only_turn_has_no_readable_source() -> None:
    cap = ExploreContextCapability()
    # Image attachments never enter the source index, so an image-only turn
    # carries no readable source and the pre-pass stays dormant.
    img = Attachment(type="image", id="i1")
    assert cap.is_active(_ctx(_attachments=[img])) is False


def test_capability_owns_no_tools_and_no_system_block() -> None:
    cap = ExploreContextCapability()
    assert cap.owned_tools == ()
    assert cap.pre_loop_seed(_ctx()) == ""
    assert cap.system_block(_ctx(), language="en", prompts={}) is None


# ---------------------------------------------------------------------------
# Single-pass fallback (non-native tool-calling models)
# ---------------------------------------------------------------------------


def _fake_stream(briefing_chunks: list[str]):
    async def _stream(*_args: Any, **_kwargs: Any):
        for chunk in briefing_chunks:
            yield chunk

    return _stream


@pytest.fixture
def _force_single_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the explorer onto its single-pass (llm_stream) fallback path."""
    monkeypatch.setattr(explorer_mod, "can_use_native_tool_calling", lambda **_kwargs: False)


@pytest.mark.asyncio
async def test_single_pass_returns_investigation_block(
    monkeypatch: pytest.MonkeyPatch, _force_single_pass: None
) -> None:
    monkeypatch.setattr(
        explorer_mod,
        "llm_stream",
        _fake_stream(["In this transcript, the user and ", "the other agent updated the nav."]),
    )
    cap = ExploreContextCapability()
    ctx = _ctx(
        source_index={"hs-imported_claude_code_x": "## Claude Code\nI updated the nav."},
        history_references=["imported_claude_code_x"],
        _manifest="[Attached Sources]\n- id=hs-imported_claude_code_x type=history name='nav'",
    )

    block = await cap.pre_loop(ctx, StreamBus(), usage=None)

    assert isinstance(block, PromptBlock)
    assert block.name == "explore_context"
    # Header framing + the model's third-person account are both present.
    assert "Context Investigation" in block.content
    assert "the other agent updated the nav." in block.content


@pytest.mark.asyncio
async def test_pre_loop_emits_no_content_events(
    monkeypatch: pytest.MonkeyPatch, _force_single_pass: None
) -> None:
    """The pre-pass must never stream CONTENT — only that channel is captured
    as the turn's user-facing answer."""
    monkeypatch.setattr(explorer_mod, "llm_stream", _fake_stream(["briefing"]))
    cap = ExploreContextCapability()
    ctx = _ctx(source_index={"hs-x": "transcript"}, history_references=["x"])
    bus = StreamBus()

    await cap.pre_loop(ctx, bus, usage=None)

    kinds = [e.type for e in bus._history]
    assert StreamEventType.CONTENT not in kinds
    assert StreamEventType.STAGE_START in kinds
    assert StreamEventType.THINKING in kinds


@pytest.mark.asyncio
async def test_pre_loop_inactive_returns_none() -> None:
    cap = ExploreContextCapability()
    # No readable sources → inactive → no pre-pass, no LLM call.
    assert await cap.pre_loop(_ctx(history_references=["x"]), StreamBus(), usage=None) is None


@pytest.mark.asyncio
async def test_pre_loop_empty_investigation_returns_none(
    monkeypatch: pytest.MonkeyPatch, _force_single_pass: None
) -> None:
    monkeypatch.setattr(explorer_mod, "llm_stream", _fake_stream(["   "]))
    cap = ExploreContextCapability()
    ctx = _ctx(source_index={"hs-x": "t"}, history_references=["x"])
    assert await cap.pre_loop(ctx, StreamBus(), usage=None) is None


@pytest.mark.asyncio
async def test_pre_loop_swallows_llm_failure(
    monkeypatch: pytest.MonkeyPatch, _force_single_pass: None
) -> None:
    def _boom(*_args: Any, **_kwargs: Any):
        raise RuntimeError("provider down")

    monkeypatch.setattr(explorer_mod, "llm_stream", _boom)
    cap = ExploreContextCapability()
    ctx = _ctx(source_index={"hs-x": "t"}, history_references=["x"])
    # A failed pre-pass degrades to no investigation, never raises.
    assert await cap.pre_loop(ctx, StreamBus(), usage=None) is None


# ---------------------------------------------------------------------------
# Agentic loop (native tool-calling models)
# ---------------------------------------------------------------------------


class _FakeFunc:
    def __init__(self, name: str | None = None, arguments: str | None = None) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, index: int, call_id: str, name: str, arguments: str) -> None:
        self.index = index
        self.id = call_id
        self.function = _FakeFunc(name=name, arguments=arguments)


class _FakeDelta:
    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[_FakeToolCall] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = None
        self.reasoning = None


class _FakeChoice:
    def __init__(self, delta: _FakeDelta) -> None:
        self.delta = delta
        self.finish_reason = None


class _FakeChunk:
    def __init__(self, delta: _FakeDelta) -> None:
        self.choices = [_FakeChoice(delta)]
        self.usage = None


class _FakeResponseStream:
    def __init__(self, chunks: list[_FakeChunk]) -> None:
        self._chunks = chunks

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk


class _FakeCompletions:
    """Returns one queued response per ``create`` call (one per loop round)."""

    def __init__(self, rounds: list[list[_FakeChunk]]) -> None:
        self._rounds = list(rounds)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _FakeResponseStream:
        self.calls.append(kwargs)
        chunks = self._rounds.pop(0) if self._rounds else []
        return _FakeResponseStream(chunks)


class _FakeClient:
    def __init__(self, rounds: list[list[_FakeChunk]]) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(rounds)})()


@pytest.fixture
def _force_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(explorer_mod, "can_use_native_tool_calling", lambda **_kwargs: True)


@pytest.mark.asyncio
async def test_loop_reads_source_then_writes_investigation(
    monkeypatch: pytest.MonkeyPatch, _force_loop: None
) -> None:
    """The investigator calls read_source on a source, then writes an
    investigation grounded in the loaded full text."""
    rounds = [
        # Round 0: ask to read the attached transcript.
        [
            _FakeChunk(
                _FakeDelta(
                    tool_calls=[_FakeToolCall(0, "call_1", "read_source", '{"source_id": "hs-x"}')]
                )
            )
        ],
        # Round 1: no tool calls → this text is the investigation.
        [_FakeChunk(_FakeDelta(content="The other agent rewrote the nav and shipped it."))],
    ]
    fake_client = _FakeClient(rounds)
    monkeypatch.setattr(explorer_mod, "build_openai_client", lambda _cfg: fake_client)

    cap = ExploreContextCapability()
    ctx = _ctx(
        source_index={"hs-x": "## Claude Code\nI rewrote the nav and shipped it."},
        history_references=["x"],
        _manifest="[Attached Sources]\n- id=hs-x type=history name='nav'",
    )
    bus = StreamBus()

    block = await cap.pre_loop(ctx, bus, usage=None)

    assert isinstance(block, PromptBlock)
    assert "Context Investigation" in block.content
    assert "rewrote the nav" in block.content
    # read_source was dispatched (the model's source_id reached the create
    # call only via the tool round, and a tool result fed the second round).
    completions = fake_client.chat.completions
    assert len(completions.calls) == 2
    # Never streamed CONTENT — the investigation rides the thinking channel.
    kinds = [e.type for e in bus._history]
    assert StreamEventType.CONTENT not in kinds
    assert StreamEventType.TOOL_CALL in kinds


@pytest.mark.asyncio
async def test_loop_falls_back_to_single_pass_on_client_error(
    monkeypatch: pytest.MonkeyPatch, _force_loop: None
) -> None:
    """A loop that errors before producing anything degrades to the robust
    single-pass dump-and-brief so the answer loop still gets grounding."""

    def _boom_client(_cfg: Any) -> Any:
        raise RuntimeError("schema rejected")

    monkeypatch.setattr(explorer_mod, "build_openai_client", _boom_client)
    monkeypatch.setattr(explorer_mod, "llm_stream", _fake_stream(["fallback briefing text"]))

    cap = ExploreContextCapability()
    ctx = _ctx(source_index={"hs-x": "transcript body"}, history_references=["x"])

    block = await cap.pre_loop(ctx, StreamBus(), usage=None)

    assert isinstance(block, PromptBlock)
    assert "fallback briefing text" in block.content


# ---------------------------------------------------------------------------
# ContextExplorer source assembly (single-pass helpers)
# ---------------------------------------------------------------------------


def test_explorer_clips_and_caps_sources() -> None:
    explorer = explorer_mod.ContextExplorer(language="en", prompts={})
    big = {f"nb-{i}": "y" * 100_000 for i in range(explorer_mod.MAX_SOURCES + 5)}
    blocks = explorer._render_source_blocks(big)
    assert blocks.count("### [") <= explorer_mod.MAX_SOURCES
    assert "(truncated)" in blocks
    assert len(blocks) <= explorer_mod.TOTAL_CHARS + 5_000  # blocks + headers/notes


def test_explorer_kind_label_from_prefix() -> None:
    explorer = explorer_mod.ContextExplorer(language="en", prompts={})
    assert explorer._kind_label("hs-abc") == "Conversation transcript"
    assert explorer._kind_label("at-abc") == "Document"
    assert explorer._kind_label("zz-abc") == "Source"
