"""Live-turn previews, compact-on-overflow, and resume from a stored checkpoint."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.agents.loop.compact import compact_view, deterministic_note
from deeptutor.agents.loop.stored_results import (
    observation_char_budget,
    preview_file_read,
    preview_stored,
    slice_stored,
    write_loop_checkpoint,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import ToolResult
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.services.llm.exceptions import ProviderContextWindowError
from deeptutor.tools.stored_result import ReadStoredResultTool


def test_preview_budget_follows_the_model_window() -> None:
    small = observation_char_budget(8_192)
    large = observation_char_budget(200_000)
    assert small < large
    text = "x" * (small + 1)
    shown_small, stored_small = preview_stored(text, max_chars=small)
    shown_large, stored_large = preview_stored(text, max_chars=large)
    assert stored_small is not None
    assert stored_large is None
    assert shown_large == text
    window = slice_stored(stored_small[1], 0, 100_000_000, max_chars=small)
    assert "x" * small in window
    assert "x" * (small + 1) not in window
    assert f"limit up to {small}" in window


def test_file_read_preview_points_at_the_path_and_is_not_stored() -> None:
    shown = preview_file_read("read_file", {"path": "notes.md"}, "y" * 3000, max_chars=2000)
    assert shown is not None
    assert "file_path=notes.md" in shown
    assert "read_with=read_file" in shown
    assert "offset" in shown
    assert "result_id=" not in shown
    assert preview_file_read("rag", {"path": "notes.md"}, "y" * 3000) is None


def test_preview_keeps_an_id_and_slice_caps_the_range() -> None:
    page = observation_char_budget(16_384)
    shown, stored = preview_stored("x" * (page + 10), max_chars=page)
    assert stored is not None
    result_id, body = stored
    assert result_id in shown
    assert "read_stored_result" in shown
    assert len(body) == page + 10
    window = slice_stored(body, 0, 100_000, max_chars=page)
    assert f"limit up to {page}" in window
    assert "x" * page in window
    assert "x" * (page + 1) not in window


@pytest.mark.asyncio
async def test_read_stored_result_rejects_ids_outside_this_session() -> None:
    tool = ReadStoredResultTool()
    missing = await tool.execute(result_id="tr_other", _stored_results={"tr_mine": "hello"})
    assert missing.success is False
    found = await tool.execute(result_id="tr_mine", offset=1, limit=2, _stored_results={"tr_mine": "hello"})
    assert "el" in found.content


@pytest.mark.asyncio
async def test_compact_returns_a_copy_and_keeps_result_ids() -> None:
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "round-one"},
        {"role": "tool", "tool_call_id": "c1", "name": "rag", "content": "result_id=tr_KEEP\npreview"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "round-two"},
        {"role": "user", "content": "current"},
    ]
    original = [dict(message) for message in messages]

    async def _note(middle):
        return deterministic_note(middle)

    compacted = await compact_view(
        messages,
        keep_rounds=1,
        summarize=_note,
    )

    assert messages == original
    assert compacted is not None
    assert compacted[0]["content"] == "system"
    assert compacted[1]["content"].startswith("[Session compact]")
    assert "result_id=tr_KEEP" in compacted[1]["content"]
    assert compacted[-1]["content"] == "current"
    assert any(message.get("content") == "round-two" for message in compacted)
    assert not any(message.get("content") == "round-one" for message in compacted)


class _Client:
    def __init__(self, scripted: list[Any]) -> None:
        self._script = list(scripted)
        self.calls: list[list[dict[str, Any]]] = []

        class _Completions:
            def __init__(self, parent: _Client) -> None:
                self.parent = parent

            async def create(self, **kwargs):
                self.parent.calls.append(list(kwargs.get("messages") or []))
                if not self.parent._script:
                    raise RuntimeError("script exhausted")
                step = self.parent._script.pop(0)
                if isinstance(step, Exception):
                    raise step
                return step

        class _Chat:
            def __init__(self, parent: _Client) -> None:
                self.completions = _Completions(parent)

        self.chat = _Chat(self)


class _Registry:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def deferred_tools(self):
        return []

    def build_prompt_text(self, _enabled, **_kwargs):
        return ""

    def build_openai_schemas(self, _enabled):
        return []

    async def execute(self, name: str, **kwargs):
        self.executed.append(name)
        return ToolResult(content="ran again", success=True)


def _chunk(content: str):
    delta = SimpleNamespace(content=content, reasoning_content=None, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason="stop", message=SimpleNamespace())
    return SimpleNamespace(choices=[choice], usage=None)


async def _async_stream(chunks: list[Any]):
    for chunk in chunks:
        yield chunk


def _answer_stream():
    return _async_stream([_chunk("Answer")])


@pytest.fixture
def _isolated(monkeypatch, tmp_path):
    from deeptutor.capabilities.setup.binding import mark_intro_shown
    from deeptutor.services.path_service import PathService

    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    paths = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(PathService, "_instance", paths)
    paths.ensure_all_directories()
    mark_intro_shown()
    monkeypatch.setattr(
        "deeptutor.agents.loop.pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai",
            model="gpt-test",
            api_key="k",
            base_url="u",
            api_version=None,
            extra_headers={},
            reasoning_effort=None,
            context_window=8192,
            max_tokens=256,
        ),
    )
    monkeypatch.setattr(
        "deeptutor.agents.loop.compact.summarize_earlier_rounds",
        lambda _pipeline, middle: _as_note(middle),
    )


async def _as_note(middle):
    return deterministic_note(middle)


@pytest.mark.asyncio
async def test_context_length_retries_a_shorter_view_without_rewriting_the_transcript(
    _isolated, monkeypatch
) -> None:
    client = _Client([ProviderContextWindowError("maximum context length"), _answer_stream()])
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = _Registry()
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _: [])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)
    pipeline._respond_max_tokens = 256
    context = UnifiedContext(session_id="s", user_message="current")
    context.runtime.model_history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "round-one"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "round-two"},
    ]
    bus = StreamBus()
    await pipeline.run(context, bus)
    await bus.close()

    assert len(client.calls) == 2
    assert any(message.get("content") == "round-one" for message in client.calls[0])
    assert any(
        str(message.get("content") or "").startswith("[Session compact]") for message in client.calls[1]
    )
    retained = context.runtime.model_turn["messages"]
    assert not any(
        str(message.get("content") or "").startswith("[Session compact]") for message in retained
    )


@pytest.mark.asyncio
async def test_resume_checkpoint_does_not_execute_the_finished_tool(_isolated, monkeypatch) -> None:
    client = _Client([_answer_stream()])
    registry = _Registry()
    pipeline = AgenticChatPipeline(language="en")
    pipeline.registry = registry
    pipeline._respond_max_tokens = 256
    monkeypatch.setattr(pipeline, "_compose_enabled_tools", lambda _: ["web_search"])
    monkeypatch.setattr(pipeline, "_build_openai_client", lambda: client)
    context = UnifiedContext(session_id="s", user_message="Solve")
    context.runtime.resume_model_turn = {
        "version": 1,
        "messages": [
            {"role": "user", "content": "Solve"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "name": "web_search",
                "content": "ALREADY_FETCHED",
            },
        ],
        "stored_results": {"tr_saved": "full body"},
    }
    bus = StreamBus()
    await pipeline.run(context, bus)
    await bus.close()

    assert registry.executed == []
    assert any(message.get("content") == "ALREADY_FETCHED" for message in client.calls[0])
    assert context.runtime.stored_results["tr_saved"] == "full body"


def test_checkpoint_file_round_trip(tmp_path, monkeypatch) -> None:
    from deeptutor.agents.loop.stored_results import read_loop_checkpoint
    from deeptutor.services.path_service import PathService

    monkeypatch.setattr(PathService, "_instance", PathService(workspace_root=tmp_path))
    write_loop_checkpoint("sess", "turn", {"version": 1, "messages": [{"role": "user", "content": "a"}]})
    loaded = read_loop_checkpoint("sess")
    assert loaded is not None
    assert loaded["model_turn"]["messages"][0]["content"] == "a"
    assert read_loop_checkpoint("other") is None
